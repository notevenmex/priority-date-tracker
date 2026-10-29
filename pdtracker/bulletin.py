"""Read Visa Bulletin cutoffs from travel.state.gov, or from a file someone filled in by hand.

The State Department page layout is the part most likely to change, so everything that
depends on it lives here: URLs come from config and the parser matches tables by their
header text rather than by position.
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin

from .models import DATES_FOR_FILING, FINAL_ACTION, Bulletin, month_key, parse_cutoff

DEFAULT_INDEX_URL = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"
DEFAULT_PAGE_URL = ("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/"
                    "{fiscal_year}/visa-bulletin-for-{month_name}-{year}.html")


class BulletinError(RuntimeError):
    pass


class BulletinSource(Protocol):
    def latest(self) -> Bulletin | None: ...
    def fetch(self, month: str) -> Bulletin | None: ...


# Parsing

class _TableCollector(HTMLParser):
    """Collect, in document order, the text between tables and each table's cell text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, object]] = []
        self._text: list[str] = []
        self._depth = 0
        self._rows: list[list[str]] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self.items.append(("text", " ".join(self._text)))
                self._text, self._rows = [], []
        elif self._depth == 1 and tag == "tr":
            self._rows.append([])
        elif self._depth == 1 and tag in ("td", "th"):
            self._cell = []
        elif tag in ("br", "p", "div") and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "table" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                self.items.append(("table", [r for r in self._rows if r]))
        elif self._depth == 1 and tag in ("td", "th") and self._cell is not None:
            if not self._rows:
                self._rows.append([])
            self._rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        elif not self._depth:
            self._text.append(data)

    def close(self):
        super().close()
        self.items.append(("text", " ".join(self._text)))


_HEADING = re.compile(r"\b(FINAL ACTION DATES|DATES FOR FILING)\b")

_EMPLOYMENT_ROWS = [
    (re.compile(r"^1st"), "EB1"),
    (re.compile(r"^2nd"), "EB2"),
    (re.compile(r"^3rd"), "EB3"),
    (re.compile(r"other workers", re.I), "EW"),
    (re.compile(r"^4th"), "EB4"),
    (re.compile(r"religious", re.I), "SR"),
    (re.compile(r"unreserved|non-regional", re.I), "EB5U"),
    (re.compile(r"rural", re.I), "EB5R"),
    (re.compile(r"high unemployment", re.I), "EB5H"),
    (re.compile(r"infrastructure", re.I), "EB5I"),
]


def _column(header: str) -> str | None:
    h = header.upper()
    if "CHINA" in h:
        return "CHINA"
    if "INDIA" in h:
        return "INDIA"
    if "MEXICO" in h:
        return "MEXICO"
    if "PHILIPPINES" in h:
        return "PHILIPPINES"
    if "EL SALVADOR" in h:
        return "ESGH"
    if "CHARGEABILITY" in h or "EXCEPT" in h:
        return "ROW"
    return None


def _row_category(label: str, kind: str) -> str | None:
    label = label.strip()
    if kind == "family":
        m = re.match(r"^(F1|F2A|F2B|F3|F4)\b", label.upper())
        return m[1] if m else None
    for pattern, cat in _EMPLOYMENT_ROWS:
        if pattern.search(label):
            return cat
    return None


def _parse_table(rows: list[list[str]], kind: str) -> dict:
    header = rows[0]
    columns = [_column(h) for h in header]
    out = {}
    for row in rows[1:]:
        if not row:
            continue
        cat = _row_category(row[0], kind)
        if not cat or cat in out:       # first match wins, e.g. a later footnote row
            continue
        values = {}
        for col, cell in zip(columns[1:], row[1:]):
            if not col or not cell:
                continue
            try:
                values[col] = parse_cutoff(cell.replace("\xa0", "").replace(" ", ""))
            except ValueError:
                continue
        if values:
            out[cat] = values
    return out


