from datetime import date
from pathlib import Path

import pytest

from pdtracker import bulletin, config, evaluate, importers, render, tracker
from pdtracker.categories import chargeability_column, normalize_category
from pdtracker.models import CURRENT, DATES_FOR_FILING, FINAL_ACTION, UNAVAILABLE, Bulletin, Client, parse_date
from pdtracker.stores import MemoryStore, SqliteStore

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = Path(__file__).parent.parent / "config" / "office.example.yaml"
SAMPLE = (FIXTURES / "bulletin_sample.html").read_text()


@pytest.fixture
def settings():
    return config.load(EXAMPLE)


def client(**kw):
    base = dict(name="Garcia, Maria", category="F2A", chargeability="Mexico", priority_date="2022-06-01")
    base.update(kw)
    return Client(**base)


def bull(month, fa, dff=None, **kw):
    """fa/dff: {category: {country: value}}"""
    return Bulletin.from_dict({"month": month, "final_action": fa, "dates_for_filing": dff or fa, **kw})


# categories and dates

def test_category_and_country_normalization():
    assert normalize_category("eb-2") == "EB2"
    assert normalize_category("F2a") == "F2A"
    assert normalize_category("EB-3 other workers") == "EW"
    assert chargeability_column("México") == "MEXICO"
    assert chargeability_column("Guatemala") == "ESGH"
    assert chargeability_column("Brazil") == "ROW"
    assert chargeability_column("China-mainland born") == "CHINA"
    with pytest.raises(ValueError, match="immediate relative"):
        normalize_category("IR1")


def test_bulletin_date_formats():
    assert parse_date("01JAN17") == date(2017, 1, 1)
    assert parse_date("01OCT01") == date(2001, 10, 1)
    assert parse_date("15MAR98") == date(1998, 3, 15)
    assert parse_date("03/04/2020") == date(2020, 3, 4)


# parsing

def test_parse_sample_bulletin():
    b = bulletin.parse_bulletin_html(SAMPLE, "2026-12")
    assert b.cutoff(FINAL_ACTION, "F2A", "MEXICO") == date(2023, 2, 1)
    assert b.cutoff(DATES_FOR_FILING, "F2A", "MEXICO") == date(2025, 2, 1)
    assert b.cutoff(FINAL_ACTION, "F4", "PHILIPPINES") == date(2005, 4, 22)
    assert b.cutoff(FINAL_ACTION, "EB1", "ROW") == CURRENT
    assert b.cutoff(FINAL_ACTION, "SR", "ROW") == UNAVAILABLE
    assert b.cutoff(DATES_FOR_FILING, "SR", "ROW") == CURRENT
    assert b.cutoff(FINAL_ACTION, "EB5U", "INDIA") == date(2022, 5, 1)
    assert b.cutoff(FINAL_ACTION, "EB5R", "CHINA") == CURRENT
    assert b.cutoff(FINAL_ACTION, "EW", "CHINA") == date(2018, 1, 1)
    # A country without its own column falls back to ROW.
    assert b.cutoff(FINAL_ACTION, "F1", "ESGH") == date(2016, 11, 8)


def test_parse_without_headings_uses_table_order():
    page = SAMPLE.replace("FINAL ACTION DATES", "x").replace("DATES FOR FILING", "y")
    b = bulletin.parse_bulletin_html(page, "2026-12")
    assert b.cutoff(DATES_FOR_FILING, "F2A", "ROW") == date(2025, 10, 22)


def test_parse_garbage_is_a_clear_error():
    with pytest.raises(bulletin.BulletinError, match="by hand"):
        bulletin.parse_bulletin_html("<html><p>moved</p></html>", "2026-12")


def test_index_links_and_url_pattern():
    found = bulletin.months_on_index(SAMPLE, "https://travel.state.gov/x/visa-bulletin.html")
    assert found == {"2026-12": "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/2027/"
                                "visa-bulletin-for-december-2026.html"}
    src = bulletin.StateDeptSource(session=object())
    assert src.url_for("2026-10").endswith("/2027/visa-bulletin-for-october-2026.html")
    assert src.url_for("2027-03").endswith("/2027/visa-bulletin-for-march-2027.html")


class FakeResp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, **kw):
        self.calls.append(url)
        return FakeResp(self.pages[url]) if url in self.pages else FakeResp("", 404)


def test_state_dept_source_latest():
    url = ("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/2027/"
           "visa-bulletin-for-december-2026.html")
    session = FakeSession({bulletin.DEFAULT_INDEX_URL: SAMPLE, url: SAMPLE})
    b = bulletin.StateDeptSource(session=session).latest()
    assert b.month == "2026-12" and b.source == url


# evaluation

