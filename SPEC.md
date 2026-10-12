# Yuja (유자): v1 spec

A Migaku / Kimchi Reader rival built on kparse (Kiwi + Jev). Built for one
user first, structured so it could go public later.

## Shape

```
Chrome extension (MV3)  ──HTTP──▶  local Python server (localhost)
  YouTube overlay                    kparse  (parse lines → words + grammar)
  web-page coloring                  KRDict  (local dictionary)
  player page (mp4 + srt)            word-status store (SQLite)
                                     AnkiConnect, yt-dlp, Soniox, ffmpeg
```

The extension stays thin: everything Korean-specific lives in the server.

## Features

| Feature | Decision |
|---|---|
| Content | YouTube, local mp4 + SRT, any web page |
| YouTube subs | Korean captions via yt-dlp if they exist, otherwise Soniox transcription |
| Local video | Extension player page: drop an mp4 + srt |
| Web pages | Every Korean word on the page is colored and clickable |
| Lookup | **Click** a word for a popup: lemma, KRDict definitions, grammar morphemes |
| Statuses | Unknown / Learning / Known / Ignored |
| Known words | **Both**: statuses set in Yuja, plus mature (≥21d) / learning Anki cards from the sentence-mining config's `known_words.sources`. Seeded from its `word_lists` |
| Grammar | **Graded like words**: particles, endings and Tier-3 patterns (것 같다…) get statuses and coloring too |
| Mining | One click creates an MvJ note in `Database::Kimchi+`: Word, Sentence (word bolded), Sentence Audio (ffmpeg clip), Image (frame), Definition (field you add) |
| Comprehension | % known on the YouTube watch page **and** on thumbnails |
| Subtitle browser | Side panel: every line, current highlighted + auto-scroll, click to seek, unknown counts, sort, Recommended (i+1) filter, search, mine per line, `[` `]` `\` keys, auto-pause |
| Uncertain parses | Use Kiwi's guess as-is |
| Config | Reuses `~/.claude/skills/sentence-mining/config.json` |

## Out of v1 (YAGNI)

Netflix (built once, removed until it can be tested), Claude explanations, accounts/sync, mobile, Firefox, editing
parses, SRS inside Yuja.

## Build order

Done: 1 server · 2 page coloring + card · 3 YouTube overlay · 4 mining · 5 badge · subtitle browser · 6 local player page · 7 thumbnail scores. All v1 steps built.
After v1: fruit themes · server auto-start · parse fixes in the card · stats page · README + setup.py · subtitle hide (`C`) + style (size, font, background, color, outline, drag to place).

Each step is usable on its own:

1. **Server core**: `/parse` (kparse + statuses), `/status` (set), `/lookup` (KRDict).
2. **Web-page coloring + popup**: the simplest end-to-end check of the extension.
3. **YouTube overlay**: fetch subtitles, interactive subtitle bar, click to pause and look up.
4. **Mining**: Anki card with audio clip and screenshot.
5. **Comprehension badge** on the watch page.
6. **Player page** for local mp4 + srt.
7. **Thumbnail scores**: last, because it's the heaviest (see open questions).

## Decided

- KRDict: you download the full dictionary once and it's loaded into local SQLite.
- Thumbnails: scored only when YouTube has Korean captions (no Soniox).
- Anki: `Definition` field added to MvJ by you.
- Style: YAGNI, smallest thing that works, reuse existing code.
