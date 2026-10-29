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
DEFAULT_PDF_URL = "https://travel.state.gov/content/dam/visas/Bulletins/visabulletin_{MonthName}{year}.pdf"
FORMATS = ("pdf", "html", "auto")


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
                            "upload the bulletin PDF or enter this month's dates by hand.")
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



# PDF parsing. Text extraction from the bulletin PDF can put a table row on one line or
# each cell on its own line, so this works on the stream of words rather than on lines.

_CUTOFF_TOKEN = re.compile(r"^(C|U|\d{2}[A-Z]{3}\d{2})$")
_SECTIONS = [
    (re.compile(r"FINAL\s+ACTION\s+DATES\s+FOR\s+FAMILY", re.I), "family", FINAL_ACTION),
    (re.compile(r"DATES\s+FOR\s+FILING\s+(?:OF\s+)?FAMILY", re.I), "family", DATES_FOR_FILING),
    (re.compile(r"FINAL\s+ACTION\s+DATES\s+FOR\s+EMPLOYMENT", re.I), "employment", FINAL_ACTION),
    (re.compile(r"DATES\s+FOR\s+FILING\s+(?:OF\s+)?EMPLOYMENT", re.I), "employment", DATES_FOR_FILING),
]
_DEFAULT_COLUMNS = ["ROW", "CHINA", "INDIA", "MEXICO", "PHILIPPINES"]
_TITLE = re.compile(r"VISA\s+BULLETIN\s+FOR\s+([A-Z]+)\s+(\d{4})", re.I)


def month_from_text(text: str) -> str | None:
    names = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
    m = _TITLE.search(text[:5000])
    if m and m[1].lower() in names:
        return f"{int(m[2]):04d}-{names[m[1].lower()]:02d}"
    return None


def _columns_from_header(text: str) -> list[str]:
    """Column order from the header words before the first row; standard order if unclear."""
    found = []
    for pattern, col in (("ALL CHARGEABILITY", "ROW"), ("CHINA", "CHINA"), ("INDIA", "INDIA"),
                         ("MEXICO", "MEXICO"), ("PHILIPPINES", "PHILIPPINES"), ("EL SALVADOR", "ESGH")):
        i = " ".join(text.upper().split()).find(pattern)
        if i >= 0:
            found.append((i, col))
    cols = [c for _, c in sorted(found)]
    return cols if len(cols) >= 5 else list(_DEFAULT_COLUMNS)


def _parse_rows(text: str, kind: str) -> dict:
    tokens = text.split()
    first_value = next((i for i, t in enumerate(tokens) if _CUTOFF_TOKEN.match(t)), len(tokens))
    columns = _columns_from_header(" ".join(tokens[:first_value]))
    width = len(columns)
    out, label, i = {}, [], 0
    while i < len(tokens):
        if not _CUTOFF_TOKEN.match(tokens[i]):
            label.append(tokens[i])
            i += 1
            continue
        run = []
        while i < len(tokens) and _CUTOFF_TOKEN.match(tokens[i]):
            run.append(tokens[i])
            i += 1
        if len(run) >= width and label:
            # The label is the end of the words before the values: try the shortest tail that names a row.
            cat = next((c for n in range(1, min(len(label), 14) + 1)
                        if (c := _row_category(" ".join(label[-n:]), kind))), None)
            if cat and cat not in out:
                out[cat] = {col: parse_cutoff(v) for col, v in zip(columns, run[:width])}
        label = []
    return out


def parse_bulletin_text(text: str, month: str | None = None, source: str = "") -> Bulletin:
    month = month or month_from_text(text)
    if not month:
        raise BulletinError("Couldn't tell which month this bulletin is for. Give the month explicitly.")
    bulletin = Bulletin(month=month, source=source)
    marks = sorted((m.start(), kind, chart) for pattern, kind, chart in _SECTIONS
                   for m in [pattern.search(text)] if m)
    for n, (start, kind, chart) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(text)
        # Skip the heading line itself so its words don't end up in a row label.
        body = text[start:end].split("\n", 1)[-1]
        rows = _parse_rows(body, kind)
        target = bulletin.chart(chart)
        for cat, values in rows.items():
            target.setdefault(cat, values)
    if not bulletin.final_action:
        raise BulletinError("No Final Action table found in the bulletin text. The layout may have changed; "
                            "enter this month's dates by hand.")
    return bulletin


def pdf_text(data: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    if not data.startswith(b"%PDF"):
        raise BulletinError("That file isn't a PDF.")
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)


def parse_bulletin_pdf(data: bytes, month: str | None = None, source: str = "") -> Bulletin:
    return parse_bulletin_text(pdf_text(data), month, source)


# Sources

