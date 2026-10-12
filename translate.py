"""Translation and in-context explanations for Yuja, with swappable backends (gemini, deepseek, deepl).

Whole transcripts follow the dojo-prompts translate-srt protocol: chunks of 50 lines with 5 lines of
untranslated context either side, exactly one output line per input line (retried on a mismatch,
never padded), faithful over smooth, the Korean kept in parentheses when English has no clean word.
Each line is numbered (#12: ...) and must come back with its number: a plain block count passed while
Gemini drifted every line one off, so the numbers are what keep translations on their own timecodes.

Keys come from the environment or yuja/.env: GEMINI_API_KEY, DEEPSEEK_API_KEY, DEEPL_API_KEY.
"""
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).parent
CHUNK, CONTEXT, RETRIES = 50, 5, 3
DEFAULT = "deepseek"   # won the 2026-10 blind test (eval/): most faithful, line-aligned, best explanations


def key(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name].strip()
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name and v.strip():
                return v.split("#")[0].strip().strip('"').strip("'")
    return None


# ---- backends: llm(backend, system, user) -> (text, {"in": tokens, "out": tokens}) ----
_models: dict[str, str] = {}


def gemini_model() -> str:
    """Newest Flash-Lite the key can use (names change with each release)."""
    if "gemini" not in _models:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                         headers={"x-goog-api-key": key("GEMINI_API_KEY")}, timeout=30)
        r.raise_for_status()
        names = [m["name"].split("/")[-1] for m in r.json()["models"]
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        lite = sorted((n for n in names if re.fullmatch(r"gemini-[\d.]+-flash-lite", n)),   # not -tts/-image/-preview
                      key=lambda n: [int(x) for x in re.findall(r"\d+", n)])
        _models["gemini"] = lite[-1] if lite else "gemini-flash-lite-latest"
    return _models["gemini"]


def deepseek_model() -> str:
    if "deepseek" not in _models:
        r = requests.get("https://api.deepseek.com/models", headers={"Authorization": f"Bearer {key('DEEPSEEK_API_KEY')}"}, timeout=30)
        r.raise_for_status()
        ids = [m["id"] for m in r.json()["data"]]
        _models["deepseek"] = next((i for i in ids if "flash" in i), "deepseek-chat" if "deepseek-chat" in ids else ids[0])
    return _models["deepseek"]


def llm(backend: str, system: str, user: str, think: bool = True) -> tuple[str, dict]:
    if backend == "gemini":
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model()}:generateContent",
                          headers={"x-goog-api-key": key("GEMINI_API_KEY")}, timeout=180,
                          json={"systemInstruction": {"parts": [{"text": system}]},
                                "contents": [{"role": "user", "parts": [{"text": user}]}],
                                "generationConfig": {"temperature": 0.2}})
        r.raise_for_status()
        j = r.json()
        text = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        u = j.get("usageMetadata", {})
        return text, {"in": u.get("promptTokenCount", 0), "out": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)}
    if backend == "deepseek":
        r = requests.post("https://api.deepseek.com/chat/completions", timeout=180,
                          headers={"Authorization": f"Bearer {key('DEEPSEEK_API_KEY')}"},
                          json={"model": deepseek_model(), "temperature": 0.2,
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                                **({} if think else {"thinking": {"type": "disabled"}})})
        r.raise_for_status()
        j = r.json()
        u = j.get("usage", {})
        return j["choices"][0]["message"]["content"], {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}
    raise ValueError(f"{backend} is not a language model")


def deepl(texts: list[str], context: str = "") -> tuple[list[str], dict]:
    """DeepL translates line by line; surrounding lines go in `context` (used, not translated, not billed)."""
    k = key("DEEPL_API_KEY")
    host = "api-free.deepl.com" if k.endswith(":fx") else "api.deepl.com"
    body = {"text": texts, "source_lang": "KO", "target_lang": "EN-US"}
    if context:
        body["context"] = context
    r = requests.post(f"https://{host}/v2/translate", headers={"Authorization": f"DeepL-Auth-Key {k}"}, json=body, timeout=60)
    r.raise_for_status()
    return [t["text"] for t in r.json()["translations"]], {"chars": sum(len(t) for t in texts)}


# ---- transcripts (and single lines) ----
SYSTEM = """You translate user-provided Korean subtitles into English for the user's private language-learning study.
The user supplied this text so they can understand what was said in Korean. Treat this as translation of provided
excerpts for personal study, not publication of a subtitle file; subtitle format alone is not a reason to decline."""

