"""Yuja local server: parse, word statuses, dictionary lookup.

    python yuja/server.py      -> http://localhost:8766
"""
import base64
import csv
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from flask import Flask, jsonify, request
from korean_romanizer.romanizer import Romanizer

HERE = Path(__file__).resolve().parent

# Started by autostart (pythonw, no console), every yt-dlp/ffmpeg call would pop up its own
# console window on Windows. Launch them all windowless.
if os.name == "nt":
    _popen_init = subprocess.Popen.__init__
    subprocess.Popen.__init__ = lambda self, *a, **k: _popen_init(self, *a, **{"creationflags": subprocess.CREATE_NO_WINDOW, **k})
sys.path[:0] = [str(HERE.parent / "korean-parser"),
                os.path.expanduser("~/.claude/skills/sentence-mining/scripts")]

from analyze import get_known_intervals, load_word_list_known  # noqa: E402  (sentence-mining)
from _config import load_config  # noqa: E402
from kparse import Parser  # noqa: E402
from kparse.jev import Jev, api_key  # noqa: E402
from kparse.learner import coarse  # noqa: E402
import translate as TR  # noqa: E402  (yuja/translate.py: DeepSeek translate / explain / definitions)
from kparse.parser import HANGUL, choice, fix_key  # noqa: E402

STATUSES = ("unknown", "learning", "known", "ignored")
CFG = load_config()
try:
    INTERVALS = get_known_intervals(CFG)      # {lemma: days} from Anki + word lists
except RuntimeError:                          # Anki closed: word lists only
    INTERVALS = dict.fromkeys(load_word_list_known(CFG["known_words"]["word_lists"]), 21)
PARSER = Parser(jev=Jev() if api_key() else None)
DB = sqlite3.connect(HERE / "yuja.sqlite", check_same_thread=False)
DB_LOCK = threading.Lock()                    # requests + background scoring share one connection
DB.execute("CREATE TABLE IF NOT EXISTS status (key TEXT PRIMARY KEY, status TEXT)")
DICT = HERE / "krdict.sqlite"                 # built by build_dict.py
KR_POS = {"VV": "동사", "VX": "보조 동사", "VA": "형용사", "NNG": "명사", "NNP": "명사", "NNB": "의존 명사",
          "MAG": "부사", "MAJ": "부사", "MM": "관형사", "NP": "대명사", "NR": "수사", "IC": "감탄사",
          "XSN": "접사", "XPN": "접사"}

app = Flask(__name__)
app.register_error_handler(Exception, lambda e: (jsonify(error=str(e)), 500))   # the extension shows the message


def status(key: str) -> str:
    row = DB.execute("SELECT status FROM status WHERE key=?", (key,)).fetchone()
    if row:
        return row[0]
    ivl = INTERVALS.get(key, 0)
    return "known" if ivl >= 21 else "learning" if ivl > 0 else "unknown"


@app.post("/parse")
def parse():
    return jsonify(**analyze(request.json["lines"]))


PARSE_LOCK = threading.Lock()                 # thumbnail scoring parses in background threads too


def analyze(lines: list[str], use_jev: bool = True) -> dict:
    """Parse lines and attach statuses; known_pct = share of counted words you know."""
    out, known, total, seen = [{"text": l, "words": [], "grammar": []} for l in lines], 0, 0, []
    hangul = [i for i, l in enumerate(lines) if HANGUL.search(l)]  # parse_lines skips the rest
    with PARSE_LOCK:
        parsed = PARSER.parse_lines(lines, use_jev=use_jev)
    for i, line in zip(hangul, parsed):
        words = []
        for w in line.words:
            cls = coarse(w.tag)
            st = status(w.lemma) if cls != "SYM" else "ignored"
            words.append({"s": w.start, "e": w.end, "lemma": w.lemma, "tag": w.tag,
                          "cls": cls, "status": st})
            if st != "ignored":
                total += 1
                known += st == "known"
        grammar = [{**g, "key": f"GRAM:{g['name']}", "status": status(f"GRAM:{g['name']}")}
                   for g in line.grammar]
        out[i] = {"text": line.text, "words": words, "grammar": grammar}
        if use_jev:                                       # content you actually opened (not thumbnail scoring)
            seen += [(w["lemma"], w["tag"]) for w in words if w["status"] == "unknown" and w["tag"] != "NNP"]
            seen += [(g["key"], "GRAM") for g in grammar if g["status"] == "unknown"]
    if seen:
        with DB_LOCK:
            DB.executemany("INSERT INTO seen VALUES (?, ?, 1) ON CONFLICT(key) DO UPDATE SET n = n + 1", seen)
            DB.commit()
    return {"lines": out, "known_pct": round(100 * known / total, 1) if total else None}


# ---- YouTube subtitles: YouTube's Korean captions, else (if the user agrees) Soniox. Fetched in a
# background thread; the extension polls /subs, and asks before calling /transcribe.
SUBS = HERE / "cache"
JOBS: dict[str, str] = {}                     # video id -> "working" | "no-captions" | "transcribing" | error


