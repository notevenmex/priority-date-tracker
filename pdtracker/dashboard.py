"""The dashboard look for the local web page: page shell, summary, client table and bulletin grid.

Pure functions from an Analysis to HTML, so the same view can be served live by webui.py or
written out as a static snapshot.
"""

from __future__ import annotations

import calendar
import html
from datetime import date

from .categories import CATEGORIES, COUNTRIES, country_name, is_family
from .evaluate import (APPROACHING, BECAME_CURRENT, CSPA_REVIEW, IS_CURRENT, NO_LONGER_CURRENT, NOT_AVAILABLE,
                       NEEDS_INFO, UNKNOWN, WAITING, Analysis, _rank, uscis_chart)
from .evaluate import status as evaluate_status
import json

from . import history as hist
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
[hidden]{display:none!important}
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
button.link{border:0;background:none;color:var(--accent);padding:2px 4px;font-weight:500;white-space:nowrap}
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
nav.views{display:flex;flex-wrap:nowrap;overflow-x:auto;gap:6px;border-bottom:1px solid var(--line);padding-bottom:0;scrollbar-width:thin}
nav.views button{flex:none}
nav.views button{font:inherit;font-size:.95rem;font-weight:600;padding:10px 14px;background:none;border:0;border-bottom:3px solid transparent;
  color:var(--muted);border-radius:0;cursor:pointer;margin-bottom:-1px}
nav.views button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent)}
nav.views .count{font-size:.75rem;font-weight:700;margin-left:6px;padding:1px 7px;border-radius:999px;background:var(--soft);color:var(--muted)}
.view{display:flex;flex-direction:column;gap:20px}
.intro{margin:0;color:var(--muted);font-size:.92rem;max-width:72ch}
.intro b{color:var(--ink)}
.glance{font-size:1.05rem;line-height:1.55;max-width:70ch}
td.days{min-width:150px}
.big{font-size:1.15rem;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.big.ok{color:var(--ok)}
.toolbar{margin:0 0 14px}
.toolbar input[type=search]{width:100%;max-width:420px;font-size:1.05rem;padding:10px 12px}
.profiles{display:flex;flex-direction:column;gap:20px}
.profile{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:22px 24px;display:flex;flex-direction:column;gap:18px;min-width:0}
.profile header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;gap:10px}
.profile h3{font-size:1.6rem;line-height:1.2;margin:0}
.profile h3 a{color:inherit}
.profile header .sub{font-size:1rem}
.pill.lg{font-size:1rem;padding:5px 14px}
.profile dl.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:0}
.profile dl.facts div{background:var(--soft);border-radius:10px;padding:12px 14px}
.profile dl.matter{display:flex;flex-wrap:wrap;gap:8px 28px;margin:0;padding:0 2px}
.profile dl.matter dd{font-size:1.05rem;font-weight:500}
.mismatch{margin:0;padding:12px 14px;border-radius:10px;background:var(--warn-bg);color:var(--ink);font-size:1rem;
  border-left:4px solid var(--warn)}