def parse_bulletin_html(html: str, month: str, source: str = "") -> Bulletin:
    collector = _TableCollector()
    collector.feed(html)
    collector.close()

    bulletin = Bulletin(month=month, source=source)
    seen = {"family": 0, "employment": 0}
    last_heading = None
    for kind_of_item, value in collector.items:
        if kind_of_item == "text":
            found = _HEADING.findall(value)
            if found:
                last_heading = found[-1]
            continue
        rows = value
        if not rows:
            continue
        first = rows[0][0].lower() if rows[0] else ""
        kind = "family" if "family" in first else "employment" if "employment" in first else None
        if not kind:
            continue
        # Prefer the section heading above the table; fall back to order (A = final action, B = filing).
        if last_heading == "FINAL ACTION DATES":
            chart = FINAL_ACTION
        elif last_heading == "DATES FOR FILING":
            chart = DATES_FOR_FILING
        else:
            chart = FINAL_ACTION if seen[kind] == 0 else DATES_FOR_FILING
        seen[kind] += 1
        last_heading = None
        target = bulletin.chart(chart)
        for cat, values in _parse_table(rows, kind).items():
            target.setdefault(cat, values)

    if not bulletin.final_action:
        raise BulletinError("No Final Action table found on the bulletin page. The page layout may have changed; "
                            "enter this month's dates by hand with 'pdtrack bulletin template'.")
    return bulletin


def months_on_index(html: str, base_url: str) -> dict[str, str]:
    """Map 'YYYY-MM' to bulletin URL for every bulletin linked from the index page."""
    names = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
    found = {}
    for href in re.findall(r'href="([^"]*visa-bulletin-for-[a-z]+-\d{4}\.html)"', html, re.I):
        m = re.search(r"visa-bulletin-for-([a-z]+)-(\d{4})\.html", href, re.I)
        month = names.get(m[1].lower())
        if month:
            found[f"{int(m[2]):04d}-{month:02d}"] = urljoin(base_url, href)
    return found


# Sources

class StateDeptSource:
    """Fetch bulletins from travel.state.gov. Pass a requests-like session for testing."""

    def __init__(self, index_url: str = DEFAULT_INDEX_URL, page_url: str = DEFAULT_PAGE_URL, session=None):
        import requests

        self.index_url = index_url
        self.page_url = page_url
        self.session = session or requests.Session()

    def _get(self, url: str) -> str:
        resp = self.session.get(url, timeout=60, headers={"User-Agent": "pdtracker (law office priority date tracker)"})
        if resp.status_code == 404:
            return ""
        if resp.status_code >= 400:
            raise BulletinError(f"{url} returned HTTP {resp.status_code}")
        return resp.text

    def url_for(self, month: str) -> str:
        year, mon = map(int, month_key(month).split("-"))
        fiscal_year = year + 1 if mon >= 10 else year
        return self.page_url.format(fiscal_year=fiscal_year, year=year,
                                    month_name=calendar.month_name[mon].lower())

    def available(self) -> dict[str, str]:
        return months_on_index(self._get(self.index_url), self.index_url)

    def fetch(self, month: str) -> Bulletin | None:
        month = month_key(month)
        url = self.available().get(month) or self.url_for(month)
        html = self._get(url)
        return parse_bulletin_html(html, month, source=url) if html else None

    def latest(self) -> Bulletin | None:
        available = self.available()
        if not available:
            # Index layout changed: try next month, then this month, by URL pattern.
            today = date.today()
            nxt = f"{today.year + (today.month == 12):04d}-{today.month % 12 + 1:02d}"
            return self.fetch(nxt) or self.fetch(f"{today:%Y-%m}")
        month = max(available)
        html = self._get(available[month])
        return parse_bulletin_html(html, month, source=available[month]) if html else None


class StoredSource:
    """Manual mode: the newest bulletin someone entered into the store."""

    def __init__(self, store):
        self.store = store

    def latest(self) -> Bulletin | None:
        months = self.store.bulletin_months()
        return self.store.get_bulletin(months[-1]) if months else None

    def fetch(self, month: str) -> Bulletin | None:
        return self.store.get_bulletin(month_key(month))


def load_bulletin_file(path: str | Path) -> Bulletin:
    text = Path(path).read_text()
    if str(path).endswith((".yaml", ".yml")):
        import yaml
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return Bulletin.from_dict(data)