RULES = """Translate ONLY the numbered lines between "=== TRANSLATE THE FOLLOWING ===" and "=== END TRANSLATE ===".
Do NOT translate the context sections; they are there so you understand who is talking and what about.

There are EXACTLY {n} numbered lines, #{first} to #{last}. Output exactly {n} lines, each starting with the SAME
number as the line it translates, in order: "#{first}: ...", then "#{second}: ...", and so on.

CRITICAL RULES:
- Each numbered line is shown on screen at its own time. Translate each one ON ITS OWN: never move words or
  meaning from one numbered line to another, even when a sentence continues across several lines. A fragment
  stays a fragment; a line that ends mid-sentence ends mid-sentence in English too.
- Lines starting with "- " indicate a speaker change. Preserve the "- " prefix after the number.
- These subtitles are for LANGUAGE LEARNING. Faithfulness to the Korean is more important than natural-sounding English. The reader is trying to understand what was said, not read a polished script.
- Translate each line fully. Do not skip lines, merge lines, summarize, compress, or replace content with explanations.
- Preserve the structure and nuance of the original. If a sentence is awkward or roundabout, reflect that; don't clean it up into smooth English.
- When a Korean word or phrase has no clean English equivalent, include the original in parentheses in Korean script (never romanized), e.g. "it's so frustrating (답답해)"
- Never use square brackets of any kind.
- Keep proper nouns (names, places) in their original form.
- If the text is ordinary dialogue, narration, or on-screen text, translate it.

Write ONLY the {n} numbered translations, one per line. No extra text, no explanations, no headers."""


def chunk_prompt(lines: list[str], start: int, end: int) -> str:
    """Lines to translate are numbered by their position in the whole transcript; context lines are not numbered."""
    flat = lambda ls: "\n".join(l.replace("\n", " ") for l in ls)
    before, after = lines[max(0, start - CONTEXT):start], lines[end:end + CONTEXT]
    out = []
    if before:
        out.append(f"=== CONTEXT BEFORE (do NOT translate, reference only) ===\n{flat(before)}\n=== END CONTEXT BEFORE ===\n")
    body = "\n".join(f"#{i + 1}: {lines[i].replace(chr(10), ' ')}" for i in range(start, end))
    out.append(f"=== TRANSLATE THE FOLLOWING ===\n{body}\n=== END TRANSLATE ===\n")
    if after:
        out.append(f"=== CONTEXT AFTER (do NOT translate, reference only) ===\n{flat(after)}\n=== END CONTEXT AFTER ===\n")
    n = end - start
    return "\n".join(out) + "\n" + RULES.format(n=n, first=start + 1, second=start + 2, last=end)


def parse_numbered(text: str, start: int, end: int) -> list[str] | None:
    """The translations in order, or None unless every number start+1..end comes back exactly once, in order,
    non-empty, with nothing else (a model that reflows text across lines has to break the numbering to do it)."""
    rows = [r.strip() for r in text.strip().splitlines() if r.strip()]
    got = [re.match(r"#(\d+):\s*(.*)", r) for r in rows]
    if any(m is None for m in got) or [int(m[1]) for m in got] != list(range(start + 1, end + 1)):
        return None
    out = [m[2].strip() for m in got]
    return out if all(out) else None


def translate_chunk(lines: list[str], start: int, end: int, backend: str) -> tuple[list[str], dict]:
    usage = {"in": 0, "out": 0, "chars": 0, "retries": 0}
    if backend == "deepl":
        ctx = " ".join(lines[max(0, start - CONTEXT):start] + lines[end:end + CONTEXT])
        out, u = deepl(lines[start:end], ctx)
        usage["chars"] = u["chars"]
        return out, usage
    for attempt in range(RETRIES + 1):
        try:
            text, u = llm(backend, SYSTEM, chunk_prompt(lines, start, end))
        except requests.RequestException:                 # dropped connection, 429, 5xx: back off and try again
            usage["retries"] += 1
            time.sleep(2 * (attempt + 1))
            continue
        usage["in"] += u["in"]
        usage["out"] += u["out"]
        blocks = parse_numbered(text, start, end)
        if blocks:
            return blocks, usage
        usage["retries"] += 1
    raise RuntimeError(f"{backend}: lines {start + 1}-{end} came back misnumbered {RETRIES + 1} times")


def translate_lines(lines: list[str], backend: str = DEFAULT) -> tuple[list[str], dict]:
    """Whole transcript, 3 chunks at a time (~4 min for a 36-minute video; 6 at a time was no faster, DeepSeek
    dropped connections instead). Returns one English line per Korean line, plus usage totals."""
    spans = [(s, min(s + CHUNK, len(lines))) for s in range(0, len(lines), CHUNK)]
    with ThreadPoolExecutor(3) as pool:
        results = list(pool.map(lambda sp: translate_chunk(lines, *sp, backend), spans))
    out, total = [], {"in": 0, "out": 0, "chars": 0, "retries": 0}
    for blocks, u in results:
        out += blocks
        for k in total:
            total[k] += u[k]
    return out, total