def parse_vtt(text: str) -> list[dict]:
    """VTT or SRT -> [{start, end, text}]. Auto-captions (word-timed <c> tags) are
    rebuilt into sentences by sentence_cues; normal subtitles are kept as they are."""
    secs = lambda t: sum(float(x) * 60 ** i for i, x in enumerate(reversed(t.replace(",", ".").split(":"))))
    if "<c>" in text:
        return sentence_cues(text)
    cues = []
    for block in re.split(r"\n\n+", text.replace("\r", "")):
        m = re.search(r"([\d:.,]+) --> ([\d:.,]+)", block)       # SRT uses 00:00:01,360
        if not m:
            continue
        rows = [r for r in block[m.end():].split("\n")[1:] if r.strip()]
        line = re.sub(r"\[[^\]]*\]|<[^>]+>", "", " ".join(rows)).strip()   # drop [음악] and tags
        start, end = secs(m[1]), secs(m[2])
        if line and end - start > 0.05 and (not cues or cues[-1]["text"] != line):
            cues.append({"start": start, "end": end, "text": line})
    return cues


def sentence_cues(vtt: str) -> list[dict]:
    """Auto-captions are chopped every few words, not at sentences. They do time every
    word (<00:00:07.120><c> word</c>), so rebuild real sentences: collect the timed
    words, split with Kiwi's sentence splitter, and time each sentence by its words."""
    secs = lambda t: sum(float(x) * 60 ** i for i, x in enumerate(reversed(t.split(":"))))
    words, end = [], 0.0                                  # [(start_seconds, word)]
    for block in re.split(r"\n\n+", vtt.replace("\r", "")):
        m = re.search(r"([\d:.]+) --> ([\d:.]+)", block)
        line = next((r for r in block.split("\n") if "<c>" in r), None)
        if not m or not line:
            continue
        end = secs(m[2])
        line = re.sub(r"\[[^\]]*\]", "", line)            # drop [음악]
        first, *rest = re.split(r"<([\d:.]+)>", line)     # "w0", t1, "<c> w1</c>", t2, ...
        timed = [(secs(m[1]), first)] + [(secs(t), w) for t, w in zip(rest[::2], rest[1::2])]
        words += [(t, re.sub(r"<[^>]+>", "", w).strip()) for t, w in timed if re.sub(r"<[^>]+>", "", w).strip()]
    text, starts = "", []                                 # char offset -> word index
    for i, (_, w) in enumerate(words):
        starts.append(len(text))
        text += w + " "
    gap = lambda i: (words[i + 1][0] if i + 1 < len(words) else end) - words[i][0]

    def pieces(wi):
        """Split run-ons (> 45 chars) after the connective ending (-고, -는데, -서…) nearest the middle."""
        line = " ".join(words[i][1] for i in wi)
        if len(line) <= 45 or len(wi) < 2:
            return [wi]
        ends, pos = [], -1                                # char offset where each word ends
        for i in wi:
            pos += len(words[i][1]) + 1
            ends.append(pos)
        ec = {t.start + t.len for t in PARSER.kiwi.tokenize(line) if t.tag == "EC"}
        cuts = [k for k in range(len(wi) - 1) if ends[k] in ec] or range(len(wi) - 1)
        k = min(cuts, key=lambda k: abs(ends[k] - len(line) / 2))
        return pieces(wi[:k + 1]) + pieces(wi[k + 1:])

    cues = []
    for sent in PARSER.kiwi.split_into_sents(text):
        for wi in pieces([i for i, s in enumerate(starts) if sent.start <= s < sent.end]):
            if wi:
                last = words[wi[-1]][0]
                cues.append({"start": words[wi[0]][0], "end": min(last + gap(wi[-1]), last + 2.5),
                             "text": " ".join(words[i][1] for i in wi)})
    return cues


def soniox_cues(audio: Path) -> list[dict]:
    """Transcribe with the sentence-mining skill's Soniox script; group words into cues
    at pauses > 0.8s, sentence ends, or ~32 characters."""
    script = Path(os.path.expanduser("~/.claude/skills/sentence-mining/scripts/transcribe.py"))
    words = json.loads(subprocess.run([sys.executable, str(script), str(audio)], capture_output=True,
                                      text=True, encoding="utf-8", check=True).stdout)["words"]
    cues = []
    for w in words:
        c = cues[-1] if cues else None
        if c and w["start_ms"] / 1000 - c["end"] < 0.8 and len(c["text"]) < 32 and not c["text"].endswith((".", "?", "!")):
            c["text"] += " " + w["text"]
            c["end"] = w["end_ms"] / 1000
        else:
            cues.append({"start": w["start_ms"] / 1000, "end": w["end_ms"] / 1000, "text": w["text"]})
    return cues


def fetch_captions(vid: str) -> list[dict] | None:
    """YouTube's Korean captions as cues: uploaded Korean subtitles, else original-language
    Korean auto-captions; None otherwise. Never YouTube's machine-translated "Korean"
    (English videos offer one -- wrong text, and fetching those trips 429 rate limits)."""
    info = json.loads(subprocess.run(["yt-dlp", "-J", "--skip-download", f"https://www.youtube.com/watch?v={vid}"],
                                     capture_output=True, text=True, encoding="utf-8").stdout or "{}")
    auto = info.get("automatic_captions") or {}
    track = ((info.get("subtitles") or {}).get("ko") or auto.get("ko-orig")
             or (auto.get("ko") if info.get("language") == "ko" else None))
    url = next((t["url"] for t in track or [] if t.get("ext") == "vtt"), None)
    return parse_vtt(requests.get(url, timeout=30).text) if url else None


