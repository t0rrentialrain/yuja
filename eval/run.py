"""Run the translate/explain comparison on eval/testset.json (+ the start of one transcript) with every
backend that has a key, then write eval/compare.html for blind judging.
Usage: python yuja/eval/run.py [transcript_vid]"""
import json
import random
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.stdout.reconfigure(encoding="utf-8")
import translate as T  # noqa: E402

PRICE = {"gemini": (0.30, 2.50), "deepseek": (0.14, 0.28)}   # $ per million tokens in/out (checked 2026-10)
KEYS = {"gemini": "GEMINI_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "deepl": "DEEPL_API_KEY"}
backends = [b for b, k in KEYS.items() if T.key(k)]
print("backends:", backends, "| missing keys:", [k for b, k in KEYS.items() if b not in backends])
cost = lambda b, u: (u.get("in", 0) * PRICE[b][0] + u.get("out", 0) * PRICE[b][1]) / 1e6 if b in PRICE else 0.0

tests = json.loads((HERE / "testset.json").read_text(encoding="utf-8"))
res = {"backends": backends, "models": {}, "lines": [], "transcript": {}, "stats": {b: {} for b in backends}}
for b in backends:
    res["models"][b] = T.gemini_model() if b == "gemini" else T.deepseek_model() if b == "deepseek" else "DeepL API"

for i, t in enumerate(tests):
    row = {**t, "tr": {}, "ex": {}}
    for b in backends:
        t0 = time.time()
        row["tr"][b], u = T.translate_line(t["text"], t["before"], t["after"], b)
        s = res["stats"][b]
        s["line_s"] = s.get("line_s", 0) + time.time() - t0
        s["line_cost"] = s.get("line_cost", 0) + cost(b, u)
        if b != "deepl":
            t0 = time.time()
            row["ex"][b], u = T.explain(t["word"], t["surface"], t["text"], t["before"], t["after"], b)
            s["ex_s"] = s.get("ex_s", 0) + time.time() - t0
            s["ex_cost"] = s.get("ex_cost", 0) + cost(b, u)
    res["lines"].append(row)
    print(f"{i + 1}/{len(tests)} {t['word']}")

vid = sys.argv[1] if len(sys.argv) > 1 else "NfLKaRfgIh4"
cues = requests.get(f"http://127.0.0.1:8766/subs?v={vid}", timeout=300).json()["cues"][:100]
lines = [c["text"] for c in cues]
res["transcript"] = {"vid": vid, "ko": lines, "en": {}}
for b in backends:
    t0 = time.time()
    res["transcript"]["en"][b], u = T.translate_lines(lines, b)
    s = res["stats"][b]
    s["tx_s"], s["tx_cost"], s["tx_retries"] = time.time() - t0, cost(b, u), u["retries"]
    s["tx_chars"] = u["chars"]
    print(f"transcript {b}: {s['tx_s']:.1f}s, ${s['tx_cost']:.4f}, retries {u['retries']}")

(HERE / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(res["stats"], indent=1))
