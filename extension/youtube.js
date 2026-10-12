// Yuja on YouTube: a subtitle bar inside the player (with a settings menu on the
// ⚙ shown on hover) and a Migaku-style subtitle browser beside it. Shares scope with content.js.
let yt = null;   // { vid, bar, panel, cues, idx, pausedAt, rate }
const video = () => document.querySelector("#movie_player video");
const fmt = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

// ---- video settings (S lives in content.js, stored in chrome.storage so it follows you everywhere) ----
function applySettings() {
  applyTheme();
  if (!yt?.bar) return;
  const b = yt.bar;
  Object.assign(b.style, { fontSize: `calc(clamp(18px, 2.3vw, 36px) * ${S.size / 100})`,
    fontFamily: S.font ? `"${S.font}", "Malgun Gothic", sans-serif` : "", color: S.color });
  b.style.setProperty("--ys-a", `${S.bgOpacity}%`);
  b.style.setProperty("--ys-pad", S.pad / 100);
  b.style.setProperty("--ys-stroke", `${S.stroke * 2}px ${S.strokeColor}`);   // ×2: half of it hides behind the fill
  b.dataset.bg = S.bg;
  if (yt.panel) yt.panel.hidden = !S.panel;
  b.classList.toggle("off", !S.subs);
  b.classList.toggle("blur", S.blur);
  b.classList.toggle("plain", !S.underline);
  b.classList.toggle("en-only", S.listen === "primed" && S.primeShow === "en");
  if (S.listen !== "primed" && yt.priming) { clearTimeout(yt.priming); yt.priming = null; }
  hush();
  ensureEnglish();
  ensureSummaries();
  placeBar();
}

// ---- listening modes ----
// Primed (like the dojo-prompts mpv script): each line pauses at its start and is shown (Korean, English or
// both) for a reading time, then plays with the subtitles hidden. Space during that pause holds it.
// Listen first: subtitles hidden while a line plays; at its end it pauses and reveals it.
// Either way the subtitles show whenever the video is paused. Condensed skips the gaps between lines.
const needEnglish = () => (S.listen === "primed" && S.primeShow !== "ko") || (S.listen === "reveal" && S.revealShow === "both");
const hush = () => yt?.bar.classList.toggle("hush", S.listen !== "normal" && !!video() && !video().paused);

function readTime(cue) {
  const n = s => (s ?? "").replace(/\s/g, "").length, ko = n(cue.text), en = n(cue.en) * 0.5;   // English reads ~2x faster per char
  const chars = S.primeShow === "ko" || !cue.en ? ko : S.primeShow === "en" ? en : ko + en;
  return Math.max(0.5, chars * S.ppc);
}

function prime(idx, cue) {
  const v = video();
  yt.primedIdx = idx;
  v.pause();
  yt.priming = setTimeout(() => {
    yt.priming = null;
    v.currentTime = cue.start;                          // the check runs every 50 ms: don't lose the first syllable
    v.play();
  }, readTime(cue) * 1000);
}

// Summaries (dojo-prompts primed-summaries): at the start of each topical chunk, pause and show its English
// summary for a reading time (Space holds), then play the chunk with the subtitles hidden.
function primeSummary(idx, cue, chunk) {
  const v = video();
  yt.primedIdx = idx;
  v.pause();
  yt.bar.innerHTML = `<span class="yuja-sum"><b>Coming up</b>${esc(chunk.summary)}</span>`;
  yt.sumShown = true;
  placeBar();
  yt.priming = setTimeout(() => {
    yt.priming = null;
    v.currentTime = cue.start;
    v.play();
  }, Math.max(1.5, chunk.summary.replace(/\s/g, "").length * S.ppc * 0.5) * 1000);
}

// The server writes the summaries window by window; use each batch as it arrives.
async function ensureSummaries() {
  if (!yt?.cues.length || S.listen !== "summary" || yt.sumDone || yt.sumLoading) return;
  yt.sumLoading = true;
  const vid = yt.vid, lines = yt.cues.map(c => c.text);
  for (let shown = false; yt?.vid === vid; ) {
    const r = await api("/summaries", { vid, lines });
    if (yt?.vid !== vid) return;
    yt.chunkAt = new Map((r.chunks ?? []).map(c => [c.start - 1, c]));   // cue index -> chunk starting there
    if (r.chunks?.length && shown) { hideNotice(); shown = false; }
    if (r.error) { notice(`Summaries stopped: ${r.error}`, 8000); }
    if (r.done || r.error || !r.chunks) { yt.sumDone = !!r.done; break; }
    if (!r.chunks.length && !shown) { notice(`Writing section summaries… the first ones take about 30 s`); shown = true; }
    await sleep(4000);
  }
  if (yt) yt.sumLoading = false;
}

// English for the whole transcript, translated once per video on the server (DeepSeek, translate-srt protocol).
async function ensureEnglish() {
  if (!yt?.cues.length || !needEnglish() || yt.en || yt.enLoading) return;
  yt.enLoading = true;
  const vid = yt.vid, lines = yt.cues.map(c => c.text);
  for (let shown = false; yt?.vid === vid; ) {
    const r = await api("/english", { vid, lines });
    if (yt?.vid !== vid) return;
    if (r.en) {
      yt.cues.forEach((c, i) => (c.en = r.en[i]));
      yt.en = true;
      if (shown) hideNotice();
      const t = video()?.currentTime;
      yt.idx = -2;                                      // redraw the current line with its English
      if (t !== undefined) showCue(t);
      break;
    }
    if (r.status !== "working") { notice(`English unavailable: ${r.status ?? r.error ?? "server offline"}`, 8000); break; }
    if (!shown) { notice(`Translating the subtitles to English… ${eta(video()?.duration * 2.75)}`); shown = true; }
    await sleep(3000);
  }
  if (yt) yt.enLoading = false;
}