def save_cues(vid: str, cues: list[dict]) -> None:
    SUBS.mkdir(exist_ok=True)
    (SUBS / f"{vid}.json").write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")


def fetch_subs(vid: str, transcribe: bool = False) -> None:
    try:
        cues = None if transcribe else fetch_captions(vid)
        if cues is None and not transcribe:               # no Korean captions: the extension asks first
            SUBS.mkdir(exist_ok=True)
            (SUBS / f"{vid}.none").touch()
            JOBS[vid] = "no-captions"
            return
        if cues is None:                                  # the user said yes: transcribe the audio
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(["yt-dlp", "-f", "ba", "-o", f"{tmp}/a.%(ext)s", f"https://www.youtube.com/watch?v={vid}"],
                               capture_output=True, check=True)
                cues = soniox_cues(next(Path(tmp).glob("a.*")))
        save_cues(vid, cues)
        JOBS.pop(vid, None)
    except Exception as e:                                # surfaced to the extension via /subs
        JOBS[vid] = f"error: {e}"


# ---- Thumbnail scores: % known for videos with Korean captions (never transcribed).
# Kiwi only (no Jev) -- a percentage doesn't need that precision. Captions are cached,
# so opening a scored video later is instant.
SCORES: dict[str, float | None] = {}                 # vid -> % known, None = no Korean captions
SCORE_POOL = ThreadPoolExecutor(2)                   # gentle on YouTube (429s)
SCORING: set[str] = set()


def score_video(vid: str) -> None:
    try:
        cached = SUBS / f"{vid}.json"
        cues = json.loads(cached.read_text(encoding="utf-8")) if cached.exists() else fetch_captions(vid)
        if cues is None:
            SUBS.mkdir(exist_ok=True)
            (SUBS / f"{vid}.none").touch()                # remember "no captions" across restarts
        elif not cached.exists():
            save_cues(vid, cues)
        SCORES[vid] = cues and analyze([c["text"] for c in cues], use_jev=False)["known_pct"]
    except Exception:
        SCORES[vid] = None
    finally:
        SCORING.discard(vid)


@app.post("/scores")
def scores():
    """{vids: [...]} -> {vid: % known | null (no Korean captions) | "working"}"""
    out = {}
    for vid in request.json["vids"][:60]:
        if vid in SCORES or (SUBS / f"{vid}.none").exists():
            out[vid] = SCORES.get(vid)
        else:
            if vid not in SCORING:
                SCORING.add(vid)
                SCORE_POOL.submit(score_video, vid)
            out[vid] = "working"
    return jsonify(out)


# ---- Anki mining (note type, deck and fields from the sentence-mining config) ----
ANKI_URL = CFG.get("anki_connect_url", "http://127.0.0.1:8765").replace("localhost", "127.0.0.1")  # skip IPv6 stall
FIELDS = {"definition": "Definition", "word_audio": "Word Audio", "definition_audio": "Definition Audio", **CFG["field_map"]}

# Word / Definition Audio on mined cards (your template plays them front / back). edge-tts: free Microsoft
# neural voices, no key. The extension's ⚙ menu picks the voices (sent with each mine); these are the defaults.
VOICES = {"word": "ko-KR-SunHiNeural", "definition": "en-US-AvaNeural"}
VOICE_RE = re.compile(r"[a-z]{2,3}-[A-Z]{2,4}-\w+Neural")


def tts(text: str, voice: str, path: str) -> None:
    subprocess.run([sys.executable, "-m", "edge_tts", "--voice", voice, "--text", text, "--write-media", path],
                   capture_output=True, check=True, timeout=60)


def note_fields() -> list[str]:
    """The note type's fields (asked once): only fill audio fields it actually has."""
    if not hasattr(note_fields, "names"):
        note_fields.names = anki("modelFieldNames", modelName=CFG["note_type"])
    return note_fields.names


def anki(action: str, **params):
    r = requests.post(ANKI_URL, json={"action": action, "version": 6, "params": params}, timeout=30).json()
    if r.get("error"):
        raise RuntimeError(r["error"])
    return r["result"]


def in_deck(word: str) -> bool:
    return bool(anki("findNotes", query=f'deck:"{CFG["decks"]["main"]}" "{FIELDS["word"]}:{word}"'))


@app.get("/in_anki")
def in_anki():
    try:
        return jsonify(found=in_deck(request.args["word"]))
    except Exception:                                     # Anki closed
        return jsonify(found=None)


@app.get("/voices")
def voices():
    """Korean and English edge-tts voices for the ⚙ menu: [{name, label, lang}]."""
    if not hasattr(voices, "cache"):
        out = subprocess.run([sys.executable, "-m", "edge_tts", "--list-voices"], capture_output=True, text=True,
                             encoding="utf-8", timeout=60).stdout
        rows = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and VOICE_RE.fullmatch(parts[0]) and parts[0][:3] in ("ko-", "en-"):
                lang, region, who = parts[0].split("-", 2)
                rows.append({"name": parts[0], "lang": lang,
                             "label": f"{who.replace('MultilingualNeural', ' (multilingual)').replace('Neural', '')}"
                                      + (f" · {region}" if lang == "en" else "") + f" · {parts[1].lower()}"})
        voices.cache = rows
    return jsonify(voices=voices.cache)


