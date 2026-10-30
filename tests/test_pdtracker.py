import json
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


def test_index_links_and_url_patterns():
    found = bulletin.months_on_index(SAMPLE, "https://travel.state.gov/x/visa-bulletin.html")
    assert found == {"2026-12": "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/2027/"
                                "visa-bulletin-for-december-2026.html"}
    src = bulletin.StateDeptSource(session=object())
    assert src.url_for("2026-10").endswith("/2027/visa-bulletin-for-october-2026.html")
    assert src.url_for("2027-03").endswith("/2027/visa-bulletin-for-march-2027.html")
    assert src.pdf_url_for("2026-11") == ("https://travel.state.gov/content/dam/visas/Bulletins/"
                                          "visabulletin_November2026.pdf")


class FakeResp:
    def __init__(self, body, status=200):
        self.content = body if isinstance(body, bytes) else body.encode()
        self.text = body if isinstance(body, str) else ""
        self.status_code = status


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, **kw):
        self.calls.append(url)
        return FakeResp(self.pages[url]) if url in self.pages else FakeResp("", 404)


DEC_PDF_URL = "https://travel.state.gov/content/dam/visas/Bulletins/visabulletin_December2026.pdf"
DEC_HTML_URL = ("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/2027/"
                "visa-bulletin-for-december-2026.html")
SAMPLE_PDF = (FIXTURES / "bulletin_sample.pdf").read_bytes()


def test_pdf_parses_the_same_as_the_web_page():
    pdf = bulletin.parse_bulletin_pdf(SAMPLE_PDF)
    html = bulletin.parse_bulletin_html(SAMPLE, "2026-12")
    assert pdf.month == "2026-12"                      # read from the title
    assert pdf.to_dict()["final_action"] == html.to_dict()["final_action"]
    assert pdf.to_dict()["dates_for_filing"] == html.to_dict()["dates_for_filing"]
    assert len(pdf.final_action) == 15


def test_text_with_rows_on_one_line():
    text = ("VISA BULLETIN FOR JANUARY 2027\nA. FINAL ACTION DATES FOR FAMILY-SPONSORED PREFERENCE CASES\n"
            "Family- Sponsored All Chargeability Areas Except Those Listed CHINA- mainland born INDIA MEXICO PHILIPPINES\n"
            "F1 08NOV16 08NOV16 08NOV16 22APR05 01MAR13\nF2A 01FEB24 01FEB24 01FEB24 01FEB23 01FEB24\n"
            "A. FINAL ACTION DATES FOR EMPLOYMENT-BASED PREFERENCE CASES\n"
            "Employment- based All Chargeability Areas Except Those Listed CHINA- mainland born INDIA MEXICO PHILIPPINES\n"
            "1st C 15FEB23 15APR22 C C\n5th Set Aside:\nRural (20%, including NR, RR) C C C C C\n")
    b = bulletin.parse_bulletin_text(text)
    assert b.month == "2027-01"
    assert b.cutoff(FINAL_ACTION, "F2A", "MEXICO") == date(2023, 2, 1)
    assert b.cutoff(FINAL_ACTION, "EB1", "INDIA") == date(2022, 4, 15)
    assert b.cutoff(FINAL_ACTION, "EB5R", "ROW") == CURRENT


def test_not_a_pdf_is_a_clear_error():
    with pytest.raises(bulletin.BulletinError, match="isn't a PDF"):
        bulletin.parse_bulletin_pdf(b"<html>not found</html>")


def test_state_dept_source_prefers_pdf_then_web_page():
    session = FakeSession({DEC_PDF_URL: SAMPLE_PDF, DEC_HTML_URL: SAMPLE})
    b = bulletin.StateDeptSource(session=session).latest(today=date(2026, 11, 18))
    assert b.month == "2026-12" and b.source == DEC_PDF_URL

    session = FakeSession({DEC_HTML_URL: SAMPLE})        # no PDF yet
    b = bulletin.StateDeptSource(session=session).fetch("2026-12")
    assert b.source == DEC_HTML_URL

    session = FakeSession({DEC_HTML_URL: SAMPLE})
    assert bulletin.StateDeptSource(fmt="pdf", session=session).fetch("2026-12") is None


