"""Double-click launcher for the desktop app: no config file or command line needed.

The first run makes a folder for the office (Documents/Priority Date Tracker, or PDTRACKER_HOME), asks for
the office name (or reads PDTRACKER_OFFICE_NAME), and writes office.yaml there. Every run then opens the
dashboard. With arguments it runs any pdtrack command against that folder's config, for example
"PriorityDateTracker.exe check" from Task Scheduler. "demo" opens the sample data on its own port.
"""

from __future__ import annotations

import os
import socket
import sys
import webbrowser
from pathlib import Path

import yaml

from . import cli, config

FOLDER_NAME = "Priority Date Tracker"
CONFIG_NAME = "office.yaml"
DEFAULT_PORT = 8765
DEMO_PORT = 8766

CONFIG_TEMPLATE = """\
# Made by the Priority Date Tracker app the first time it opened. Every setting is explained in
# config/office.example.yaml in the project. Paths are relative to this folder.

office:
  name: {name}

storage:
  backend: sqlite
  sqlite_path: data/priority-dates.db

bulletin:
  source: state_dept              # download the Visa Bulletin from travel.state.gov
  inbox_dir: bulletin-inbox       # or drop the bulletin PDF in this folder
  reminder_day: 20

alerts:
  report_dir: reports
"""


def home_dir() -> Path:
    custom = os.environ.get("PDTRACKER_HOME")
    if custom:
        return Path(custom).expanduser()
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / FOLDER_NAME


def port() -> int:
    return int(os.environ.get("PDTRACKER_PORT") or DEFAULT_PORT)


def ensure_config(home: Path, ask=input) -> Path:
    """Return the office config, writing it first if this is the first run."""
    path = home / CONFIG_NAME
    if path.exists():
        return path
    name = os.environ.get("PDTRACKER_OFFICE_NAME", "").strip()
    while not name:
        print()
        print("Welcome! This is the first time the Priority Date Tracker has opened on this computer.")
        name = ask("Type your office's name and press Enter: ").strip()
    home.mkdir(parents=True, exist_ok=True)
    (home / "bulletin-inbox").mkdir(exist_ok=True)
    path.write_text(CONFIG_TEMPLATE.format(name=yaml.safe_dump(name, default_style='"').strip()), encoding="utf-8")
    print(f"Saved. Your office's files are in {home}")
    return path


def already_running(p: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", p)) == 0


def _title(text: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text)


def _open_or_serve(s, p: int, what: str) -> int:
    url = f"http://localhost:{p}/"
    if already_running(p):
        print(f"{what} is already open. Showing it in your web browser.")
        webbrowser.open(url)
        return 0
    from .webui import serve
    print()
    print(f"  {what} is running.")
    print(f"  Your web browser will open it. If it doesn't, go to {url}")
    print()
    print("  Leave this window open while you use it. Close this window when you're done.")
    print()
    serve(s, port=p)
    return 0


def run_dashboard() -> int:
    _title("Priority Date Tracker - leave this window open")
    home = home_dir()
    s = config.load(ensure_config(home))
    return _open_or_serve(s, port(), "The Priority Date Tracker")


def run_demo(args: list[str]) -> int:
    _title("Priority Date Tracker SAMPLE DATA - leave this window open")
    if "--dir" not in args:
        args += ["--dir", str(home_dir() / "Sample data")]
    if "--port" not in args:
        args += ["--port", str(DEMO_PORT)]
    p = int(args[args.index("--port") + 1])
    if already_running(p):
        return _open_or_serve(None, p, "The sample dashboard")
    print("Opening the sample dashboard with made-up clients. Nothing here is real.")
    return cli.main(["demo", *args])


def run_command(args: list[str]) -> int:
    if "-c" not in args and "--config" not in args:
        path = home_dir() / CONFIG_NAME
        if not path.exists():
            print(f"error: no office set up in {path.parent}. Open the app once first.", file=sys.stderr)
            return 1
        args = ["-c", str(path), *args]
    return cli.main(args)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "demo":
        return run_demo(args[1:])
    if args:
        return run_command(args)
    try:
        return run_dashboard()
    except KeyboardInterrupt:
        return 0
    except Exception as err:        # a double-clicked window would otherwise vanish before anyone reads it
        print()
        print(f"Something went wrong: {err}")
        print("Take a picture of this window and send it to whoever set up the tracker.")
        try:
            input("Press Enter to close.")
        except EOFError:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