@app.post("/speak")
def speak():
    """{voice, text} -> {audio: base64 mp3}: the ⚙ menu's voice preview."""
    j = request.json
    if not VOICE_RE.fullmatch(j.get("voice", "")):
        return jsonify(error="unknown voice")
    with tempfile.TemporaryDirectory() as tmp:
        tts(j["text"][:200], j["voice"], f"{tmp}/a.mp3")
        return jsonify(audio=base64.b64encode(Path(f"{tmp}/a.mp3").read_bytes()).decode())


# ---- AI help on the card (translate the line, explain the word) and the mined Definition ----
# Answers are cached forever by their exact input: each word-in-line is only ever asked once.
DB.execute("CREATE TABLE IF NOT EXISTS ai (k TEXT PRIMARY KEY, v TEXT)")
SPEAK_POOL = ThreadPoolExecutor(2)                   # word audio is made while the Definition is written


def ai(kind: str, j: dict) -> str:
    args = (j.get("word", ""), j.get("surface", ""), j["line"], j.get("before", [])[-2:], j.get("after", [])[:2])
    k = json.dumps([kind, *args], ensure_ascii=False)
    with DB_LOCK:
        row = DB.execute("SELECT v FROM ai WHERE k=?", (k,)).fetchone()
    if row:
        return row[0]
    if kind == "translate":
        text, _ = TR.translate_line(args[2], args[3], args[4])
    else:
        text, _ = (TR.explain if kind == "explain" else TR.concept)(*args)
    with DB_LOCK:
        DB.execute("INSERT OR REPLACE INTO ai VALUES (?, ?)", (k, text.strip()))
        DB.commit()
    return text.strip()


@app.post("/ai")
def ai_route():
    """{kind: translate | explain | concept, line, before?, after?, word?, surface?} -> {text} | {error}"""
    j = request.json
    try:
        return jsonify(text=ai(j["kind"], j))
    except Exception as e:                                # no key, network, rate limit: the card says so
        return jsonify(error=str(e)[:200])


MEDIA_LOCK = threading.Lock()                        # one 360p download per video, even with a batch running


def mine_one(j: dict) -> str | None:
    """{word, key, sentence (html), definition, ctx?, voices?, vid?, start?, end?} -> Anki note; returns the
    word's new status. Definition: one English line from the user's prompt (DeepSeek), the dictionary glosses
    the extension sent as fallback. An empty word makes a sentence card: Word, Definition and their audio left
    empty to fill in by hand (batches do this for lines with 0 or 2+ unknowns). Videos: audio clip + frame."""
    if not j.get("word"):
        j = {**j, "word": "", "key": "", "definition": "", "ctx": None}
    tmp_audio = tempfile.TemporaryDirectory()
    stem = f"yuja_{hashlib.sha1((j['key'] + j['sentence']).encode()).hexdigest()[:12]}"   # per word + sentence
    # Word Audio: the dictionary form, said in Korean (not bare endings like -ㄴ). Runs while the Definition is written.
    voice = {k: v if VOICE_RE.fullmatch(v or "") else VOICES[k] for k, v in {**VOICES, **(j.get("voices") or {})}.items()}
    speak = FIELDS["word_audio"] in note_fields() and j["word"] and not j["word"].startswith("-")
    word_mp3 = f"{stem}_word.mp3"
    word_job = SPEAK_POOL.submit(tts, j["word"], voice["word"], f"{tmp_audio.name}/{word_mp3}") if speak else None
    definition = j["definition"]
    if j.get("ctx"):
        try:
            definition = ai("concept", j["ctx"])
        except Exception:
            pass                                          # keep the dictionary glosses
    fields = {FIELDS["word"]: j["word"], FIELDS["sentence"]: j["sentence"], FIELDS["definition"]: definition}
    audio = []                                            # (field, mp3 name), stored in Anki below
    if FIELDS["definition_audio"] in note_fields() and definition:
        def_mp3 = f"{stem}_def.mp3"
        try:
            tts(re.sub(r"<[^>]+>", " ", definition.replace("<br>", ". ")), voice["definition"], f"{tmp_audio.name}/{def_mp3}")
            audio.append((FIELDS["definition_audio"], def_mp3))
        except Exception:
            pass                                          # a card without definition audio beats no card
    if word_job:
        try:
            word_job.result()
            audio.append((FIELDS["word_audio"], word_mp3))
        except Exception:
            pass
    for field, name in audio:
        anki("storeMediaFile", filename=name, path=f"{tmp_audio.name}/{name}")
        fields[field] = f"[sound:{name}]"
    tmp_audio.cleanup()
    if j.get("vid"):
        name = f"yuja_{safe(j['vid'])}_{int(j['start'] * 1000)}"
        media = SUBS / f"{safe(j['vid'])}.mp4"      # YouTube: whole video at 360p, downloaded on the first mine
        if not media.exists() and j["vid"].startswith("local:"):    # local: the player page uploads it first
            raise RuntimeError("local video not uploaded")
        with MEDIA_LOCK:
            if not media.exists():                  # (YouTube 403s yt-dlp's partial --download-sections)
                subprocess.run(["yt-dlp", "-f", "bv*[height<=360]+ba/b[height<=360]/b", "--merge-output-format", "mp4",
                                "-o", str(media), f"https://www.youtube.com/watch?v={j['vid']}"], capture_output=True, check=True)
        with tempfile.TemporaryDirectory() as tmp:
            span = ["-ss", f"{j['start']:.2f}", "-to", f"{j['end'] + 0.3:.2f}", "-i", str(media)]
            subprocess.run(["ffmpeg", "-y", *span, "-vn", "-q:a", "4", f"{tmp}/{name}.mp3"], capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-y", "-ss", f"{(j['start'] + j['end']) / 2:.2f}", "-i", str(media), "-frames:v", "1",
                            "-vf", "scale=640:-2", f"{tmp}/{name}.jpg"], capture_output=True, check=True)
            for ext in ("mp3", "jpg"):
                anki("storeMediaFile", filename=f"{name}.{ext}", path=f"{tmp}/{name}.{ext}")
        fields[FIELDS["sentence_audio"]] = f"[sound:{name}.mp3]"
        fields[FIELDS["picture"]] = f'<img src="{name}.jpg">'
    anki("addNote", note={"deckName": CFG["decks"]["main"], "modelName": CFG["note_type"], "fields": fields,
                          "tags": ["yuja"], "options": {"allowDuplicate": True}})
    with DB_LOCK:
        DB.execute("INSERT INTO mined VALUES (datetime('now','localtime'), ?)", (j["key"],))
        if j["key"] and status(j["key"]) == "unknown":    # mined words become Learning, like Migaku
            DB.execute("INSERT OR REPLACE INTO status VALUES (?, 'learning')", (j["key"],))
        DB.commit()
    return status(j["key"]) if j["key"] else None