def test_latest_falls_back_to_this_month():
    session = FakeSession({DEC_PDF_URL: SAMPLE_PDF})
    b = bulletin.StateDeptSource(session=session).latest(today=date(2026, 12, 3))   # January not out yet
    assert b.month == "2026-12"


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
    session = FakeSession({DEC_PDF_URL: SAMPLE_PDF})

    class Src(bulletin.StateDeptSource):
        def latest(self):
            return super().latest(today=date(2026, 11, 18))
    source = Src(session=session)
    note = ListNotifier()

    first = tracker.check(store, source, settings, [note], today=date(2026, 11, 18))
    assert first.new and "1 newly current" in first.subject
    assert "Garcia, Maria" in note.sent[0][1]
    assert store.statuses  # written back

    again = tracker.check(store, source, settings, [note], today=date(2026, 11, 18))
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
    g.lists["Priority Dates"]["98"] = {"Title": "Typo", "Category": "F9"}
    listed = {x.name: x for x in store.list_clients()}
    assert sorted(listed) == ["Garcia, Maria", "Half filled"]
    assert listed["Half filled"].missing == ["priority date", "chargeability"]
    assert store.invalid_rows() == ["Typo"]

    b = bulletin.parse_bulletin_html(SAMPLE, "2026-12")
    store.save_bulletin(b)
    assert store.bulletin_months() == ["2026-12"] and not store.is_processed("2026-12")
    a = evaluate.analyze(store.list_clients(), store.get_bulletin("2026-12"))
    store.record_statuses("2026-12", a.rows)
    store.mark_processed("2026-12")
    assert store.is_processed("2026-12")
    assert g.lists["Priority Dates"][c.id]["StatusMonth"] == "2026-12"


# month-to-month changes

def test_report_lists_every_change_even_without_clients(settings):
    nov = bull("2026-11", {"EB2": {"INDIA": "01JAN13"}, "F3": {"ROW": "01JAN11"}, "F1": {"ROW": "01JAN16"}},
               uscis_family_chart=DATES_FOR_FILING)
    dec = bull("2026-12", {"EB2": {"INDIA": "01JAN12"}, "F3": {"ROW": "01MAR11"}, "F1": {"ROW": "01JAN16"}},
               uscis_family_chart=FINAL_ACTION)
    a = evaluate.analyze([client()], dec, nov)          # the one client is F2A Mexico, unaffected
    md = render.to_markdown("X", a)
    assert "## Everything that changed since November 2026" in md
    assert "**EB2 India:** retrogressed 1 year, from Jan 01, 2013 to Jan 01, 2012" in md
    assert "**F3 All other countries:** advanced 2 months, from Jan 01, 2011 to Mar 01, 2011" in md
    assert "F1 All other countries" not in md.split("Everything that changed")[1]   # unchanged cells left out
    assert "changed from Dates for Filing to Final Action Dates" in md
    assert "2 cutoffs retrogressed" in render.subject("X", a)      # EB2 India in both charts
    assert "<h4>" in render.to_html(md)


def test_report_says_when_nothing_changed():
    b = {"F1": {"ROW": "01JAN16"}}
    md = render.to_markdown("X", evaluate.analyze([], bull("2026-12", b), bull("2026-11", b)))
    assert "No cutoffs changed since November 2026." in md


# reminders

class RemindNotifier(ListNotifier):
    def __init__(self):
        super().__init__()
        self.reminders = []

    def remind(self, subject, md):
        self.reminders.append((subject, md))
        return "reminded"


class NothingSource:
    def latest(self):
        return None


class BrokenSource:
    def latest(self):
        raise bulletin.BulletinError("travel.state.gov returned HTTP 503")