// S.x is the share of the free width left of the bar (50 = centered), S.pos the gap below it (% of player
// height): the bar stays inside the player for any line length or player size. Re-run on every resize.
function placeBar() {
  const b = yt?.bar, p = b?.parentElement;
  if (!p || !b.offsetWidth) return;
  const { width: W, height: H } = p.getBoundingClientRect(), cs = getComputedStyle(b);
  const w = parseFloat(cs.width), h = parseFloat(cs.height);   // layout size in fractional px
  b.style.left = `${Math.max(0, W - w) * S.x / 100}px`;
  b.style.bottom = `${Math.max(0, Math.min(H * S.pos / 100, H - h))}px`;
}

// Korean fonts worth offering, kept only if installed (a font that's missing measures like the fallback).
const FONTS = ["Malgun Gothic", "Noto Sans KR", "Noto Serif KR", "Pretendard", "Spoqa Han Sans Neo", "IBM Plex Sans KR",
  "Nanum Gothic", "NanumSquare", "Nanum Myeongjo", "Gowun Dodum", "Jua", "Do Hyeon", "Black Han Sans", "BM HANNA 11yrs old",
  "BM HANNA Air", "BM EULJIRO", "BM kkubulim", "Maplestory", "Gulim", "Dotum", "Batang", "Gungsuh"];
let installedFonts;
function fontList() {
  if (installedFonts) return installedFonts;
  const c = document.createElement("canvas").getContext("2d"), width = font => ((c.font = `40px ${font}`), c.measureText("가나다라 abc").width);
  return (installedFonts = FONTS.filter(f => ["monospace", "serif"].some(g => width(`"${f}", ${g}`) !== width(g))));
}

// Drag the bar anywhere in the player. A press that moves under 5px is still a click (word lookup).
function makeDraggable(bar, player) {
  let drag = null, dragged = false;
  // Moves are tracked on window: a quick flick leaves the bar before the 5px threshold.
  const move = e => {
    const dx = e.clientX - drag.e.clientX, dy = e.clientY - drag.e.clientY;
    if (!drag.moving && Math.hypot(dx, dy) < 5) return;
    drag.moving = true;
    bar.classList.add("dragging");
    const W = drag.p.width - drag.b.width, H = drag.p.height;
    S.x = W > 0 ? +(100 * Math.max(0, Math.min(W, drag.b.left - drag.p.left + dx)) / W).toFixed(2) : 50;
    S.pos = +(100 * Math.max(0, Math.min(H - drag.b.height, drag.p.bottom - drag.b.bottom - dy)) / H).toFixed(2);
    applySettings();
  };
  const end = () => {
    removeEventListener("pointermove", move);
    removeEventListener("pointerup", end);
    removeEventListener("pointercancel", end);
    if (drag.moving) { dragged = true; bar.classList.remove("dragging"); saveSettings(); setTimeout(() => (dragged = false)); }
    drag = null;
  };
  bar.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    drag = { e, p: player.getBoundingClientRect(), b: bar.getBoundingClientRect(), moving: false };
    addEventListener("pointermove", move);
    addEventListener("pointerup", end);
    addEventListener("pointercancel", end);
  });
  // Window capture runs before every other click handler, so the drop doesn't open a card or toggle play.
  addEventListener("click", e => dragged && (e.stopPropagation(), e.preventDefault()), true);
}

// Brief on-video message, e.g. after toggling subtitles with C.
function flash(text) {
  yt.bar.parentElement.querySelector(".yuja-flash")?.remove();
  const f = Object.assign(document.createElement("div"), { className: "yuja-flash", textContent: text });
  yt.bar.parentElement.append(f);
  setTimeout(() => f.remove(), 1400);
}

// For mining: which video/time span a parsed line came from (null off YouTube).
function cueFor(line) {
  const c = yt?.cues.find(c => c.line === line);
  return c && { vid: yt.vid, start: c.start, end: c.end };
}

// Unknown items in a line: words + grammar, not names (names aren't vocab).
const unknowns = line => lineItems(line).filter(i => i.ref.status === "unknown" && base(i.tag) !== "NNP");

async function loadYouTube() {
  const vid = location.pathname === "/watch" && new URLSearchParams(location.search).get("v");
  if (vid && yt?.vid === vid && yt.bar.isConnected) return;   // already loaded/loading this video
  document.querySelectorAll(".yuja-subs, .yuja-gear, .yuja-settings, .yuja-panel, .yuja-flash, .yuja-status").forEach(el => el.remove());
  yt = null;
  if (!vid) return;
  let player;
  while (!(player = document.querySelector("#movie_player"))) await sleep(300);
  mountPlayer(vid, player);
  let res;
  for (;;) {
    res = await api(`/subs?v=${vid}`);
    if (yt?.vid !== vid) return;                       // navigated away
    if (res.status === "no-captions") {                // transcribing costs time + Soniox credit: ask first
      if (!await ask("No Korean captions", "Generate subtitles")) return;
      res = await api("/transcribe", { vid });
    }
    if (res.status === "transcribing") notice(`Generating subtitles… ${eta(video()?.duration)}`);
    if (res.status !== "working" && res.status !== "transcribing") break;
    await sleep(1500);
  }
  if (yt?.vid === vid) startCues(res);
}

