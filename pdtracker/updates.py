"""Tell staff when a newer version of the desktop app is out.

The app asks once per launch, in the background, for the newest release. PDTRACKER_UPDATE_URL
points it at another project's releases (a fork, or an office's own copy); set it to "off" to
never check. Nothing about the office or its clients is sent: it is a plain download of public
release information. Installing stays a person's choice: the dashboard shows a link to the new
installer, which replaces the program files and leaves the office folder alone.
"""

from __future__ import annotations

import os
import re
import threading

DEFAULT_URL = "https://api.github.com/repos/notevenmex/priority-date-tracker/releases/latest"
INSTALLER = "PriorityDateTracker-Setup.exe"

_latest: dict | None = None


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2); anything unreadable sorts lowest."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def check(current: str, url: str | None = None, get=None) -> dict | None:
    """The newer release as {'version', 'url'}, or None when up to date, turned off, or offline."""
    url = url if url is not None else os.environ.get("PDTRACKER_UPDATE_URL", DEFAULT_URL)
    if not url or url.lower() == "off":
        return None
    if get is None:
        import requests
        get = requests.get
    try:
        resp = get(url, timeout=10, headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        release = resp.json()
    except Exception:           # offline, blocked or rate-limited: try again next launch
        return None
    version = str(release.get("tag_name") or "").lstrip("vV")
    if parse_version(version) <= parse_version(current):
        return None
    download = next((a.get("browser_download_url") for a in release.get("assets") or []
                     if a.get("name") == INSTALLER), None)
    return {"version": version, "url": download or release.get("html_url") or ""}


def start(current: str) -> None:
    """Check in the background so a slow network never delays opening the dashboard."""
    def run():
        global _latest
        _latest = check(current)
    threading.Thread(target=run, daemon=True).start()


def available() -> dict | None:
    return _latest
