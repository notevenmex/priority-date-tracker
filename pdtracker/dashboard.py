"""The dashboard look for the local web page: page shell, summary, client table and bulletin grid.

Pure functions from an Analysis to HTML, so the same view can be served live by webui.py or
written out as a static snapshot.
"""

from __future__ import annotations

import calendar
import html
from datetime import date

from .categories import CATEGORIES, COUNTRIES, is_family
from .evaluate import (APPROACHING, BECAME_CURRENT, CSPA_REVIEW, IS_CURRENT, NO_LONGER_CURRENT, NOT_AVAILABLE,
                       UNKNOWN, WAITING, Analysis, _rank)
from .models import CHART_LABELS, CURRENT, DATES_FOR_FILING, FINAL_ACTION, UNAVAILABLE

FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&"
         "family=IBM+Plex+Sans:wght@400;500;600;700&display=swap")

CSS = """
/* Layout: a working docket. Header band, attention summary, client table, then the bulletin grid. */
:root{
  --bg:#f4f6f5; --surface:#ffffff; --ink:#16212a; --muted:#5b6872; --line:#dde3e1; --soft:#eef2f1;
  --accent:#245b78; --accent-ink:#ffffff;
  --ok:#2c7a4b; --ok-bg:#e3f2e8; --warn:#9a5a00; --warn-bg:#fbefd9; --bad:#a8342a; --bad-bg:#f8e1de;
  --info:#46559c; --info-bg:#e6e9f7; --idle:#6b7680; --idle-bg:#eceff1;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#11181d; --surface:#172129; --ink:#e6ecef; --muted:#9aa8b1; --line:#2a3741; --soft:#1d2932;
  --accent:#7fb6d4; --accent-ink:#0d1418;
  --ok:#7fcf9c; --ok-bg:#183326; --warn:#e8b25e; --warn-bg:#3a2b12; --bad:#f08b80; --bad-bg:#3c1d1a;
  --info:#a9b5f0; --info-bg:#232a4a; --idle:#9aa5ad; --idle-bg:#222d35; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#11181d; --surface:#172129; --ink:#e6ecef; --muted:#9aa8b1; --line:#2a3741; --soft:#1d2932;
  --accent:#7fb6d4; --accent-ink:#0d1418;
  --ok:#7fcf9c; --ok-bg:#183326; --warn:#e8b25e; --warn-bg:#3a2b12; --bad:#f08b80; --bad-bg:#3c1d1a;
  --info:#a9b5f0; --info-bg:#232a4a; --idle:#9aa5ad; --idle-bg:#222d35; color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans)}
.wrap{max-width:1180px;margin:0 auto;padding-block:20px 48px;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));
  display:flex;flex-direction:column;gap:24px}
a{color:var(--accent)} a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
h1,h2,h3{text-wrap:balance;margin:0}
h1{font-size:1.5rem;font-weight:700;letter-spacing:-.01em}
h2{font-size:1.05rem;font-weight:600}
.eyebrow{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.muted{color:var(--muted)} .small{font-size:.85rem}
header.top{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:16px}
header.top .title{display:flex;flex-direction:column;gap:4px;min-width:0}
nav.tabs{display:flex;flex-wrap:wrap;gap:4px}
nav.tabs a{padding:6px 12px;border-radius:999px;text-decoration:none;color:var(--muted);font-weight:500;font-size:.9rem}
nav.tabs a[aria-current="page"]{background:var(--surface);color:var(--ink);box-shadow:0 0 0 1px var(--line)}
.bulletin-line{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;
  background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
.bulletin-line .what{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;min-width:0}
.bulletin-line strong{font-size:1.05rem}
button,.btn{font:inherit;font-weight:600;font-size:.9rem;padding:8px 14px;border-radius:8px;border:1px solid var(--accent);
  background:var(--accent);color:var(--accent-ink);cursor:pointer;text-decoration:none;display:inline-block}
button.ghost,.btn.ghost{background:transparent;color:var(--accent)}
button.link{border:0;background:none;color:var(--accent);padding:2px 4px;font-weight:500}
.notice{border-radius:10px;padding:12px 16px;background:var(--info-bg);color:var(--ink);border:1px solid var(--line)}
.notice.warn{background:var(--warn-bg)}
.tiles{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}
@media (max-width:900px){.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.tiles .tile:last-child{grid-column:span 2}}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;display:flex;flex-direction:column;gap:2px;
  border-top:3px solid var(--tone,var(--line))}
.tile .n{font-size:1.9rem;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}
.tile .lbl{font-weight:600} .tile .sub{font-size:.8rem;color:var(--muted)}
.tile.ok{--tone:var(--ok)} .tile.bad{--tone:var(--bad)} .tile.warn{--tone:var(--warn)} .tile.info{--tone:var(--info)} .tile.acc{--tone:var(--accent)}
section.panel{background:var(--surface);border:1px solid var(--line);border-radius:12px;display:flex;flex-direction:column;min-width:0}
section.panel>.head{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--line)}
section.panel>.body{padding:6px 16px 14px}
ul.events{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}
ul.events li{display:grid;grid-template-columns:132px minmax(0,1fr);gap:4px 14px;padding:10px 0;border-bottom:1px solid var(--line);align-items:baseline}
ul.events li:last-child{border-bottom:0}
@media (max-width:600px){ul.events li{grid-template-columns:1fr}}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:.78rem;font-weight:600;padding:2px 9px;border-radius:999px;white-space:nowrap;
  background:var(--idle-bg);color:var(--idle)}
ul.events .pill{justify-self:start}
.nowrap{white-space:nowrap}
.pill::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.pill.ok{background:var(--ok-bg);color:var(--ok)} .pill.warn{background:var(--warn-bg);color:var(--warn)}
.pill.bad{background:var(--bad-bg);color:var(--bad)} .pill.info{background:var(--info-bg);color:var(--info)}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.filters input[type=search]{min-width:0;width:220px;max-width:100%}
.chip{font:inherit;font-size:.82rem;font-weight:500;padding:5px 11px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--muted);cursor:pointer}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600;text-align:left;padding:10px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:11px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--soft)}
td .sub{display:block;font-size:.8rem;color:var(--muted);margin-top:3px}
td.client a{font-weight:600;text-decoration:none;color:var(--ink)} td.client a:hover{color:var(--accent);text-decoration:underline}
tr.inactive td{opacity:.55}
.cat{font-family:var(--mono);font-weight:500}
input,select,textarea{font:inherit;padding:7px 9px;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:7px}
.form-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.form-grid label{display:flex;flex-direction:column;gap:4px;font-size:.82rem;color:var(--muted);font-weight:500;min-width:0}
details.add>summary{cursor:pointer;font-weight:600;list-style:none;padding:14px 16px}
details.add>summary::-webkit-details-marker{display:none}
details.add>summary::before{content:"+ ";color:var(--accent)}
details.add[open]>summary::before{content:"\\2212  "}
details.add>form{padding:0 16px 16px;display:flex;flex-direction:column;gap:14px}
.grid-tabs{display:flex;gap:4px}
table.bulletin{font-size:.84rem}
table.bulletin th.row{font-family:var(--mono);color:var(--ink);text-transform:none;letter-spacing:0;font-size:.84rem;position:sticky;left:0;background:var(--surface)}
table.bulletin td{white-space:nowrap;padding:8px 10px}
table.bulletin td.moved{background:var(--ok-bg)} table.bulletin td.back{background:var(--bad-bg)}
.delta{font-size:.72rem;font-weight:600;margin-left:6px} .delta.up{color:var(--ok)} .delta.down{color:var(--bad)}
.dot{display:inline-block;min-width:18px;padding:0 5px;margin-left:6px;border-radius:999px;background:var(--accent);color:var(--accent-ink);
  font-size:.7rem;font-weight:700;text-align:center;font-family:var(--sans)}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:.8rem;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
.toast{position:fixed;right:max(16px,env(safe-area-inset-right,0px));bottom:calc(16px + env(safe-area-inset-bottom,0px));background:var(--ink);color:var(--surface);
  padding:10px 14px;border-radius:8px;font-size:.88rem}
.empty{padding:20px 0;color:var(--muted)}
@media (prefers-reduced-motion:no-preference){tbody tr td{transition:background .12s}}
"""

