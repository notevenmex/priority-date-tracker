"""Bulletin history: month-to-month changes in the cutoffs, in plain words."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .evaluate import movement
from .models import CHARTS, CURRENT, UNAVAILABLE, Bulletin

HISTORY_WINDOW = 6       # months shown in the month-by-month tables


def months_between(a: str, b: str) -> int:
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (yb - ya) * 12 + (mb - ma)


def series(history: list[Bulletin], chart: str, category: str, country: str) -> list[tuple[str, object]]:
    """(month, cutoff) for every bulletin on file that lists this cell, oldest first."""
    out = []
    for b in sorted(history, key=lambda b: b.month):
        cut = b.cutoff(chart, category, country)
        if cut is not None:
            out.append((b.month, cut))
    return out


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
    """How one cutoff moved, in the words attorneys use: 'advanced 1 month', 'retrogressed 2 weeks', 'no movement'."""
    if before is None:
        return "new this month"
    if after is None:
        return "no longer listed"
    if before == after:
        return "no movement"
    if after == CURRENT:
        return "became current (C)"
    if after == UNAVAILABLE:
        return "became unavailable (U)"
    if before == CURRENT:
        return "retrogressed from current to a cutoff date"
    if before == UNAVAILABLE:
        return "available again, up to a cutoff date"
    days = (after - before).days
    return f"{'advanced' if days > 0 else 'retrogressed'} {_amount(days)}"


def days_words(days: int) -> str:
    return f"{days:,} day{'s' if days != 1 else ''}"
