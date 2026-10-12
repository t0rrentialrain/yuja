// Yuja content script: underlines Korean words by status; click for a glass card.
// youtube.js (loaded after this, same scope) adds the subtitle bar and browser.
// After Yuja is reloaded in chrome://extensions, tabs that were already open keep this old copy, cut off
// from Chrome: every chrome.* call throws. Say so once instead of failing silently.
let staleShown = false;
function stale() {
  if (staleShown || !document.body) return;
  staleShown = true;
  const t = Object.assign(document.createElement("div"), { className: "yuja-toast" });
  t.innerHTML = `🍋 <b>Yuja was updated.</b> Refresh this tab to use the new version.`;
  document.body.append(t);
  setTimeout(() => t.remove(), 12000);
}
const alive = () => { try { return !!chrome.runtime?.id; } catch { return false; } };
const api = (path, body) => {
  if (!alive()) return (stale(), Promise.resolve({ error: "Yuja was updated: refresh this tab" }));
  return chrome.runtime.sendMessage({ path, body }).then(r => (r?.offline && serverDown(), r),
    e => (stale(), { error: String(e) }));
};

// One friendly notice per tab when the local server isn't running.
let downShown = false;
function serverDown() {
  if (downShown || !document.body) return;
  downShown = true;
  const t = Object.assign(document.createElement("div"), { className: "yuja-toast" });
  t.innerHTML = `🍋 <b>Yuja's server isn't running.</b> It starts with Windows once you run <code>python yuja/autostart.py</code> — or start it now with <code>python yuja/server.py</code>.`;
  document.body.append(t);
  setTimeout(() => t.remove(), 12000);
}
const HANGUL = /[가-힣]/;
const STATUSES = [["unknown", "New", "1"], ["learning", "Learning", "2"], ["known", "Known", "3"], ["ignored", "Ignore", "0"]];
const POS = { VV: "verb", VA: "adjective", VX: "helper verb", NNG: "noun", NNP: "name", NNB: "bound noun", NP: "pronoun",
  NR: "number", MAG: "adverb", MAJ: "adverb", MM: "determiner", IC: "interjection", XSN: "suffix", XSV: "suffix",
  XSA: "suffix", XPN: "prefix", XR: "root", VCP: "copula", VCN: "copula", EP: "tense / honorific", EF: "ending",
  EC: "connector", ETM: "modifier ending", ETN: "noun ending", GRAM: "grammar pattern" };
