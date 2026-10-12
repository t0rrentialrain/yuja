// Stats page: hero numbers, one single-series chart per measure, and the unknown
// words you keep meeting (clickable, with the usual card).
const tip = document.getElementById("tip");
const day = d => new Date(d + "T00:00");
const fmtDay = d => day(d).toLocaleDateString(undefined, { month: "short", day: "numeric" });

// Last `n` days as YYYY-MM-DD, so bars show quiet days as zero instead of skipping them.
function lastDays(n) {
  const out = [], t = new Date();
  for (let i = n - 1; i >= 0; i--) out.push(new Date(t.getFullYear(), t.getMonth(), t.getDate() - i).toLocaleDateString("sv"));
  return out;
}

function showTip(e, html) {
  tip.innerHTML = html;
  tip.hidden = false;
  Object.assign(tip.style, { left: `${Math.min(e.clientX + 12, innerWidth - 180)}px`, top: `${e.clientY - 36}px` });
}

// One series, one axis. Line for a running total, bars for per-day counts.
function chart(el, data, { kind, color, unit }) {
  const W = el.clientWidth, H = 180, pad = { l: 40, r: 12, t: 12, b: 24 };
  if (!data.length || data.every(d => !d.value)) {
    el.innerHTML = `<p class="empty">Nothing yet. This fills in as you watch and mine.</p>`;
    return;
  }
  const vals = data.map(d => d.value), lo = kind === "line" ? Math.min(...vals) * 0.98 : 0, hi = Math.max(...vals) * 1.05 || 1;
  const x = i => pad.l + (data.length === 1 ? (W - pad.l - pad.r) / 2 : i * (W - pad.l - pad.r) / (data.length - 1));
  const y = v => H - pad.b - (v - lo) / (hi - lo) * (H - pad.t - pad.b);
  const ticks = [lo, (lo + hi) / 2, hi].map(v => `<line class="grid" x1="${pad.l}" x2="${W - pad.r}" y1="${y(v)}" y2="${y(v)}"/>
    <text class="tick" x="${pad.l - 6}" y="${y(v) + 4}" text-anchor="end">${Math.round(v).toLocaleString()}</text>`).join("");
  const labels = `<text class="tick" x="${pad.l}" y="${H - 6}">${fmtDay(data[0].date)}</text>
    <text class="tick" x="${W - pad.r}" y="${H - 6}" text-anchor="end">${fmtDay(data.at(-1).date)}</text>`;
  let marks;
  if (kind === "line") {
    marks = `<polyline fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" points="${data.map((d, i) => `${x(i)},${y(d.value)}`).join(" ")}"/>
      ${data.map((d, i) => `<circle cx="${x(i)}" cy="${y(d.value)}" r="${data.length === 1 ? 5 : 3}" fill="${color}" stroke="var(--y-surface1)" stroke-width="2"/>`).join("")}
      <line class="cross" y1="${pad.t}" y2="${H - pad.b}" hidden/>`;
  } else {
    const bw = Math.max(3, (W - pad.l - pad.r) / data.length - 2);
    marks = data.map((d, i) => d.value ? `<path fill="${color}" d="M${x(i) - bw / 2},${y(0)} V${y(d.value) + Math.min(4, y(0) - y(d.value))}
      q0,-4 4,-4 h${bw - 8} q4,0 4,4 V${y(0)} Z"/>` : "").join("");     // empty days draw nothing
  }
  el.innerHTML = `<svg width="${W}" height="${H}" role="img">${ticks}${labels}${marks}<rect class="hit" x="${pad.l}" y="0" width="${W - pad.l - pad.r}" height="${H}"/></svg>`;
  if (kind === "line" && data.length === 1) el.insertAdjacentHTML("beforeend", `<p class="empty">History builds from today: one point per day.</p>`);
  const hit = el.querySelector(".hit"), cross = el.querySelector(".cross");
  hit.addEventListener("mousemove", e => {
    const r = hit.getBoundingClientRect(), i = Math.round((e.clientX - r.left) / r.width * (data.length - 1));
    const d = data[Math.max(0, Math.min(data.length - 1, i))];
    if (cross) { cross.hidden = false; cross.setAttribute("x1", x(data.indexOf(d))); cross.setAttribute("x2", x(data.indexOf(d))); }
    showTip(e, `<b>${d.value.toLocaleString()}</b> ${unit}<br><span>${fmtDay(d.date)}</span>`);
  });
  hit.addEventListener("mouseleave", () => { tip.hidden = true; cross?.setAttribute("hidden", ""); });
}

async function load() {
  const s = await api("/stats");
  if (s.error) return;
  const days = lastDays(30), fill = rows => days.map(date => ({ date, value: rows.find(r => r.date === date)?.value ?? 0 }));
  const week = rows => fill(rows).slice(-7).reduce((a, d) => a + d.value, 0);
  const total = rows => rows.reduce((a, d) => a + d.value, 0);
  document.getElementById("tiles").innerHTML = [
    ["Known words", s.known.at(-1)?.value ?? 0], ["Minutes watched this week", week(s.watch)],
    ["Cards mined this week", week(s.mined)], ["Cards mined in total", total(s.mined)],
  ].map(([label, v]) => `<div class="tile"><b>${v.toLocaleString()}</b><span>${label}</span></div>`).join("");
  const css = getComputedStyle(document.documentElement), c = name => css.getPropertyValue(name).trim();
  chart(document.getElementById("known"), s.known, { kind: "line", color: c("--y-known"), unit: "known words" });
  chart(document.getElementById("watch"), fill(s.watch), { kind: "bar", color: c("--y-new"), unit: "minutes" });
  chart(document.getElementById("mined"), fill(s.mined), { kind: "bar", color: c("--y-learn-lo"), unit: "cards" });

  // Unknown words: each row is a one-word "line", so render() + the card work as everywhere else.
  const list = document.getElementById("unknown");
  list.innerHTML = s.unknown.length ? "" : `<p class="empty">No unknown words yet. Watch something!</p>`;
  for (const u of s.unknown) {
    const text = item({ lemma: u.key, tag: u.tag }).label;          // same labels as the card (-ㄴ, ≈ 것 같다)
    const li = document.createElement("li");
    li.innerHTML = `<span class="w"></span><span class="n">seen ${u.n}×</span>${u.rank ? `<span class="r">#${u.rank.toLocaleString()}</span>` : ""}`;
    const node = document.createTextNode(text);
    li.querySelector(".w").append(node);
    list.append(li);
    render(node, { text, synthetic: true, grammar: [], words: [{ s: 0, e: Array.from(text).length, lemma: u.key, tag: u.tag, cls: "NOM", status: "unknown" }] });
  }
}

// Charts take their colors from the theme: redraw when it changes.
chrome.storage.onChanged.addListener(c => c.settings && setTimeout(load, 50));
load();
