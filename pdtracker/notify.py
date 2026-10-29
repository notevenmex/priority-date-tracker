"""Where alerts go: a report file, Microsoft 365 email, and/or a webhook (Teams, Power Automate, Slack)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import render
from .evaluate import APPROACHING, BECAME_CURRENT, CSPA_REVIEW, NO_LONGER_CURRENT, Analysis

ALERT_KINDS = (BECAME_CURRENT, NO_LONGER_CURRENT, CSPA_REVIEW)


class ConsoleNotifier:
    """Prints reminders when the check runs by hand from the command line."""

    def send(self, subject: str, markdown: str, analysis: Analysis) -> str:
        return ""

    def remind(self, subject: str, markdown: str) -> str:
        print(f"\n{subject}\n\n{markdown}\n")
        return ""


class FileNotifier:
    def __init__(self, folder: Path):
        self.folder = folder

    def send(self, subject: str, markdown: str, analysis: Analysis) -> str:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"visa-bulletin-{analysis.bulletin.month}.md"
        path.write_text(markdown)
        return f"wrote {path}"

    def remind(self, subject: str, markdown: str) -> str:
        return ""        # reminders need to reach a person; a file nobody opens doesn't


class EmailNotifier:
    """Office report to the configured recipients, plus a short note to each responsible attorney."""

    def __init__(self, graph, sender: str, recipients: list[str], notify_responsible: bool = True):
        self.graph = graph
        self.sender = sender
        self.recipients = recipients
        self.notify_responsible = notify_responsible

    def send(self, subject: str, markdown: str, analysis: Analysis) -> str:
        self.graph.send_mail(self.sender, self.recipients, subject, render.to_html(markdown))
        sent = len(self.recipients)
        if self.notify_responsible:
            by_person = defaultdict(list)
            for e in analysis.events:
                if e.kind in ALERT_KINDS + (APPROACHING,) and e.client.responsible_email:
                    by_person[e.client.responsible_email.lower()].append(e)
            for person, events in by_person.items():
                if person in (r.lower() for r in self.recipients):
                    continue
                lines = [f"# Your clients in the {analysis.bulletin.month} Visa Bulletin", ""]
                lines += [f"- **{e.client.name} ({e.client.category}):** {e.detail}" for e in events]
                self.graph.send_mail(self.sender, [person], subject, render.to_html("\n".join(lines)))
                sent += 1
        return f"emailed {sent} people"

    def remind(self, subject: str, markdown: str) -> str:
        self.graph.send_mail(self.sender, self.recipients, subject, render.to_html(markdown))
        return f"emailed a reminder to {len(self.recipients)} people"


class WebhookNotifier:
    """POSTs a small JSON message. Works with a Teams or Power Automate workflow trigger and Slack."""

    def __init__(self, url: str, session=None):
        import requests

        self.url = url
        self.session = session or requests.Session()

    def send(self, subject: str, markdown: str, analysis: Analysis) -> str:
        alerts = [f"- {e.client.name}: {e.detail}" for e in analysis.events if e.kind in ALERT_KINDS]
        alerts += [f"- Moved back: {m.category} {m.country} ({m.chart.replace('_', ' ')}) "
                   f"{render.cutoff_label(m.previous)} to {render.cutoff_label(m.current)}"
                   for m in analysis.retrogressions]
        text = subject + ("\n" + "\n".join(alerts) if alerts else "")
        self.session.post(self.url, json={"text": text, "title": subject,
                                          "month": analysis.bulletin.month}, timeout=30).raise_for_status()
        return "posted to webhook"

    def remind(self, subject: str, markdown: str) -> str:
        self.session.post(self.url, json={"text": f"{subject}\n{markdown}", "title": subject},
                          timeout=30).raise_for_status()
        return "posted a reminder to webhook"