// Download + Soniox take ~8 s plus ~0.04 s per second of video (measured: 11.5 min -> 28 s).
function eta(duration) {
  if (!duration) return "";
  const sec = 8 + duration * 0.04;
  return sec < 60 ? `about ${Math.max(10, Math.round(sec / 10) * 10)} s` : `about ${Math.round(sec / 60)} min`;
}

// Shared with the local player page (player.js): subtitle bar + ⚙ (visible on hover) in the player...
function mountPlayer(vid, player) {
  const bar = Object.assign(document.createElement("div"), { className: "yuja-subs" });
  const gear = Object.assign(document.createElement("button"), { className: "yuja-gear", textContent: "⚙", title: "Yuja settings" });
  player.append(bar, gear);
  document.documentElement.classList.add("yuja-yt");
  yt = { vid, bar, cues: [], idx: -1, pausedAt: -1, rate: null };
  applySettings();
  makeDraggable(bar, player);
  yt.fit = new ResizeObserver(() => placeBar());        // new line, font or size, fullscreen (kept on yt so it isn't collected)
  yt.fit.observe(bar);
  yt.fit.observe(player);
  gear.addEventListener("click", e => { e.stopPropagation(); toggleSettings(); });
  notice("Loading subtitles…");
}

// Status ("Loading subtitles…") is a small pill in the player's top-left corner with a bobbing yuja,
// kept out of the subtitle bar. notice(text, ms) shows it (fading after ms if given); hideNotice() fades it.
function notice(text, ms = 0) {
  const player = yt.bar.parentElement;
  let pill = player.querySelector(".yuja-status");
  if (!pill) {
    pill = Object.assign(document.createElement("div"), { className: "yuja-status" });
    pill.innerHTML = `<img src="${chrome.runtime.getURL("icons/icon32.png")}" alt=""><span></span>`;
    player.append(pill);
  }
  pill.querySelector("span").textContent = text.charAt(0).toUpperCase() + text.slice(1);
  pill.classList.remove("out");
  clearTimeout(yt.noticeTimer);
  if (ms) yt.noticeTimer = setTimeout(hideNotice, ms);
}

// The pill as a question: resolves true for the button, false for ✕.
function ask(text, label) {
  notice(text);
  const pill = yt.bar.parentElement.querySelector(".yuja-status");
  pill.classList.add("ask");
  pill.insertAdjacentHTML("beforeend", `<button class="ys-go">${esc(label)}</button><button class="ys-no" title="Not now">✕</button>`);
  return new Promise(done => pill.addEventListener("click", e => {
    const yes = e.target.closest(".ys-go"), no = e.target.closest(".ys-no");
    if (!yes && !no) return;
    e.stopPropagation();
    pill.classList.remove("ask");
    pill.querySelectorAll("button").forEach(b => b.remove());
    if (no) hideNotice();
    done(!!yes);
  }));
}

function hideNotice() {
  const pill = yt?.bar.parentElement?.querySelector(".yuja-status");
  if (!pill) return;
  pill.classList.add("out");
  setTimeout(() => pill.classList.contains("out") && pill.remove(), 400);
}

// ...then the parsed lines ({cues, lines, bookmarks, known_pct}) drive bar + browser.
function startCues(res) {
  if (!res.cues) return notice(res.status ?? res.error ?? "no subtitles", 8000);
  yt.cues = res.cues.map((c, i) => ({ ...c, line: res.lines[i], bm: res.bookmarks.includes(c.start) }));
  allLines.push(...res.lines);                         // so status changes reach cues not shown yet
  hideNotice();
  buildPanel();
  ensureEnglish();
  ensureSummaries();
}

// Show the latest cue that has started; stays up until the next one begins.
function showCue(t) {
  const idx = yt.cues.findLastIndex(c => c.start <= t), cue = yt.cues[idx], v = video();
  if (S.condensed && v && !v.paused && !yt.priming) {   // condensed: jump over gaps longer than ~0.6 s
    const next = yt.cues[idx + 1], gapFrom = cue ? cue.end + 0.25 : 0;
    if (next && t > gapFrom && next.start - t > 0.6) { v.currentTime = next.start - 0.1; return; }
  }
  const pauseHere = S.autopause === "all" || S.listen === "reveal" || (S.autopause === "unknown" && cue && unknowns(cue.line).length);
  if (pauseHere && cue && t >= cue.end - 0.05 && yt.pausedAt !== idx) { yt.pausedAt = idx; video()?.pause(); }
  if (yt.rate !== null && idx !== yt.replayIdx) { video().playbackRate = yt.rate; yt.rate = null; }   // slow replay ends with its line
  if (idx === yt.idx) return;
  yt.idx = idx;
  yt.bar.textContent = "";
  yt.panel?.querySelector(".yp-row.on")?.classList.remove("on");
  if (idx < 0) return;
  const ko = Object.assign(document.createElement("span"), { className: "yuja-ko" }), node = document.createTextNode(cue.text);
  ko.append(node);
  yt.bar.append(ko);
  render(node, cue.line);
  if (cue.en && needEnglish()) yt.bar.append(Object.assign(document.createElement("span"), { className: "yuja-en", textContent: cue.en }));
  placeBar();
  if (S.listen === "primed" && v && !v.paused && yt.primedIdx !== idx) prime(idx, cue);
  const chunk = S.listen === "summary" && yt.chunkAt?.get(idx);
  if (chunk?.summary && v && !v.paused && yt.primedIdx !== idx) primeSummary(idx, cue, chunk);
  const row = yt.panel?.querySelector(`.yp-row[data-i="${idx}"]`);
  row?.classList.add("on");
  if (row && !row.hidden && !yt.panel.matches(":hover")) row.scrollIntoView({ block: "center", behavior: "smooth" });
}