@app.post("/mine")
def mine():
    try:
        return jsonify(ok=True, status=mine_one(request.json))
    except Exception as e:
        return jsonify(error=str(e)[:300])


# ---- Batch mining (subtitle browser): the cards are made one by one in the background, so it keeps
# going if you switch videos; the extension polls for progress.
BATCHES: dict[str, dict] = {}


def run_batch(bid: str) -> None:
    b = BATCHES[bid]
    for i, j in enumerate(b["items"]):
        try:
            b["results"][i] = {"ok": True, "key": j.get("key") or "", "status": mine_one(j)}
        except Exception as e:                            # one bad line doesn't stop the batch
            b["results"][i] = {"ok": False, "error": str(e)[:200]}
    b["done"] = True


@app.post("/mine_batch")
def mine_batch():
    """{items: [mine payloads]} -> {id}; GET /mine_batch?id= -> {done, total, results: [null | {ok, key, status, error}]}"""
    bid = hashlib.sha1(os.urandom(8)).hexdigest()[:10]
    items = request.json["items"]
    BATCHES[bid] = {"items": items, "results": [None] * len(items), "done": not items}
    threading.Thread(target=run_batch, args=(bid,), daemon=True).start()
    return jsonify(id=bid)


@app.get("/mine_batch")
def mine_batch_status():
    b = BATCHES.get(request.args["id"])
    return jsonify(error="unknown batch") if b is None else jsonify(done=b["done"], total=len(b["items"]), results=b["results"])


# ---- Local videos (player page): subtitles come from the dropped .srt/.vtt; the video
# itself is uploaded once (from disk to localhost, so fast) the first time you mine from it.
safe = lambda vid: re.sub(r"[^\w.-]", "_", vid)


# ---- Whole-transcript English for the listening modes (Primed: read the English first). DeepSeek with the
# translate-srt protocol + numbered lines, made in the background once per video and kept in cache/.
EN_JOBS: dict[str, str] = {}                         # vid -> "working" | error


def make_english(vid: str, lines: list[str]) -> None:
    try:
        en, _ = TR.translate_lines(lines)
        (SUBS / f"{safe(vid)}.en.json").write_text(json.dumps({"ko": lines, "en": en}, ensure_ascii=False), encoding="utf-8")
        EN_JOBS.pop(vid, None)
    except Exception as e:
        EN_JOBS[vid] = f"error: {str(e)[:200]}"


@app.post("/english")
def english():
    """{vid, lines} -> {en: [...]} once translated, else {status: "working" | "error: ..."}; the first call starts it.
    Cached per video; redone if the lines changed (e.g. a different subtitle file)."""
    j = request.json
    vid, lines = j["vid"], j["lines"]
    f = SUBS / f"{safe(vid)}.en.json"
    if f.exists():
        cached = json.loads(f.read_text(encoding="utf-8"))
        if cached["ko"] == lines:
            return jsonify(en=cached["en"])
    if EN_JOBS.get(vid, "").startswith("error"):
        return jsonify(status=EN_JOBS.pop(vid))            # report once; asking again retries
    if vid not in EN_JOBS:
        EN_JOBS[vid] = "working"
        SUBS.mkdir(exist_ok=True)
        threading.Thread(target=make_english, args=(vid, lines), daemon=True).start()
    return jsonify(status=EN_JOBS[vid])


