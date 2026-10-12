"""Load the KRDict XML download into krdict.sqlite (one-time).

    python yuja/build_dict.py
"""
import html
import io
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTROL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")  # the source XML has stray control chars
feat = lambda el, att: next((f.get("val") for f in el.findall("feat") if f.get("att") == att), None)

db = sqlite3.connect(HERE / "krdict.sqlite")
db.executescript("DROP TABLE IF EXISTS entries; CREATE TABLE entries (word TEXT, pos TEXT, level TEXT, defs TEXT);")
for zpath in HERE.glob("*한국어기초사전_xml*.zip"):
    z = zipfile.ZipFile(zpath)
    for name in z.namelist():
        for _, el in ET.iterparse(io.BytesIO(CONTROL.sub(b"", z.read(name)))):
            if el.tag != "LexicalEntry":
                continue
            defs = []
            for sense in el.findall("Sense"):
                en = next((e for e in sense.findall("Equivalent") if feat(e, "language") == "영어"), None)
                defs.append(f"{feat(en, 'lemma')}: {feat(en, 'definition')}" if en is not None else feat(sense, "definition"))
            db.execute("INSERT INTO entries VALUES (?, ?, ?, ?)",
                       (feat(el.find("Lemma"), "writtenForm"), feat(el, "partOfSpeech"), feat(el, "vocabularyLevel"),
                        html.unescape("\n".join(filter(None, defs)))))   # source double-escapes (&apos;)
            el.clear()
db.execute("CREATE INDEX word_idx ON entries(word)")

# Fallback for slang/loanwords KRDict lacks: Wiktionary via kaikki.org. Glosses are stored
# as "gloss: note" like KRDict's "gloss: definition"; romanizations "(meokda)" are dropped.
db.executescript("DROP TABLE IF EXISTS wikt; CREATE TABLE wikt (word TEXT, pos TEXT, level TEXT, defs TEXT);")
ROMAN = re.compile(r"\s*\([A-Za-z'-]+\)|(?<=\()[A-Za-z'-]+,\s*(?=“)")   # one-word romanizations only
for path in HERE.glob("kaikki*.jsonl"):
    with open(path, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            glosses = [ROMAN.sub("", s["glosses"][0]) for s in e.get("senses", []) if s.get("glosses")]
            if glosses:
                db.execute("INSERT INTO wikt VALUES (?, ?, NULL, ?)",
                           (e["word"], e.get("pos"), "\n".join(g if ": " in g else g + ": " for g in glosses)))
db.execute("CREATE INDEX wikt_idx ON wikt(word)")
db.commit()
print(db.execute("SELECT count(*) FROM entries").fetchone()[0], "entries")