function seekCue(i, replay = false) {
  const c = yt.cues[Math.max(0, Math.min(i, yt.cues.length - 1))];
  if (!c) return;
  yt.pausedAt = -1;
  video().currentTime = c.start;
  if (replay && S.replay !== 1) {                      // slow replay of the current line
    yt.rate ??= video().playbackRate;
    yt.replayIdx = yt.cues.indexOf(c);
    video().playbackRate = S.replay;
  }
  video().play();
}

// ---- settings menu (opened from the ⚙) ----
function toggleSettings() {
  const open = document.querySelector(".yuja-settings");
  if (open) return open.remove();
  const m = Object.assign(document.createElement("div"), { className: "yuja-settings" });
  const seg = (key, opts) => `<div class="ys-seg">${opts.map(([v, label]) =>
    `<button data-key="${key}" data-val="${v}" class="${S[key] == v ? "on" : ""}">${label}</button>`).join("")}</div>`;
  const check = (key, label) => `<label class="ys-check"><input type="checkbox" data-key="${key}" ${S[key] ? "checked" : ""}> ${label}</label>`;
  const fonts = fontList(), custom = S.font && !fonts.includes(S.font);
  m.innerHTML = `
    <label>Theme</label><div class="ys-themes">${THEMES.map(([v, emoji, name, c1, c2]) =>
      `<button data-key="theme" data-val="${v}" title="${name}" class="${S.theme === v ? "on" : ""}"
        style="background:linear-gradient(180deg,${c1},${c2})">${emoji}</button>`).join("")}</div>
    <div class="ys-head">Subtitles</div>
    ${check("subs", "Show subtitles <kbd>C</kbd>")}
    ${check("panel", "Subtitle browser")}
    <div class="ys-row"><span>Size</span><input type="range" data-key="size" min="60" max="200" value="${S.size}"></div>
    <div class="ys-row"><span>Font</span><select class="ys-font">
      <option value="">Default</option>${fonts.map(f => `<option ${S.font === f ? "selected" : ""}>${esc(f)}</option>`).join("")}
      <option value="*" ${custom ? "selected" : ""}>Other installed font…</option></select></div>
    <input class="ys-font-name" data-key="font" placeholder="Font name, e.g. Pretendard" value="${esc(S.font)}" ${custom ? "" : "hidden"}>
    <div class="ys-row"><span>Background</span>${seg("bg", [["theme", "Fruit"], ["dark", "Dark"], ["none", "None"]])}</div>
    <div class="ys-row ys-box"><span>Opacity</span><input type="range" data-key="bgOpacity" min="0" max="100" value="${S.bgOpacity}"></div>
    <div class="ys-row ys-box"><span>Box size</span><input type="range" data-key="pad" min="0" max="200" value="${S.pad}"></div>
    <div class="ys-row"><span>Text</span><button class="ys-auto ${S.color ? "" : "on"}" data-act="auto-color">Auto</button>
      <input type="color" data-key="color" value="${S.color || "#ffffff"}"></div>
    <div class="ys-row"><span>Outline</span><input type="range" data-key="stroke" min="0" max="6" step="0.5" value="${S.stroke}">
      <input type="color" data-key="strokeColor" value="${S.strokeColor}"></div>
    <div class="ys-row ys-hint"><span>Position</span><em>Drag the subtitles</em><button class="ys-auto" data-act="reset-pos">Reset</button></div>
    ${check("blur", "Blur until hover")}
    ${check("underline", "Underline unknown words")}
    <div class="ys-head">Playback</div>
    <label>Auto-pause</label>${seg("autopause", [["off", "Off"], ["all", "Every line"], ["unknown", "Unknown lines"]])}
    <label>Replay speed</label>${seg("replay", [[1, "1×"], [0.75, "0.75×"], [0.5, "0.5×"]])}
    <label>Listening</label>${seg("listen", [["normal", "Normal"], ["primed", "Primed"], ["reveal", "Listen first"], ["summary", "Summaries"]])}
    <div class="ys-row ys-primed"><span>Show first</span>${seg("primeShow", [["ko", "한국어"], ["en", "English"], ["both", "Both"]])}</div>
    <div class="ys-row ys-readtime"><span>Read time</span><input type="range" data-key="ppc" min="0.02" max="0.15" step="0.01" value="${S.ppc}">
      <em class="ys-ppc"></em></div>
    <div class="ys-row ys-reveal"><span>Reveal</span>${seg("revealShow", [["ko", "한국어"], ["both", "+ English"]])}</div>
    ${check("condensed", "Condensed: skip the gaps between lines")}
    <div class="ys-head">Card audio</div>
    <div class="ys-row"><span>Word</span><select data-key="wordVoice" data-lang="ko"><option>${esc(S.wordVoice)}</option></select>
      <button class="ys-play" data-play="wordVoice" title="Hear it">▶</button></div>
    <div class="ys-row"><span>Definition</span><select data-key="defVoice" data-lang="en"><option>${esc(S.defVoice)}</option></select>
      <button class="ys-play" data-play="defVoice" title="Hear it">▶</button></div>
    <div class="ys-keys"><kbd>[</kbd> previous <kbd>]</kbd> next <kbd>\\</kbd> replay line <kbd>C</kbd> subtitles · Primed / Summaries: <kbd>Space</kbd> holds the pause</div>`;
  const sync = () => {
    m.querySelectorAll(".ys-box").forEach(el => (el.hidden = S.bg === "none"));   // opacity + box size need a box
    m.querySelectorAll(".ys-primed").forEach(el => (el.hidden = S.listen !== "primed"));
    m.querySelectorAll(".ys-readtime").forEach(el => (el.hidden = !["primed", "summary"].includes(S.listen)));
    m.querySelectorAll(".ys-reveal").forEach(el => (el.hidden = S.listen !== "reveal"));
    m.querySelector(".ys-ppc").textContent = `${S.ppc.toFixed(2)} s per character`;
    m.querySelector("[data-act=auto-color]").classList.toggle("on", !S.color);
  };
  const save = () => { saveSettings(); applySettings(); sync(); };
  sync();
  m.addEventListener("click", e => {
    e.stopPropagation();
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "auto-color") S.color = "";
    if (act === "reset-pos") Object.assign(S, { x: DEFAULTS.x, pos: DEFAULTS.pos });
    const play = e.target.closest("[data-play]");
    if (play) return preview(play, S[play.dataset.play], play.dataset.play === "wordVoice" ? SAMPLE.word : SAMPLE.definition);
    if (act) return save();
    const b = e.target.closest("button[data-key]");
    if (!b) return;
    S[b.dataset.key] = b.dataset.key === "replay" ? +b.dataset.val : b.dataset.val;
    b.parentElement.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    save();
  });
  m.addEventListener("input", e => {
    const t = e.target, name = m.querySelector(".ys-font-name");
    if (t.matches(".ys-font")) {                         // "Other…" reveals a free-text font name
      name.hidden = t.value !== "*";
      S.font = t.value === "*" ? name.value : t.value;
      if (!name.hidden) name.focus();
    } else if (t.dataset.key) S[t.dataset.key] = t.type === "checkbox" ? t.checked : t.type === "range" ? +t.value : t.value;
    save();
  });
  document.querySelector("#movie_player").append(m);
  api("/voices").then(r => m.querySelectorAll("select[data-lang]").forEach(sel => {   // fill once the list arrives
    const list = (r.voices ?? []).filter(v => v.lang === sel.dataset.lang);
    if (list.length) sel.innerHTML = list.map(v => `<option value="${v.name}" ${v.name === S[sel.dataset.key] ? "selected" : ""}>${esc(v.label)}</option>`).join("");
  }));
}