def translate_line(line: str, before: list[str], after: list[str], backend: str = DEFAULT) -> tuple[str, dict]:
    """One subtitle line, translated with its neighbours as context (same protocol as transcripts)."""
    lines = before + [line] + after
    i = len(before)
    if backend == "deepl":
        out, u = deepl([line], " ".join(before + after))
        return out[0], {"chars": u["chars"]}
    blocks, u = translate_chunk(lines, i, i + 1, backend)
    return blocks[0], u


# ---- explain a word in context ----
EXPLAIN = """You explain Korean to an English-speaking learner who is watching Korean videos.
Explain the target word AS IT IS USED IN THIS LINE, in plain English: 1 or 2 short sentences, under 40 words.
Say what it means here and the one thing a learner would miss (its form in this line, or a nuance), if anything.
No preamble, no headings, no romanization, no square brackets. Quote Korean in Korean script."""

# The user's own Definition prompt (2026-10-10), used verbatim; the definition is also read aloud on the card.
CONCEPT = """This will be read aloud on a flashcard. The learner has heard the Korean word in a sentence and needs to understand what it means.
Explain simply and naturally, as you would to a friend. Don't just give an English translation; explain what the word actually means. For simple, concrete things, just say what it is. Define the word's core meaning, not what it means in this specific sentence; the right level is where the sentence meaning becomes obvious.
One sentence. 15 words max. No em dashes; use semicolons to connect ideas. English only. Don't define other words in the sentence. Don't use the Korean word in the sentence.
Examples:
책 / 이건 좋은 책이에요. → A book.
단백질 / 단백질이 많이 필요해요. → Protein.
좋아하다 / 저는 와인을 좋아해요. → The feeling of "that's nice, I want more of that."
나오다 / 방에서 나왔어요. → To come out or emerge from somewhere.
씨 / 당신은 톰 씨예요? → Attached to a person's name to show respect.
좋다 / 저 사람은 좋은 사람이에요. → Good, pleasing, or satisfying.
Word: {word}
Sentence (for context only): {sentence}"""


def concept(word: str, surface: str, line: str, before: list[str], after: list[str], backend: str = DEFAULT,
            think: bool = True) -> tuple[str, dict]:
    """The card's Definition when mining. Only the word and its sentence go in, as in the user's prompt."""
    text, u = llm(backend, "Answer with only the definition.", CONCEPT.format(word=word, sentence=line), think)
    return text.strip().splitlines()[0].strip(), u


def explain(word: str, surface: str, line: str, before: list[str], after: list[str], backend: str = DEFAULT,
            think: bool = True) -> tuple[str, dict]:
    """~5 s with DeepSeek thinking on; off is ~1.6 s but made things up on tricky lines (a garbled 바이트 became
    "a bite", 보드 "often clipped from 보드게임"), so the card prefetches and caches instead of turning it off."""
    ctx = "\n".join(f"  {l}" for l in before) + f"\n> {line}\n" + "\n".join(f"  {l}" for l in after)
    user = f"Lines around it (the > line is the one being read):\n{ctx}\n\nTarget word: {word} (appears as \"{surface}\")"
    return llm(backend, EXPLAIN, user, think)


# ---- Primed Summaries (dojo-prompts primed-summaries + scripts/srt_summarize.py, same prompts and rules) ----
# A premise of the whole video, then windows of 40 lines grouped into topical chunks of 3-15 lines with a 1-3
# sentence English summary each; only chunks inside the first 25 lines of a window are kept (except the last),
# so chunk edges fall on real topic changes, not window edges. Windows run in order: each sees the last 3 summaries.
WINDOW_SIZE, CORE_SIZE, RECENT_SUMMARIES, FALLBACK_CHUNK_SIZE = 40, 25, 3, 10

PREMISE = """Read this whole Korean video transcript and write a 2-4 sentence English PREMISE covering:
- the genre/format (lecture, interview, vlog, anime episode, podcast, etc.)
- who's speaking (count, named hosts/characters if identifiable, roles)
- the overall topic/setting/arc
- the tone (casual, formal, comedic, instructional, etc.)
Write ONLY the premise (no headers, no commentary). Names and specifics matter.

Transcript:
{transcript}"""