const esc = s => String(s).replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`);
const base = tag => tag.split("-")[0];
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---- settings (incl. fruit theme), in chrome.storage so every tab and the player share them ----
const THEMES = [["yuja", "🍋", "유자 Yuja", "#ffe680", "#ffc21a"], ["strawberry", "🍓", "딸기 Strawberry", "#ffadc2", "#ff5c8a"],
  ["grape", "🍇", "청포도 Green grape", "#d6f2a0", "#a3d64a"], ["peach", "🍑", "복숭아 Peach", "#ffc6ae", "#ff8f6b"],
  ["blueberry", "🫐", "블루베리 Blueberry (dark)", "#4a4c7a", "#2a2b46"]];
const DEFAULTS = { theme: "yuja", autopause: "off", size: 100, pos: 12, blur: false, underline: true, replay: 1,
  subs: true, panel: true, listen: "normal", primeShow: "ko", revealShow: "ko", ppc: 0.06, condensed: false, wordVoice: "ko-KR-SunHiNeural", defVoice: "en-US-AvaNeural", x: 50, font: "", bg: "theme", bgOpacity: 92, pad: 100, color: "", stroke: 0,
  strokeColor: "#000000" };   // x/pos: see placeBar() in youtube.js
let S = { ...DEFAULTS };
const applyTheme = () => (document.documentElement.dataset.yujaTheme = S.theme);
const saveSettings = () => {                     // never throws: the change still applies in this tab
  try { chrome.storage.local.set({ settings: S }).catch(stale); } catch { stale(); }
};
const loadSettings = v => { S = { ...DEFAULTS, ...v }; typeof applySettings === "function" ? applySettings() : applyTheme(); };
chrome.storage.local.get("settings").then(r => loadSettings(r.settings));
chrome.storage.onChanged.addListener(c => c.settings && loadSettings(c.settings.newValue));   // live across tabs

// One underline per thing to learn: solid = unknown word, dotted = unknown grammar
// pattern (may span several words), faint = learning. Names aren't vocab, so no line.
function paint(span) {
  const has = s => span.yuja.parts.some(p => p.status === s && base(p.tag) !== "NNP");
  const st = has("unknown") ? "unknown" : span.yuja.grammar.some(g => g.status === "unknown") ? "gram"
    : has("learning") ? "learning" : "known";
  span.className = `yuja yuja-${st}`;
}

const allLines = [];   // every parsed line on this page, so status changes reach them all

// Replace a text node with spans, one per parsed word. Offsets are Python
// code-point indices, so slice with Array.from (emoji-safe).
function render(node, line) {
  if (!allLines.includes(line)) allLines.push(line);
  const chars = Array.from(line.text), frag = document.createDocumentFragment();
  let pos = 0;
  for (const w of line.words) {
    if (w.s < pos || w.cls === "SYM") continue;   // contractions share chars (했 = 하+었); skip punctuation
    frag.append(chars.slice(pos, w.s).join(""));
    const end = Math.max(w.e, ...line.words.filter(x => x.s < w.e && x.s >= w.s).map(x => x.e));
    const span = Object.assign(document.createElement("span"), { textContent: chars.slice(w.s, end).join("") });
    const parts = line.words.filter(x => x.s >= w.s && x.s < end && x.cls !== "SYM");
    const grammar = line.grammar.filter(g => g.s < end && g.e > w.s);
    span.yuja = { word: w, line, grammar, parts };
    paint(span);
    frag.append(span);
    pos = end;
  }
  frag.append(chars.slice(pos).join(""));
  node.replaceWith(frag);
}

async function colorPage() {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: n => HANGUL.test(n.nodeValue) && !n.parentElement.closest(".yuja, yuja-card, .yuja-panel, script, style, textarea, input, [contenteditable]")
      ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (let i = 0; i < nodes.length; i += 100) {
    const batch = nodes.slice(i, i + 100);
    const res = await api("/parse", { lines: batch.map(n => n.nodeValue) });
    res.lines?.forEach((line, j) => render(batch[j], line));
  }
}

// ---- items: words, endings and patterns all get the same status controls ----
const item = p => p.key
  ? { ref: p, key: p.key, tag: "GRAM", label: "≈ " + p.name.replace(/_/g, " ") }
  : { ref: p, key: p.lemma, tag: p.tag, label: p.tag === "GRAM" ? "≈ " + p.lemma.slice(5).replace(/_/g, " ")   // stats-page rows
    : base(p.tag) === "EP" ? `-${p.lemma}-` : p.tag[0] === "E" ? `-${p.lemma}` : p.lemma };
const lineItems = line => [...line.words.filter(w => w.cls !== "SYM").map(item), ...line.grammar.map(item)];

const defsCache = new Map();
const lookup = it => {
  const id = `${it.key}|${it.tag}`;
  if (!defsCache.has(id)) defsCache.set(id, api(`/lookup?lemma=${encodeURIComponent(it.key)}&tag=${it.tag}`));
  return defsCache.get(id);
};

function applyStatus(key, status) {
  allLines.flatMap(l => [...l.words, ...l.grammar]).forEach(p => { if ((p.key ?? p.lemma) === key) p.status = status; });
  document.querySelectorAll(".yuja").forEach(paint);
  dispatchEvent(new Event("yuja-status"));       // subtitle browser recounts unknowns
}

// The item, its line and (in videos) two lines either side: what the AI help and the mined Definition see.
function ctxFor(it, line) {
  const i = typeof yt !== "undefined" && yt?.cues ? yt.cues.findIndex(c => c.line === line) : -1;
  const texts = (a, b) => (i < 0 ? [] : yt.cues.slice(Math.max(0, a), b).map(c => c.text));
  return { word: it.label.replace(/^≈ /, ""), surface: Array.from(line.text).slice(it.ref.s, it.ref.e).join(""),
    line: line.text, before: texts(i - 2, i), after: texts(i + 1, i + 3) };
}

// Translate / Explain on the card. One request per (kind, item, line), shared by prefetch and click.
const aiCache = new Map();
const aiAsk = (kind, ctx) => {
  const id = JSON.stringify([kind, ctx]);
  if (!aiCache.has(id)) aiCache.set(id, api("/ai", { kind, ...ctx }));
  return aiCache.get(id);
};

// Mine an item from a line: sentence with the item bolded, a one-line English Definition the server
// writes (dictionary glosses as fallback), and (for videos) audio + screenshot. Mined words become Learning.
// What the server needs to make one card. No item = a sentence card (Word and Definition left empty).
async function minePayload(it, line) {
  const media = cueFor?.(line) ?? {};
  if (!it) return { word: "", key: "", sentence: esc(line.text), definition: "", ...media };
  const chars = Array.from(line.text), { s, e } = it.ref;
  const sentence = esc(chars.slice(0, s).join("")) + `<b>${esc(chars.slice(s, e).join(""))}</b>` + esc(chars.slice(e).join(""));
  const senses = (await lookup(it)).entries?.[0]?.senses ?? [];
  const definition = senses.slice(0, 3).map(x => esc(x.gloss || x.def)).join("<br>");
  return { word: it.label.replace(/^≈ /, ""), key: it.key, sentence, definition,
    ctx: line.synthetic ? null : ctxFor(it, line), voices: { word: S.wordVoice, definition: S.defVoice }, ...media };
}

async function mine(it, line) {
  const payload = await minePayload(it, line);
  await window.beforeMine?.(payload);              // player page: upload the local video once
  const res = await api("/mine", payload);
  if (res.error) throw new Error(res.error);
  applyStatus(it.key, res.status);
}

// ---- card ----
let card, cardLine, cardSpan, items = [], focus = 0;

function closeCard() { card?.remove(); card = null; }

function openCard(span) {
  closeCard();
  cardLine = span.yuja.line;
  cardSpan = span;
  items = [...span.yuja.parts.map(item), ...span.yuja.grammar.map(item)];
  focus = Math.max(0, items.findIndex(i => i.ref.status === "unknown"));
  card = document.createElement("yuja-card");
  const root = card.attachShadow({ mode: "open" });
  root.innerHTML = `<link rel="stylesheet" href="${chrome.runtime.getURL("card.css")}"><div class="card"></div>`;
  root.addEventListener("click", onCardClick);
  (document.fullscreenElement || document.body).append(card);   // fullscreen video only shows its own subtree
  const r = span.getBoundingClientRect(), below = r.bottom + 330 < innerHeight;
  Object.assign(card.style, { position: "fixed", zIndex: 2147483647,
    left: `${Math.max(8, Math.min(r.left, innerWidth - 348))}px`,
    top: `${below ? r.bottom + 8 : r.top - 8}px`,
    transform: below ? "" : "translateY(-100%)" });
  draw();
}

async function draw(showAll = false) {
  const it = items[focus], el = card.shadowRoot.querySelector(".card");
  el.innerHTML = `
    ${items.length < 2 ? "" : `<div class="chips">${items.map((i, n) => `<button class="chip ${n === focus ? "on" : ""}" data-i="${n}">
      <i class="dot ${i.ref.status}"></i>${esc(i.label)}</button>`).join("")}</div>`}
    <div class="head"><span class="word">${esc(it.label)}</span><span class="pos">${POS[base(it.tag)] ?? (it.tag[0] === "J" ? "particle" : "")}</span><span class="meta"></span></div>
    <div class="defs"><span class="none">…</span></div>
    <div class="status">${STATUSES.map(([s, name, k]) => `<button class="pill ${s} ${it.ref.status === s ? "on" : ""}" data-status="${s}">
      <kbd>${k}</kbd>${name}</button>`).join("")}</div>
    ${cardLine.synthetic ? "" : `<div class="ai"><button class="ai-btn" data-ai="explain"><kbd>E</kbd>Explain</button>
      <button class="ai-btn" data-ai="translate"><kbd>T</kbd>Translate line</button></div><div class="ai-out" hidden></div>`}
    <div class="mine-row"><button class="mine"><kbd>M</kbd>＋ Anki</button><span class="mine-note"></span></div>
    <div class="fix"></div>`;
  showFixes(el.querySelector(".fix"));
  if (!cardLine.synthetic && ["unknown", "learning"].includes(it.ref.status)) aiAsk("explain", ctxFor(it, cardLine));   // ~3 s: start now
  api(`/in_anki?word=${encodeURIComponent(it.label.replace(/^≈ /, ""))}`).then(r => {
    if (r.found && items[focus] === it && card) el.querySelector(".mine-note").textContent = "already in Anki";
  });
  const { entries = [], rank } = await lookup(it);
  if (items[focus] !== it || !card) return;     // focus moved while loading
  // Kimchi-style: frequency rank (Kimchi Reader list) + KRDict level as 1-3 stars.
  const lvl = entries[0]?.level, LV = ["Beginner", "Intermediate", "Advanced"];
  el.querySelector(".meta").innerHTML =
    (rank ? `<span class="rank" title="Frequency rank (Kimchi Reader list)">#${rank.toLocaleString()}</span>` : "")
    + (lvl != null ? `<span class="stars" title="${LV[lvl]} word (KRDict)">${"★".repeat(lvl + 1)}<i>${"★".repeat(2 - lvl)}</i></span>` : "");
  // Concept first: the English gloss leads; the explanation is a quiet second line.
  const senses = entries[0]?.senses ?? [];
  el.querySelector(".defs").innerHTML = senses.length
    ? `<ol>${senses.slice(0, showAll ? 99 : 3).map(s => `<li>
        ${s.gloss ? `<span class="gloss">${esc(s.gloss)}</span>` : `<span class="concept">${esc(s.def)}</span>`}
        ${s.note ? `<span class="note">${esc(s.note)}</span>` : ""}
        ${s.gloss ? `<div class="explain">${esc(s.def)}</div>` : ""}</li>`).join("")}</ol>`
      + (senses.length > 3 && !showAll ? `<button class="more">+${senses.length - 3} more</button>` : "")
    : `<span class="none">${base(it.tag) === "NNP" ? "A name" : "No dictionary entry"}</span>`;
}

