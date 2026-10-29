"""Cloud version: an Azure Function in the office's own Azure subscription.

- A daily timer checks travel.state.gov for a new bulletin, compares it with the last one,
  updates each client's status in the SharePoint list and emails alerts once per bulletin.
- HTTP endpoints (function key required) let staff or a Power Automate flow run a check,
  read the current status, or post a bulletin entered by hand.

Config comes from app settings: PDTRACKER_CONFIG_YAML holds the office's YAML and
PDTRACKER_CLIENT_SECRET (ideally a Key Vault reference) holds the app secret.
"""

import json
import logging

import azure.functions as func

from pdtracker import config, tracker
from pdtracker.models import Bulletin

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def _setup():
    s = config.from_env()
    graph = tracker.graph_for(s)
    store = tracker.store_for(s, graph)
    return s, graph, store


def _run(force: bool = False, month: str | None = None) -> tracker.CheckResult:
    s, graph, store = _setup()
    source = tracker.source_for(s, store)
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
    """Body: the same JSON 'pdtrack bulletin template' produces."""
    try:
        b = Bulletin.from_dict(req.get_json())
    except (ValueError, KeyError) as e:
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=400, mimetype="application/json")
    _, _, store = _setup()
    store.save_bulletin(b)
    return func.HttpResponse(json.dumps({"saved": b.month}), mimetype="application/json")
