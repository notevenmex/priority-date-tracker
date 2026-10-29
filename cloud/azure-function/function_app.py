"""Cloud version: an Azure Function in the office's own Azure subscription.

- A daily timer looks for a new bulletin (a PDF staff dropped in the SharePoint folder, else the
  PDF or web page on travel.state.gov), compares it with the last one, updates each client's
  status in the SharePoint list and emails alerts once per bulletin. If next month's bulletin
  still isn't in by the reminder day, it emails staff asking them to add it.
- HTTP endpoints (function key required) let staff or a Power Automate flow run a check,
  read the current status, or post a bulletin entered by hand.

Config comes from app settings: PDTRACKER_CONFIG_YAML holds the office's YAML and
PDTRACKER_CLIENT_SECRET (ideally a Key Vault reference) holds the app secret.
"""

import json
import logging

import azure.functions as func

from pdtracker import config, tracker
from pdtracker.bulletin import BulletinError, parse_bulletin_pdf
from pdtracker.models import Bulletin

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def _setup():
    s = config.from_env()
    graph = tracker.graph_for(s)
    store = tracker.store_for(s, graph)
    return s, graph, store


def _run(force: bool = False, month: str | None = None) -> tracker.CheckResult:
    s, graph, store = _setup()
    source = tracker.source_for(s, store, graph)
    # No local disk worth keeping in the cloud, so no report files; email and webhook only.
    return tracker.check(store, source, s, tracker.notifiers_for(s, graph, write_files=False),
                         month=month, force=force)


@app.timer_trigger(schedule="%PDTRACKER_SCHEDULE%", arg_name="timer", run_on_startup=False)
def daily_check(timer: func.TimerRequest) -> None:
    result = _run()
    logging.info("pdtracker: %s", result.summary)


@app.route(route="check", methods=["POST"])
def check_now(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json() if req.get_body() else {}
    result = _run(force=bool(body.get("force")), month=body.get("month"))
    return func.HttpResponse(json.dumps({"summary": result.summary, "month": result.month,
                                         "delivered": result.delivered}), mimetype="application/json")


@app.route(route="status", methods=["GET"])
def status(req: func.HttpRequest) -> func.HttpResponse:
    s, _, store = _setup()
    out = tracker.current_report(store, s, req.params.get("month"))
    if not out:
        return func.HttpResponse(json.dumps({"error": "no bulletin on file"}), status_code=404,
                                 mimetype="application/json")
    analysis, _ = out
    rows = [{"id": r.client.id, "name": r.client.name, "category": r.client.category,
             "chargeability": r.client.chargeability, "priority_date": r.client.priority_date.isoformat(),
             "final_action": r.final_action, "dates_for_filing": r.dates_for_filing,
             "i485_open": r.can_file_i485} for r in analysis.rows]
    return func.HttpResponse(json.dumps({"month": analysis.bulletin.month, "clients": rows}),
                             mimetype="application/json")


@app.route(route="bulletin", methods=["POST"])
def save_bulletin(req: func.HttpRequest) -> func.HttpResponse:
    """Body: the bulletin PDF (Content-Type: application/pdf), or the JSON 'pdtrack bulletin template' produces.

    A PDF is checked right away (compared with last month, alerts sent). Add ?month=YYYY-MM if the
    month can't be read from the PDF.
    """
    try:
        if req.headers.get("Content-Type", "").startswith("application/pdf"):
            b = parse_bulletin_pdf(req.get_body(), req.params.get("month"), source="upload")
        else:
            b = Bulletin.from_dict(req.get_json())
    except (ValueError, KeyError, BulletinError) as e:
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=400, mimetype="application/json")
    s, graph, store = _setup()
    stored = store.get_bulletin(b.month)
    if stored:
        b.uscis_family_chart = b.uscis_family_chart or stored.uscis_family_chart
        b.uscis_employment_chart = b.uscis_employment_chart or stored.uscis_employment_chart
    store.save_bulletin(b)
    result = tracker.check(store, tracker.StoredSource(store), s,
                           tracker.notifiers_for(s, graph, write_files=False), month=b.month)
    return func.HttpResponse(json.dumps({"saved": b.month, "summary": result.summary}), mimetype="application/json")