class StateDeptSource:
    """Fetch bulletins from travel.state.gov, as the PDF, the web page, or PDF then web page.

    Pass a requests-like session for testing.
    """

    def __init__(self, index_url: str = DEFAULT_INDEX_URL, page_url: str = DEFAULT_PAGE_URL,
                 pdf_url: str = DEFAULT_PDF_URL, fmt: str = "auto", session=None):
        import requests

        if fmt not in FORMATS:
            raise ValueError(f"bulletin format must be one of {FORMATS}")
        self.index_url = index_url
        self.page_url = page_url
        self.pdf_url = pdf_url
        self.fmt = fmt
        self.session = session or requests.Session()

    def _get(self, url: str):
        resp = self.session.get(url, timeout=60, headers={"User-Agent": "pdtracker (law office priority date tracker)"})
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise BulletinError(f"{url} returned HTTP {resp.status_code}")
        return resp

    @staticmethod
    def _parts(month: str) -> dict:
        year, mon = map(int, month_key(month).split("-"))
        name = calendar.month_name[mon]
        return {"fiscal_year": year + 1 if mon >= 10 else year, "year": year,
                "month_name": name.lower(), "MonthName": name}

    def url_for(self, month: str) -> str:
        return self.page_url.format(**self._parts(month))

    def pdf_url_for(self, month: str) -> str:
        return self.pdf_url.format(**self._parts(month))

    def available(self) -> dict[str, str]:
        resp = self._get(self.index_url)
        return months_on_index(resp.text, self.index_url) if resp else {}

    def _fetch_pdf(self, month: str) -> Bulletin | None:
        url = self.pdf_url_for(month)
        resp = self._get(url)
        if not resp or not resp.content.startswith(b"%PDF"):
            return None          # not published yet (some servers answer a missing file with an HTML page)
        return parse_bulletin_pdf(resp.content, month, source=url)

    def _fetch_html(self, month: str, url: str | None = None) -> Bulletin | None:
        url = url or self.url_for(month)
        resp = self._get(url)
        return parse_bulletin_html(resp.text, month, source=url) if resp else None

    def fetch(self, month: str) -> Bulletin | None:
        month = month_key(month)
        if self.fmt in ("pdf", "auto"):
            try:
                b = self._fetch_pdf(month)
                if b or self.fmt == "pdf":
                    return b
            except BulletinError:
                if self.fmt == "pdf":
                    raise
        return self._fetch_html(month)

    def latest(self, today: date | None = None) -> Bulletin | None:
        """The newest bulletin: next month's if it's out (it usually appears mid-month), else this month's."""
        today = today or date.today()
        nxt = f"{today.year + (today.month == 12):04d}-{today.month % 12 + 1:02d}"
        return self.fetch(nxt) or self.fetch(f"{today:%Y-%m}")


class StoredSource:
    """Manual mode: the newest bulletin someone entered into the store."""

    def __init__(self, store):
        self.store = store

    def latest(self) -> Bulletin | None:
        months = self.store.bulletin_months()
        return self.store.get_bulletin(months[-1]) if months else None

    def fetch(self, month: str) -> Bulletin | None:
        return self.store.get_bulletin(month_key(month))


def _same_dates(a: Bulletin, b: Bulletin) -> bool:
    da, db = a.to_dict(), b.to_dict()
    return all(da[c] == db[c] for c in (FINAL_ACTION, DATES_FOR_FILING))


class FolderInbox:
    """A local folder where staff drop bulletin PDFs."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def pdfs(self) -> list[tuple[str, object]]:
        if not self.path.is_dir():
            return []
        return [(f"folder:{p.name}", p.read_bytes) for p in sorted(self.path.glob("*.pdf"))]


class InboxSource:
    """Use bulletin PDFs staff dropped in an inbox (a local folder or a SharePoint folder) first,
    then fall back to another source, such as the State Department site."""

    def __init__(self, store, inbox, fallback=None):
        self.store = store
        self.inbox = inbox
        self.fallback = fallback

    def _from_inbox(self) -> Bulletin | None:
        known = {b.source for b in (self.store.get_bulletin(m) for m in self.store.bulletin_months()) if b}
        newest = None
        for name, load in self.inbox.pdfs():
            if name in known:
                continue
            b = parse_bulletin_pdf(load(), source=name)
            stored = self.store.get_bulletin(b.month)
            if stored and self.store.is_processed(b.month) and _same_dates(stored, b):
                continue     # a copy of a bulletin already checked
            if newest and newest.month >= b.month:
                continue
            newest = b
        return newest

    def latest(self) -> Bulletin | None:
        b = self._from_inbox()
        if b:
            return b
        return self.fallback.latest() if self.fallback else None

    def fetch(self, month: str) -> Bulletin | None:
        return self.fallback.fetch(month) if self.fallback else self.store.get_bulletin(month)


def load_bulletin_file(path: str | Path, month: str | None = None) -> Bulletin:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return parse_bulletin_pdf(path.read_bytes(), month, source=f"file:{path.name}")
    text = path.read_text()
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return Bulletin.from_dict(data)