FILTER_JS = """
(function(){
  var q=document.getElementById('client-search'), rows=[].slice.call(document.querySelectorAll('#clients tbody tr[data-status]'));
  var chips=[].slice.call(document.querySelectorAll('.chip[data-filter]')), active='all';
  var counter=document.getElementById('client-count');
  function apply(){
    var term=(q&&q.value||'').toLowerCase(), shown=0;
    rows.forEach(function(r){
      var okF = active==='all' || (r.dataset.filters||'').split(' ').indexOf(active)>=0;
      var okQ = !term || r.dataset.search.indexOf(term)>=0;
      r.hidden=!(okF&&okQ); if(!r.hidden) shown++;
    });
    if(counter) counter.textContent = shown + ' of ' + rows.length;
  }
  chips.forEach(function(c){c.addEventListener('click',function(){
    active=c.dataset.filter; chips.forEach(function(x){x.setAttribute('aria-pressed', x===c?'true':'false')}); apply();});});
  if(q) q.addEventListener('input',apply);
  var gt=[].slice.call(document.querySelectorAll('[data-chart-tab]'));
  gt.forEach(function(b){b.addEventListener('click',function(){
    gt.forEach(function(x){x.setAttribute('aria-pressed', x===b?'true':'false')});
    document.querySelectorAll('[data-chart]').forEach(function(t){t.hidden = t.dataset.chart!==b.dataset.chartTab});});});
  apply();
})();
"""