// Voice preview in the ⚙ menu: the server speaks a sample, the page plays it.
const SAMPLE = { word: "유자차", definition: "A sweet tea made from yuja; warm and comforting in winter." };
async function preview(btn, voice, text) {
  btn.textContent = "…";
  const r = await api("/speak", { voice, text });
  btn.textContent = "▶";
  if (!r.audio) return (btn.title = r.error ?? "server offline");
  const url = URL.createObjectURL(new Blob([Uint8Array.from(atob(r.audio), c => c.charCodeAt(0))], { type: "audio/mpeg" }));
  const a = new Audio(url);
  a.onended = () => URL.revokeObjectURL(url);
  a.play();
}

// ---- subtitle browser ----
const FILTERS = [["all", "Show all"], ["rec", "Recommended sentences"], ["u1", "1 Unknown word"],
  ["uniq", "Unique 1 Unknown"], ["u1p", "1+ Unknown words"], ["u2p", "2+ Unknown words"],
  ["learning", "Learning"], ["known", "All Known"], ["bm", "Bookmarked"]];

async function buildPanel() {
  const panel = Object.assign(document.createElement("div"), { className: "yuja-panel" });
  panel.innerHTML = `
    <div class="yp-head">
      <div class="yp-dd">
        <button class="yp-dd-btn"><span class="yp-dd-label"></span><span class="yp-dd-caret">▾</span></button>
        <div class="yp-dd-list" hidden>${FILTERS.map(([v, l]) =>
          `<button data-filter="${v}"><span>${l}</span><span class="yp-dd-n"></span><span class="yp-dd-check">✓</span></button>`).join("")}</div>
      </div>
      <span class="yp-pct" title="Share of words in this video you know"></span>
      <button class="yp-icon yp-find" title="Search">⌕</button>
      <button class="yp-icon yp-copy" title="Copy the lines shown">⧉</button>
      <button class="yp-icon yp-select" title="Select lines to mine as a batch">☑</button>
      <button class="yp-icon yp-close" title="Close (reopen from ⚙)">✕</button>
    </div>
    <input class="yp-search" placeholder="Search subtitles…" hidden>
    <div class="yp-batch" hidden><button class="yp-all">Select shown</button><button class="yp-none">Clear</button>
      <span class="yp-count"></span><button class="yp-go">Mine</button></div>
    <div class="yp-list"></div>`;
  const list = panel.querySelector(".yp-list");
  yt.cues.forEach((c, i) => {
    const row = Object.assign(document.createElement("div"), { className: "yp-row" });
    row.dataset.i = i;
    row.innerHTML = `<span class="yp-check"></span><span class="yp-text"></span><span class="yp-n"></span>
      <span class="yp-acts"><span class="yp-time">${fmt(c.start)}</span><button class="yp-bm" title="Bookmark">☆</button><button class="yp-mine" title="Mine its unknown word">＋</button></span>`;
    const text = document.createTextNode(c.text);
    row.querySelector(".yp-text").append(text);
    render(text, c.line);
    list.append(row);
  });
  let secondary;
  while (!(secondary = document.querySelector("#secondary-inner, #secondary"))) await sleep(300);
  secondary.prepend(panel);
  yt.panel = panel;
  panel.hidden = !S.panel;
  panel.addEventListener("input", refreshPanel);
  panel.addEventListener("click", onPanelClick);
  panel.querySelector(".yp-dd").addEventListener("keydown", e => {   // ↑/↓ move, Enter picks, Esc closes
    const items = [...panel.querySelectorAll(".yp-dd-list button")], i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (panel.querySelector(".yp-dd-list").hidden) dropdown(true);
      else items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    } else if (e.key === "Escape") dropdown(false);
    else return;                                       // Enter/Space click the focused button natively
    e.preventDefault();
    e.stopPropagation();
  });
  refreshPanel();
}