def test_reminder_when_next_bulletin_is_missing(settings):
    store = MemoryStore()
    note = RemindNotifier()
    for day in (19, 20, 21, 22, 23):
        tracker.check(store, NothingSource(), settings, [note], today=date(2026, 11, day))
    assert len(note.reminders) == 2                     # day 20, then every 3 days
    subject, md = note.reminders[0]
    assert "December 2026 Visa Bulletin" in subject
    assert "visabulletin_December2026.pdf" in md and "Enter a bulletin" in md

    store.save_bulletin(bull("2026-12", {"F1": {"ROW": "C"}}))
    tracker.check(store, NothingSource(), settings, [note], today=date(2026, 11, 26))
    assert len(note.reminders) == 2                     # bulletin on file now


def test_failed_download_is_reported_not_raised(settings):
    note = RemindNotifier()
    result = tracker.check(MemoryStore(), BrokenSource(), settings, [note], today=date(2026, 11, 20))
    assert "HTTP 503" in result.summary and "HTTP 503" in note.reminders[0][1]
    assert tracker.check(MemoryStore(), BrokenSource(), settings, [note],
                         today=date(2026, 11, 5)).delivered == []


def test_reminders_off(settings):
    settings.reminder_day = 0
    note = RemindNotifier()
    tracker.check(MemoryStore(), NothingSource(), settings, [note], today=date(2026, 11, 20))
    assert note.reminders == []


# drop-folder inbox

def test_pdf_dropped_in_folder_is_picked_up_once(tmp_path, settings):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    store = MemoryStore()
    store.save_client(client())
    source = bulletin.InboxSource(store, bulletin.FolderInbox(inbox), NothingSource())
    note = RemindNotifier()
    assert not tracker.check(store, source, settings, [note], today=date(2026, 11, 10)).new

    (inbox / "visabulletin_December2026.pdf").write_bytes(SAMPLE_PDF)
    first = tracker.check(store, source, settings, [note], today=date(2026, 11, 20))
    assert first.new and first.month == "2026-12" and note.reminders == []
    assert store.get_bulletin("2026-12").source == "folder:visabulletin_December2026.pdf"

    (inbox / "copy.pdf").write_bytes(SAMPLE_PDF)       # same bulletin saved twice
    assert not tracker.check(store, source, settings, [note], today=date(2026, 11, 21)).new


def test_load_pdf_file(tmp_path):
    p = tmp_path / "dec.pdf"
    p.write_bytes(SAMPLE_PDF)
    b = bulletin.load_bulletin_file(p)
    assert b.month == "2026-12" and b.source == "file:dec.pdf"


# Real bulletins from travel.state.gov (public documents)

REAL_OCT = (FIXTURES / "visabulletin_October2026.pdf").read_bytes()
REAL_NOV = (FIXTURES / "visabulletin_November2026.pdf").read_bytes()


def test_real_november_2026_bulletin():
    b = bulletin.parse_bulletin_pdf(REAL_NOV)
    assert b.month == "2026-11"
    assert len(b.final_action) == 15 and len(b.dates_for_filing) == 15
    assert b.cutoff(FINAL_ACTION, "F1", "MEXICO") == date(2008, 9, 22)
    assert b.cutoff(FINAL_ACTION, "F2A", "MEXICO") == date(2026, 4, 22)
    assert b.cutoff(DATES_FOR_FILING, "F2A", "ROW") == CURRENT
    assert b.cutoff(DATES_FOR_FILING, "F4", "MEXICO") == date(2001, 4, 30)
    assert b.cutoff(FINAL_ACTION, "EW", "PHILIPPINES") == date(2022, 1, 1)
    assert b.cutoff(FINAL_ACTION, "SR", "INDIA") == date(2022, 12, 15)     # label split over three lines
    assert b.cutoff(DATES_FOR_FILING, "EB5U", "CHINA") == date(2021, 3, 1)   # table split across pages
    assert b.cutoff(DATES_FOR_FILING, "EB5I", "ROW") == CURRENT