table.worklist td{vertical-align:middle} table.worklist td.client{min-width:240px}
table.worklist input,table.worklist select{width:100%;min-width:130px}
.profile dt{font-size:.85rem;color:var(--muted);font-weight:600;letter-spacing:.02em}
.profile dd{margin:4px 0 0;font-size:1.3rem;font-weight:600}
.profile dd .cat{font-size:1.2rem}
.pcharts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
@media (max-width:820px){.pcharts{grid-template-columns:1fr}}
.pchart{border:1px solid var(--line);border-radius:12px;padding:16px 18px;display:flex;flex-direction:column;gap:12px;min-width:0}
.pchart h4{margin:0;font-size:1.15rem;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.cuts{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:10px 14px}
.cut{display:flex;flex-direction:column;gap:4px}
.cut .lbl{font-size:.9rem;color:var(--muted);font-weight:600}
.cut .val{font-size:2.1rem;font-weight:600;line-height:1.1}
.cut .plain{font-size:.95rem;color:var(--muted)}
.cut.now .val{color:var(--text)}
.cut:not(.now) .val{color:var(--muted)}
.cuts .arrow{font-size:1.8rem;color:var(--muted)}
.change{margin:0;font-size:1.15rem;font-weight:600;padding:8px 12px;border-radius:8px;background:var(--soft)}
.change.fwd{background:var(--ok-bg);color:var(--ok)} .change.back{background:var(--bad-bg);color:var(--bad)}
.flip{margin:0;font-size:1.05rem}
.standing{margin:0;font-size:1.05rem;display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 10px}
.standing b{font-size:1.7rem;font-variant-numeric:tabular-nums}
.standing.ok b{color:var(--ok)} .standing.warn b{color:var(--warn)} .standing.bad b{color:var(--bad)}
.standing span{color:var(--muted)}
@media (max-width:520px){.profile{padding:16px}.profile h3{font-size:1.35rem}.cut .val{font-size:1.45rem}
  .profile dl.facts{grid-template-columns:1fr 1fr}.profile dd{font-size:1.1rem}.pchart{padding:14px}}
.lookup-form{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px 16px;padding:16px}
.lookup-form label{display:flex;flex-direction:column;gap:6px;font-weight:600;font-size:.95rem;min-width:0}
.lookup-form input,.lookup-form select{font-size:1.1rem;padding:10px 12px;width:100%;max-width:100%;min-width:0;box-sizing:border-box}
.lookup-form p{grid-column:1/-1;margin:0}
@media (max-width:720px){.lookup-form{grid-template-columns:1fr}}
#lk-result{margin-top:16px}
.lk-save{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin-top:14px}
.lk-save label{display:flex;flex-direction:column;gap:4px;font-weight:600}
.compare-bar{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:end}
.compare-bar label{display:flex;flex-direction:column;gap:4px;font-size:.8rem;color:var(--muted);font-weight:600}
.compare-cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
@media (max-width:900px){.compare-cols{grid-template-columns:1fr}}
.ccol{background:var(--surface);border:1px solid var(--line);border-radius:12px;min-width:0;border-top:3px solid var(--tone,var(--line))}
.ccol.fwd{--tone:var(--ok)} .ccol.back{--tone:var(--bad)} .ccol.same{--tone:var(--idle)}
.ccol h3{font-size:1rem;padding:12px 14px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between}
.ccol ul{list-style:none;margin:0;padding:4px 14px 10px;display:flex;flex-direction:column}
.ccol li{padding:8px 0;border-bottom:1px solid var(--line);font-size:.88rem}
.ccol li:last-child{border-bottom:0}
.ccol li .k{font-weight:600} .ccol li .mono{font-size:.82rem}
.ccol .none{color:var(--muted);padding:12px 14px;font-size:.88rem}
table.history td{white-space:nowrap}
table.history td.up{background:var(--ok-bg)} table.history td.down{background:var(--bad-bg)}
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
  var ps=document.getElementById('profile-search'), cards=[].slice.call(document.querySelectorAll('.profile[data-search]'));
  if(ps) ps.addEventListener('input',function(){ var t=ps.value.toLowerCase();
    cards.forEach(function(c){c.hidden = !!t && c.dataset.search.indexOf(t)<0;});});
  // Tabs: one view at a time, remembered in the address (#overview, #clients ...).
  var tabs=[].slice.call(document.querySelectorAll('nav.views button')), views=[].slice.call(document.querySelectorAll('.view'));
  function show(name){
    if(!views.some(function(v){return v.dataset.view===name})) name='overview';
    views.forEach(function(v){v.hidden=v.dataset.view!==name});
    tabs.forEach(function(t){t.setAttribute('aria-selected', t.dataset.view===name?'true':'false')});
  }
  function remember(name){ try{ history.replaceState(null,'','#'+name) }catch(err){} }
  tabs.forEach(function(t){t.addEventListener('click',function(){ remember(t.dataset.view); show(t.dataset.view);});});
  window.addEventListener('hashchange',function(){show(location.hash.slice(1))});
  if(tabs.length) show(location.hash.slice(1));
  [].slice.call(document.querySelectorAll('[data-goto]')).forEach(function(a){a.addEventListener('click',function(ev){
    ev.preventDefault(); remember(a.dataset.goto); show(a.dataset.goto); window.scrollTo(0,0);});});
  // Compare any two bulletins.
  var dataEl=document.getElementById('bulletin-data'); if(!dataEl) return;
  var D=JSON.parse(dataEl.textContent), fromSel=document.getElementById('cmp-from'), toSel=document.getElementById('cmp-to'),
      chartSel=document.getElementById('cmp-chart'), mine=document.getElementById('cmp-mine');
  var MON=['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  var MONTH=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  function parse(c){ if(!c||c==='C'||c==='U') return c||null; var p=c.split('-'); return new Date(Date.UTC(+p[0],+p[1]-1,+p[2])); }
  function code(c){ if(!c) return '–'; if(c==='C'||c==='U') return c; var d=parse(c);
    return ('0'+d.getUTCDate()).slice(-2)+MON[d.getUTCMonth()]+String(d.getUTCFullYear()).slice(-2); }
  function longDate(d){ return MONTH[d.getUTCMonth()]+' '+d.getUTCDate()+', '+d.getUTCFullYear(); }
  function rank(c){ return c==='U'?0:c==='C'?3e15:parse(c).getTime(); }
  // Calendar distance, the same way the server writes it: "1 year, 4 months, 14 days".
  function gap(a,b){ if(b<a){var t=a;a=b;b=t;}
    function plus(n){ var tot=a.getUTCFullYear()*12+a.getUTCMonth()+n, y=Math.floor(tot/12), m=tot%12,
      dim=new Date(Date.UTC(y,m+1,0)).getUTCDate(); return new Date(Date.UTC(y,m,Math.min(a.getUTCDate(),dim))); }
    var months=(b.getUTCFullYear()-a.getUTCFullYear())*12+b.getUTCMonth()-a.getUTCMonth();
    while(months>0&&plus(months)>b) months--;
    var days=Math.round((b-plus(months))/864e5), y=Math.floor(months/12), parts=[]; months%=12;
    [[y,'year'],[months,'month'],[days,'day']].forEach(function(p){ if(p[0]) parts.push(p[0]+' '+p[1]+(p[0]!==1?'s':'')); });
    return parts.join(', ')||'0 days'; }
  function words(a,b){ if(!a) return 'new this month'; if(!b) return 'no longer listed'; if(a===b) return 'no movement';
    if(b==='C') return 'became current (C)'; if(b==='U') return 'became unavailable (U)'; if(a==='C') return 'retrogressed from current to a cutoff date'; if(a==='U') return 'available again, up to a cutoff date';
    return (rank(b)>rank(a)?'advanced ':'retrogressed ')+gap(parse(a),parse(b)); }
  function esc(t){var x=document.createElement('span'); x.textContent=t; return x.innerHTML;}
  // Quick lookup.
  var lkPd=document.getElementById('lk-pd'), lkCat=document.getElementById('lk-cat'), lkArea=document.getElementById('lk-area'),
      lkOut=document.getElementById('lk-result'), lkSave=document.getElementById('lk-save');
  var CHARTS=[['final_action','Final Action Date'],['dates_for_filing','Date for Filing']];
  function cell(month,chart,cat,area){ var b=D.bulletins[month]; return b?(((b[chart]||{})[cat]||{})[area]||null):null; }
  function standing(pd,c){ if(!c) return ['','Not listed','this category is not in the bulletin'];
    if(c==='U') return ['bad','Unavailable','no visa numbers in this category this month (U)'];
    if(c==='C'||pd<parse(c)) return ['ok','Current','the priority date is earlier than the cutoff'];
    return ['warn',gap(parse(c),pd),'until current: how far the cutoff must advance to reach this priority date']; }
  function lookup(){
    if(!lkOut) return;
    if(!lkPd.value){ lkOut.innerHTML='<p class="empty">Enter a priority date to see where it stands in the '+esc(D.labels[D.latest])+' bulletin.</p>';
      if(lkSave) lkSave.hidden=true; return; }
    var p=lkPd.value.split('-'), pd=new Date(Date.UTC(+p[0],+p[1]-1,+p[2])), cat=lkCat.value;
    var area=D.countries.indexOf(lkArea.value)>=0||lkArea.value==='ESGH'?lkArea.value:'ROW';
    var uscis=D.family.indexOf(cat)>=0?D.uscis.family:D.uscis.employment, blocks='', fa='', canFile=false;
    CHARTS.forEach(function(ch){
      var now=cell(D.latest,ch[0],cat,area), st=standing(pd,now), cur=st[1]==='Current';
      if(ch[0]==='final_action') fa=st; if(ch[0]===uscis) canFile=cur;
      var pair='<div class="cut now"><span class="lbl">'+esc(D.labels[D.latest])+' bulletin</span><span class="val mono">'+code(now)+
        '</span><span class="plain">'+(now&&now!=='C'&&now!=='U'?longDate(parse(now)):now==='C'?'current':now==='U'?'unavailable':'not listed')+'</span></div>';
      var change='<p class="change same">No earlier bulletin on file to compare with.</p>';
      if(D.previous){ var before=cell(D.previous,ch[0],cat,area), w=words(before,now),
          tone=before&&now&&rank(now)>rank(before)?'fwd':before&&now&&rank(now)<rank(before)?'back':'same';
        pair='<div class="cut"><span class="lbl">'+esc(D.labels[D.previous])+' bulletin</span><span class="val mono">'+code(before)+
          '</span><span class="plain">'+(before&&before!=='C'&&before!=='U'?longDate(parse(before)):before==='C'?'current':before==='U'?'unavailable':'not listed')+
          '</span></div><div class="arrow" aria-hidden="true">→</div>'+pair;
        change='<p class="change '+tone+'">'+esc(w.charAt(0).toUpperCase()+w.slice(1))+'</p>'; }
      blocks+='<section class="pchart"><h4>'+ch[1]+(ch[0]===uscis?' <span class="pill info">USCIS chart for I-485 this month</span>':'')+
        '</h4><div class="cuts">'+pair+'</div>'+change+'<p class="standing '+st[0]+'"><b>'+esc(st[1])+'</b> <span>'+esc(st[2])+'</span></p></section>';
    });
    var pill=fa[1]==='Current'?['ok','Current']:fa[0]==='warn'?['warn','Not current']:[fa[0],fa[1]];
    lkOut.innerHTML='<article class="profile"><header><h3>Priority date '+longDate(pd)+'</h3><span class="pill '+pill[0]+' lg">'+
      pill[1]+' · Final Action</span></header><dl class="facts"><div><dt>Preference category</dt><dd><span class="cat">'+esc(cat)+
      '</span></dd></div><div><dt>Chargeability</dt><dd>'+esc(lkArea.options[lkArea.selectedIndex].text)+'</dd></div><div><dt>May file I-485</dt><dd>'+
      (canFile?'Yes':'Not yet')+'</dd></div></dl><div class="pcharts">'+blocks+'</div>'+
      '<p class="muted small">Based on the '+esc(D.labels[D.latest])+' Visa Bulletin. Not a prediction: cutoffs can stall or retrogress.</p></article>';
    if(lkSave){ lkSave.hidden=false; lkSave.priority_date.value=lkPd.value; lkSave.category.value=cat; lkSave.chargeability.value=lkArea.value; }
  }
  [lkPd,lkCat,lkArea].forEach(function(x){ if(x){ x.addEventListener('input',lookup); x.addEventListener('change',lookup); } });
  lookup();
  if(!fromSel) return;
  function render(){
    var A=D.bulletins[fromSel.value], B=D.bulletins[toSel.value], chart=chartSel.value, groups={fwd:[],back:[],same:[]};
    D.categories.forEach(function(cat){ D.countries.forEach(function(ct){
      var key=cat+'|'+ct, n=D.clients[key]||0; if(mine.checked && !n) return;
      var a=((A[chart]||{})[cat]||{})[ct], b=((B[chart]||{})[cat]||{})[ct];
      if(!a&&!b) return;
      var g = (!a||!b)?'same' : rank(b)>rank(a)?'fwd' : rank(b)<rank(a)?'back':'same';
      groups[g].push('<li><span class="k">'+esc(cat)+' · '+esc(D.countryNames[ct])+'</span>'+(n?' <span class="dot" title="your clients">'+n+'</span>':'')+
        '<br><span class="mono">'+code(a)+' → '+code(b)+'</span> <span class="muted">'+esc(words(a,b))+'</span></li>');
    });});
    [['fwd','Advanced'],['back','Retrogressed'],['same','No movement']].forEach(function(g){
      var el=document.getElementById('cmp-'+g[0]);
      el.querySelector('.n').textContent=groups[g[0]].length;
      el.querySelector('.items').innerHTML = groups[g[0]].length ? '<ul>'+groups[g[0]].join('')+'</ul>'
        : '<p class="none">'+(g[0]==='same'?'Every cutoff moved.':'Nothing '+g[1].toLowerCase()+'.')+'</p>';
    });
    document.getElementById('cmp-title').textContent = D.labels[fromSel.value]+' → '+D.labels[toSel.value];
  }
  [fromSel,toSel,chartSel,mine].forEach(function(x){x.addEventListener('change',render)});
  render();
})();
"""

STATUS = {
    IS_CURRENT: ("Current", "ok"),
    WAITING: ("Not current", "warn"),
    NOT_AVAILABLE: ("Unavailable", "bad"),
    UNKNOWN: ("Not listed", ""),
    NEEDS_INFO: ("Needs details", "info"),
}
EVENT = {
    BECAME_CURRENT: ("Newly current", "ok"),
    NO_LONGER_CURRENT: ("Retrogressed", "bad"),
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
    return f"{d:%b} {d.day}, {d.year}" if d else "Not entered"


def cat_label(category: str) -> str:
    return category or "–"


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
    tabs = [("clients", "/", "Dashboard"), ("bulletin", "/bulletin", "Enter a bulletin"),
            ("import", "/import", "Import clients"), ("report", "/report", "Report")]
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
            + tile("bad", count(NO_LONGER_CURRENT), "Retrogressed",
                   f"{back} cutoff{'s' if back != 1 else ''} retrogressed overall" if a.previous else "nothing to compare")
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
                first.detail = "No longer current under either chart (retrogression)."
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
                       f"<span class='muted small'><span class='cat'>{e(cat_label(c.category))}</span> · {e(country_name(c.chargeability))}"
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
        filters = [r.final_action] + ([("family" if is_family(c.category) else "employment")] if c.category else [])
        if r.can_file_i485:
            filters.append("i485")
        filters += events_by_client.get(c.id, [])
        fa_cut, df_cut = r.cutoffs[FINAL_ACTION], r.cutoffs[DATES_FOR_FILING]
        chart = "Filing chart" if r.uscis_chart == DATES_FOR_FILING else "Final Action chart"
        i485 = ("<span class='pill ok'>Open</span>" if r.can_file_i485 else "<span class='pill'>Not yet</span>")
        if r.final_action == NEEDS_INFO:
            days_cell = f"<span class='sub'>Add the {e(c.missing_text)} to check this client</span>"
        elif r.final_action == IS_CURRENT:
            days_cell = "<span class='big ok'>Current</span><span class='sub'>no wait under Final Action</span>"
        elif r.days_to_cutoff is not None:
            days_cell = (f"<span class='big'>{hist.gap_words(r.cutoffs[FINAL_ACTION], c.priority_date)}</span>"
                         f"<span class='sub'>until the Final Action cutoff passes</span>")
        else:
            days_cell = "<span class='muted small'>–</span>"
        search = " ".join([c.name, c.category, country_name(c.chargeability), c.receipt_number, c.case_type]).lower()
        sub = " · ".join(x for x in (c.case_type, c.receipt_number) if x)
        name = (f"<a href='/client/{e(c.id)}'>{e(c.name)}</a>" if row_actions else f"<b>{e(c.name)}</b>")
        actions = f"<td>{row_actions(c)}</td>" if row_actions else ""
        rows.append(
            f"<tr data-status='{r.final_action}' data-filters='{' '.join(filters)}' data-search='{e(search)}'>"
            f"<td class='client'>{name}<span class='sub'>{e(sub)}</span></td>"
            f"<td><span class='cat'>{e(cat_label(c.category))}</span><span class='sub'>{e(country_name(c.chargeability))}</span></td>"
            f"<td class='mono nowrap'>{long_date(c.priority_date)}</td>"
            f"<td class='days'>{days_cell}</td>"
            f"<td>{_pill(r.final_action)}<span class='sub mono'>cutoff {bulletin_code(fa_cut)}</span></td>"
            f"<td>{_pill(r.dates_for_filing)}<span class='sub mono'>cutoff {bulletin_code(df_cut)}</span></td>"
            f"<td>{i485}<span class='sub'>{chart}</span></td>{actions}</tr>")
    for c in inactive:
        name = f"<a href='/client/{e(c.id)}'>{e(c.name)}</a>" if row_actions else e(c.name)
        actions = f"<td>{row_actions(c)}</td>" if row_actions else ""
        rows.append(f"<tr class='inactive' data-status='inactive' data-filters='inactive' data-search='{e(c.name.lower())}'>"
                    f"<td class='client'>{name}<span class='sub'>Not tracked (case closed)</span></td>"
                    f"<td><span class='cat'>{e(cat_label(c.category))}</span><span class='sub'>{e(country_name(c.chargeability))}</span></td>"
                    f"<td class='mono'>{long_date(c.priority_date)}</td><td colspan='4' class='muted small'>–</td>{actions}</tr>")
    chips = [("all", "All"), (IS_CURRENT, "Current"), (WAITING, "Not current"), ("i485", "Can file I-485"),
             ("family", "Family"), ("employment", "Employment")]
    if any(r.final_action == NEEDS_INFO for r in a.rows):
        chips.append((NEEDS_INFO, "Needs details"))
    if inactive:
        chips.append(("inactive", "Not tracked"))
    chip_html = "".join(f"<button type='button' class='chip' data-filter='{k}' aria-pressed='{str(k == 'all').lower()}'>{v}</button>"
                        for k, v in chips)
    head = ("<tr><th>Client</th><th>Category</th><th>Priority date</th><th>Days left</th><th>Final Action</th>"
            "<th>Dates for Filing</th><th>I-485 filing</th>" + ("<th></th>" if row_actions else "") + "</tr>")
    body = "".join(rows) if rows else f"<tr><td colspan='8' class='empty'>No clients yet. Add the first one below.</td></tr>"
    return (f"<section class='panel' id='clients'><div class='head'><div><h2>All clients</h2>"
            f"<span class='muted small' id='client-count'></span></div><div class='filters'>"
            f"<input type='search' id='client-search' placeholder='Search name, category, receipt' aria-label='Search clients'>"
            f"{chip_html}</div></div><div class='scroll'><table><thead>{head}</thead><tbody>{body}</tbody></table></div></section>")


def bulletin_grid(a: Analysis) -> str:
    b, prev = a.bulletin, a.previous
    clients_in = {}
    for r in a.rows:
        if r.final_action == NEEDS_INFO:
            continue
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
              "<span><i class='sw' style='background:var(--bad-bg)'></i>retrogressed</span>"
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


def intro(text: str) -> str:
    return f"<p class='intro'>{text}</p>"


def glance(a: Analysis) -> str:
    if not a.previous:
        return (f"<p class='glance'>This is the first bulletin on file. Comparisons start once the next "
                f"bulletin arrives.</p>")
    fwd = sum(1 for m in a.movements if m.direction == "forward")
    back = len(a.retrogressions)
    cur = len({ev.client.id for ev in a.events_of(BECAME_CURRENT)})
    lost = len({ev.client.id for ev in a.events_of(NO_LONGER_CURRENT)})
    parts = [f"Since the {month_label(a.previous.month)} bulletin, <b>{fwd}</b> cutoff{'s' if fwd != 1 else ''} advanced "
             f"and <b>{back}</b> retrogressed."]
    if cur:
        parts.append(f"<b>{cur}</b> of your clients became current.")
    if lost:
        parts.append(f"<b>{lost}</b> of your clients retrogressed.")
    if not cur and not lost:
        parts.append("None of your clients changed status.")
    return f"<p class='glance'>{' '.join(parts)} <a href='#changes' data-goto='changes'>See every change</a></p>"


CHART_TITLES = {FINAL_ACTION: "Final Action Date", DATES_FOR_FILING: "Date for Filing"}


def _standing(status_now: str, pd, cut) -> str:
    if status_now == IS_CURRENT:
        return ("<p class='standing ok'><b>Current</b> <span>the priority date is earlier than the cutoff</span></p>")
    if status_now == WAITING:
        return (f"<p class='standing warn'><b>{hist.gap_words(cut, pd)}</b> <span>until current: how far the "
                "cutoff must advance to reach this priority date</span></p>")
    if status_now == NOT_AVAILABLE:
        return "<p class='standing bad'><b>Unavailable</b> <span>no visa numbers in this category this month (U)</span></p>"
    return "<p class='standing'><b>Not listed</b> <span>this category isn't in the bulletin</span></p>"


def _cut(label: str, cutoff, now: bool = False) -> str:
    plain = ("current" if cutoff == CURRENT else "unavailable" if cutoff == UNAVAILABLE
             else "not listed" if cutoff is None else long_date(cutoff))
    return (f"<div class='cut{' now' if now else ''}'><span class='lbl'>{label}</span>"
            f"<span class='val mono'>{bulletin_code(cutoff)}</span><span class='plain'>{plain}</span></div>")


def chart_block(r, a: Analysis, chart: str) -> str:
    """One chart in a client profile: the previous bulletin's cutoff, this one's, and the movement."""
    c = r.client
    now = r.cutoffs[chart]
    status_now = getattr(r, chart)
    uses = " <span class='pill info'>USCIS chart for I-485 this month</span>" if r.uscis_chart == chart else ""
    this_month = _cut(f"{month_label(a.bulletin.month)} bulletin", now, now=True)
    if a.previous:
        before = a.previous.cutoff(chart, c.category, c.chargeability)
        _, direction = delta(before, now)
        words = hist.delta_words(before, now)
        tone = {"up": "fwd", "down": "back"}.get(direction, "same")
        status_before = evaluate_status(c.priority_date, before)
        flip = ""
        if status_before != status_now:
            flip = (f"<p class='flip'>{STATUS[status_before][0]} in {month_label(a.previous.month)}, "
                    f"<b>{STATUS[status_now][0].lower()}</b> now.</p>")
        pair = (_cut(f"{month_label(a.previous.month)} bulletin", before)
                + f"<div class='arrow' aria-hidden='true'>→</div>{this_month}")
        change = f"<p class='change {tone}'>{e(words[:1].upper() + words[1:])}</p>{flip}"
    else:
        pair = this_month + "<div></div><div></div>"
        change = "<p class='change same'>No earlier bulletin on file to compare with.</p>"
    return (f"<section class='pchart'><h4>{CHART_TITLES[chart]}{uses}</h4><div class='cuts'>{pair}</div>"
            f"{change}{_standing(status_now, c.priority_date, now)}</section>")


def outside_check(r, month: str) -> str:
    """Compare the case system's own current / not current flag with the tracker's reading."""
    said = (r.client.outside_status or "").strip().lower()
    if said not in ("current", "not current") or r.final_action == NEEDS_INFO:
        return ""
    ours = {FINAL_ACTION: r.final_action == IS_CURRENT, DATES_FOR_FILING: r.dates_for_filing == IS_CURRENT}
    agrees = (said == "current") in ours.values()
    if agrees:
        return ""
    return (f"<p class='mismatch' role='note'>The case system marks this matter <b>{e(r.client.outside_status)}</b>, "
            f"but the {month_label(month)} bulletin reads <b>{STATUS[r.final_action][0].lower()}</b> on Final Action "
            f"and <b>{STATUS[r.dates_for_filing][0].lower()}</b> on Dates for Filing. Check the priority date, "
            "category and chargeability.</p>")


def client_profile(r, a: Analysis, link: bool = False) -> str:
    c = r.client
    label, tone = STATUS[r.final_action]
    name = f"<a href='/client/{e(c.id)}'>{e(c.name)}</a>" if link else e(c.name)
    facts = [("Priority date", f"<span class='mono'>{long_date(c.priority_date)}</span>"),
             ("Preference category", f"<span class='cat'>{e(cat_label(c.category))}</span>"),
             ("Chargeability", e(country_name(c.chargeability))),
             ("May file I-485", "Yes" if r.can_file_i485 else "Not yet")]
    matter = [(k, v) for k, v in (("Matter", c.case_type), ("Petitioner", c.petitioner), ("Case status", c.case_status),
                                  ("Attorney", c.attorney), ("Receipt", c.receipt_number),
                                  ("Case system says", c.outside_status)) if v]
    matter_html = ("<dl class='matter'>" + "".join(f"<div><dt>{k}</dt><dd>{e(v)}</dd></div>" for k, v in matter)
                   + "</dl>") if matter else ""
    search = " ".join([c.name, c.category, country_name(c.chargeability), c.receipt_number, c.petitioner]).lower()
    if r.final_action == NEEDS_INFO:
        edit = f" <a href='/client/{e(c.id)}'>Fill them in</a>" if link else ""
        charts = (f"<p class='standing'><b>Needs details</b> <span>add the {e(c.missing_text)} to see where "
                  f"this client stands in the bulletin.{edit}</span></p>")
    else:
        charts = f"<div class='pcharts'>{chart_block(r, a, FINAL_ACTION)}{chart_block(r, a, DATES_FOR_FILING)}</div>"
    return (f"<article class='profile' data-search='{e(search)}'>"
            f"<header><h3>{name}</h3><span class='pill {tone} lg'>{label} · Final Action</span></header>"
            f"<dl class='facts'>" + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts) + "</dl>"
            f"{matter_html}{outside_check(r, a.bulletin.month)}{charts}"
            f"</article>")


def profiles(a: Analysis, link: bool = False) -> str:
    if not a.rows:
        return "<p class='empty'>No active clients yet.</p>"
    order = {WAITING: 0, IS_CURRENT: 1}
    rows = sorted(a.rows, key=lambda r: (order.get(r.final_action, 2), r.days_to_cutoff or 0, r.client.name.lower()))
    search = ("<div class='toolbar'><input type='search' id='profile-search' placeholder='Find a client, petitioner "
              "or receipt number' aria-label='Find a client'></div>")
    return search + f"<div class='profiles'>{''.join(client_profile(r, a, link) for r in rows)}</div>"


def bulletin_data(a: Analysis, history: list, chart_defaults: dict | None = None) -> str:
    """Every bulletin on file as JSON, for the in-page comparison and the quick lookup."""
    bulletins = sorted(history, key=lambda b: b.month)
    clients = {}
    for r in a.rows:
        if r.final_action == NEEDS_INFO:
            continue
        key = f"{r.client.category}|{r.client.chargeability}"
        clients[key] = clients.get(key, 0) + 1
    defaults = chart_defaults or {}
    data = {
        "bulletins": {b.month: {k: v for k, v in b.to_dict().items() if k in (FINAL_ACTION, DATES_FOR_FILING)} for b in bulletins},
        "labels": {b.month: month_label(b.month) for b in bulletins},
        "categories": list(CATEGORIES), "countries": GRID_COUNTRIES,
        "countryNames": {k: SHORT_COUNTRY[k] for k in GRID_COUNTRIES}, "clients": clients,
        "latest": a.bulletin.month, "previous": a.previous.month if a.previous else None,
        "family": [c for c in CATEGORIES if is_family(c)],
        "uscis": {"family": uscis_chart(a.bulletin, "F1", defaults), "employment": uscis_chart(a.bulletin, "EB2", defaults)},
    }
    payload = json.dumps(data).replace("</", "<\\/")
    return f"<script type='application/json' id='bulletin-data'>{payload}</script>"


def compare_view(a: Analysis, history: list) -> str:
    bulletins = sorted(history, key=lambda b: b.month)
    if len(bulletins) < 2:
        return ("<p class='empty'>Only one bulletin is on file, so there's nothing to compare yet. "
                "Comparisons appear once next month's bulletin is added.</p>")
    opts = lambda sel: "".join(f"<option value='{b.month}'{' selected' if b.month == sel else ''}>{month_label(b.month)}</option>"
                               for b in bulletins)
    newer, older = bulletins[-1].month, bulletins[-2].month
    cols = "".join(f"<div class='ccol {k}' id='cmp-{k}'><h3>{label}<span class='n'>0</span></h3><div class='items'></div></div>"
                   for k, label in (("fwd", "Advanced"), ("back", "Retrogressed"), ("same", "No movement")))
    return (f"<section class='panel'><div class='head'><div><h2 id='cmp-title'></h2>"
            f"<span class='muted small'>Pick any two bulletins to compare</span></div></div><div class='body' style='padding-top:14px'>"
            f"<div class='compare-bar'><label for='cmp-from'>Earlier bulletin<select id='cmp-from'>{opts(older)}</select></label>"
            f"<label for='cmp-to'>Later bulletin<select id='cmp-to'>{opts(newer)}</select></label>"
            f"<label for='cmp-chart'>Chart<select id='cmp-chart'><option value='{FINAL_ACTION}'>Final Action Dates</option>"
            f"<option value='{DATES_FOR_FILING}'>Dates for Filing</option></select></label>"
            f"<label style='flex-direction:row;align-items:center;gap:8px'><input type='checkbox' id='cmp-mine' checked> "
            f"Only categories where I have clients</label></div></div></section>"
            f"<div class='compare-cols'>{cols}</div>")


def history_table(a: Analysis, history: list) -> str:
    bulletins = sorted(history, key=lambda b: b.month)[-hist.HISTORY_WINDOW - 1:]
    cells = sorted({(r.client.category, r.client.chargeability) for r in a.rows if r.final_action != NEEDS_INFO},
                   key=lambda k: (list(CATEGORIES).index(k[0]), GRID_COUNTRIES.index(k[1]) if k[1] in GRID_COUNTRIES else 9))
    if len(bulletins) < 2 or not cells:
        return ""
    head = "<tr><th>Category</th>" + "".join(f"<th>{month_label(b.month)}</th>" for b in bulletins) + "</tr>"
    body = []
    for cat, country in cells:
        tds, prev = [], None
        for b in bulletins:
            cur = b.cutoff(FINAL_ACTION, cat, country)
            label, direction = delta(prev, cur) if prev is not None else ("", "")
            mark = f"<span class='delta {direction}'>{label}</span>" if label else ""
            tds.append(f"<td class='{direction}'><span class='mono'>{bulletin_code(cur)}</span>{mark}</td>")
            prev = cur
        body.append(f"<tr><th class='row' style='font-family:var(--sans)'><span class='cat'>{cat}</span> "
                    f"<span class='muted small'>{e(SHORT_COUNTRY.get(country, country))}</span></th>{''.join(tds)}</tr>")
    return (f"<section class='panel'><div class='head'><div><h2>Month by month</h2><span class='muted small'>"
            f"Final Action cutoffs for your clients' categories, last {len(bulletins)} bulletins</span></div></div>"
            f"<div class='body'><div class='scroll'><table class='history bulletin'><thead>{head}</thead>"
            f"<tbody>{''.join(body)}</tbody></table></div></div></section>")


VIEWS = [("overview", "Overview"), ("clients", "Clients"), ("profiles", "Client profiles"), ("lookup", "Quick lookup"),
         ("changes", "Bulletin changes"), ("chart", "Full bulletin")]


def lookup_view(a: Analysis, save_html: str = "") -> str:
    """Quick lookup for a phone call: type a priority date, category and chargeability; the page answers at once."""
    cats = "".join(f"<option value='{k}'>{k} · {e(v)}</option>" for k, v in CATEGORIES.items())
    areas = "".join(f"<option value='{k}'>{e(v)}</option>" for k, v in COUNTRIES.items())
    save = ""
    if save_html:
        save = (f"<form method='post' action='/client' id='lk-save' class='lk-save' hidden>{save_html}"
                "<input type='hidden' name='priority_date'><input type='hidden' name='category'>"
                "<input type='hidden' name='chargeability'><label>Client name<input name='name'></label>"
                "<button>Save as a client</button></form>")
    return (f"<section class='panel'><div class='body lookup-form'>"
            "<label>Priority date<input type='date' id='lk-pd'></label>"
            f"<label>Preference category<select id='lk-cat'>{cats}</select></label>"
            f"<label>Chargeability<select id='lk-area'>{areas}</select></label>"
            "<p class='muted small'>Chargeability is usually the country of birth. Any country without its own "
            "column in the bulletin is “All other countries”.</p></div></section>"
            f"<div id='lk-result' aria-live='polite'><p class='empty'>Enter a priority date to see where it stands in the "
            f"{month_label(a.bulletin.month)} bulletin.</p></div>{save}")


def dashboard(a: Analysis | None, inactive: list, row_actions=None, action_html: str = "",
              history: list | None = None, chart_defaults: dict | None = None, save_html: str = "") -> str:
    parts = [bulletin_bar(a, action_html)]
    if not a:
        return "".join(parts)
    history = history or [b for b in (a.previous, a.bulletin) if b]
    n_events = len({(ev.client.id, ev.kind) for ev in a.events})
    counts = {"overview": n_events, "clients": len(a.rows), "profiles": len(a.rows)}
    nav = "".join(f"<button type='button' role='tab' data-view='{k}' aria-selected='{str(k == 'overview').lower()}'>{label}"
                  + (f"<span class='count'>{counts[k]}</span>" if k in counts else "") + "</button>" for k, label in VIEWS)
    parts.append(f"<nav class='views' role='tablist' aria-label='Dashboard sections'>{nav}</nav>")
    views = {
        "overview": intro("<b>What changed this month, and who needs attention.</b> Start here after each new bulletin.")
                    + glance(a) + summary(a) + attention(a),
        "clients": intro("<b>Every client, with how long they have left.</b> “Time left” is how far the Final Action "
                         "cutoff still has to advance to reach the client's priority date. Use the buttons to filter.")
                   + client_table(a, inactive, row_actions),
        "profiles": intro("<b>One profile per client.</b> Each compares the previous bulletin's cutoff with this "
                          "month's, shows how far it moved, and how much time remains until the priority date is "
                          "current. Clients who are not yet current come first.")
                    + profiles(a, link=row_actions is not None),
        "changes": intro("<b>How the cutoffs moved between bulletins.</b> Pick any two months to compare. "
                         "The table below shows each of your clients' categories month by month.")
                   + compare_view(a, history) + history_table(a, history),
        "lookup": intro("<b>Check a date during a call.</b> Type a priority date, category and chargeability to see "
                        "where it stands against this month's bulletin, how far it has to go, and how the cutoff moved "
                        "since last month. Nothing is saved unless you choose to.") + lookup_view(a, save_html),
        "chart": intro("<b>The whole bulletin as published</b>, with each cutoff's change since last month and how many "
                       "of your clients sit in each box.") + bulletin_grid(a),
    }
    for k, _ in VIEWS:
        hidden = "" if k == "overview" else " hidden"
        parts.append(f"<div class='view' data-view='{k}' role='tabpanel'{hidden}>{views[k]}</div>")
    parts.append(bulletin_data(a, history, chart_defaults))
    return "".join(parts)
