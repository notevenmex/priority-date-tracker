"""Client records and bulletin snapshots. Plain dataclasses that serialize to JSON-friendly dicts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from .categories import CATEGORIES, chargeability_column, normalize_category

CURRENT = "C"
UNAVAILABLE = "U"
FINAL_ACTION = "final_action"
DATES_FOR_FILING = "dates_for_filing"
CHARTS = (FINAL_ACTION, DATES_FOR_FILING)
CHART_LABELS = {FINAL_ACTION: "Final Action Dates", DATES_FOR_FILING: "Dates for Filing"}

Cutoff = "date | str"   # a date, CURRENT or UNAVAILABLE

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def parse_date(value) -> date | None:
    """Accept date objects, ISO strings, US 'MM/DD/YYYY', and bulletin style '01JAN17'."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?", text)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        return date(int(m[3]), int(m[1]), int(m[2]))
    m = re.fullmatch(r"(\d{1,2})\s*([A-Za-z]{3})\s*(\d{2}|\d{4})", text)
    if m and m[2].upper() in _MONTHS:
        year = int(m[3])
        if year < 100:
            year += 1900 if year >= 50 else 2000
        return date(year, _MONTHS.index(m[2].upper()) + 1, int(m[1]))
    raise ValueError(f"Can't read the date '{value}'. Use YYYY-MM-DD.")


def parse_cutoff(value):
    text = str(value).strip().upper()
    if text in ("C", "CURRENT"):
        return CURRENT
    if text in ("U", "UNAVAILABLE"):
        return UNAVAILABLE
    return parse_date(text)


def cutoff_str(cutoff) -> str:
    return cutoff.isoformat() if isinstance(cutoff, date) else str(cutoff)


def gap_words(earlier: date, later: date) -> str:
    """Calendar distance between two dates: '1 year, 4 months, 14 days', '6 months, 2 days', '9 days'.

    Counted the way a person reads a calendar: whole months from the earlier date (a day that
    doesn't exist in a shorter month falls on its last day), then the days left over.
    """
    import calendar
    if later < earlier:
        earlier, later = later, earlier

    def plus(months: int) -> date:
        total = earlier.year * 12 + earlier.month - 1 + months
        y, m = divmod(total, 12)
        return date(y, m + 1, min(earlier.day, calendar.monthrange(y, m + 1)[1]))

    months = (later.year - earlier.year) * 12 + later.month - earlier.month
    while months > 0 and plus(months) > later:
        months -= 1
    days = (later - plus(months)).days
    years, months = divmod(months, 12)
    parts = [f"{n} {unit}{'s' if n != 1 else ''}" for n, unit in ((years, "year"), (months, "month"), (days, "day")) if n]
    return ", ".join(parts) or "0 days"


def cutoff_label(cutoff) -> str:
    if cutoff == CURRENT:
        return "Current"
    if cutoff == UNAVAILABLE:
        return "Unavailable"
    if cutoff is None:
        return "n/a"
    return f"{cutoff:%b %d, %Y}"


def month_key(value: str) -> str:
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", str(value).strip())
    if not m or not 1 <= int(m[2]) <= 12:
        raise ValueError(f"Months are written YYYY-MM, got '{value}'.")
    return f"{int(m[1]):04d}-{int(m[2]):02d}"


@dataclass
class Client:
    name: str
    category: str
    chargeability: str
    priority_date: date
    id: str = ""
    case_type: str = ""
    receipt_number: str = ""
    beneficiary_dob: date | None = None
    responsible_email: str = ""
    notes: str = ""
    active: bool = True
    external_id: str = ""            # id in an outside case system, for syncing
    petitioner: str = ""             # employer or relative filing for the client
    case_status: str = ""            # where the matter stands in the case system
    attorney: str = ""               # who handles it (name or initials)
    outside_status: str = ""         # the case system's own current / not current flag, to cross-check

    def __post_init__(self):
        self.category = normalize_category(self.category)
        self.chargeability = chargeability_column(self.chargeability)
        self.priority_date = parse_date(self.priority_date)
        self.beneficiary_dob = parse_date(self.beneficiary_dob)
        if not self.name.strip():
            raise ValueError("Client name is required.")
        if self.priority_date is None:
            raise ValueError("Priority date is required.")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["priority_date"] = self.priority_date.isoformat()
        d["beneficiary_dob"] = self.beneficiary_dob.isoformat() if self.beneficiary_dob else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Client":
        fields = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        if isinstance(fields.get("active"), str):
            fields["active"] = fields["active"].strip().lower() not in ("0", "false", "no", "n", "")
        return cls(**fields)


@dataclass
class Bulletin:
    month: str                                    # "2026-11"
    final_action: dict = field(default_factory=dict)       # category -> country -> cutoff
    dates_for_filing: dict = field(default_factory=dict)
    source: str = ""
    # Which chart USCIS accepts for I-485 this month. None means "use the office default".
    uscis_family_chart: str | None = None
    uscis_employment_chart: str | None = None

    def __post_init__(self):
        self.month = month_key(self.month)

    def chart(self, name: str) -> dict:
        return self.final_action if name == FINAL_ACTION else self.dates_for_filing

    def cutoff(self, chart: str, category: str, country: str):
        row = self.chart(chart).get(category)
        if not row:
            return None
        return row.get(country, row.get("ROW"))

    def to_dict(self) -> dict:
        def ser(chart):
            return {cat: {c: cutoff_str(v) for c, v in row.items()} for cat, row in chart.items()}
        return {
            "month": self.month, "source": self.source,
            "uscis_family_chart": self.uscis_family_chart,
            "uscis_employment_chart": self.uscis_employment_chart,
            FINAL_ACTION: ser(self.final_action), DATES_FOR_FILING: ser(self.dates_for_filing),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Bulletin":
        def de(chart):
            out = {}
            for cat, row in (chart or {}).items():
                cat = normalize_category(cat)
                out[cat] = {chargeability_column(c): parse_cutoff(v) for c, v in (row or {}).items() if v not in (None, "")}
            return out
        for chart_name in ("uscis_family_chart", "uscis_employment_chart"):
            if d.get(chart_name) not in (None, *CHARTS):
                raise ValueError(f"{chart_name} must be one of {CHARTS}.")
        return cls(
            month=d["month"], source=d.get("source", ""),
            uscis_family_chart=d.get("uscis_family_chart"),
            uscis_employment_chart=d.get("uscis_employment_chart"),
            final_action=de(d.get(FINAL_ACTION)), dates_for_filing=de(d.get(DATES_FOR_FILING)),
        )

    @classmethod
    def template(cls, month: str, previous: "Bulletin | None" = None) -> dict:
        """A fill-in-the-blanks dict for manual entry, prefilled from last month when given."""
        if previous:
            d = previous.to_dict()
            d.update(month=month_key(month), source="manual", uscis_family_chart=None, uscis_employment_chart=None)
            return d
        blank = {cat: {c: "" for c in ("ROW", "CHINA", "INDIA", "MEXICO", "PHILIPPINES")} for cat in CATEGORIES}
        return {"month": month_key(month), "source": "manual", "uscis_family_chart": None,
                "uscis_employment_chart": None, FINAL_ACTION: blank, DATES_FOR_FILING: blank}