def test_real_october_to_november_changes():
    oct_, nov = bulletin.parse_bulletin_pdf(REAL_OCT), bulletin.parse_bulletin_pdf(REAL_NOV)
    assert oct_.month == "2026-10"
    a = evaluate.analyze([], nov, oct_)
    moved = {(m.chart, m.category, m.country): m.direction for m in a.movements}
    assert moved[(FINAL_ACTION, "F1", "ROW")] == "forward"           # 22JAN20 -> 22JAN21
    assert moved[(FINAL_ACTION, "EB2", "ROW")] == "forward"          # 01JAN25 -> 01APR25
    assert (FINAL_ACTION, "EB4", "ROW") not in moved                 # unchanged
    assert not a.retrogressions


# days left and bulletin history

from pdtracker import dashboard, history  # noqa: E402


def test_series_skips_months_that_dont_list_the_cell():
    hist_ = [bull("2026-08", {"F3": {"MEXICO": "01JAN01"}}), bull("2026-09", {"F4": {"ROW": "01JAN08"}}),
             bull("2026-10", {"F3": {"MEXICO": "01APR01"}})]
    assert [m for m, _ in history.series(hist_, FINAL_ACTION, "F3", "MEXICO")] == ["2026-08", "2026-10"]


def test_delta_words():
    assert history.delta_words(date(2020, 1, 22), date(2021, 1, 22)) == "advanced 1 year"
    assert history.delta_words(date(2008, 9, 8), date(2008, 9, 22)) == "advanced 14 days"
    assert history.delta_words(date(2013, 8, 1), date(2013, 7, 15)) == "retrogressed 17 days"
    assert history.delta_words(date(2019, 8, 22), date(2021, 1, 5)) == "advanced 1 year, 4 months, 14 days"
    assert history.delta_words(date(2013, 8, 1), CURRENT).startswith("became current")
    assert history.delta_words(CURRENT, CURRENT) == "no movement"
    assert history.delta_words(CURRENT, date(2020, 1, 1)).startswith("retrogressed")


def test_compare_any_two_bulletins():
    a = bull("2026-07", {"F1": {"ROW": "01JAN15"}})
    c = bull("2026-10", {"F1": {"ROW": "01JAN14"}})
    changes = [x for x in history.compare(a, c, ["ROW"]) if x.chart == FINAL_ACTION]
    assert [(x.category, x.direction) for x in changes] == [("F1", "backward")]


def test_report_and_dashboard_show_days_left_and_history():
    oct_, nov = bulletin.parse_bulletin_pdf(REAL_OCT), bulletin.parse_bulletin_pdf(REAL_NOV)
    c = client(id="h", name="Hernandez, Jose", category="F3", priority_date="2001-11-20")
    a = evaluate.analyze([c], nov, oct_)
    md = render.to_markdown("X", a, history=[oct_, nov])
    assert "## Time until current (1 not yet current)" in md
    assert ("4 months, 5 days until current. Final Action cutoff advanced 14 days: Jul 01, 2001 (October 2026) "
            "to Jul 15, 2001 (November 2026)") in md
    assert "estimate" not in md.lower() and "pace" not in md.lower()
    assert "Final Action cutoffs over the last 2 bulletins" in md
    page = dashboard.dashboard(a, [], history=[oct_, nov])
    for view in ("overview", "clients", "profiles", "changes", "chart"):
        assert f"data-view='{view}'" in page
    assert "4 months, 5 days" in page and "id='bulletin-data'" in page
    assert "Estimate" not in page and "pace" not in page.lower()
    # the client's profile puts last month's cutoff next to this month's, with the change in words
    profile = page[page.index("<article class='profile'"):]
    assert "October 2026 bulletin" in profile and "01JUL01" in profile
    assert "November 2026 bulletin" in profile and "15JUL01" in profile
    assert "Advanced 14 days" in profile and "until current" in profile


# Docketwise matters export

from pdtracker import docketwise, stores  # noqa: E402

DW_MATTERS = FIXTURES / "docketwise_matters_sample.csv"
DW_REPORT = FIXTURES / "docketwise_report_sample.csv"


