"""Turn an analysis into a plain-language markdown report and a minimal HTML version for email."""

from __future__ import annotations

import html

from .categories import CATEGORIES, COUNTRIES
from . import history as hist
from .evaluate import (APPROACHING, BECAME_CURRENT, CSPA_REVIEW, IS_CURRENT, NO_LONGER_CURRENT,
                       NOT_AVAILABLE, UNKNOWN, WAITING, Analysis)
from .models import CHART_LABELS, DATES_FOR_FILING, FINAL_ACTION, cutoff_label

STATUS_LABELS = {IS_CURRENT: "Current", WAITING: "Not current", NOT_AVAILABLE: "Unavailable", UNKNOWN: "Not in bulletin"}


def _month_label(month: str) -> str:
    import calendar
    y, m = month.split("-")
    return f"{calendar.month_name[int(m)]} {y}"


def _who(client) -> str:
    bits = [client.name, f"{client.category} {COUNTRIES[client.chargeability]}",
            f"PD {client.priority_date:%b %d, %Y}"]
    if client.receipt_number:
        bits.append(client.receipt_number)
    return " · ".join(bits)


def subject(office: str, analysis: Analysis) -> str:
    n_cur = len({e.client.id for e in analysis.events_of(BECAME_CURRENT)})
    n_back = len({e.client.id for e in analysis.events_of(NO_LONGER_CURRENT)})
    bits = []
    if n_cur:
        bits.append(f"{n_cur} newly current")
    if n_back:
        bits.append(f"{n_back} retrogressed")
    n_moved_back = len(analysis.retrogressions)
    if n_moved_back and not n_back:
        bits.append(f"{n_moved_back} cutoff{'s' if n_moved_back != 1 else ''} retrogressed")
    tail = ", ".join(bits) if bits else "no changes for clients"
    return f"{office}: {_month_label(analysis.bulletin.month)} Visa Bulletin, {tail}"


def to_markdown(office: str, a: Analysis, chart_defaults: dict | None = None,
                history: list | None = None) -> str:
    chart_defaults = chart_defaults or {"family": DATES_FOR_FILING, "employment": FINAL_ACTION}
    b = a.bulletin
    lines = [f"# {office}: {_month_label(b.month)} Visa Bulletin", ""]
    if b.source:
        lines += [f"_Source: {b.source}_", ""]
    def chart_note(kind, chosen):
        if chosen:
            return f"{kind} {CHART_LABELS[chosen]}"
        return f"{kind} {CHART_LABELS[chart_defaults.get(kind, DATES_FOR_FILING)]} (office default, not yet confirmed)"

    note = ("USCIS chart for I-485 filing: " + chart_note("family", b.uscis_family_chart) + "; "
            + chart_note("employment", b.uscis_employment_chart) + ". "
            "Confirm at uscis.gov/visabulletininfo before filing.")
    lines += [note, ""]

    def section(title, events):
        if not events:
            return
        lines.extend([f"## {title} ({len(events)})", ""])
        for e in events:
            lines.append(f"- **{_who(e.client)}:** {e.detail}")
        lines.append("")

    section("Newly current", a.events_of(BECAME_CURRENT))
    section("Retrogressed for these clients", a.events_of(NO_LONGER_CURRENT))
    section("Close to current", a.events_of(APPROACHING))
    section("Age-out check", a.events_of(CSPA_REVIEW))

    lines += days_left_section(a)
    if a.previous is None:
        lines += ["This is the first bulletin on file, so there is nothing to compare against yet.", ""]
    else:
        lines += changes_section(a)
    if history and len(history) > 1:
        lines += history_section(a, history)

    lines += [f"## All active clients ({len(a.rows)})", ""]
    for r in sorted(a.rows, key=lambda r: (r.final_action != IS_CURRENT, r.client.name.lower())):
        i485 = "yes" if r.can_file_i485 else "no"
        lines.append(f"- **{_who(r.client)}:** Final Action {STATUS_LABELS[r.final_action]} "
                     f"({cutoff_label(r.cutoffs['final_action'])}), Dates for Filing "
                     f"{STATUS_LABELS[r.dates_for_filing]} ({cutoff_label(r.cutoffs['dates_for_filing'])}), "
                     f"I-485 filing open: {i485}")
    lines.append("")
    lines.append("_This is a tracking aid. Verify cutoffs against the published bulletin before advising a client._")
    return "\n".join(lines)


