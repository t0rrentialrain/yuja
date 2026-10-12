"""Start the Yuja server automatically when you log in to Windows (no console window).

    python yuja/autostart.py           # install (and start it now)
    python yuja/autostart.py --remove  # uninstall

Puts a tiny .vbs launcher in your Startup folder that runs server.py with pythonw
and logs to yuja/yuja.log.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
LAUNCHER = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/Yuja server.vbs"
COMMAND = f'cmd /c cd /d "{HERE}" && "{PYTHONW}" server.py > yuja.log 2>&1'

if "--remove" in sys.argv:
    LAUNCHER.unlink(missing_ok=True)
    print(f"Removed {LAUNCHER}")
else:
    LAUNCHER.write_text(f'CreateObject("WScript.Shell").Run "{COMMAND.replace(chr(34), chr(34) * 2)}", 0\n', encoding="utf-8")
    subprocess.Popen(["wscript", str(LAUNCHER)])
    print(f"Installed {LAUNCHER}\nThe server starts at login; started it now too (ready in ~20 s, log: {HERE / 'yuja.log'}).")