async function setStatus(status) {
  const { key } = items[focus];
  await api("/status", { key, status });
  applyStatus(key, status);
  draw();
}

async function showAI(kind) {
  const out = card?.shadowRoot.querySelector(".ai-out"), it = items[focus];
  if (!out) return;
  out.hidden = false;
  out.dataset.kind = kind;
  out.textContent = kind === "explain" ? "Thinking…" : "Translating…";
  const res = await aiAsk(kind, ctxFor(it, cardLine));
  if (items[focus] !== it || out.dataset.kind !== kind || !out.isConnected) return;   // moved on meanwhile
  out.textContent = res.text ?? `Couldn't reach the AI: ${res.error ?? "server offline"}`;
}

async function mineFocused() {
  const btn = card.shadowRoot.querySelector(".mine"), note = card.shadowRoot.querySelector(".mine-note");
  btn.disabled = true;
  note.textContent = "mining…";
  try { await mine(items[focus], cardLine); note.textContent = "✓ added to Anki"; }
  catch (err) { note.textContent = `✗ ${err.message}`; btn.disabled = false; }
}

function onCardClick(e) {
  const t = e.target.closest("button");
  if (!t) return;
  if (t.dataset.i) { focus = +t.dataset.i; draw(); }
  else if (t.dataset.status) setStatus(t.dataset.status);
  else if (t.classList.contains("more")) draw(true);
  else if (t.classList.contains("mine")) mineFocused();
  else if (t.dataset.ai) showAI(t.dataset.ai);
  else if (t.classList.contains("fix-toggle")) t.nextElementSibling.hidden = !t.nextElementSibling.hidden;
  else if (t.dataset.fix) applyFix(...t.dataset.fix.split(",").map(Number));
}