# ---- Primed Summaries listening mode: topical chunks with English summaries (dojo-prompts primed-summaries),
# written window by window in the background; the extension uses whatever chunks are ready so far.
SUM_JOBS: dict[str, dict] = {}                       # vid -> {"chunks": [...], "done": bool, "error": str?}


def make_summaries(vid: str, lines: list[str]) -> None:
    job = SUM_JOBS[vid]
    try:
        chunks, _ = TR.summarize(lines, progress=lambda ch: job.update(chunks=ch))
        (SUBS / f"{safe(vid)}.sum.json").write_text(json.dumps({"ko": lines, "chunks": chunks}, ensure_ascii=False), encoding="utf-8")
        job.update(chunks=chunks, done=True)
    except Exception as e:
        job.update(error=str(e)[:200], done=True)


@app.post("/summaries")
def summaries():
    """{vid, lines} -> {chunks: [{start, end, summary}] (1-based lines), done, error?}; the first call starts it."""
    j = request.json
    vid, lines = j["vid"], j["lines"]
    f = SUBS / f"{safe(vid)}.sum.json"
    if f.exists():
        cached = json.loads(f.read_text(encoding="utf-8"))
        if cached["ko"] == lines:
            return jsonify(chunks=cached["chunks"], done=True)
    job = SUM_JOBS.get(vid)
    if job and job.get("error"):
        SUM_JOBS.pop(vid)                                 # report once; asking again retries
        return jsonify(chunks=job["chunks"], done=True, error=job["error"])
    if not job:
        job = SUM_JOBS[vid] = {"chunks": [], "done": False}
        SUBS.mkdir(exist_ok=True)
        threading.Thread(target=make_summaries, args=(vid, lines), daemon=True).start()
    return jsonify(chunks=job["chunks"], done=job["done"])


@app.post("/local/subs")
def local_subs():
    vid, cues = request.json["vid"], parse_vtt(request.json["text"])
    marks = [r[0] for r in DB.execute("SELECT start FROM bookmark WHERE vid=?", (vid,))]
    return jsonify(cues=cues, bookmarks=marks, **analyze([c["text"] for c in cues]))


@app.post("/local/media")
def local_media():
    SUBS.mkdir(exist_ok=True)
    with open(SUBS / f"{safe(request.args['vid'])}.mp4", "wb") as f:
        while chunk := request.stream.read(1 << 20):
            f.write(chunk)
    return jsonify(ok=True)


# ---- Stats: known words per day, minutes watched, cards mined, most-seen unknown words ----
DB.executescript("""
CREATE TABLE IF NOT EXISTS daily (date TEXT PRIMARY KEY, known INT);
CREATE TABLE IF NOT EXISTS watch (date TEXT, vid TEXT, seconds INT, PRIMARY KEY (date, vid));
CREATE TABLE IF NOT EXISTS mined (ts TEXT, key TEXT);
CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY, tag TEXT, n INT);
""")


def snapshot_known() -> int:
    """Today's known-word total (Anki/word lists + your statuses); one row per day."""
    known = {k for k, ivl in INTERVALS.items() if ivl >= 21 and HANGUL.search(k)}   # word lists also hold "!" etc.
    for k, st in DB.execute("SELECT key, status FROM status"):
        (known.add if st == "known" else known.discard)(k)
    # The word-list loader adds a "-다" twin to every entry (주식 + 주식다) to match verb stems: count once.
    n = len({k[:-1] if k.endswith("다") and k[:-1] in known else k for k in known})
    with DB_LOCK:
        DB.execute("INSERT OR REPLACE INTO daily VALUES (date('now','localtime'), ?)", (n,))
        DB.commit()
    return n


@app.post("/watch")
def watch():
    """Heartbeat from a playing video: {vid, seconds}."""
    with DB_LOCK:
        DB.execute("INSERT INTO watch VALUES (date('now','localtime'), ?, ?) ON CONFLICT(date, vid) DO UPDATE SET seconds = seconds + ?",
                   (request.json["vid"], request.json["seconds"], request.json["seconds"]))
        DB.commit()
    return jsonify(ok=True)


@app.get("/stats")
def stats():
    snapshot_known()
    q = lambda sql: DB.execute(sql).fetchall()
    top = [(k, t, n) for k, t, n in q("SELECT key, tag, n FROM seen ORDER BY n DESC LIMIT 200") if status(k) == "unknown"][:30]
    return jsonify(
        known=[{"date": d, "value": v} for d, v in q("SELECT date, known FROM daily ORDER BY date")],
        watch=[{"date": d, "value": round(s / 60)} for d, s in q("SELECT date, SUM(seconds) FROM watch GROUP BY date ORDER BY date")],
        mined=[{"date": d, "value": n} for d, n in q("SELECT date(ts), COUNT(*) FROM mined GROUP BY date(ts) ORDER BY date(ts)")],
        unknown=[{"key": k, "tag": t, "n": n, "rank": RANKS.get(k)} for k, t, n in top])


