"""One-command Yuja setup: checks everything, installs only what's missing.

    python yuja/setup.py              # check + install + build dictionary
    python yuja/setup.py --autostart  # ...and start the server with Windows
"""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ok = lambda msg: print(f"  ✓ {msg}")
todo = lambda msg: print(f"  ✗ {msg}")
problems = 0

print("Python packages")
for module, package in [("flask", "flask"), ("requests", "requests"), ("kiwipiepy", "kiwipiepy"),
                        ("korean_romanizer", "korean-romanizer"), ("yt_dlp", "yt-dlp")]:
    if importlib.util.find_spec(module):
        ok(package)
    else:
        print(f"  … installing {package}")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", package], check=True)
        ok(f"{package} (installed)")

print("Tools on PATH")
for tool in ("yt-dlp", "ffmpeg"):
    if shutil.which(tool):
        ok(tool)
    else:
        problems += 1
        todo(f"{tool} not found. Install it (ffmpeg: `winget install Gyan.FFmpeg`) and reopen the terminal.")

print("Sibling projects")
for folder, why in [("korean-parser", "the Kiwi + Jev parser"), ("kiwi-ankimorphs", "compound merging, grammar patterns, Kimchi frequency list")]:
    if (ROOT / folder).is_dir():
        ok(f"{folder}/ ({why})")
    else:
        problems += 1
        todo(f"{folder}/ missing next to yuja/ ({why})")

print("Config (shared with the sentence-mining skill)")
cfg = Path.home() / ".claude/skills/sentence-mining/config.json"
if cfg.exists():
    ok(f"{cfg}  (Anki note type, deck, known-word sources)")
else:
    problems += 1
    todo(f"{cfg} missing. Run the sentence-mining skill's setup first (`/sentence-mining setup`).")

print("Dictionary")
if (HERE / "krdict.sqlite").exists():
    ok("krdict.sqlite")
elif list(HERE.glob("*한국어기초사전_xml*.zip")):
    print("  … building krdict.sqlite (about 15 s)")
    subprocess.run([sys.executable, str(HERE / "build_dict.py")], check=True)
    ok("krdict.sqlite (built)")
else:
    problems += 1
    todo("Download KRDict's full XML (free login): https://krdict.korean.go.kr/download/downloadPopup\n"
         "    put the .zip in yuja/ and run this again. Optional: Wiktionary's Korean dump from\n"
         "    https://kaikki.org/dictionary/Korean/ (kaikki.org-dictionary-Korean.jsonl) for slang/loanwords.")

print("Optional keys")
env = ROOT / "korean-parser/.env"
jev = os.environ.get("TYPESAFE_API_KEY") or (env.exists() and "TYPESAFE_API_KEY=" in env.read_text(encoding="utf-8"))
ok("Jev key (better parses, Recommended sentences)") if jev else print(
    "  – No Jev key: Kiwi-only parsing, no Recommended sentences. Add TYPESAFE_API_KEY=... to korean-parser/.env")
skill_env = Path.home() / ".claude/skills/sentence-mining/.env"
soniox = os.environ.get("SONIOX_API_KEY") or (skill_env.exists() and "SONIOX_API_KEY=" in skill_env.read_text(encoding="utf-8"))
ok("Soniox key (transcribes YouTube videos without Korean captions)") if soniox else print(
    "  – No Soniox key: videos without Korean captions can't be transcribed.")

if "--autostart" in sys.argv and not problems:
    subprocess.run([sys.executable, str(HERE / "autostart.py")], check=True)

print(f"""
{"All set." if not problems else f"{problems} thing(s) to fix above, then run this again."}
Load the extension: chrome://extensions → Developer mode → Load unpacked → {HERE / "extension"}
Start the server:   python {HERE / "server.py"}   (or: python {HERE / "setup.py"} --autostart)""")