const dropdown = open => {
  const list = yt.panel.querySelector(".yp-dd-list");
  list.hidden = !(open ?? list.hidden);
  if (!list.hidden) list.querySelector(".on")?.focus();
};

async function onPanelClick(e) {
  const p = yt.panel;
  if (e.target.closest(".yp-dd-btn")) return dropdown();
  const pick = e.target.closest("[data-filter]");
  if (pick) { yt.filter = pick.dataset.filter; dropdown(false); return refreshPanel(); }
  if (!e.target.closest(".yp-dd")) dropdown(false);
  if (e.target.closest(".yp-find")) {
    const s = p.querySelector(".yp-search");
    s.hidden = !s.hidden;
    if (s.hidden) s.value = ""; else s.focus();
    return refreshPanel();
  }
  if (e.target.closest(".yp-close")) { S.panel = false; saveSettings(); return applySettings(); }
  if (e.target.closest(".yp-select")) return selecting(!p.classList.contains("selecting"));
  if (e.target.closest(".yp-all")) { p.querySelectorAll(".yp-row:not([hidden])").forEach(r => yt.sel.add(+r.dataset.i)); return paintSel(); }
  if (e.target.closest(".yp-none")) { yt.sel.clear(); return paintSel(); }
  if (e.target.closest(".yp-go")) return mineBatch();
  if (e.target.closest(".yp-copy")) {
    const rows = [...p.querySelectorAll(".yp-row")].filter(r => !r.hidden);
    await navigator.clipboard.writeText(rows.map(r => yt.cues[+r.dataset.i].text).join("\n"));
    const b = e.target.closest(".yp-copy");
    b.textContent = "✓";
    return setTimeout(() => (b.textContent = "⧉"), 1200);
  }
  const row = e.target.closest(".yp-row");
  if (!row) return;
  const cue = yt.cues[+row.dataset.i];
  if (p.classList.contains("selecting") && !e.target.closest(".yp-acts")) {   // pick / unpick the line
    yt.sel.has(+row.dataset.i) ? yt.sel.delete(+row.dataset.i) : yt.sel.add(+row.dataset.i);
    return paintSel();
  }
  if (e.target.closest(".yp-bm")) {
    cue.bm = !cue.bm;
    api("/bookmark", { vid: yt.vid, start: cue.start, on: cue.bm });
    return refreshPanel();
  }
  if (e.target.closest(".yp-mine")) {                  // mine the line's unknown item
    const btn = e.target.closest(".yp-mine"), it = unknowns(cue.line)[0];
    if (!it) return;
    btn.textContent = "…";
    try { await mine(it, cue.line); btn.textContent = "✓"; }
    catch (err) { btn.textContent = "✗"; btn.title = err.message; }
    return;
  }
  seekCue(+row.dataset.i);
}

// ---- batch mining (Migaku-style): ☑ → pick lines (or "Select shown" for the current filter) → Mine.
// A line with exactly one unknown makes a normal card for it; any other line makes a sentence card with
// Word and Definition left empty. The server works through them in the background.
function selecting(on) {
  yt.sel ??= new Set();
  yt.panel.classList.toggle("selecting", on);
  yt.panel.querySelector(".yp-batch").hidden = !on;
  paintSel();
}