@app.get("/subs")
def subs():
    vid = request.args["v"]
    cached = SUBS / f"{vid}.json"
    if cached.exists():
        cues = json.loads(cached.read_text(encoding="utf-8"))
        marks = [r[0] for r in DB.execute("SELECT start FROM bookmark WHERE vid=?", (vid,))]
        return jsonify(cues=cues, bookmarks=marks, **analyze([c["text"] for c in cues]))
    if JOBS.get(vid, "").startswith("error"):            # report once; opening the video again retries
        return jsonify(status=JOBS.pop(vid))
    if vid not in JOBS and (SUBS / f"{vid}.none").exists():
        JOBS[vid] = "no-captions"                         # known from an earlier check or thumbnail scoring
    if vid not in JOBS:
        JOBS[vid] = "working"
        threading.Thread(target=fetch_subs, args=(vid,), daemon=True).start()
    return jsonify(status=JOBS[vid])


@app.post("/transcribe")
def transcribe():
    """{vid} -> start transcribing a video without Korean captions (the user agreed in the extension)."""
    vid = request.json["vid"]
    if JOBS.get(vid) != "transcribing" and not (SUBS / f"{vid}.json").exists():
        JOBS[vid] = "transcribing"
        threading.Thread(target=fetch_subs, args=(vid, True), daemon=True).start()
    return jsonify(status=JOBS.get(vid, "done"))


# ---- Your parse fixes: pick another reading in the card; it applies wherever that text appears ----
DB.execute("CREATE TABLE IF NOT EXISTS correction (surface TEXT PRIMARY KEY, choice TEXT)")
PARSER.corrections = {k: json.loads(c) for k, c in DB.execute("SELECT surface, choice FROM correction")}   # surface = fix_key


@app.post("/alternatives")
def alternatives():
    """{text, s, e} -> the ambiguous spans overlapping [s, e) with every reading Kiwi considered."""
    j = request.json
    with PARSE_LOCK:
        a = PARSER.analyze(j["text"])
    return jsonify(spans=[{
        "surface": j["text"][r.start:r.end], "key": fix_key(j["text"], r.start, r.end), "s": r.start, "e": r.end,
        "options": [{"label": o.describe(), "choice": [list(choice(u)) for u in o.units]} for o in r.options if o.units]}
        for r in a.regions if r.start < j["e"] and r.end > j["s"] and len(r.options) > 1])


@app.post("/correct")
def correct():
    """{text, key, choice} -> saves the fix, returns the line re-parsed with it."""
    j = request.json
    DB.execute("INSERT OR REPLACE INTO correction VALUES (?, ?)", (j["key"], json.dumps(j["choice"], ensure_ascii=False)))
    DB.commit()
    PARSER.corrections[j["key"]] = j["choice"]
    return jsonify(line=analyze([j["text"]])["lines"][0])


@app.post("/status")
def set_status():
    key, st = request.json["key"], request.json["status"]
    assert st in STATUSES
    DB.execute("INSERT OR REPLACE INTO status VALUES (?, ?)", (key, st))
    DB.commit()
    snapshot_known()
    return jsonify(ok=True)


BOILERPLATE = re.compile(r"^(?:an?|the)\s+(?:[\w-]+\s+){0,2}?(?:expression|ending(?: of a word)?|particle|bound noun|"
                         r"suffix|prefix)\s+(?:that serves as\s+|used\s+)?(?:to indicate\s+|to mean\s+|when\s+)?(?:that\s+)?", re.I)
LEVEL = {"초급": 0, "중급": 1, "고급": 2}   # KRDict vocabulary level: common senses are beginner words
letters = lambda s: re.sub(r"[^a-z]", "", s.lower())


def sense(raw: str, word: str) -> dict:
    """'-eot-: An ending of a word used to indicate that an event happened…' ->
    {gloss: '', def: 'An event happened…'}: no romanization, no boilerplate."""
    gloss, _, d = raw.partition(": ") if ": " in raw else ("", "", raw)
    note = re.match(r"\((.*?)\)\s*", d)
    d = re.sub(r"^To\s+", "", BOILERPLATE.sub("", d[note.end():] if note else d), flags=re.I).strip()
    # KRDict "glosses" grammar and counters with their romanization (nyeon, -eul geot): drop those.
    if gloss.startswith("(no equivalent") or letters(gloss) == letters(Romanizer(word.strip("-")).romanize()):
        gloss = ""
    return {"gloss": " · ".join(gloss.split("; ")[:3]), "def": d[:1].upper() + d[1:],
            "note": note.group(1) if note else ""}


def grammar_glosses() -> dict:
    """Pattern name -> (notation, gloss) from your curated grammar list, via the
    '# #123' comment above each template in kiwi-ankimorphs' patterns.py."""
    ka = HERE.parent / "kiwi-ankimorphs"
    records = {r["number"]: r for r in json.loads((ka / "data/grammar_records.json").read_text(encoding="utf-8"))}
    out, num, names = {}, None, []
    for line in (ka / "kiwi_ankimorphs/patterns.py").read_text(encoding="utf-8").splitlines():
        if m := re.match(r"\s*# #(\d+)", line):
            num = int(m[1])
        elif re.match(r"\s*# ---", line):
            num = None                                   # new section: the last #NNN no longer applies
        elif m := re.search(r'PatternTemplate\("([^"]+)"', line):
            names.append(m[1])
            if num in records:
                out[m[1]] = (records[num]["pattern"], records[num]["gloss"])
    for n in names:                                      # uncommented ones
        twin = re.sub(r"^ㄹ_", "을_", re.sub(r"^ㄴ_", "은_", n))      # vowel-stem twin: ㄹ_줄_알다 <- 을_줄_알다
        text = n.replace("_", " ")
        out.setdefault(n, out.get(twin) or out.get("으" + n) or next(
            ((r["pattern"], r["gloss"]) for r in records.values() if text in r["pattern"]), None))
    return {k: v for k, v in out.items() if v}


