# 🍋 Yuja (유자)

A Korean immersion tool in the spirit of Migaku and Kimchi Reader: known/unknown
word coloring everywhere, a click-to-look-up card, one-click Anki mining, a
subtitle browser with i+1 recommendations, and comprehension scores. Built on
[kparse](../korean-parser) (Kiwi + Jev) so words *and grammar patterns* are
tracked like vocabulary.

## Features

- **Any web page** – Korean words are underlined by status (solid = unknown word,
  dotted = unknown grammar pattern, faint = learning). Click for the card.
- **Card** – concept-first definitions (KRDict, Wiktionary fallback, your grammar
  list's glosses), Kimchi-style frequency rank and level stars, statuses
  (`1` New · `2` Learning · `3` Known · `0` Ignore), `E` explain the word in this line and `T` translate
  the line (DeepSeek, cached), `M` to mine, and
  "Split looks wrong?" to fix a parse (remembered by context).
- **YouTube** – Yuja's own subtitle bar (YouTube's Korean captions, auto-captions
  rebuilt into sentences, or Soniox transcription), click to pause and look up,
  ⚙ settings on hover, and % known on thumbnails. `C` hides/shows the subtitles; drag
  them anywhere, and set their size, font, background (fruit / dark / none + opacity),
  text color, outline and box size in ⚙. ✕ closes
  the subtitle browser (reopen it from ⚙). The same settings apply on the local player.
- **Subtitle browser** – every line with unknown counts; filters (Recommended
  sentences, 1 Unknown, Unique 1 Unknown, 1+/2+ Unknown, Learning, All Known,
  Bookmarked), search, copy, bookmark and mine from any line.
- **Batch mining** – ☑ in the subtitle browser, pick lines (or *Select shown* for the current
  filter), *Mine*. One unknown → a full word card; 0 or 2+ unknowns → a sentence card with Word and
  Definition left empty. Runs in the background on the server, rows tick off as cards are made.
- **Listening modes** (⚙ → Playback) – *Primed*, like the dojo-prompts mpv script: each line pauses
  at its start and shows Korean, English or both for a reading time (s per character), then plays with
  the subtitles hidden; `Space` holds the pause. *Listen first*: hidden while it plays, revealed (Korean or
  + English) when it ends. *Condensed* skips the gaps between lines. *Summaries* (dojo-prompts
  primed-summaries): before each topical chunk, an English summary of what's coming, then the chunk with
  the subtitles hidden; written window by window in the background, the first ones in ~20 s. English is the whole transcript,
  translated once per video in the background (DeepSeek, translate-srt protocol) and kept in `cache/`.
- **Recommended sentences** – i+1 lines that are short, have enough known
  context, and that Jev rates as a clear example of the word.
- **Local player** – click the toolbar icon, drop a video + .srt/.vtt.
- **Anki mining** – sentence (word bolded), audio clip, screenshot, and a one-line English Definition
  written by DeepSeek with your Definition prompt (dictionary glosses if it fails).
  Word Audio (Korean) and Definition Audio (English) by edge-tts; pick the voices under ⚙ → Card audio.
- **Stats** – known words over time, minutes watched, cards mined, and the
  unknown words you keep meeting.
- **Fruit themes** – 🍋 유자 · 🍓 딸기 · 🍇 청포도 · 🍑 복숭아 · 🫐 블루베리 (dark).

## Setup

```
python yuja/setup.py --autostart
```

Checks Python packages, yt-dlp/ffmpeg, the sibling projects, the config and the
dictionary, installs only what's missing, and starts the server with Windows.
Then in Chrome: `chrome://extensions` → Developer mode → **Load unpacked** →
`yuja/extension`.

Requirements:

- `korean-parser/` and `kiwi-ankimorphs/` next to `yuja/`.
- The sentence-mining skill's `config.json` (Anki note type, deck, known-word
  sources). Yuja reuses it rather than having its own.
- KRDict's full XML download (free login) in `yuja/`. Optionally Wiktionary's
  Korean dump from kaikki.org for slang and loanwords.
- Optional keys: Jev (`korean-parser/.env`) for better parses and
  Recommended sentences; Soniox for videos without Korean captions; DeepSeek (`yuja/.env`, see
  `.env.example`) for Explain, Translate and mined Definitions.

## How it fits together

```
Chrome extension ──HTTP (127.0.0.1:8766)──▶ server.py
  content.js   page coloring, card, mining     kparse: Kiwi top-5 + rules + Jev
  youtube.js   bar, ⚙, subtitle browser, ...   statuses (yuja.sqlite) + Anki/word lists
  player.*     local video page                KRDict / Wiktionary (krdict.sqlite)
  stats.*      stats page                      yt-dlp, ffmpeg, Soniox, AnkiConnect
```

## Files and data

| Path | What |
|---|---|
| `server.py` | All endpoints (parse, lookup, subs, mine, scores, stats, fixes) |
| `translate.py` | DeepSeek translate / explain / Definition; transcripts via the translate-srt protocol with numbered lines |
| `eval/` | The 2026-10 blind test that picked DeepSeek over Gemini Flash-Lite and DeepL |
| `build_dict.py` | Builds `krdict.sqlite` from the KRDict zip (+ Wiktionary) |
| `autostart.py` | Start the server at login (`--remove` to undo) |
| `setup.py` | One-command setup |
| `logo/` | Logo source and variants; `clean.py` (transparent, crop, colors, bumpy peel), `pixels.py` (16/32 px pixel art + all icon sizes), `compare.py` (preview sheet). Installed icons live in `extension/icons/` |
| `yuja.sqlite` | Your statuses, parse fixes, bookmarks, stats |
| `cache/` | Subtitles and 360p videos used for mining |
| `yuja.log` | Server log when started by autostart |

Everything stays on your machine. Network calls: YouTube (yt-dlp), Jev and
Soniox (if keys are set), KRDict/Wiktionary only at build time.