// ---- fixing a wrong split: pick another reading Kiwi considered; Yuja remembers it ----
async function showFixes(box) {
  const span = cardSpan;
  if (span.yuja.line.synthetic) return;              // stats-page rows aren't real sentences
  span.yuja.alts ??= api("/alternatives", { text: span.yuja.line.text, s: span.yuja.word.s,
    e: Math.max(...span.yuja.parts.map(p => p.e)) });
  const { spans = [] } = await span.yuja.alts;
  if (!spans.length || cardSpan !== span || !box.isConnected) return;
  // ✓ = the reading currently shown (may be Jev's pick, not Kiwi's favourite)
  const shown = r => span.yuja.line.words.filter(w => w.s >= r.s && w.e <= r.e).map(w => w.lemma).join("+");
  box.innerHTML = `<button class="fix-toggle">Split looks wrong?</button><div class="fix-list" hidden>${spans.map((r, i) =>
    `<div class="fix-surface">${esc(r.surface)}</div>${r.options.map((o, j) => {
      const on = o.choice.map(c => c[0]).join("+") === shown(r);
      return `<button data-fix="${i},${j}" class="${on ? "on" : ""}">${on ? "✓ " : ""}${esc(o.label)}</button>`; }).join("")}`).join("")}</div>`;
}

