"""Wire config to a store, bulletin source and notifiers, and run the monthly check.

The local CLI, the local web page and the Azure Function all call check(); they differ only in
which store and notifiers config gives them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import evaluate, render
from .bulletin import StateDeptSource, StoredSource
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


def source_for(s: Settings, store):
    if s.bulletin_source == "manual":
        return StoredSource(store)
    return StateDeptSource(s.index_url, s.page_url)


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

    @property
    def summary(self) -> str:
        if not self.month:
            return "No bulletin found."
        if not self.new:
            return f"{self.month} bulletin was already processed. Nothing new."
        return self.subject


def analyze(store, s: Settings, bulletin: Bulletin) -> evaluate.Analysis:
    return evaluate.analyze(
        store.list_clients(), bulletin, previous_bulletin(store, bulletin.month),
        chart_defaults=s.chart_defaults, approaching_days=s.approaching_days,
        cspa_warning_days=s.cspa_warning_days)


def check(store, source, s: Settings, notifiers: list, month: str | None = None,
          force: bool = False) -> CheckResult:
    """Get the newest (or named) bulletin, compare it with the last one, alert once per bulletin."""
    bulletin = source.fetch(month) if month else source.latest()
    if bulletin is None:
        return CheckResult(month=month, new=False)
    stored = store.get_bulletin(bulletin.month)
    if stored and store.is_processed(bulletin.month) and not force:
        return CheckResult(month=bulletin.month, new=False)
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
