"""Load the per-office config. One YAML file per office; secrets come from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .bulletin import DEFAULT_INDEX_URL, DEFAULT_PAGE_URL, DEFAULT_PDF_URL, FORMATS
from .models import CHARTS, DATES_FOR_FILING, FINAL_ACTION


class ConfigError(ValueError):
    pass


@dataclass
class Settings:
    office_name: str
    timezone: str = "UTC"
    base_dir: Path = Path(".")
    storage: str = "sqlite"
    sqlite_path: str = "data/priority-dates.db"
    # Microsoft 365 (cloud storage and/or email)
    tenant_id: str = ""
    client_id: str = ""
    client_secret_env: str = "PDTRACKER_CLIENT_SECRET"
    sp_hostname: str = ""
    sp_site_path: str = ""
    clients_list: str = "Priority Dates"
    bulletins_list: str = "Visa Bulletins"
    bulletin_folder: str = ""        # SharePoint folder (in the site's Documents) where staff drop bulletin PDFs
    # Bulletin
    bulletin_source: str = "state_dept"
    index_url: str = DEFAULT_INDEX_URL
    page_url: str = DEFAULT_PAGE_URL
    pdf_url: str = DEFAULT_PDF_URL
    bulletin_format: str = "auto"    # pdf, html, or auto (PDF first, then the web page)
    inbox_dir: str = ""              # local folder where staff drop bulletin PDFs
    reminder_day: int = 20           # ask staff for the bulletin from this day of the month; 0 turns it off
    reminder_every_days: int = 3
    chart_defaults: dict = field(default_factory=lambda: {"family": DATES_FOR_FILING, "employment": FINAL_ACTION})
    # Alerts
    approaching_days: int = 180
    cspa_warning_days: int = 365
    report_dir: str = "reports"
    email_enabled: bool = False
    email_sender: str = ""
    email_recipients: list[str] = field(default_factory=list)
    email_responsible: bool = True
    webhook_url_env: str = ""
    # Import mapping: our field -> column header in the office's export
    import_columns: dict = field(default_factory=dict)

    def resolve(self, path: str) -> Path:
        p = Path(path).expanduser()
        return p if p.is_absolute() else self.base_dir / p

    @property
    def client_secret(self) -> str:
        secret = os.environ.get(self.client_secret_env)
        if not secret:
            raise ConfigError(f"Set the {self.client_secret_env} environment variable to the app's client secret.")
        return secret

    @property
    def uses_365(self) -> bool:
        return self.storage == "sharepoint" or self.email_enabled

    @property
    def webhook_url(self) -> str:
        return os.environ.get(self.webhook_url_env, "") if self.webhook_url_env else ""


def _need(section: dict, key: str, where: str):
    if section.get(key) in (None, ""):
        raise ConfigError(f"Missing '{where}.{key}' in config.")
    return section[key]


def parse(raw: dict, base_dir: Path = Path(".")) -> Settings:
    office = raw.get("office") or {}
    storage = raw.get("storage") or {}
    m365 = raw.get("microsoft365") or {}
    bulletin = raw.get("bulletin") or {}
    alerts = raw.get("alerts") or {}
    email = alerts.get("email") or {}

    s = Settings(office_name=_need(office, "name", "office"), timezone=office.get("timezone", "UTC"),
                 base_dir=base_dir)
    s.storage = storage.get("backend", "sqlite")
    if s.storage not in ("sqlite", "sharepoint"):
        raise ConfigError("storage.backend must be 'sqlite' or 'sharepoint'.")
    s.sqlite_path = storage.get("sqlite_path", s.sqlite_path)

    s.tenant_id = m365.get("tenant_id", "") or ""
    s.client_id = m365.get("client_id", "") or ""
    s.client_secret_env = m365.get("client_secret_env", s.client_secret_env)
    s.sp_hostname = m365.get("hostname", "") or ""
    s.sp_site_path = m365.get("site_path", "") or ""
    s.clients_list = m365.get("clients_list", s.clients_list)
    s.bulletins_list = m365.get("bulletins_list", s.bulletins_list)
    s.bulletin_folder = m365.get("bulletin_folder", "") or ""

    s.bulletin_source = bulletin.get("source", "state_dept")
    if s.bulletin_source not in ("state_dept", "manual"):
        raise ConfigError("bulletin.source must be 'state_dept' or 'manual'.")
    s.index_url = bulletin.get("index_url", s.index_url)
    s.page_url = bulletin.get("page_url", s.page_url)
    s.pdf_url = bulletin.get("pdf_url", s.pdf_url)
    s.bulletin_format = bulletin.get("format", s.bulletin_format)
    if s.bulletin_format not in FORMATS:
        raise ConfigError(f"bulletin.format must be one of {FORMATS}.")
    s.inbox_dir = bulletin.get("inbox_dir", "") or ""
    s.reminder_day = int(bulletin.get("reminder_day", s.reminder_day))
    s.reminder_every_days = max(1, int(bulletin.get("reminder_every_days", s.reminder_every_days)))
    chart = bulletin.get("uscis_chart_default") or {}
    for key in ("family", "employment"):
        if key in chart:
            if chart[key] not in CHARTS:
                raise ConfigError(f"bulletin.uscis_chart_default.{key} must be one of {CHARTS}.")
            s.chart_defaults[key] = chart[key]

    s.approaching_days = int(alerts.get("approaching_days", s.approaching_days))
    s.cspa_warning_days = int(alerts.get("cspa_warning_days", s.cspa_warning_days))
    s.report_dir = alerts.get("report_dir", s.report_dir)
    s.email_enabled = bool(email.get("enabled", False))
    s.email_sender = email.get("sender", "") or ""
    s.email_recipients = list(email.get("recipients") or [])
    s.email_responsible = bool(email.get("notify_responsible_attorney", True))
    s.webhook_url_env = alerts.get("webhook_url_env", "") or ""
    s.import_columns = dict((raw.get("import") or {}).get("columns") or {})

    if s.uses_365:
        for key in ("tenant_id", "client_id"):
            _need(m365, key, "microsoft365")
    if s.storage == "sharepoint":
        for key in ("hostname", "site_path"):
            _need(m365, key, "microsoft365")
    if s.email_enabled and (not s.email_sender or not s.email_recipients):
        raise ConfigError("alerts.email needs a sender and at least one recipient when enabled.")
    return s


def load(path: str | Path) -> Settings:
    path = Path(path)
    return parse(yaml.safe_load(path.read_text()) or {}, base_dir=path.parent.resolve())


def from_env() -> Settings:
    """For the cloud: config text in PDTRACKER_CONFIG_YAML, or a path in PDTRACKER_CONFIG."""
    inline = os.environ.get("PDTRACKER_CONFIG_YAML")
    if inline:
        return parse(yaml.safe_load(inline) or {}, base_dir=Path(os.environ.get("TMPDIR", "/tmp")))
    path = os.environ.get("PDTRACKER_CONFIG")
    if not path:
        raise ConfigError("Set PDTRACKER_CONFIG_YAML (the config text) or PDTRACKER_CONFIG (a path).")
    return load(path)