def test_current_means_strictly_earlier_than_cutoff():
    assert evaluate.status(date(2020, 1, 1), date(2020, 1, 2)) == evaluate.IS_CURRENT
    assert evaluate.status(date(2020, 1, 2), date(2020, 1, 2)) == evaluate.WAITING
    assert evaluate.status(date(2030, 1, 1), CURRENT) == evaluate.IS_CURRENT
    assert evaluate.status(date(2000, 1, 1), UNAVAILABLE) == evaluate.NOT_AVAILABLE


def test_became_current_and_retrogression_events():
    c1 = client(id="a")                                         # F2A Mexico PD 2022-06-01
    c2 = client(id="b", name="Reyes, Ana", category="F4", chargeability="Philippines", priority_date="2005-01-01")
    nov = bull("2026-11", {"F2A": {"MEXICO": "01JAN22"}, "F4": {"PHILIPPINES": "01MAR05"}})
    dec = bull("2026-12", {"F2A": {"MEXICO": "01JAN23"}, "F4": {"PHILIPPINES": "01JAN04"}})
    a = evaluate.analyze([c1, c2], dec, nov, today=date(2026, 11, 15))
    became = {(e.client.id, e.chart) for e in a.events_of(evaluate.BECAME_CURRENT)}
    lost = {(e.client.id, e.chart) for e in a.events_of(evaluate.NO_LONGER_CURRENT)}
    assert became == {("a", FINAL_ACTION), ("a", DATES_FOR_FILING)}
    assert lost == {("b", FINAL_ACTION), ("b", DATES_FOR_FILING)}
    back = [m for m in a.retrogressions if m.chart == FINAL_ACTION]
    assert [(m.category, m.country, [c.id for c in m.clients]) for m in back] == [("F4", "PHILIPPINES", ["b"])]


def test_approaching_and_cspa(settings):
    kid = client(id="k", priority_date="2023-03-01", beneficiary_dob="2006-02-01")
    b = bull("2026-12", {"F2A": {"MEXICO": "01FEB23"}})
    a = evaluate.analyze([kid], b, today=date(2026, 6, 1))
    assert [e.kind for e in a.events] == [evaluate.APPROACHING, evaluate.CSPA_REVIEW]
    assert "Feb 01, 2027" in a.events[1].detail


def test_uscis_chart_decides_i485(settings):
    c = client(priority_date="2024-06-01")   # behind FA (2023) but ahead of DFF (2025)
    b = bull("2026-12", {"F2A": {"MEXICO": "01FEB23"}}, {"F2A": {"MEXICO": "01FEB25"}})
    row = evaluate.analyze([c], b, chart_defaults=settings.chart_defaults).rows[0]
    assert row.final_action == evaluate.WAITING and row.can_file_i485   # office default: family uses DFF
    b.uscis_family_chart = FINAL_ACTION
    assert not evaluate.analyze([c], b).rows[0].can_file_i485


def test_inactive_clients_are_skipped():
    a = evaluate.analyze([client(active=False)], bull("2026-12", {"F2A": {"MEXICO": "C"}}))
    assert a.rows == [] and a.events == []


# end to end

class ListNotifier:
    def __init__(self):
        self.sent = []

    def send(self, subject, md, analysis):
        self.sent.append((subject, md))
        return "noted"


def test_check_alerts_once_per_bulletin(settings):
    store = MemoryStore()
    store.save_client(client())
    store.save_bulletin(bull("2026-11", {"F2A": {"MEXICO": "01JAN22"}}))
    store.mark_processed("2026-11")
    session = FakeSession({bulletin.DEFAULT_INDEX_URL: SAMPLE,
                           "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/2027/"
                           "visa-bulletin-for-december-2026.html": SAMPLE})
    source = bulletin.StateDeptSource(session=session)
    note = ListNotifier()

    first = tracker.check(store, source, settings, [note])
    assert first.new and "1 newly current" in first.subject
    assert "Garcia, Maria" in note.sent[0][1]
    assert store.statuses  # written back

    again = tracker.check(store, source, settings, [note])
    assert not again.new and len(note.sent) == 1


def test_manual_chart_choice_survives_refetch(settings):
    store = MemoryStore()
    store.save_bulletin(bull("2026-12", {"F2A": {"ROW": "C"}}, uscis_family_chart=FINAL_ACTION))
    fresh = bulletin.parse_bulletin_html(SAMPLE, "2026-12")

    class Src:
        def latest(self):
            return fresh
    tracker.check(store, Src(), settings, [])
    assert store.get_bulletin("2026-12").uscis_family_chart == FINAL_ACTION


def test_sqlite_store_roundtrip(tmp_path):
    store = SqliteStore(tmp_path / "pd.db")
    c = store.save_client(client(beneficiary_dob="2010-05-05"))
    assert store.get_client(c.id).beneficiary_dob == date(2010, 5, 5)
    b = bulletin.parse_bulletin_html(SAMPLE, "2026-12")
    store.save_bulletin(b)
    assert store.get_bulletin("2026-12").to_dict() == b.to_dict()
    assert not store.is_processed("2026-12")
    store.mark_processed("2026-12")
    assert store.is_processed("2026-12")
    c.active = False
    store.save_client(c)
    assert store.list_clients() == [] and len(store.list_clients(include_inactive=True)) == 1