def test_docketwise_matters_export_sorts_and_infers():
    ms = {m.applicant: m for m in docketwise.read(DW_MATTERS)}
    assert ms["Test Person"].kind == docketwise.OTHER                 # H-1B is not a green card matter
    jane = ms["DOE, Jane"]
    assert jane.kind == docketwise.PREFERENCE and (jane.category, jane.chargeability) == ("EB2", "INDIA")
    assert jane.status == "Biometrics scheduled" and "I-140 + AOS" in jane.type      # I-140 and AOS combined
    assert jane.missing == ["priority date"] and jane.outside_status == "Not current"
    john = ms["DOE, John"]
    assert (john.category, john.chargeability) == ("EB2", "INDIA") and "derivative of DOE, Jane" in john.notes[-1]
    assert ms["Sam Sample"].kind == docketwise.IMMEDIATE
    assert ms["ROE, Rita"].category == "SR" and ms["ROE, Rita"].chargeability == ""     # never guess a country
    assert ms["POE, Pat"].kind == docketwise.DONE
    assert "Lee Example" in ms and ms["Lee Example"].petitioner == ""                    # name from the contact
    assert "Old matter" not in ms                                                         # archived


def test_docketwise_worklist_round_trip(tmp_path):
    matters = docketwise.read(DW_MATTERS)
    store = stores.MemoryStore()
    assert docketwise.sync(store, matters) == {"added": 0, "updated": 0}
    path = tmp_path / "todo.csv"
    assert docketwise.write_worklist(matters, path) == 4
    text = path.read_text().replace("DOE, Jane\",,EB2", "DOE, Jane\",2015-03-01,EB2")
    path.write_text(text)
    result = importers.sync(store, importers.CsvFeed(path))
    assert result["added"] == 1 and len(result["errors"]) == 3
    jane = store.list_clients()[0]
    assert jane.petitioner == "Example Tech Inc." and jane.attorney == "CD" and jane.outside_status == "Not current"


def test_docketwise_matter_report_with_dates(tmp_path):
    matters = docketwise.read(DW_REPORT)
    assert all(m.complete for m in matters)
    store = stores.MemoryStore()
    assert docketwise.sync(store, matters)["added"] == 2
    assert docketwise.sync(store, matters) == {"added": 0, "updated": 2}                # re-import updates
    ana = next(c for c in store.list_clients() if c.name == "Smith, Ana")
    assert (ana.category, ana.chargeability, str(ana.priority_date)) == ("EB3", "PHILIPPINES", "2023-03-15")


def test_profile_flags_case_system_disagreement():
    oct_, nov = bulletin.parse_bulletin_pdf(REAL_OCT), bulletin.parse_bulletin_pdf(REAL_NOV)
    c = client(id="m", name="Mismatch, Mo", category="F3", priority_date="2005-01-01", outside_status="Current",
               petitioner="Mismatch, Mia", case_status="NVC processing")
    a = evaluate.analyze([c], nov, oct_)
    html_ = dashboard.client_profile(a.rows[0], a)
    assert "class='mismatch'" in html_ and "Petitioner" in html_ and "NVC processing" in html_
    c.outside_status = "Not current"
    assert "class='mismatch'" not in dashboard.client_profile(evaluate.analyze([c], nov, oct_).rows[0], a)