STATUS = {
    IS_CURRENT: ("Current", "ok"),
    WAITING: ("Waiting", "warn"),
    NOT_AVAILABLE: ("Unavailable", "bad"),
    UNKNOWN: ("Not listed", ""),
}
EVENT = {
    BECAME_CURRENT: ("Newly current", "ok"),
    NO_LONGER_CURRENT: ("Lost place", "bad"),
    APPROACHING: ("Close to current", "warn"),
    CSPA_REVIEW: ("Age-out check", "info"),
}
GRID_COUNTRIES = ["ROW", "CHINA", "INDIA", "MEXICO", "PHILIPPINES"]
SHORT_COUNTRY = {"ROW": "All others", "CHINA": "China", "INDIA": "India", "MEXICO": "Mexico", "PHILIPPINES": "Philippines",
                 "ESGH": "El Salv./Guat./Hond."}
_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def month_label(month: str) -> str:
    y, m = month.split("-")
    return f"{calendar.month_name[int(m)]} {y}"


def bulletin_code(cutoff) -> str:
    """The bulletin's own notation: 22OCT26, C or U."""
    if cutoff in (CURRENT, UNAVAILABLE):
        return cutoff
    if cutoff is None:
        return "–"
    return f"{cutoff.day:02d}{_MON[cutoff.month - 1]}{cutoff.year % 100:02d}"


def long_date(d) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def span(days: int) -> str:
    """Rough human length of a gap in days."""
    days = abs(days)
    if days >= 365:
        y, rem = divmod(days, 365)
        m = rem // 30
        return f"{y} yr {m} mo" if m else f"{y} yr"
    if days >= 30:
        return f"{days // 30} mo"
    return f"{days} days"


def delta(prev, cur) -> tuple[str, str]:
    """Short label and direction class for how a cutoff moved."""
    a, b = _rank(prev), _rank(cur)
    if prev is None or a == b:
        return "", ""
    up = b > a
    if cur == CURRENT:
        return "now C", "up"
    if cur == UNAVAILABLE:
        return "now U", "down"
    if prev in (CURRENT, UNAVAILABLE):
        return ("set" if up else "set"), ("up" if up else "down")
    days = (cur - prev).days
    label = ("+" if up else "−") + (f"{round(abs(days) / 365, 1):g}y" if abs(days) >= 330 else
                                      f"{round(abs(days) / 30.4)}m" if abs(days) >= 28 else f"{abs(days)}d")
    return label, "up" if up else "down"


