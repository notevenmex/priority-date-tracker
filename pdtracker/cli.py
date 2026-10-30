"""Command line entry point. Every command takes --config so one install can serve many offices."""

from __future__ import annotations

import argparse
import json
import sys

from . import config, importers, tracker
from .bulletin import BulletinError, load_bulletin_file
from .categories import CATEGORIES, COUNTRIES, country_name
from .graph import GraphError
from .models import CHARTS, Bulletin, Client, month_key
from .stores import previous_bulletin


def _store(s):
    return tracker.store_for(s)


def cmd_add(s, a):
    client = Client(name=a.name, category=a.category, chargeability=a.country, priority_date=a.pd,
                    case_type=a.case_type or "", receipt_number=a.receipt or "", beneficiary_dob=a.dob,
                    responsible_email=a.email or "", notes=a.notes or "")
    client = _store(s).save_client(client)
    print(f"Added {client.name} ({client.category or 'no category'}, {country_name(client.chargeability)}, "
          f"PD {client.priority_date or 'not entered'}) as {client.id}")
    if client.missing:
        print(f"Still needed before it can be checked: {', '.join(client.missing)}")


def cmd_edit(s, a):
    store = _store(s)
    client = store.get_client(a.id)
    if not client:
        raise ValueError(f"No client with id {a.id}")
    d = client.to_dict()
    for field, value in (("name", a.name), ("category", a.category), ("chargeability", a.country),
                         ("priority_date", a.pd), ("beneficiary_dob", a.dob), ("case_type", a.case_type),
                         ("receipt_number", a.receipt), ("responsible_email", a.email), ("notes", a.notes)):
        if value is not None:
            d[field] = value
    if a.inactive:
        d["active"] = False
    if a.active:
        d["active"] = True
    store.save_client(Client.from_dict(d))
    print(f"Updated {d['name']}")


def cmd_remove(s, a):
    store = _store(s)
    if a.delete:
        store.delete_client(a.id)
        print(f"Deleted {a.id}")
    else:
        client = store.get_client(a.id)
        if not client:
            raise ValueError(f"No client with id {a.id}")
        client.active = False
        store.save_client(client)
        print(f"Marked {client.name} inactive (kept on file). Use --delete to remove for good.")


def cmd_list(s, a):
    for c in _store(s).list_clients(include_inactive=a.all):
        flag = "" if c.active else "  (inactive)"
        print(f"{c.id:10} {c.name[:28]:28} {c.category or '-':5} {c.chargeability or '-':11} "
              f"{c.priority_date or 'no PD'}{flag}")


def cmd_import_docketwise(s, a):
    from . import docketwise
    matters = docketwise.read(a.file, s.import_columns)
    n = docketwise.summary(matters)
    result = docketwise.sync(_store(s), matters)
    print(f"{n['preference']} clients wait on the Visa Bulletin. Also in the export: {n['immediate']} immediate "
          f"relatives (nothing to track), {n['finished']} finished cases, {n['other']} other matter types.")
    print(f"Added {result['added']}, updated {result['updated']}.")
    left = n["preference"] - n["complete"]
    if left:
        missing = ", ".join(f"{v} without a {k}" for k, v in n["missing"].items() if v)
        print(f"{left} still need information ({missing}).")
        if a.worklist:
            docketwise.write_worklist(matters, a.worklist)
            print(f"Fill in {a.worklist} and load it with: pdtrack import {a.worklist}")
        else:
            print("Add --worklist FILE to get them as a spreadsheet to fill in.")


def cmd_import(s, a):
    result = importers.sync(_store(s), importers.CsvFeed(a.file, s.import_columns))
    print(f"Added {result['added']}, updated {result['updated']}.")
    for err in result["errors"]:
        print(f"  skipped {err}", file=sys.stderr)


def cmd_export(s, a):
    print(f"Wrote {importers.export_csv(_store(s), a.file)} clients to {a.file}")


def cmd_bulletin_fetch(s, a):
    store = _store(s)
    source = tracker.StateDeptSource(s.index_url, s.page_url, s.pdf_url, a.format or s.bulletin_format)
    b = source.fetch(a.month) if a.month else source.latest()
    if not b:
        raise BulletinError("No bulletin found for that month yet.")
    store.save_bulletin(b)
    print(f"Saved the {b.month} bulletin ({len(b.final_action)} categories) from {b.source}")