def _change_line(m) -> str:
    who = f" ({len(m.clients)} of your clients)" if m.clients else ""
    return (f"- **{m.category} {COUNTRIES[m.country]}:** {hist.delta_words(m.previous, m.current)}, from "
            f"{cutoff_label(m.previous)} to {cutoff_label(m.current)}{who}")


def days_left_section(a: Analysis) -> list[str]:
    waiting = sorted((r for r in a.rows if r.days_to_cutoff is not None),
                     key=lambda r: (r.days_to_cutoff, r.client.name.lower()))
    if not waiting:
        return []
    lines = [f"## Time until current ({len(waiting)} not yet current)", "",
             "How far the Final Action cutoff must advance to reach each priority date, and how that cutoff "
             "moved since the previous bulletin.", ""]
    for r in waiting:
        c = r.client
        now = r.cutoffs[FINAL_ACTION]
        line = (f"- **{c.name} ({c.category} {COUNTRIES[c.chargeability]}):** "
                f"{hist.gap_words(now, c.priority_date)} until current. Final Action cutoff ")
        if a.previous:
            before = a.previous.cutoff(FINAL_ACTION, c.category, c.chargeability)
            line += (f"{hist.delta_words(before, now)}: {cutoff_label(before)} ({_month_label(a.previous.month)}) "
                     f"to {cutoff_label(now)} ({_month_label(a.bulletin.month)})")
        else:
            line += f"{cutoff_label(now)} in {_month_label(a.bulletin.month)}"
        lines.append(line + ".")
    lines.append("")
    return lines


def history_section(a: Analysis, history: list) -> list[str]:
    cells = sorted({(r.client.category, r.client.chargeability) for r in a.rows},
                   key=lambda k: (list(CATEGORIES).index(k[0]), k[1]))
    upto = [b for b in history if b.month <= a.bulletin.month][-hist.HISTORY_WINDOW - 1:]
    if len(upto) < 2 or not cells:
        return []
    lines = [f"## Final Action cutoffs over the last {len(upto)} bulletins (your clients' categories)", ""]
    for cat, country in cells:
        pts = hist.series(upto, FINAL_ACTION, cat, country)
        trail = " → ".join(f"{cutoff_label(c)} ({_month_label(m)[:3]} {m[:4]})" for m, c in pts)
        lines.append(f"- **{cat} {COUNTRIES[country]}:** {trail}")
    lines.append("")
    return lines


def changes_section(a: Analysis) -> list[str]:
    """Every cutoff that differs from the previous bulletin, whether or not a client is affected."""
    prev = _month_label(a.previous.month)
    lines = [f"## Everything that changed since {prev}", ""]
    for kind, label in (("uscis_family_chart", "family"), ("uscis_employment_chart", "employment")):
        old, new = getattr(a.previous, kind), getattr(a.bulletin, kind)
        if old and new and old != new:
            lines.append(f"- **USCIS {label} filing chart:** changed from {CHART_LABELS[old]} to {CHART_LABELS[new]}")
    if not a.movements:
        lines += [f"No cutoffs changed since {prev}.", ""]
        return lines
    for chart in (FINAL_ACTION, DATES_FOR_FILING):
        moved = [m for m in a.movements if m.chart == chart]
        if not moved:
            lines += [f"{CHART_LABELS[chart]}: no movement.", ""]
            continue
        back = [m for m in moved if m.direction == "backward"]
        fwd = [m for m in moved if m.direction == "forward"]
        lines += [f"### {CHART_LABELS[chart]}: {len(back)} retrogressed, {len(fwd)} advanced", ""]
        lines += [_change_line(m) for m in back + fwd]
        lines.append("")
    return lines


def to_html(md: str) -> str:
    out = []
    in_list = False
    for line in md.splitlines():
        text = html.escape(line)
        while "**" in text:
            text = text.replace("**", "<b>", 1).replace("**", "</b>", 1)
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{text[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("# "):
            out.append(f"<h2>{text[2:]}</h2>")
        elif line.startswith("### "):
            out.append(f"<h4>{text[4:]}</h4>")
        elif line.startswith("## "):
            out.append(f"<h3>{text[3:]}</h3>")
        elif line.startswith("_") and line.endswith("_"):
            out.append(f"<p><i>{text[1:-1]}</i></p>")
        elif line:
            out.append(f"<p>{text}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def category_choices() -> list[tuple[str, str]]:
    return list(CATEGORIES.items())