def shell(title: str, office: str, body: str, active: str = "clients", message: str = "",
          message_kind: str = "", script: str = "") -> str:
    tabs = [("clients", "/", "Clients"), ("bulletin", "/bulletin", "Enter a bulletin"), ("report", "/report", "Report")]
    nav = "".join(f'<a href="{href}"{" aria-current=\"page\"" if key == active else ""}>{label}</a>'
                  for key, href, label in tabs)
    note = f'<div class="notice {e(message_kind)}" role="status">{e(message)}</div>' if message else ""
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>"
            f"<title>{e(title)}</title><link rel='stylesheet' href='{FONTS}'><style>{CSS}</style></head><body>"
            f"<div class='wrap'><header class='top'><div class='title'><span class='eyebrow'>{e(office)}</span>"
            f"<h1>Priority dates</h1></div><nav class='tabs'>{nav}</nav></header>{note}{body}</div>"
            f"<script>{FILTER_JS}{script}</script></body></html>")


def _pill(status: str) -> str:
    label, cls = STATUS[status]
    return f'<span class="pill {cls}">{label}</span>'


def summary(a: Analysis) -> str:
    def tile(cls, n, label, sub):
        return (f'<div class="tile {cls}"><span class="n">{n}</span><span class="lbl">{label}</span>'
                f'<span class="sub">{sub}</span></div>')

    def count(kind):
        return len({ev.client.id for ev in a.events_of(kind)})

    can_file = sum(1 for r in a.rows if r.can_file_i485)
    back = len(a.retrogressions)
    prev = f"since {month_label(a.previous.month)}" if a.previous else "first bulletin on file"
    return ("<div class='tiles'>"
            + tile("ok", count(BECAME_CURRENT), "Newly current", prev)
            + tile("bad", count(NO_LONGER_CURRENT), "Lost their place",
                   f"{back} cutoff{'s' if back != 1 else ''} moved back overall" if a.previous else "nothing to compare")
            + tile("warn", count(APPROACHING), "Close to current", "within the watch window")
            + tile("info", count(CSPA_REVIEW), "Age-out checks", "beneficiary turns 21 soon")
            + tile("acc", can_file, "Can file I-485", f"of {len(a.rows)} active clients")
            + "</div>")


def attention(a: Analysis) -> str:
    order = [BECAME_CURRENT, NO_LONGER_CURRENT, APPROACHING, CSPA_REVIEW]
    # One line per client and kind: "current under Final Action" and "under Dates for Filing" merge.
    merged = {}
    for ev in a.events:
        key = (ev.client.id, ev.kind)
        if key in merged:
            first = merged[key]
            if ev.kind == BECAME_CURRENT:
                first.detail = "Current under both Final Action and Dates for Filing."
            elif ev.kind == NO_LONGER_CURRENT:
                first.detail = "No longer current under either chart (cutoffs moved back)."
        else:
            merged[key] = type(ev)(ev.kind, ev.client, ev.chart, ev.detail)
    events = sorted(merged.values(), key=lambda ev: (order.index(ev.kind), ev.client.name.lower()))
    if not events:
        items = "<p class='empty'>Nothing needs attention this month.</p>"
    else:
        lis = []
        for ev in events:
            label, cls = EVENT[ev.kind]
            c = ev.client
            lis.append(f"<li><span class='pill {cls}'>{label}</span><div><b>{e(c.name)}</b> "
                       f"<span class='muted small'><span class='cat'>{e(c.category)}</span> · {e(COUNTRIES[c.chargeability])}"
                       f" · PD <span class='mono nowrap'>{long_date(c.priority_date)}</span></span><br>"
                       f"<span class='small'>{e(ev.detail)}</span></div></li>")
        items = f"<ul class='events'>{''.join(lis)}</ul>"
    return (f"<section class='panel'><div class='head'><h2>Needs attention</h2>"
            f"<span class='muted small'>{len(events)} item{'s' if len(events) != 1 else ''}</span></div>"
            f"<div class='body'>{items}</div></section>")