GRAMMAR = grammar_glosses()


def dict_forms(lemma: str, tag: str) -> list[str]:
    """KRDict headword spellings to try: endings are -어요 / -었-, patterns -을 것 같다."""
    if lemma.startswith("GRAM:"):
        n = lemma[5:].replace("_", " ")
        return [f"-{n}", f"-{n.replace(' ', '')}", *(f"-{p} {n}" for p in ("는", "은", "을", "ㄴ", "ㄹ", "기")), n]
    if tag == "EP":
        return [f"-{lemma}-", f"-{lemma}"]
    if tag == "XR":
        return [lemma + "하다", lemma]           # 어떡 -> 어떡하다
    return ([f"-{lemma}", lemma] if tag[:1] == "E" or tag in ("XSN", "XSV", "XSA")
            else [f"{lemma}-", lemma] if tag == "XPN" else [lemma])


# Kimchi Reader's frequency list (same source as your known words), for the card's #rank.
RANKS = {w: int(r) for r, w in csv.reader(open(HERE.parent / "kiwi-ankimorphs/data/kimchireader_lemma_frequency.csv",
                                               encoding="utf-8-sig")) if r.isdigit()}


@app.get("/lookup")
def lookup():
    lemma = request.args["lemma"]
    return jsonify(entries=entries_for(lemma, request.args.get("tag", "")), rank=RANKS.get(lemma))


def entries_for(lemma: str, tag: str) -> list[dict]:
    if not DICT.exists():
        return []
    tag = tag.split("-")[0]                                       # VA-I -> VA
    with sqlite3.connect(DICT) as d:
        rows = next((r for table in ("entries", "wikt") for w in dict_forms(lemma, tag)   # KRDict, else Wiktionary
                     if (r := d.execute(f"SELECT word, pos, level, defs FROM {table} WHERE word=?", (w,)).fetchall())), [])
    # Homonyms: matching part of speech, then commonest level (년 "year" before the insult),
    # then most senses (먹다 "eat" before "be deaf").
    pos = "조사" if tag.startswith("J") else KR_POS.get(tag)
    rows.sort(key=lambda r: (r[1] != pos, LEVEL.get(r[2], 3), -r[3].count("\n")))
    entries = [{"word": w, "pos": p, "level": LEVEL.get(lv), "senses": [sense(s, w) for s in defs.split("\n")]}
               for w, p, lv, defs in rows]
    if lemma.startswith("GRAM:") and (g := GRAMMAR.get(lemma[5:])):   # your grammar list's gloss leads
        notation, gloss = g
        entries = entries or [{"word": notation, "pos": "표현", "senses": [{"gloss": "", "def": notation, "note": ""}]}]
        entries[0]["senses"][0]["gloss"] = gloss
    return entries


# ---- Recommended sentences: Jev rates each i+1 line as an example of its unknown item ----
QUALITY = {"type": "score", "criteria": [
    "Vague or a fragment: the word's meaning can't be worked out from this sentence",
    "Understandable, but the word's meaning is only loosely implied",
    "Clear and natural: the context shows what the word means",
]}


@app.post("/quality")
def quality():
    """{items: [{text, key, tag}]} -> {scores: [0..1 | null]}, 1 = an excellent example sentence."""
    items = request.json["items"]
    if PARSER.jev is None:
        return jsonify(scores=[None] * len(items))
    def ask(batch):
        qs = {}
        for i, it in enumerate(batch):
            senses = (entries_for(it["key"], it["tag"]) or [{"senses": [{}]}])[0]["senses"]
            meaning = senses[0].get("gloss") or senses[0].get("def") or ""
            word = it["key"].removeprefix("GRAM:").replace("_", " ")
            qs[f"q{i}"] = {**QUALITY, "instructions": {
                "task": "Rate this Korean subtitle line as an example sentence for learning the target word.",
                "sentence": it["text"], "target_word": word, "meaning": meaning}}
        answers = PARSER.jev.ask("Korean learner example-sentence rating", qs)
        return [answers.get(f"q{i}", {}).get("score") for i in range(len(batch))]
    with ThreadPoolExecutor(8) as pool:
        batches = [items[i:i + 20] for i in range(0, len(items), 20)]
        scores = [s for b in pool.map(ask, batches) for s in b]
    return jsonify(scores=[None if s is None else round(s / (len(QUALITY["criteria"]) - 1), 2) for s in scores])


# ---- Bookmarked lines ----
DB.execute("CREATE TABLE IF NOT EXISTS bookmark (vid TEXT, start REAL, PRIMARY KEY (vid, start))")


@app.post("/bookmark")
def bookmark():
    j = request.json
    DB.execute("INSERT OR IGNORE INTO bookmark VALUES (?, ?)" if j["on"] else "DELETE FROM bookmark WHERE vid=? AND start=?",
               (j["vid"], j["start"]))
    DB.commit()
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(port=8766)
