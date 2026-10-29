"""Bulletin history: how far each client still has to go, how fast cutoffs move, and month-to-month changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .evaluate import WAITING, ClientStatus, movement
from .models import CHARTS, CURRENT, UNAVAILABLE, Bulletin

PACE_WINDOW = 6          # months of history used for the pace estimate


def months_between(a: str, b: str) -> int:
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (yb - ya) * 12 + (mb - ma)


def add_months(month: str, n: int) -> str:
    y, m = map(int, month.split("-"))
    total = y * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def series(history: list[Bulletin], chart: str, category: str, country: str) -> list[tuple[str, object]]:
    """(month, cutoff) for every bulletin on file that lists this cell, oldest first."""
    out = []
    for b in sorted(history, key=lambda b: b.month):
        cut = b.cutoff(chart, category, country)
        if cut is not None:
            out.append((b.month, cut))
    return out


def pace(points: list[tuple[str, object]], window: int = PACE_WINDOW) -> float | None:
    """Average days the cutoff moved per bulletin month over the recent window.

    Only date-to-date stretches count; a "C" or "U" in the window breaks the trend, so the
    pace is measured from the last such break. None when there's less than a month of dates.
    """
    recent = points[-(window + 1):]
    dated = []
    for month, cut in recent:
        if cut in (CURRENT, UNAVAILABLE):
            dated = []
        else:
            dated.append((month, cut))
    if len(dated) < 2:
        return None
    span = months_between(dated[0][0], dated[-1][0])
    if span <= 0:
        return None
    return (dated[-1][1] - dated[0][1]).days / span


@dataclass
class Wait:
    days_left: int | None        # days the cutoff still has to move; 0 when current; None if unknown
    pace: float | None           # days per month the cutoff has been moving
    months: float | None         # estimated months until current at that pace
    estimate_month: str | None   # "YYYY-MM" of the bulletin that might make the client current
    history_months: int          # how many months of history the pace is based on

    @property
    def stalled(self) -> bool:
        return self.days_left and self.pace is not None and self.pace <= 0


def wait_for(row: ClientStatus, chart: str, history: list[Bulletin], latest_month: str) -> Wait:
    status = getattr(row, chart)
    cut = row.cutoffs[chart]
    pts = series(history, chart, row.client.category, row.client.chargeability)
    p = pace(pts)
    hist = max(0, months_between(pts[0][0], pts[-1][0])) if pts else 0
    if status != WAITING:
        return Wait(0 if status == "current" else None, p, None, None, hist)
    days = (row.client.priority_date - cut).days            # how far the cutoff still has to move
    if p is None or p <= 0:
        return Wait(days, p, None, None, hist)
    months = days / p
    return Wait(days, p, months, add_months(latest_month, max(1, round(months))), hist)


@dataclass
class Change:
    chart: str
    category: str
    country: str
    before: object
    after: object
    direction: str               # forward, backward, same, new


def compare(older: Bulletin, newer: Bulletin, countries: list[str]) -> list[Change]:
    """Every cell in both charts, with how it moved between two bulletins (any two, not just adjacent)."""
    out = []
    for chart in CHARTS:
        cats = list(dict.fromkeys(list(newer.chart(chart)) + list(older.chart(chart))))
        for cat in cats:
            for country in countries:
                a, b = older.cutoff(chart, cat, country), newer.cutoff(chart, cat, country)
                if a is None and b is None:
                    continue
                out.append(Change(chart, cat, country, a, b, movement(a, b)))
    return out


def all_bulletins(store) -> list[Bulletin]:
    return [b for b in (store.get_bulletin(m) for m in store.bulletin_months()) if b]


def today_month(today: date | None = None) -> str:
    today = today or date.today()
    return f"{today:%Y-%m}"


def _amount(days: int) -> str:
    days = abs(days)
    if days >= 330:
        years = round(days / 365.25, 1)
        return f"{years:g} year{'s' if years != 1 else ''}"
    if days >= 28:
        months = round(days / 30.44)
        return f"{months} month{'s' if months != 1 else ''}"
    if days >= 7 and days % 7 == 0:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''}"
    return f"{days} day{'s' if days != 1 else ''}"


def delta_words(before, after) -> str:
    """Plain words for how one cutoff moved: 'moved forward 1 month', 'became current', 'no change'."""
    if before is None:
        return "new this month"
    if after is None:
        return "no longer listed"
    if before == after:
        return "no change"
    if after == CURRENT:
        return "became current (everyone can move ahead)"
    if after == UNAVAILABLE:
        return "became unavailable (no one can move ahead)"
    if before in (CURRENT, UNAVAILABLE):
        return "now has a cutoff date"
    days = (after - before).days
    return f"moved {'forward' if days > 0 else 'back'} {_amount(days)}"


def days_words(days: int) -> str:
    return f"{days:,} day{'s' if days != 1 else ''}"


def wait_words(w: Wait) -> str:
    """'about 9 months (around Aug 2027) at the recent pace' or why there is no estimate."""
    import calendar
    if w.days_left == 0:
        return "current now"
    if w.days_left is None:
        return "no estimate (category unavailable or not listed)"
    if w.pace is None:
        return "no estimate yet (needs at least two bulletins with dates)"
    if w.pace <= 0:
        return "no estimate: this cutoff hasn't moved forward recently"
    y, m = map(int, w.estimate_month.split("-"))
    months = w.months
    length = f"about {round(months)} month{'s' if round(months) != 1 else ''}" if months < 23.5 \
        else f"about {round(months / 12, 1):g} years"
    basis = (f", based on only {w.history_months} month{'s' if w.history_months != 1 else ''} of history"
             if w.history_months < 3 else "")
    return f"{length} (around {calendar.month_abbr[m]} {y}) at the recent pace{basis}"