def client_table(a: Analysis, inactive: list, row_actions=None) -> str:
    """row_actions(client) -> extra cell HTML (edit / stop tracking), or None for a read-only view."""
    events_by_client = {}
    for ev in a.events:
        events_by_client.setdefault(ev.client.id, []).append(ev.kind)
    rows = []
    for r in sorted(a.rows, key=lambda r: ({IS_CURRENT: 0, WAITING: 1}.get(r.final_action, 2),
                                           r.days_to_cutoff or 0, r.client.name.lower())):
        c = r.client
        filters = [r.final_action, "family" if is_family(c.category) else "employment"]
        if r.can_file_i485:
            filters.append("i485")
        filters += events_by_client.get(c.id, [])
        fa_cut, df_cut = r.cutoffs[FINAL_ACTION], r.cutoffs[DATES_FOR_FILING]
        gap = (f"<span class='sub'>{span(r.days_to_cutoff)} from cutoff</span>"
               if r.days_to_cutoff is not None else "")
        chart = "Filing chart" if r.uscis_chart == DATES_FOR_FILING else "Final Action chart"
        i485 = ("<span class='pill ok'>Open</span>" if r.can_file_i485 else "<span class='pill'>Not yet</span>")
        search = " ".join([c.name, c.category, COUNTRIES[c.chargeability], c.receipt_number, c.case_type]).lower()
        sub = " · ".join(x for x in (c.case_type, c.receipt_number) if x)
        name = (f"<a href='/client/{e(c.id)}'>{e(c.name)}</a>" if row_actions else f"<b>{e(c.name)}</b>")
        actions = f"<td>{row_actions(c)}</td>" if row_actions else ""
        rows.append(
            f"<tr data-status='{r.final_action}' data-filters='{' '.join(filters)}' data-search='{e(search)}'>"
            f"<td class='client'>{name}<span class='sub'>{e(sub)}</span></td>"
            f"<td><span class='cat'>{e(c.category)}</span><span class='sub'>{e(COUNTRIES[c.chargeability])}</span></td>"
            f"<td class='mono nowrap'>{long_date(c.priority_date)}</td>"
            f"<td>{_pill(r.final_action)}<span class='sub mono'>cutoff {bulletin_code(fa_cut)}</span>{gap}</td>"
            f"<td>{_pill(r.dates_for_filing)}<span class='sub mono'>cutoff {bulletin_code(df_cut)}</span></td>"
            f"<td>{i485}<span class='sub'>{chart}</span></td>{actions}</tr>")
    for c in inactive:
        name = f"<a href='/client/{e(c.id)}'>{e(c.name)}</a>" if row_actions else e(c.name)
        actions = f"<td>{row_actions(c)}</td>" if row_actions else ""
        rows.append(f"<tr class='inactive' data-status='inactive' data-filters='inactive' data-search='{e(c.name.lower())}'>"
                    f"<td class='client'>{name}<span class='sub'>Not tracked (case closed)</span></td>"
                    f"<td><span class='cat'>{e(c.category)}</span><span class='sub'>{e(COUNTRIES[c.chargeability])}</span></td>"
                    f"<td class='mono'>{long_date(c.priority_date)}</td><td colspan='3' class='muted small'>–</td>{actions}</tr>")
    chips = [("all", "All"), (IS_CURRENT, "Current"), (WAITING, "Waiting"), ("i485", "Can file I-485"),
             ("family", "Family"), ("employment", "Employment")]
    if inactive:
        chips.append(("inactive", "Not tracked"))
    chip_html = "".join(f"<button type='button' class='chip' data-filter='{k}' aria-pressed='{str(k == 'all').lower()}'>{v}</button>"
                        for k, v in chips)
    head = ("<tr><th>Client</th><th>Category</th><th>Priority date</th><th>Final Action</th>"
            "<th>Dates for Filing</th><th>I-485 filing</th>" + ("<th></th>" if row_actions else "") + "</tr>")
    body = "".join(rows) if rows else f"<tr><td colspan='7' class='empty'>No clients yet. Add the first one below.</td></tr>"
    return (f"<section class='panel' id='clients'><div class='head'><div><h2>Clients</h2>"
            f"<span class='muted small' id='client-count'></span></div><div class='filters'>"
            f"<input type='search' id='client-search' placeholder='Search name, category, receipt' aria-label='Search clients'>"
            f"{chip_html}</div></div><div class='scroll'><table><thead>{head}</thead><tbody>{body}</tbody></table></div></section>")


