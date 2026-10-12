"""Build eval/compare.html from eval/results.json: blind A/B/C judging (shuffled per item), names,
speed and cost hidden until you press Reveal. Usage: python yuja/eval/report.py"""
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
res = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
rnd = random.Random(11)


def blind(options: dict) -> list:
    keys = list(options)
    rnd.shuffle(keys)
    return [{"label": "ABC"[i], "who": k, "text": options[k]} for i, k in enumerate(keys)]


items = [{"word": r["word"], "surface": r["surface"], "text": r["text"], "before": r["before"], "after": r["after"],
          "tr": blind(r["tr"]), "ex": blind(r["ex"])} for r in res["lines"]]
tx = res["transcript"]
cols = blind(tx["en"])
data = {"items": items, "tx": {"ko": tx["ko"], "cols": cols}, "models": res["models"], "stats": res["stats"]}

html = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yuja translation test</title><style>
:root { --bg: #fffdf2; --card: #fff; --ink: #2f4424; --soft: #7c9a5e; --line: #e6dc9e; --hi: #ffe680; --pick: #b8e04a; }
@media (prefers-color-scheme: dark) { :root:not([data-theme=light]) { --bg: #1e1f36; --card: #2a2b46; --ink: #ebe9ff; --soft: #a9a7d0; --line: #45476e; --hi: #5a5c99; --pick: #4cb983; } }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.6 "Nunito", "Malgun Gothic", system-ui, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 24px 16px 80px; }
h1 { font-size: 22px; } h2 { font-size: 17px; margin-top: 36px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px; margin: 14px 0; }
.ctx { color: var(--soft); font-size: 14px; } .line { font-size: 18px; margin: 4px 0 10px; }
mark { background: var(--hi); color: inherit; border-radius: 4px; padding: 0 2px; }
.opt { display: flex; gap: 10px; align-items: flex-start; padding: 8px 10px; border-radius: 12px; cursor: pointer; border: 1px solid transparent; }
.opt:hover { border-color: var(--line); } .opt.on { background: color-mix(in srgb, var(--pick) 35%, transparent); border-color: var(--pick); }
.opt b { flex: none; width: 22px; } .who { display: none; font-size: 12px; color: var(--soft); }
.revealed .who { display: inline; }
.k { font-size: 12px; font-weight: 800; color: var(--soft); text-transform: uppercase; letter-spacing: .04em; margin-top: 8px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; } td, th { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
.txwrap { overflow-x: auto; } .tx td:first-child { color: var(--soft); white-space: nowrap; }
button { font: 800 14px inherit; padding: 8px 18px; border-radius: 999px; border: 1px solid var(--line); background: var(--card); color: var(--ink); cursor: pointer; }
#stats { display: none; } .revealed #stats { display: block; }
</style></head><body><main id="root">
<h1>Translation test</h1>
<p>Pick the best translation and the best explanation for each line. Labels are shuffled per line. When you're done, press Reveal to see which service was which, plus speed and cost.</p>
<div id="items"></div>
<h2>Whole transcript (first 100 lines)</h2>
<p>Same protocol as dojo-prompts translate-srt. Columns are A, B, C in a fixed order for this table; pick the column you'd rather watch with.</p>
<div class="card" id="txpick"></div>
<div class="txwrap"><table class="tx" id="tx"></table></div>
<h2>Results</h2>
<p><button id="reveal">Reveal</button></p>
<div id="tally"></div>
<div id="stats" class="card"></div>
</main><script>
const D = __DATA__;
const esc = s => String(s).replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`);
let picks = {};
try { picks = JSON.parse(localStorage.getItem("yuja-eval") || "{}"); } catch {}
const save = () => { try { localStorage.setItem("yuja-eval", JSON.stringify(picks)); } catch {} tally(); };
function opts(id, list) {
  return list.map(o => `<div class="opt ${picks[id] === o.who ? "on" : ""}" data-id="${id}" data-who="${o.who}"><b>${o.label}</b>
    <span>${esc(o.text)} <span class="who">· ${esc(D.models[o.who])}</span></span></div>`).join("");
}
document.getElementById("items").innerHTML = D.items.map((it, i) => `<div class="card">
  <div class="ctx">${it.before.map(esc).join("<br>")}</div>
  <div class="line">${esc(it.text).replace(esc(it.surface), `<mark>${esc(it.surface)}</mark>`)}</div>
  <div class="ctx">${it.after.map(esc).join("<br>")}</div>
  <div class="k">Translation</div>${opts("t" + i, it.tr)}
  ${it.ex.length ? `<div class="k">Explain “${esc(it.word)}”</div>${opts("e" + i, it.ex)}` : ""}</div>`).join("");
const C = D.tx.cols;
document.getElementById("txpick").innerHTML = `<div class="k">Best transcript</div>` + opts("tx", C.map(c => ({ ...c, text: "Column " + c.label })));
document.getElementById("tx").innerHTML = `<tr><th></th><th>Korean</th>${C.map(c => `<th>${c.label} <span class="who">${esc(D.models[c.who])}</span></th>`).join("")}</tr>` +
  D.tx.ko.map((k, i) => `<tr><td>${i + 1}</td><td>${esc(k)}</td>${C.map(c => `<td>${esc(c.text[i] ?? "")}</td>`).join("")}</tr>`).join("");
document.addEventListener("click", e => {
  const o = e.target.closest(".opt");
  if (!o) return;
  picks[o.dataset.id] = o.dataset.who;
  document.querySelectorAll(`.opt[data-id="${o.dataset.id}"]`).forEach(x => x.classList.toggle("on", x === o));
  save();
});
function tally() {
  const n = (pre, who) => Object.entries(picks).filter(([k, v]) => k.startsWith(pre) && v === who).length;
  const rev = document.getElementById("root").classList.contains("revealed");
  const name = w => rev ? D.models[w] : "?";
  const ws = Object.keys(D.models);
  document.getElementById("tally").innerHTML = `<p>Picked so far: ${Object.keys(picks).length} of ${D.items.length * 2 + 1}</p>` + (rev ? `<table><tr><th>Service</th><th>Best translation</th><th>Best explanation</th><th>Best transcript</th></tr>` +
    ws.map(w => `<tr><td>${esc(name(w))}</td><td>${n("t", w)}</td><td>${n("e", w)}</td><td>${picks.tx === w ? "✓" : ""}</td></tr>`).join("") + "</table>" : "");
}
document.getElementById("reveal").onclick = () => {
  document.getElementById("root").classList.add("revealed");
  const S = D.stats, f = (x, d = 1) => x === undefined ? "–" : x.toFixed(d);
  document.getElementById("stats").innerHTML = `<table><tr><th>Service</th><th>${D.items.length} line translations</th><th>${D.items.length} explanations</th><th>100-line transcript</th></tr>` +
    Object.keys(S).map(w => `<tr><td>${esc(D.models[w])}</td><td>${f(S[w].line_s)} s · $${f(S[w].line_cost, 4)}</td>
      <td>${S[w].ex_s === undefined ? "–" : `${f(S[w].ex_s)} s · $${f(S[w].ex_cost, 4)}`}</td>
      <td>${f(S[w].tx_s)} s · ${w === "deepl" ? `${S[w].tx_chars} chars (free tier)` : `$${f(S[w].tx_cost, 4)}, ${S[w].tx_retries} retries`}</td></tr>`).join("") + "</table>";
  tally();
};
tally();
</script></body></html>"""
(HERE / "compare.html").write_text(html.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")), encoding="utf-8")
print("wrote", HERE / "compare.html")
