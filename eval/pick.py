"""Pick test lines for the translate/explain comparison: real lines from videos you watched,
each with exactly one unknown word (i+1), plus two lines of context either side.
Usage: python yuja/eval/pick.py  (needs the Yuja server running; writes eval/testset.json)"""
import json, random, re, sqlite3, sys
from pathlib import Path
import requests

HERE = Path(__file__).parent
sys.stdout.reconfigure(encoding="utf-8")
db = sqlite3.connect(f"file:{HERE.parent / 'yuja.sqlite'}?mode=ro", uri=True)
vids = [v for v, in db.execute("SELECT vid FROM watch GROUP BY vid ORDER BY SUM(seconds) DESC")]
vids += sorted({f.stem for f in (HERE.parent / "cache").glob("*.json")} - set(vids))   # then other cached videos
random.seed(7)
picked, seen = [], set()
for vid in vids:
    r = requests.get(f"http://127.0.0.1:8766/subs?v={vid}", timeout=300).json()
    if not r.get("cues") or (r.get("known_pct") or 0) < 50:     # skip non-Korean / far-too-hard videos
        continue
    cues, lines, mine = r["cues"], r["lines"], []
    for i, (c, ln) in enumerate(zip(cues, lines)):
        unk = [w for w in ln["words"] if w["status"] == "unknown" and w["cls"] in ("NOM", "PRED")
               and not w["tag"].startswith("NNP")]
        others = [w for w in ln["words"] if w["status"] == "unknown" and w not in unk and w["cls"] != "SYM"]
        if re.search(r"&gt;| [.,?!]", "".join(x["text"] for x in cues[max(0, i - 2):i + 3])):
            continue                                      # "&gt;&gt;" / "word ." = machine-made subtitles, not native lines
        if len(unk) == 1 and not others and 8 <= len(c["text"]) <= 45 and unk[0]["lemma"] not in seen:
            mine.append({"vid": vid, "start": c["start"], "text": c["text"], "word": unk[0]["lemma"], "tag": unk[0]["tag"],
                         "surface": c["text"][unk[0]["s"]:unk[0]["e"]],
                         "before": [x["text"] for x in cues[max(0, i - 2):i]], "after": [x["text"] for x in cues[i + 1:i + 3]]})
    for m in random.sample(mine, len(mine)):
        if m["word"] not in seen and sum(x["vid"] == vid for x in picked) < 3:   # varied: <= 3 lines per video
            seen.add(m["word"])
            picked.append(m)
    if len(picked) >= 20:
        break
picked = picked[:20]
(HERE / "testset.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1), encoding="utf-8")
for m in picked:
    print(f'{m["word"]:<8} {m["tag"]:<4} {m["text"]}')
print(len(picked), "lines from", len({m["vid"] for m in picked}), "videos")