def test_csv_import_with_mapping_updates_by_external_id(tmp_path, settings):
    csv_path = tmp_path / "export.csv"
    csv_path.write_text("Matter ID,Client Name,Preference Category,Country of Birth,Priority Date\n"
                        "M-1,\"Lopez, Juan\",F-4,Mexico,03/15/2001\n"
                        "M-2,\"Bad, Row\",XX,Mexico,2001-01-01\n")
    store = MemoryStore()
    result = importers.sync(store, importers.CsvFeed(csv_path, settings.import_columns))
    assert result["added"] == 1 and len(result["errors"]) == 1
    csv_path.write_text("Matter ID,Client Name,Preference Category,Country of Birth,Priority Date\n"
                        "M-1,\"Lopez, Juan\",F3,Mexico,03/15/2001\n")
    result = importers.sync(store, importers.CsvFeed(csv_path, settings.import_columns))
    assert result["updated"] == 1 and [c.category for c in store.list_clients()] == ["F3"]


def test_report_markdown_and_html(settings):
    b = bulletin.parse_bulletin_html(SAMPLE, "2026-12")
    a = evaluate.analyze([client()], b, chart_defaults=settings.chart_defaults)
    md = render.to_markdown("Example Immigration Law", a)
    assert "December 2026" in md and "first bulletin on file" in md
    html = render.to_html(md)
    assert "<ul>" in html and "<script" not in html


# config

def test_config_requires_365_only_for_cloud(tmp_path):
    p = tmp_path / "o.yaml"
    p.write_text("office: {name: X}\n")
    assert config.load(p).storage == "sqlite"
    p.write_text("office: {name: X}\nstorage: {backend: sharepoint}\n")
    with pytest.raises(config.ConfigError, match="microsoft365.tenant_id"):
        config.load(p)


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("PDTRACKER_CONFIG_YAML", "office: {name: Cloud Office}\nbulletin: {source: manual}\n")
    s = config.from_env()
    assert s.office_name == "Cloud Office" and s.bulletin_source == "manual"


# SharePoint store, against a fake Graph

class FakeGraph:
    def __init__(self):
        self.lists = {"Priority Dates": {}, "Visa Bulletins": {}}
        self.next_id = 1

    def _split(self, path):
        parts = path.split("?")[0].split("/")
        return parts[parts.index("lists") + 1], parts

    def get_all(self, path):
        name, _ = self._split(path)
        return [{"id": i, "fields": dict(f)} for i, f in self.lists[name].items()]

    def get(self, path):
        name, parts = self._split(path)
        item_id = parts[parts.index("items") + 1]
        return {"id": item_id, "fields": dict(self.lists[name][item_id])}

    def post(self, path, json):
        name, _ = self._split(path)
        item_id = str(self.next_id)
        self.next_id += 1
        self.lists[name][item_id] = dict(json["fields"])
        return {"id": item_id}

    def patch(self, path, json):
        name, parts = self._split(path)
        self.lists[name][parts[parts.index("items") + 1]].update(json)


def test_sharepoint_store_dates_and_statuses():
    from pdtracker.sharepoint import SharePointStore
    g = FakeGraph()
    store = SharePointStore(g, "site", "Priority Dates", "Visa Bulletins", timezone="Asia/Manila")
    c = store.save_client(client(chargeability="Philippines", priority_date="2015-03-01"))
    assert g.lists["Priority Dates"][c.id]["PriorityDate"] == "2015-03-01T12:00:00Z"
    # SharePoint hands back local midnight in UTC; in Manila that is the previous UTC day.
    g.lists["Priority Dates"][c.id]["PriorityDate"] = "2015-02-28T16:00:00Z"
    assert store.get_client(c.id).priority_date == date(2015, 3, 1)
    g.lists["Priority Dates"]["99"] = {"Title": "Half filled", "Category": "F2A"}
    assert [x.name for x in store.list_clients()] == ["Garcia, Maria"]
    assert store.invalid_rows() == ["Half filled"]

    b = bulletin.parse_bulletin_html(SAMPLE, "2026-12")
    store.save_bulletin(b)
    assert store.bulletin_months() == ["2026-12"] and not store.is_processed("2026-12")
    a = evaluate.analyze(store.list_clients(), store.get_bulletin("2026-12"))
    store.record_statuses("2026-12", a.rows)
    store.mark_processed("2026-12")
    assert store.is_processed("2026-12")
    assert g.lists["Priority Dates"][c.id]["StatusMonth"] == "2026-12"