function paintSel() {
  const p = yt.panel;
  p.querySelectorAll(".yp-row").forEach(r => r.classList.toggle("sel", yt.sel.has(+r.dataset.i)));
  const n = yt.sel.size, words = [...yt.sel].filter(i => unknowns(yt.cues[i].line).length === 1).length;
  p.querySelector(".yp-count").textContent = n ? `${n} lines · ${words} word, ${n - words} sentence cards` : "Pick lines";
  const go = p.querySelector(".yp-go");
  go.disabled = !n || !!yt.batch;
  if (!yt.batch) go.textContent = n ? `Mine ${n}` : "Mine";
}

async function mineBatch() {
  const p = yt.panel, go = p.querySelector(".yp-go"), idx = [...yt.sel].sort((a, b) => a - b);
  if (!idx.length || yt.batch) return;
  yt.batch = true;
  go.disabled = true;
  go.textContent = "Preparing…";
  const fail = msg => { yt.batch = null; go.disabled = false; go.textContent = `✗ ${msg}`; };
  const payloads = await Promise.all(idx.map(i => {
    const u = unknowns(yt.cues[i].line);
    return minePayload(u.length === 1 ? u[0] : null, yt.cues[i].line);
  }));
  try { await window.beforeMine?.(payloads[0]); } catch (err) { return fail(err.message); }
  const { id, error } = await api("/mine_batch", { items: payloads });
  if (!id) return fail(error ?? "server offline");
  const applied = new Set();
  for (;;) {
    await sleep(1500);
    const r = await api(`/mine_batch?id=${id}`);
    if (!r.results) break;
    r.results.forEach((res, k) => {                    // mark rows as their cards are made
      if (!res || applied.has(k)) return;
      applied.add(k);
      const row = p.querySelector(`.yp-row[data-i="${idx[k]}"]`);
      row?.classList.add(res.ok ? "mined" : "failed");
      if (!res.ok && row) row.title = res.error;
      if (res.ok && res.key) applyStatus(res.key, res.status);
    });
    const done = r.results.filter(Boolean), bad = done.filter(x => !x.ok).length;
    go.textContent = r.done ? `✓ ${done.length - bad} cards${bad ? ` · ✗ ${bad}` : ""}` : `Mining ${done.length} / ${r.total}…`;
    if (r.done) break;
  }
  yt.batch = null;
  yt.sel.clear();
  p.querySelectorAll(".yp-row.sel").forEach(r => r.classList.remove("sel"));
  setTimeout(() => yt?.panel === p && !yt.batch && paintSel(), 4000);
}

// Recommended = one unknown, short enough, enough known context, and Jev rates it a clear example.
const knownContext = (line, target) => line.words.filter(w => ["NOM", "PRED"].includes(w.cls) && w !== target.ref
  && ["known", "learning"].includes(w.status)).length;
const goodShape = (cue, target) => cue.text.length >= 6 && cue.text.length <= 40 && knownContext(cue.line, target) >= 2;
let scoring = false;

async function scoreCandidates(cands) {                // ask Jev about i+1 lines not rated yet
  if (scoring || !cands.length) return;
  scoring = true;
  try {
    const res = await api("/quality", { items: cands.map(({ cue, target }) => ({ text: cue.text, key: target.key, tag: target.tag })) });
    cands.forEach(({ cue, target }, i) => (cue.q = { key: target.key, score: res.scores?.[i] ?? null }));
  } finally { scoring = false; }
  refreshPanel();
}

// Recount unknowns, then filter + search the rows (no re-render needed).
function refreshPanel() {
  if (!yt?.panel) return;
  const p = yt.panel, q = p.querySelector(".yp-search").value.trim(), filter = yt.filter ??= "all";
  const counted = yt.cues.flatMap(c => c.line.words).filter(w => w.cls !== "SYM" && w.status !== "ignored");
  p.querySelector(".yp-pct").textContent = counted.length
    ? `${Math.round(100 * counted.filter(w => w.status === "known").length / counted.length)}% known` : "";
  const info = yt.cues.map((cue, i) => {
    const u = unknowns(cue.line), target = u.length === 1 ? u[0] : null;
    const score = target && cue.q?.key === target.key ? cue.q.score : undefined;
    return { cue, i, n: u.length, target, score, shape: target && goodShape(cue, target),
      learning: lineItems(cue.line).some(it => it.ref.status === "learning"), words: cue.line.words.length };
  });
  scoreCandidates(info.filter(x => x.shape && x.score === undefined).map(x => ({ cue: x.cue, target: x.target })));
  // Unique 1 Unknown: the best-rated i+1 line per unknown item.
  const best = new Map();
  for (const x of info.filter(x => x.n === 1)) {
    const cur = best.get(x.target.key), rank = y => (y.shape ? 1 : 0) + (y.score ?? 0);
    if (!cur || rank(x) > rank(cur)) best.set(x.target.key, x);
  }
  const keep = {
    all: () => true, rec: x => x.shape && x.score >= 0.75, u1: x => x.n === 1, uniq: x => best.get(x.target?.key) === x,
    u1p: x => x.n >= 1, u2p: x => x.n >= 2, learning: x => x.learning, known: x => x.n === 0 && x.words, bm: x => x.cue.bm };
  p.querySelectorAll(".yp-dd-list button").forEach(b => {
    const n = info.filter(keep[b.dataset.filter]).length;
    b.querySelector(".yp-dd-n").textContent = n;
    b.classList.toggle("on", b.dataset.filter === filter);
    if (b.dataset.filter === filter) p.querySelector(".yp-dd-label").innerHTML = `${b.firstElementChild.textContent} <b>${n}</b>`;
  });
  for (const x of info) {
    const row = p.querySelector(`.yp-row[data-i="${x.i}"]`), pill = row.querySelector(".yp-n");
    pill.textContent = x.n || "";
    pill.className = `yp-n ${x.n === 1 ? "one" : x.n ? "many" : ""}`;
    row.querySelector(".yp-mine").hidden = !x.n;
    row.querySelector(".yp-bm").textContent = x.cue.bm ? "★" : "☆";
    row.classList.toggle("bm", x.cue.bm);
    row.hidden = !keep[filter](x) || (q && !x.cue.text.includes(q));
  }
}