def cmd_bulletin_template(s, a):
    store = _store(s)
    month = month_key(a.month)
    print(json.dumps(Bulletin.template(month, previous_bulletin(store, month)), indent=2))


def cmd_bulletin_load(s, a):
    b = load_bulletin_file(a.file, a.month)
    _store(s).save_bulletin(b)
    print(f"Saved the {b.month} bulletin from {a.file} ({len(b.final_action)} categories). "
          "Run 'check --no-fetch' to compare it with last month and send alerts.")


def cmd_bulletin_chart(s, a):
    store = _store(s)
    b = store.get_bulletin(a.month)
    if not b:
        raise ValueError(f"No {a.month} bulletin on file. Fetch or load it first.")
    if a.family:
        b.uscis_family_chart = a.family
    if a.employment:
        b.uscis_employment_chart = a.employment
    store.save_bulletin(b)
    print(f"{b.month}: USCIS family chart {b.uscis_family_chart}, employment chart {b.uscis_employment_chart}")


def cmd_bulletin_list(s, a):
    store = _store(s)
    for m in store.bulletin_months():
        print(f"{m}  {'processed' if store.is_processed(m) else 'not yet checked'}")


def cmd_check(s, a):
    store = _store(s)
    source = tracker.StoredSource(store) if a.no_fetch else tracker.source_for(s, store)
    from .notify import ConsoleNotifier
    notifiers = tracker.notifiers_for(s) + [ConsoleNotifier()]
    result = tracker.check(store, source, s, notifiers, month=a.month, force=a.force)
    print(result.summary)
    for line in filter(None, result.delivered):
        print(f"  {line}")
    if a.print and result.report:
        print()
        print(result.report)


def cmd_report(s, a):
    out = tracker.current_report(_store(s), s, a.month)
    if not out:
        raise ValueError("No bulletin on file yet. Run 'check' or 'bulletin load' first.")
    print(out[1])


def cmd_serve(s, a):
    from .webui import serve
    serve(s, port=a.port)


def cmd_provision(s, a):
    from .sharepoint import provision
    graph = tracker.graph_for(s)
    created = provision(graph, graph.site_id(s.sp_hostname, s.sp_site_path), s.clients_list, s.bulletins_list)
    print("Created " + ", ".join(created) if created else "Lists already exist.")


def cmd_demo(a):
    from pathlib import Path

    from . import demo
    from .stores import SqliteStore
    from .webui import serve

    folder = Path(a.dir)
    db = folder / "demo.db"
    s = config.parse({"office": {"name": "Demo Immigration Law"},
                      "storage": {"sqlite_path": str(db.resolve())},
                      "bulletin": {"source": "manual", "reminder_day": 0},
                      "alerts": {"report_dir": str((folder / "reports").resolve())}})
    if not db.exists():
        demo.load(SqliteStore(db))
        print(f"Created sample data in {db}")
    serve(s, port=a.port)
    return 0


def cmd_codes(s, a):
    print("Categories:")
    for k, v in CATEGORIES.items():
        print(f"  {k:6} {v}")
    print("Chargeability columns (any other country is ROW):")
    for k, v in COUNTRIES.items():
        print(f"  {k:12} {v}")


def _client_args(p):
    p.add_argument("--name")
    p.add_argument("--category", help="F1, F2A, F2B, F3, F4, EB1, EB2, EB3, EW, EB4, EB5U ...")
    p.add_argument("--country", help="chargeability country, e.g. Mexico; others count as ROW")
    p.add_argument("--pd", help="priority date, YYYY-MM-DD")
    p.add_argument("--dob", help="beneficiary date of birth, for age-out reminders")
    p.add_argument("--case-type")
    p.add_argument("--receipt", help="receipt number")
    p.add_argument("--email", help="responsible attorney's email")
    p.add_argument("--notes")


