"""Compare each client's priority date to a bulletin, and a bulletin to the month before it."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .categories import CATEGORIES, COUNTRIES, is_family
from .models import CHARTS, CURRENT, DATES_FOR_FILING, FINAL_ACTION, UNAVAILABLE, Bulletin, Client

# Statuses
IS_CURRENT = "current"
WAITING = "waiting"
NOT_AVAILABLE = "unavailable"
UNKNOWN = "unknown"

# Event kinds, in the order the report shows them
BECAME_CURRENT = "became_current"
NO_LONGER_CURRENT = "no_longer_current"
APPROACHING = "approaching"
CSPA_REVIEW = "cspa_review"


def status(priority_date: date, cutoff) -> str:
    """A priority date is current when it is earlier than the cutoff (the bulletin's rule)."""
    if cutoff is None:
        return UNKNOWN
    if cutoff == CURRENT:
        return IS_CURRENT
    if cutoff == UNAVAILABLE:
        return NOT_AVAILABLE
    return IS_CURRENT if priority_date < cutoff else WAITING


def _rank(cutoff):
    if cutoff == UNAVAILABLE:
        return (0, date.min)
    if cutoff == CURRENT:
        return (2, date.max)
    return (1, cutoff)


def movement(previous, current) -> str:
    """'forward', 'backward', 'same' or 'new' for one category/country cell."""
    if previous is None or current is None:
        return "new"
    a, b = _rank(previous), _rank(current)
    return "same" if a == b else "forward" if b > a else "backward"


def uscis_chart(bulletin: Bulletin, category: str, defaults: dict) -> str:
    if is_family(category):
        return bulletin.uscis_family_chart or defaults.get("family", DATES_FOR_FILING)
    return bulletin.uscis_employment_chart or defaults.get("employment", FINAL_ACTION)


@dataclass
class ClientStatus:
    client: Client
    final_action: str
    dates_for_filing: str
    cutoffs: dict                    # chart -> cutoff
    uscis_chart: str                 # chart USCIS accepts for I-485 filing this month
    days_to_cutoff: int | None       # days the priority date is past the final action cutoff, when waiting

    @property
    def can_file_i485(self) -> bool:
        chart = self.final_action if self.uscis_chart == FINAL_ACTION else self.dates_for_filing
        return chart == IS_CURRENT


@dataclass
class Event:
    kind: str
    client: Client
    chart: str
    detail: str


@dataclass
class Movement:
    category: str
    country: str
    chart: str
    previous: object
    current: object
    direction: str
    clients: list[Client] = field(default_factory=list)


@dataclass
class Analysis:
    bulletin: Bulletin
    previous: Bulletin | None
    rows: list[ClientStatus]
    events: list[Event]
    movements: list[Movement]

    def events_of(self, kind: str) -> list[Event]:
        return [e for e in self.events if e.kind == kind]

    @property
    def retrogressions(self) -> list[Movement]:
        return [m for m in self.movements if m.direction == "backward"]


def client_status(client: Client, bulletin: Bulletin, chart_defaults: dict) -> ClientStatus:
    cutoffs = {chart: bulletin.cutoff(chart, client.category, client.chargeability) for chart in CHARTS}
    fa = status(client.priority_date, cutoffs[FINAL_ACTION])
    gap = None
    if fa == WAITING:
        gap = (client.priority_date - cutoffs[FINAL_ACTION]).days
    return ClientStatus(
        client=client,
        final_action=fa,
        dates_for_filing=status(client.priority_date, cutoffs[DATES_FOR_FILING]),
        cutoffs=cutoffs,
        uscis_chart=uscis_chart(bulletin, client.category, chart_defaults),
        days_to_cutoff=gap,
    )


def _age_21(dob: date) -> date:
    try:
        return dob.replace(year=dob.year + 21)
    except ValueError:                       # Feb 29
        return date(dob.year + 21, 3, 1)


def analyze(clients: list[Client], bulletin: Bulletin, previous: Bulletin | None = None, *,
            chart_defaults: dict | None = None, approaching_days: int = 180,
            cspa_warning_days: int = 365, today: date | None = None) -> Analysis:
    chart_defaults = chart_defaults or {}
    today = today or date.today()
    active = [c for c in clients if c.active]
    rows = [client_status(c, bulletin, chart_defaults) for c in active]
    before = [client_status(c, previous, chart_defaults) if previous else None for c in active]

    events: list[Event] = []
    for row, old in zip(rows, before):
        for chart in CHARTS:
            now_s = getattr(row, chart)
            was_s = getattr(old, chart) if old else None
            label = "Final Action" if chart == FINAL_ACTION else "Dates for Filing"
            if now_s == IS_CURRENT and was_s not in (None, IS_CURRENT):
                events.append(Event(BECAME_CURRENT, row.client, chart, f"Current under {label}."))
            elif was_s == IS_CURRENT and now_s in (WAITING, NOT_AVAILABLE):
                events.append(Event(NO_LONGER_CURRENT, row.client, chart,
                                    f"No longer current under {label} (cutoff moved back)."))
        if row.days_to_cutoff is not None and 0 <= row.days_to_cutoff <= approaching_days:
            events.append(Event(APPROACHING, row.client, FINAL_ACTION,
                                f"{row.days_to_cutoff} days from the Final Action cutoff."))
        dob = row.client.beneficiary_dob
        if dob:
            turns_21 = _age_21(dob)
            days_left = (turns_21 - today).days
            if 0 <= days_left <= cspa_warning_days:
                events.append(Event(CSPA_REVIEW, row.client, FINAL_ACTION,
                                    f"Beneficiary turns 21 on {turns_21:%b %d, %Y}. Review CSPA age."))

    movements: list[Movement] = []
    if previous:
        by_cell: dict[tuple, list[Client]] = {}
        for c in active:
            by_cell.setdefault((c.category, c.chargeability), []).append(c)
        for chart in CHARTS:
            for cat in CATEGORIES:
                for country in COUNTRIES:
                    cur = bulletin.chart(chart).get(cat, {}).get(country)
                    if cur is None:
                        continue
                    prev = previous.chart(chart).get(cat, {}).get(country)
                    direction = movement(prev, cur)
                    if direction in ("forward", "backward"):
                        movements.append(Movement(cat, country, chart, prev, cur, direction,
                                                  by_cell.get((cat, country), [])))
    return Analysis(bulletin, previous, rows, events, movements)
