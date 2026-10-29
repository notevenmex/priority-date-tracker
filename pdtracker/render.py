"""Turn an analysis into a plain-language markdown report and a minimal HTML version for email."""

from __future__ import annotations

import html

from .categories import CATEGORIES, COUNTRIES
from .evaluate import (APPROACHING, BECAME_CURRENT, CSPA_REVIEW, IS_CURRENT, NO_LONGER_CURRENT,
                       NOT_AVAILABLE, UNKNOWN, WAITING, Analysis)
from .models import CHART_LABELS, DATES_FOR_FILING, FINAL_ACTION, cutoff_label

STATUS_LABELS = {IS_CURRENT: "Current", WAITING: "Waiting", NOT_AVAILABLE: "Unavailable", UNKNOWN: "Not in bulletin"}


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
    tail = ", ".join(bits) if bits else "no changes for clients"
    return f"{office}: {_month_label(analysis.bulletin.month)} Visa Bulletin, {tail}"


def to_markdown(office: str, a: Analysis, chart_defaults: dict | None = None) -> str:
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
    section("Moved backward for these clients", a.events_of(NO_LONGER_CURRENT))
    section("Close to current", a.events_of(APPROACHING))
    section("Age-out check", a.events_of(CSPA_REVIEW))

    affecting = [m for m in a.movements if m.clients]
    if affecting:
        lines += [f"## Cutoff changes in your clients' categories ({len(affecting)})", ""]
        for m in affecting:
            arrow = "moved back" if m.direction == "backward" else "advanced"
            lines.append(f"- **{CHART_LABELS[m.chart]}, {m.category} {COUNTRIES[m.country]}:** {arrow} from "
                         f"{cutoff_label(m.previous)} to {cutoff_label(m.current)} "
                         f"({len(m.clients)} client{'s' if len(m.clients) != 1 else ''})")
        lines.append("")
    if a.previous is None:
        lines += ["This is the first bulletin on file, so there is nothing to compare against yet.", ""]

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