// Page-level listeners, used on YouTube and on the local player page.
function wireListeners() {
  setInterval(() => yt?.cues.length && video() && !video().paused && api("/watch", { vid: yt.vid, seconds: 30 }), 30000);   // watch time
  addEventListener("yuja-status", refreshPanel);
  document.addEventListener("timeupdate", e => yt?.cues.length && e.target.matches("video") && showCue(e.target.currentTime), true);
  // timeupdate comes ~4x a second: too coarse to pause right at a line's start or skip a gap cleanly.
  setInterval(() => (S.listen !== "normal" || S.condensed) && yt?.cues.length && video() && !video().paused && showCue(video().currentTime), 50);
  for (const ev of ["play", "pause"]) document.addEventListener(ev, e => {
    if (!e.target.matches?.("video")) return;
    if (ev === "play" && yt?.priming) { clearTimeout(yt.priming); yt.priming = null; }   // you resumed early
    if (ev === "play" && yt?.sumShown) { yt.sumShown = false; yt.idx = -2; }          // back to the line under the summary
    hush();
  }, true);
  document.addEventListener("click", e => {
    if (e.target.closest(".yuja-subs .yuja")) video()?.pause();
    if (!e.target.closest(".yuja-settings, .yuja-gear")) document.querySelector(".yuja-settings")?.remove();
    if (yt?.panel && !e.target.closest(".yp-dd")) dropdown(false);
  }, true);
  document.addEventListener("keydown", e => {             // [ prev · ] next · \ replay · C subtitles
    if (!yt || card || e.ctrlKey || e.metaKey || e.altKey || e.target.closest?.("input, textarea, select, [contenteditable]")) return;
    if (e.key === "c" || e.key === "C") {                 // C shows/hides Yuja's subtitles (YouTube's own are always off)
      S.subs = !S.subs;
      saveSettings(); applySettings();
      flash(S.subs ? "Subtitles on" : "Subtitles off");
      const box = document.querySelector(".yuja-settings [data-key=subs]");
      if (box) box.checked = S.subs;
      e.preventDefault();
      return e.stopPropagation();
    }
    if (yt.priming && (e.key === " " || e.key === "k")) {   // Primed: Space during the pause holds it
      clearTimeout(yt.priming);
      yt.priming = null;
      flash("Held · Space to continue");
      e.preventDefault();
      return e.stopPropagation();
    }
    if (!yt.cues.length) return;
    const step = { "[": -1, "]": 1, "\\": 0 }[e.key];
    if (step === undefined) return;
    seekCue(Math.max(yt.idx, 0) + step, step === 0);
    e.preventDefault();
    e.stopPropagation();
  }, true);
}

// ---- thumbnail scores: % known on thumbnails of videos with Korean captions ----
const scores = new Map();                              // vid -> % | null (no Korean captions) | "working"
const onScreen = new Set();
const seen = new IntersectionObserver(es => es.forEach(e => (e.isIntersecting ? onScreen.add(e.target) : onScreen.delete(e.target))));

function paintThumb(a, pct) {
  let pill = a.querySelector(":scope > .yuja-score");
  if (typeof pct !== "number") return pill?.remove();
  if (!pill) {
    pill = Object.assign(document.createElement("span"), { className: "yuja-score" });
    if (getComputedStyle(a).position === "static") a.style.position = "relative";
    a.append(pill);
  }
  pill.textContent = `${Math.round(pct)}%`;
  pill.dataset.tier = pct >= 95 ? "easy" : pct >= 88 ? "good" : pct >= 80 ? "hard" : "harder";
  pill.title = `You know ${pct}% of the words in this video`;
}

async function updateThumbs() {
  document.querySelectorAll('a[href*="/watch?v="]').forEach(a => {
    const vid = a.querySelector("img") && new URL(a.href).searchParams.get("v");
    if (!vid || a.dataset.yuja === vid) return;
    a.dataset.yuja = vid;                              // YouTube reuses thumbnail elements: re-key them
    paintThumb(a, null);
    seen.observe(a);
  });
  const shown = [...onScreen].filter(a => a.isConnected);
  const want = [...new Set(shown.map(a => a.dataset.yuja))].filter(v => !scores.has(v) || scores.get(v) === "working");
  if (want.length) Object.entries(await api("/scores", { vids: want }) ?? {}).forEach(([v, s]) => scores.set(v, s));
  shown.forEach(a => paintThumb(a, scores.get(a.dataset.yuja)));
}

if (location.hostname.endsWith("youtube.com")) {
  addEventListener("yt-navigate-finish", loadYouTube);   // YouTube navigates without page loads
  wireListeners();
  loadYouTube();
  setInterval(updateThumbs, 3000);
}
