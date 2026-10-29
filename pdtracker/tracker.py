"""Wire config to a store, bulletin source and notifiers, and run the monthly check.

The local CLI, the local web page and the Azure Function all call check(); they differ only in
which store and notifiers config gives them.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date

from . import evaluate, render
from .bulletin import BulletinError, FolderInbox, InboxSource, StateDeptSource, StoredSource
from .config import Settings
from .graph import GraphClient
from .models import Bulletin
from .notify import EmailNotifier, FileNotifier, WebhookNotifier
from .stores import SqliteStore, previous_bulletin


def graph_for(s: Settings) -> GraphClient:
    return GraphClient.from_settings(s.tenant_id, s.client_id, s.client_secret)


def store_for(s: Settings, graph: GraphClient | None = None):
    if s.storage == "sharepoint":
        from .sharepoint import SharePointStore
        graph = graph or graph_for(s)
        return SharePointStore(graph, graph.site_id(s.sp_hostname, s.sp_site_path),
                               s.clients_list, s.bulletins_list, s.timezone)
    return SqliteStore(s.resolve(s.sqlite_path))


def inbox_for(s: Settings, store, graph: GraphClient | None = None):
    """Where staff drop bulletin PDFs: a SharePoint folder (cloud) or a local folder."""
    if s.storage == "sharepoint" and s.bulletin_folder:
        from .sharepoint import SharePointInbox
        return SharePointInbox(store.graph, store.site, s.bulletin_folder)
    if s.inbox_dir:
        return FolderInbox(s.resolve(s.inbox_dir))
    return None


def source_for(s: Settings, store, graph: GraphClient | None = None):
    fallback = (StoredSource(store) if s.bulletin_source == "manual"
                else StateDeptSource(s.index_url, s.page_url, s.pdf_url, s.bulletin_format))
    inbox = inbox_for(s, store, graph)
    return InboxSource(store, inbox, fallback) if inbox else fallback


def notifiers_for(s: Settings, graph: GraphClient | None = None, write_files: bool = True) -> list:
    out = []
    if write_files and s.report_dir:
        out.append(FileNotifier(s.resolve(s.report_dir)))
    if s.email_enabled:
        out.append(EmailNotifier(graph or graph_for(s), s.email_sender, s.email_recipients, s.email_responsible))
    if s.webhook_url:
        out.append(WebhookNotifier(s.webhook_url))
    return out


@dataclass
class CheckResult:
    month: str | None
    new: bool
    analysis: evaluate.Analysis | None = None
    subject: str = ""
    report: str = ""
    delivered: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def summary(self) -> str:
        if self.error:
            return f"Couldn't get the bulletin: {self.error}"
        if not self.month:
            return "No bulletin found."
        if not self.new:
            return f"{self.month} bulletin was already processed. Nothing new."
        return self.subject


def next_month(today: date) -> str:
    return f"{today.year + (today.month == 12):04d}-{today.month % 12 + 1:02d}"


def reminder_due(store, s: Settings, today: date) -> str | None:
    """The month to ask staff for, if its bulletin is missing and today is a reminder day."""
    if not s.reminder_day or today.day < s.reminder_day:
        return None
    if (today.day - s.reminder_day) % s.reminder_every_days:
        return None
    wanted = next_month(today)
    return None if wanted in store.bulletin_months() else wanted


def reminder_text(s: Settings, month: str, error: str = "") -> tuple[str, str]:
    y, m = map(int, month.split("-"))
    name = f"{calendar.month_name[m]} {y}"
    pdf = s.pdf_url.format(MonthName=calendar.month_name[m], month_name=calendar.month_name[m].lower(),
                           year=y, fiscal_year=y + 1 if m >= 10 else y)
    lines = [f"# The {name} Visa Bulletin isn't in the tracker yet", ""]
    if error:
        lines += [f"The automatic download didn't work: {error}", ""]
    lines += [f"Please download it from {pdf} (or the Visa Bulletin page on travel.state.gov) once it's out, "
              "then add it in one of these ways:", ""]
    if s.storage == "sharepoint" and s.bulletin_folder:
        lines.append(f"- Drop the PDF into the '{s.bulletin_folder}' folder on the office SharePoint site.")
    if s.inbox_dir:
        lines.append(f"- Drop the PDF into the folder {s.resolve(s.inbox_dir)}.")
    if s.storage == "sqlite":
        lines.append("- Upload it on the tracker's 'Enter a bulletin' page.")
    lines.append("- Or run: pdtrack -c <config> bulletin load <file.pdf>")
    lines += ["", "The tracker compares it with last month and sends the usual alerts as soon as it has it."]
    return f"{s.office_name}: please add the {name} Visa Bulletin", "\n".join(lines)


def analyze(store, s: Settings, bulletin: Bulletin) -> evaluate.Analysis:
    return evaluate.analyze(
        store.list_clients(), bulletin, previous_bulletin(store, bulletin.month),
        chart_defaults=s.chart_defaults, approaching_days=s.approaching_days,
        cspa_warning_days=s.cspa_warning_days)


def _remind(store, s: Settings, notifiers: list, result: CheckResult, today: date) -> CheckResult:
    wanted = reminder_due(store, s, today)
    if wanted:
        subj, text = reminder_text(s, wanted, result.error)
        result.delivered += [d for d in (n.remind(subj, text) for n in notifiers if hasattr(n, "remind")) if d]
    return result


def check(store, source, s: Settings, notifiers: list, month: str | None = None,
          force: bool = False, today: date | None = None) -> CheckResult:
    """Get the newest (or named) bulletin, compare it with the last one, alert once per bulletin.

    When next month's bulletin can't be found by the reminder day, ask staff to add it.
    """
    import requests

    today = today or date.today()
    try:
        bulletin = source.fetch(month) if month else source.latest()
    except (BulletinError, requests.RequestException) as e:
        return _remind(store, s, notifiers, CheckResult(month=month, new=False, error=str(e)), today)
    if bulletin is None:
        return _remind(store, s, notifiers, CheckResult(month=month, new=False), today)
    stored = store.get_bulletin(bulletin.month)
    if stored and store.is_processed(bulletin.month) and not force:
        return _remind(store, s, notifiers, CheckResult(month=bulletin.month, new=False), today)
    if stored:
        # Keep a USCIS chart choice someone already recorded for this month.
        bulletin.uscis_family_chart = bulletin.uscis_family_chart or stored.uscis_family_chart
        bulletin.uscis_employment_chart = bulletin.uscis_employment_chart or stored.uscis_employment_chart
    store.save_bulletin(bulletin)

    analysis = analyze(store, s, bulletin)
    subject = render.subject(s.office_name, analysis)
    report = render.to_markdown(s.office_name, analysis, s.chart_defaults)
    delivered = [n.send(subject, report, analysis) for n in notifiers]
    store.record_statuses(bulletin.month, analysis.rows)
    store.mark_processed(bulletin.month)
    return CheckResult(bulletin.month, True, analysis, subject, report, delivered)


def current_report(store, s: Settings, month: str | None = None) -> tuple[evaluate.Analysis, str] | None:
    """Status against a stored bulletin without alerting anyone."""
    months = store.bulletin_months()
    if not months:
        return None
    bulletin = store.get_bulletin(month or months[-1])
    if bulletin is None:
        return None
    analysis = analyze(store, s, bulletin)
    return analysis, render.to_markdown(s.office_name, analysis, s.chart_defaults)