BRIEF = """You are a content summarizer for {source_language} audio content.
You will receive a numbered list of {source_language} sentences from a video transcript.
Group them into coherent topical chunks and provide a concise English summary for each chunk.

=== CONTENT PREMISE (full-show context) ===
{premise}

=== RECENTLY SUMMARIZED CHUNKS (just before this window) ===
{recent_block}

=== SENTENCES TO SUMMARIZE (this window only) ===
{numbered}

Rules:
- Find natural breakpoints where the topic, scene, or speaker changes
- Each chunk should contain 3-15 sentences
- Write a concise English summary (1-3 sentences) capturing the key meaning
- Use the premise and recent summaries to keep names, ongoing topics, and tone consistent
- The summary should help a listener understand what they are about to hear
- Every sentence in this window must belong to exactly one chunk (no gaps, no overlaps)

Return ONLY valid JSON (no markdown, no commentary):
[
  {{"start": 1, "end": 5, "summary": "The speaker introduces themselves."}},
  {{"start": 6, "end": 12, "summary": "Discussion of the main topic."}}
]

start/end are 1-based sentence numbers within THIS window only (1..{batch_count}).
The first chunk must start at 1; the last chunk must end at {batch_count}.
Chunks must be contiguous (no gaps, no overlaps).
"""


def _repair(chunks, batch_count):
    """srt_summarize.py's _parse_and_repair: validate, close small gaps, reject overlaps."""
    import json as _json
    if isinstance(chunks, str):
        raw = chunks.strip()
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("```"))
        chunks = _json.loads(raw)
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("not a non-empty JSON array")
    for c in chunks:
        if not isinstance(c, dict) or not all(k in c for k in ("start", "end", "summary")):
            raise ValueError(f"bad chunk {c}")
        if not isinstance(c["start"], int) or not isinstance(c["end"], int) or c["start"] > c["end"]:
            raise ValueError(f"bad range {c}")
        if not str(c["summary"]).strip():
            raise ValueError(f"empty summary {c}")
    chunks.sort(key=lambda c: c["start"])
    if chunks[0]["start"] != 1:
        raise ValueError("first chunk must start at 1")
    for i in range(1, len(chunks)):
        if chunks[i]["start"] <= chunks[i - 1]["end"]:
            raise ValueError("overlap")
        if chunks[i]["start"] > chunks[i - 1]["end"] + 1:
            chunks[i - 1]["end"] = chunks[i]["start"] - 1
    if chunks[-1]["end"] > batch_count:
        raise ValueError("last chunk past the window")
    chunks[-1]["end"] = batch_count
    return chunks


def summarize(lines: list[str], backend: str = DEFAULT, think: bool = True, progress=None) -> tuple[list[dict], dict]:
    """[{start, end, summary}] with 1-based line numbers into `lines` (summary "" where a window failed 4 times).
    progress(chunks so far) is called after each window, so a player can use the first summaries right away.
    Thinking stays on: off was 9x faster but misread 맞팔 (mutual follow) as drinking content and swapped who said what."""
    usage = {"in": 0, "out": 0, "failed_windows": 0}
    def ask(system, user):
        for attempt in range(RETRIES + 1):
            try:
                text, u = llm(backend, system, user, think)
                usage["in"] += u["in"]
                usage["out"] += u["out"]
                return text
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
        raise RuntimeError("the AI could not be reached")
    premise = ask("You summarize video transcripts.", PREMISE.format(transcript="\n".join(lines))).strip()
    accepted, cursor, total = [], 0, len(lines)
    while cursor < total:
        window_end = min(cursor + WINDOW_SIZE, total)
        is_final, n = window_end == total, window_end - cursor
        recent = accepted[-RECENT_SUMMARIES:]
        brief = BRIEF.format(source_language="Korean", premise=premise or "(no premise available)",
                             recent_block="\n".join(f'- (sentences {c["start"]}-{c["end"]}) {c["summary"]}' for c in recent)
                             or "(none — this is the first window)",
                             numbered="\n".join(f"{i + 1}. {l}" for i, l in enumerate(lines[cursor:window_end])), batch_count=n)
        chunks = None
        for _ in range(RETRIES + 1):
            try:
                chunks = _repair(ask("Return only the JSON array.", brief), n)
                break
            except (ValueError, TypeError):
                continue
        if chunks is None:                                   # srt_summarize's fallback: plain chunks, no summary
            usage["failed_windows"] += 1
            chunks = [{"start": a, "end": min(a + FALLBACK_CHUNK_SIZE - 1, n), "summary": ""} for a in range(1, n + 1, FALLBACK_CHUNK_SIZE)]
        for c in chunks:
            c["start"] += cursor
            c["end"] += cursor
        keep = chunks if is_final else [c for c in chunks if c["end"] <= cursor + CORE_SIZE] or chunks[:1]
        accepted += [{"start": c["start"], "end": c["end"], "summary": str(c["summary"]).strip()} for c in keep]
        cursor = keep[-1]["end"]
        if progress:
            progress(list(accepted))
    return accepted, {**usage, "premise": premise}