async function applyFix(i, j) {
  const { spans } = await cardSpan.yuja.alts, r = spans[i], line = cardLine;
  const res = await api("/correct", { text: line.text, key: r.key, choice: r.options[j].choice });
  if (res.line) { closeCard(); replaceLine(line, res.line); }
}

// Re-draw every rendering of a line (page, subtitle bar, browser row) with its re-parsed version.
function replaceLine(old, line) {
  const groups = new Map();
  document.querySelectorAll(".yuja").forEach(s => s.yuja.line === old && groups.set(s.parentNode, [...(groups.get(s.parentNode) ?? []), s]));
  for (const [parent, spans] of groups) {               // render() wrote: lead text, span, text, span, ..., trail text
    const first = spans[0].previousSibling, last = spans.at(-1).nextSibling, node = document.createTextNode(line.text);
    parent.insertBefore(node, first);
    for (let n = first; n; ) { const next = n.nextSibling; n.remove(); if (n === last) break; n = next; }
    render(node, line);
  }
  allLines.splice(allLines.indexOf(old), 1);
  yt?.cues.forEach(c => c.line === old && (c.line = line));
  dispatchEvent(new Event("yuja-status"));            // browser recounts
}

document.addEventListener("click", e => {
  if (e.target === card) return;                 // clicks inside the shadow root retarget to the host
  const span = e.target.closest(".yuja");
  if (span?.closest(".yuja-panel.selecting")) return;   // picking lines for a batch: the row handles it
  if (span) { e.preventDefault(); e.stopPropagation(); openCard(span); }
  else closeCard();
}, true);

document.addEventListener("keydown", e => {
  if (!card || e.target.closest?.("input, textarea, [contenteditable]")) return;
  const st = STATUSES.find(([, , k]) => k === e.key);
  if (st) setStatus(st[0]);
  else if (e.key === "m" || e.key === "M") mineFocused();
  else if (e.key === "e" || e.key === "E") showAI("explain");
  else if (e.key === "t" || e.key === "T") showAI("translate");
  else if (e.key === "Escape") closeCard();
  else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    focus = (focus + (e.key === "ArrowRight" ? 1 : items.length - 1)) % items.length;
    draw();
  } else return;
  e.preventDefault();
  e.stopPropagation();   // YouTube would otherwise seek on number keys
}, true);
addEventListener("scroll", e => e.target === document && closeCard(), { passive: true, capture: true });

// Hovering one piece of a grammar pattern lights up the whole pattern.
let hovered = null;
document.addEventListener("mouseover", e => {
  const span = e.target.closest?.(".yuja") ?? null;
  if (span === hovered) return;                  // only recompute when the hovered word changes
  hovered = span;
  document.querySelectorAll(".yuja-hl").forEach(s => s.classList.remove("yuja-hl"));
  const g = span?.yuja.grammar;
  if (g?.length) document.querySelectorAll(".yuja").forEach(s => s.yuja.grammar.some(x => g.includes(x)) && s.classList.add("yuja-hl"));
});

if (!location.hostname.endsWith("youtube.com")) colorPage();