def test_docketwise_full_report_format():
    assert docketwise.split_category("EB 2nd: India") == ("EB2", "INDIA")
    assert docketwise.split_category("EB Certain Religious Workers: All Areas") == ("SR", "ROW")
    assert docketwise.split_category("1. Emp: Religious Workers") == ("SR", "")
    assert docketwise.split_category("EB Other Workers: Philippines") == ("EW", "PHILIPPINES")
    assert docketwise.split_category("1. Immediate Relative") == ("IR", "")
    ms = {m.applicant: m for m in docketwise.read(FIXTURES / "docketwise_full_report_sample.csv")}
    jane = ms["Jane DOE"]                    # archived I-140 holds the dates; the open AOS keeps her tracked
    assert jane.complete and str(jane.priority_date) == "2024-03-15" and jane.status == "Biometrics scheduled"
    assert jane.receipt_number == "IOE0900000003" and jane.outside_status == "Not current"
    assert str(ms["Rita ROE"].priority_date) == "2007-06-21" and ms["Rita ROE"].category == "SR"
    assert ms["Pat POE"].complete and ms["Pat POE"].chargeability == "PHILIPPINES"
    assert ms["Sam SAMPLE"].kind == docketwise.IMMEDIATE
    assert "Old CLIENT" not in ms                                     # every matter archived


def test_gap_words_reads_like_a_calendar():
    from pdtracker.models import gap_words
    assert gap_words(date(2001, 7, 15), date(2001, 11, 20)) == "4 months, 5 days"
    assert gap_words(date(2020, 1, 1), date(2021, 5, 15)) == "1 year, 4 months, 14 days"
    assert gap_words(date(2024, 1, 31), date(2024, 3, 1)) == "1 month, 1 day"
    assert gap_words(date(2024, 1, 1), date(2024, 1, 10)) == "9 days"


def test_quick_lookup_is_on_the_dashboard():
    oct_, nov = bulletin.parse_bulletin_pdf(REAL_OCT), bulletin.parse_bulletin_pdf(REAL_NOV)
    a = evaluate.analyze([client(id="h", category="F3", priority_date="2001-11-20")], nov, oct_)
    page = dashboard.dashboard(a, [], history=[oct_, nov], save_html="<input type='hidden' name='token' value='t'>")
    assert "data-view='lookup'" in page and "id='lk-pd'" in page and "id='lk-save'" in page
    data = json.loads(page.split("id='bulletin-data'>")[1].split("</script>")[0])
    assert data["latest"] == "2026-11" and data["previous"] == "2026-10"
    assert data["uscis"] == {"family": "dates_for_filing", "employment": "final_action"}
    assert "id='lk-save'" not in dashboard.dashboard(a, [], history=[oct_, nov])     # read-only page: no save


# desktop app launcher

def test_app_first_run_writes_a_working_config(tmp_path, monkeypatch):
    from pdtracker import app
    monkeypatch.delenv("PDTRACKER_OFFICE_NAME", raising=False)
    answers = iter(["", "O'Brien & Díaz: Immigration"])
    path = app.ensure_config(tmp_path / "office", ask=lambda prompt: next(answers))
    s = config.load(path)
    assert s.office_name == "O'Brien & Díaz: Immigration"
    assert s.resolve(s.sqlite_path) == tmp_path / "office" / "data" / "priority-dates.db"
    assert (tmp_path / "office" / "bulletin-inbox").is_dir()
    assert app.ensure_config(tmp_path / "office", ask=lambda prompt: pytest.fail("asked twice")) == path


def test_app_runs_commands_against_the_office_folder(tmp_path, monkeypatch, capsys):
    from pdtracker import app
    monkeypatch.setenv("PDTRACKER_HOME", str(tmp_path))
    assert app.main(["list"]) == 1
    assert "Open the app once first" in capsys.readouterr().err
    monkeypatch.setenv("PDTRACKER_OFFICE_NAME", "Test Office")
    app.ensure_config(app.home_dir())
    assert app.main(["add", "--name", "Reyes, Ana", "--category", "F4", "--country", "Philippines",
                     "--pd", "2005-01-01"]) == 0
    assert app.main(["list"]) == 0
    assert "Reyes, Ana" in capsys.readouterr().out


# clients entered by hand with blanks