def main(argv=None):
    p = argparse.ArgumentParser(prog="pdtrack", description="Priority date tracker for immigration law offices")
    p.add_argument("--config", "-c", help="path to this office's YAML config (not needed for 'demo')")
    sub = p.add_subparsers(dest="command", required=True)

    _client_args(sub.add_parser("add", help="add a client (every field is optional; fill in the rest later)"))
    e = sub.add_parser("edit", help="change a client's details")
    e.add_argument("id")
    _client_args(e)
    e.add_argument("--inactive", action="store_true", help="stop tracking (case closed)")
    e.add_argument("--active", action="store_true", help="track again")
    r = sub.add_parser("remove", help="stop tracking a client")
    r.add_argument("id")
    r.add_argument("--delete", action="store_true", help="delete the record instead of marking it inactive")
    ls = sub.add_parser("list", help="list clients")
    ls.add_argument("--all", action="store_true", help="include inactive clients")
    im = sub.add_parser("import", help="add or update clients from a CSV (any case system's export)")
    im.add_argument("file")
    dw = sub.add_parser("import-docketwise", help="read a Docketwise matters export (Matters tab or Matter Report)")
    dw.add_argument("file")
    dw.add_argument("--worklist", help="write matters still missing information to this CSV")
    ex = sub.add_parser("export", help="write all clients to a CSV")
    ex.add_argument("file")

    b = sub.add_parser("bulletin", help="fetch, enter or inspect Visa Bulletins")
    bs = b.add_subparsers(dest="bulletin_command", required=True)
    bf = bs.add_parser("fetch", help="download a bulletin from travel.state.gov")
    bf.add_argument("--month", help="YYYY-MM; default is the newest published")
    bf.add_argument("--format", choices=["pdf", "html", "auto"], help="override bulletin.format")
    bt = bs.add_parser("template", help="print a JSON template for entering a bulletin by hand")
    bt.add_argument("--month", required=True)
    bl = bs.add_parser("load", help="save a bulletin from its PDF, or from a hand-filled JSON/YAML file")
    bl.add_argument("file")
    bl.add_argument("--month", help="YYYY-MM, if it can't be read from the PDF")
    bc = bs.add_parser("set-chart", help="record which chart USCIS accepts for I-485 this month")
    bc.add_argument("--month", required=True)
    bc.add_argument("--family", choices=CHARTS)
    bc.add_argument("--employment", choices=CHARTS)
    bs.add_parser("list", help="bulletins on file")

    c = sub.add_parser("check", help="get the newest bulletin, compare with last month, send alerts once")
    c.add_argument("--month", help="check a specific month instead of the newest")
    c.add_argument("--force", action="store_true", help="re-run and re-alert even if already processed")
    c.add_argument("--no-fetch", action="store_true", help="use the newest bulletin already on file")
    c.add_argument("--print", action="store_true", help="also print the full report")
    rp = sub.add_parser("report", help="print current status for every client (no alerts)")
    rp.add_argument("--month")
    sv = sub.add_parser("serve", help="open the local web page for entering clients and bulletins")
    sv.add_argument("--port", type=int, default=8765)
    sub.add_parser("provision-sharepoint", help="create the SharePoint lists for the cloud version")
    sub.add_parser("codes", help="list category and country codes")
    dm = sub.add_parser("demo", help="open the dashboard with made-up clients and the real Oct/Nov 2026 bulletins")
    dm.add_argument("--dir", default="pdtracker-demo", help="folder for the demo database (default ./pdtracker-demo)")
    dm.add_argument("--port", type=int, default=8765)

    a = p.parse_args(argv)
    handlers = {
        "add": cmd_add, "edit": cmd_edit, "remove": cmd_remove, "list": cmd_list, "import": cmd_import,
        "import-docketwise": cmd_import_docketwise, "export": cmd_export, "check": cmd_check, "report": cmd_report, "serve": cmd_serve,
        "provision-sharepoint": cmd_provision, "codes": cmd_codes,
    }
    bulletin_handlers = {"fetch": cmd_bulletin_fetch, "template": cmd_bulletin_template, "load": cmd_bulletin_load,
                         "set-chart": cmd_bulletin_chart, "list": cmd_bulletin_list}
    try:
        if a.command == "demo":
            return cmd_demo(a)
        if not a.config:
            p.error("--config is required")
        s = config.load(a.config)
        handler = bulletin_handlers[a.bulletin_command] if a.command == "bulletin" else handlers[a.command]
        handler(s, a)
    except (config.ConfigError, GraphError, BulletinError, ValueError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