def bulletin_grid(a: Analysis) -> str:
    b, prev = a.bulletin, a.previous
    clients_in = {}
    for r in a.rows:
        key = (r.client.category, r.client.chargeability)
        clients_in[key] = clients_in.get(key, 0) + 1
    tables = []
    for i, chart in enumerate((FINAL_ACTION, DATES_FOR_FILING)):
        head = "<tr><th></th>" + "".join(f"<th>{SHORT_COUNTRY[c]}</th>" for c in GRID_COUNTRIES) + "</tr>"
        body = []
        for cat in CATEGORIES:
            row = b.chart(chart).get(cat)
            if not row:
                continue
            cells = []
            for country in GRID_COUNTRIES:
                cur = row.get(country, row.get("ROW"))
                old = prev.cutoff(chart, cat, country) if prev else None
                label, direction = delta(old, cur)
                cls = "moved" if direction == "up" else "back" if direction == "down" else ""
                mark = f"<span class='delta {direction}'>{label}</span>" if label else ""
                n = clients_in.get((cat, country))
                dot = f"<span class='dot' title='{n} of your clients'>{n}</span>" if n else ""
                title = f"{CATEGORIES[cat]}, {COUNTRIES[country]}" + (f"; was {bulletin_code(old)}" if label else "")
                cells.append(f"<td class='{cls}' title='{e(title)}'><span class='mono'>{bulletin_code(cur)}</span>{mark}{dot}</td>")
            body.append(f"<tr><th class='row' title='{e(CATEGORIES[cat])}'>{cat}</th>{''.join(cells)}</tr>")
        hidden = "" if i == 0 else " hidden"
        tables.append(f"<div class='scroll' data-chart='{chart}'{hidden}><table class='bulletin'><thead>{head}</thead>"
                      f"<tbody>{''.join(body)}</tbody></table></div>")
    tabs = "".join(f"<button type='button' class='chip' data-chart-tab='{c}' aria-pressed='{str(i == 0).lower()}'>"
                   f"{CHART_LABELS[c]}</button>" for i, c in enumerate((FINAL_ACTION, DATES_FOR_FILING)))
    compare = f"compared with {month_label(prev.month)}" if prev else "no earlier bulletin to compare"
    legend = ("<div class='legend'><span><i class='sw' style='background:var(--ok-bg)'></i>advanced</span>"
              "<span><i class='sw' style='background:var(--bad-bg)'></i>moved back</span>"
              "<span><span class='dot'>2</span>your clients in this cell</span>"
              "<span class='mono'>C current · U unavailable</span></div>")
    return (f"<section class='panel'><div class='head'><div><h2>{month_label(b.month)} bulletin</h2>"
            f"<span class='muted small'>Cutoff dates, {compare}</span></div><div class='grid-tabs'>{tabs}</div></div>"
            f"<div class='body'>{''.join(tables)}{legend}</div></section>")


def bulletin_bar(a: Analysis | None, action_html: str = "") -> str:
    if not a:
        return (f"<div class='bulletin-line'><div class='what'><strong>No bulletin on file yet</strong>"
                f"<span class='muted small'>Check for one or upload the PDF.</span></div>{action_html}</div>")
    b = a.bulletin
    fam = b.uscis_family_chart
    note = (f"USCIS family filing chart: {CHART_LABELS[fam]}" if fam
            else "USCIS filing chart not confirmed yet (using the office default)")
    src = b.source.split("/")[-1] if b.source else "manual entry"
    return (f"<div class='bulletin-line'><div class='what'><span class='eyebrow'>Compared against</span>"
            f"<strong>{month_label(b.month)} Visa Bulletin</strong><span class='muted small'>{e(src)} · {e(note)}</span>"
            f"</div>{action_html}</div>")


def dashboard(a: Analysis | None, inactive: list, row_actions=None, action_html: str = "") -> str:
    parts = [bulletin_bar(a, action_html)]
    if a:
        parts += [summary(a), attention(a), client_table(a, inactive, row_actions), bulletin_grid(a)]
    return "".join(parts)