def test_client_with_blanks_is_kept_but_not_checked(tmp_path):
    blank = Client()
    assert blank.name == "Unnamed client" and blank.chargeability == ""     # never defaulted to ROW
    assert blank.missing == ["priority date", "category", "chargeability"]
    store = SqliteStore(tmp_path / "db.sqlite")
    no_pd = store.save_client(Client(name="Reyes, Ana", category="F4", chargeability="Philippines"))
    store.save_client(blank)
    store.save_client(client())
    assert store.get_client(no_pd.id).missing == ["priority date"]

    b = bull("2026-12", {"F4": {"ROW": "2008-01-01", "PHILIPPINES": "2006-01-01"},
                         "F2A": {"ROW": "2023-01-01", "MEXICO": "2023-01-01"}})
    prev = bull("2026-11", {"F4": {"ROW": "2007-01-01", "PHILIPPINES": "2005-01-01"},
                            "F2A": {"ROW": "2021-01-01", "MEXICO": "2021-01-01"}})
    a = evaluate.analyze(store.list_clients(), b, prev)
    rows = {r.client.name: r for r in a.rows}
    assert rows["Reyes, Ana"].final_action == evaluate.NEEDS_INFO
    assert not rows["Reyes, Ana"].can_file_i485
    assert rows["Garcia, Maria"].final_action == evaluate.IS_CURRENT
    assert {ev.client.name for ev in a.events} == {"Garcia, Maria"}

    from pdtracker import dashboard
    html = dashboard.dashboard(a, [], lambda c: "", "", [prev, b], {}, "")
    assert "Needs details" in html and "Add the priority date to check this client" in html
    assert "Add the priority date, category and chargeability" in html
    md = render.to_markdown("Office", a, history=[prev, b])
    assert "Unnamed client" in md and "needs details: add the priority date" in md


def test_web_form_saves_a_client_with_every_field_blank(tmp_path, settings):
    from pdtracker import webui
    settings.sqlite_path = str(tmp_path / "db.sqlite")
    app = webui.App(settings)
    form = {k: "" for k in ("name", "category", "chargeability", "priority_date", "beneficiary_dob", "case_type",
                            "receipt_number", "responsible_email", "notes")}
    status, _, redirect = app.handle("POST", "/client", {**form, "token": app.token})
    assert status == 303 and "Still needed: priority date, category, chargeability" in redirect
    assert "required" not in app.client_form()
    c = app.store.list_clients()[0]
    assert app.handle("GET", f"/client/{c.id}", {})[0] == 200
    assert app.handle("GET", "/", {})[0] == 200


def test_import_still_skips_incomplete_rows(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("name,category,chargeability,priority_date\nGarcia,F2A,Mexico,2022-01-01\nNo date,F2A,Mexico,\n,,,\n")
    store = MemoryStore()
    result = importers.sync(store, importers.CsvFeed(path))
    assert result["added"] == 1 and len(result["errors"]) == 2
    assert "missing priority date" in result["errors"][0]


# updates for the desktop app

class _Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_update_check_offers_only_a_newer_installer():
    from pdtracker import updates
    release = {"tag_name": "v0.10.0", "html_url": "https://example.com/release",
               "assets": [{"name": "PriorityDateTracker-NoInstall.zip", "browser_download_url": "zip"},
                          {"name": "PriorityDateTracker-Setup.exe", "browser_download_url": "setup"}]}
    get = lambda url, **kw: _Resp(release)
    assert updates.check("0.9.3", "u", get) == {"version": "0.10.0", "url": "setup"}
    assert updates.check("0.10.0", "u", get) is None
    assert updates.check("0.2.0", "off", get) is None

    def offline(url, **kw):
        raise OSError("no network")
    assert updates.check("0.2.0", "u", offline) is None


def test_dashboard_shows_an_available_update(tmp_path, settings, monkeypatch):
    from pdtracker import updates, webui
    settings.sqlite_path = str(tmp_path / "db.sqlite")
    app = webui.App(settings)
    assert "Download the update" not in app.handle("GET", "/", {})[1]
    monkeypatch.setattr(updates, "_latest", {"version": "9.0.0", "url": "https://example.com/setup.exe"})
    page = app.handle("GET", "/", {})[1]
    assert "Version 9.0.0" in page and "https://example.com/setup.exe" in page
