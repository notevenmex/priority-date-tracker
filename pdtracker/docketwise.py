"""Read a Docketwise matters export and sort out which matters belong in the tracker.

Docketwise's Matters tab export has one row per matter (title, client, description, type,
status, priority_date_status ...). A Matter Report can add the priority date, preference
category and country columns. This module:

  * keeps only green card matters that wait on the Visa Bulletin,
  * reads the priority date, category and country when the export has them, and otherwise
    infers what it safely can from the matter type and description,
  * links derivatives ("AOS Derivative Spouse of ...") to their principal's matter,
  * returns complete clients to import and a worklist of matters still missing information.

It never guesses a country from a name: chargeability is a legal call, so a matter without
an explicit country stays on the worklist.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from .categories import CATEGORIES, chargeability_column, normalize_category
from .models import Client, parse_date

# Header names seen in Docketwise exports, plus a few spellings for Matter Report columns.
# An office can override any of them with import.columns in its config.
ALIASES = {
    "title": ["title", "matter", "matter title", "matter name"],
    "client": ["client", "client name", "contact"],
    "applicant": ["applicant", "beneficiary", "applicant name"],
    "description": ["description", "matter description"],
    "type": ["type", "matter type"],
    "status": ["status", "matter status"],
    "outside_status": ["final_action_date_status", "final action date status", "priority_date_status",
                       "priority date status"],
    "attorney": ["assignees", "assignee", "attorney", "responsible attorney"],
    "priority_date": ["priority_date", "priority date"],
    "category": ["preference_category", "preference category", "category", "visa category"],
    "chargeability": ["country_of_chargeability", "country of chargeability", "chargeability",
                      "country of birth", "country_of_birth", "birth country"],
    "receipt_number": ["receipt_number", "receipt number", "receipt"],
    "external_id": ["id", "matter id", "matter_id", "number"],
    "archived": ["archived"],
    "updated": ["updated", "updated at", "last updated"],
    "final_action_status": ["final_action_date_status", "final action date status"],
    "receipts": ["uscis_receipts", "receipts"],
}

# Matter types that wait on a Visa Bulletin cutoff (or might, depending on the category).
GREEN_CARD_TYPES = re.compile(
    r"i-?140|perm|\baos\b|adjustment|i-?485|i-?130|i-?360|consular processing|nvc|immigrant visa|labor cert", re.I)
# Matter types that never do: visas, extensions, and filings for people who already have a green card.
NOT_GREEN_CARD_TYPES = re.compile(
    r"h-?1b|\bh-?4\b|l-?1|i-?539|\br-?1\b|\be-?3\b|i-?765 / i-?131|i-?824|i-?90\b|i-?751|naturali[sz]ation|n-?400|"
    r"i-?601a|i-?589|asylum", re.I)
UNSPECIFIED = re.compile(r"^(unspecified|)$", re.I)
DONE_STATUSES = re.compile(r"approved i-?485|case denied|green card (received|approved)", re.I)

IMMEDIATE_RELATIVE = re.compile(
    r"usc spouse|spouse of (a )?usc|married to (a )?usc|by (a )?usc child|usc child|spouse of a u\.?s\.? citizen", re.I)
DERIVATIVE = re.compile(r"derivative (?:(?:spouse|child) )?of ([^,()|]+)", re.I)

CATEGORY_HINTS = [
    (re.compile(r"other workers?|\beb-?3\s*ow\b", re.I), "EW"),
    (re.compile(r"\beb-?1[abc]?\b|multi-?national (manager|executive)", re.I), "EB1"),
    (re.compile(r"\beb-?2\b", re.I), "EB2"),
    (re.compile(r"\beb-?3\b", re.I), "EB3"),
    (re.compile(r"religious worker|\beb-?4\b", re.I), "SR"),
    (re.compile(r"\beb-?5\b", re.I), "EB5U"),
]

# Only explicit country words; anything without its own bulletin column is "all other countries".
COUNTRY_HINTS = [
    (re.compile(r"\bindia(n)?\b", re.I), "INDIA"),
    (re.compile(r"\bchin(a|ese)\b", re.I), "CHINA"),
    (re.compile(r"\bmexic(o|an)\b", re.I), "MEXICO"),
    (re.compile(r"\bphilippines\b|\bfilipin[oa]\b", re.I), "PHILIPPINES"),
    (re.compile(r"el salvador|salvadoran|guatemal|hondur", re.I), "ESGH"),
    (re.compile(r"\b(venezuela|colombia|ukrain|uganda|kenya|rwanda|burundi|congo|cameroon|nigeria|ghana|brazil|peru|"
                r"ecuador|cuba|dominican|haiti|nepal|pakistan|bangladesh|sri lanka|vietnam|korea|japan|canada)", re.I),
     "ROW"),
]

PREFERENCE = "preference"
IMMEDIATE = "immediate relative"
DONE = "finished"
OTHER = "not a green card matter"


@dataclass
class Matter:
    row: int
    title: str
    applicant: str
    petitioner: str
    description: str
    type: str
    status: str
    outside_status: str
    attorney: str
    receipt_number: str = ""
    external_id: str = ""
    updated: str = ""                         # ISO date, to pick the latest of a client's matters
    archived: bool = False
    priority_date: object = None
    category: str = ""
    chargeability: str = ""
    kind: str = OTHER
    principal: str = ""                       # for derivatives: the principal's name as written
    notes: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        out = []
        if not self.priority_date:
            out.append("priority date")
        if not self.category:
            out.append("preference category")
        if not self.chargeability:
            out.append("country of chargeability")
        return out

    @property
    def key(self) -> str:
        """Stable id for re-imports: Docketwise's own id when exported, else applicant and matter title."""
        return self.external_id or f"docketwise:{self.applicant}|{self.title}"

    @property
    def complete(self) -> bool:
        return self.kind == PREFERENCE and not self.missing

    def client(self) -> Client:
        return Client(name=self.applicant, category=self.category, chargeability=self.chargeability,
                      priority_date=self.priority_date, case_type=self.type, receipt_number=self.receipt_number,
                      external_id=self.key, petitioner=self.petitioner,
                      case_status=self.status, attorney=self.attorney, outside_status=self.outside_status,
                      notes="; ".join(self.notes))


def _pick(raw: dict, field_name: str, columns: dict) -> str:
    names = [columns[field_name]] if field_name in columns else ALIASES.get(field_name, [field_name])
    lower = {k.strip().lower(): v for k, v in raw.items() if k}
    for n in names:
        v = re.sub(r"\s+", " ", str(lower.get(n.strip().lower()) or "")).strip()
        if v and v.lower() not in BLANKS:
            return v
    return ""


BLANKS = {"unspecified", "undefined", "n/a", "none", "-"}

# Docketwise writes the preference category and the bulletin column together: "EB 2nd: India".
_DW_CATEGORY = [
    (re.compile(r"immediate relative", re.I), "IR"),
    (re.compile(r"other workers?", re.I), "EW"),
    (re.compile(r"religious", re.I), "SR"),
    (re.compile(r"\bEB\s*-?\s*(1|1st|first)\b", re.I), "EB1"),
    (re.compile(r"\bEB\s*-?\s*(2|2nd|second)\b", re.I), "EB2"),
    (re.compile(r"\bEB\s*-?\s*(3|3rd|third)\b", re.I), "EB3"),
    (re.compile(r"\bEB\s*-?\s*(4|4th|fourth)\b", re.I), "EB4"),
    (re.compile(r"\bEB\s*-?\s*(5|5th|fifth)\b", re.I), "EB5U"),
    (re.compile(r"\bF\s*-?\s*(2A|2B|1|3|4)\b", re.I), None),
]


def split_category(text: str) -> tuple[str, str]:
    """'EB 2nd: India' -> ('EB2', 'INDIA'); 'F2B: All Areas' -> ('F2B', 'ROW'); 'EB3' -> ('EB3', '').
    Immediate relatives come back as ('IR', '')."""
    head, _, area = text.partition(":")
    area = area.strip()
    if any(p.search(area) for p, _ in _DW_CATEGORY):      # "1. Emp: Religious Workers" names no country
        head, area = text, ""
    country = "" if not area else "ROW" if re.fullmatch(r"all (areas|other countries)|row", area, re.I) \
        else chargeability_column(area)
    for pattern, cat in _DW_CATEGORY:
        m = pattern.search(head)
        if m:
            return (cat or f"F{m[1].upper()}"), ("" if cat == "IR" else country)
    return normalize_category(head), country


def _date(text: str):
    """Docketwise writes dates as MM/DD/YY."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2})", text)
    if m:
        yy = int(m[3])
        text = f"{int(m[1])}/{int(m[2])}/{yy + (2000 if yy < 70 else 1900)}"
    return parse_date(text)


def applicant_from_title(title: str) -> str:
    """'MISHRA, Garvit (I-140)' -> 'MISHRA, Garvit'; 'I-140 for Ankit MEHTA' -> 'Ankit MEHTA'.
    Returns '' when the title holds no name ('465 Labor Cert')."""
    t = re.sub(r"\s+", " ", title).strip()
    name = ""
    m = re.match(r"^([^()]+?)\s*\(", t)
    if m and "," in m[1]:
        name = m[1]
    else:
        m = re.search(r"\bfor\s+(.+)$", t, re.I) or re.search(r"\bof\s+(.+)$", t, re.I)
        if m:
            name = m[1]
        else:
            m = (re.match(r"^(?:PERM|I-140)\s*[-–]\s*(.+)$", t, re.I)
                 or re.match(r"^(.+?)\s*[-–]\s*(?:PERM|I-140)\b", t, re.I) or re.match(r"^(.+?)\s+PERM$", t, re.I))
            name = m[1] if m else t
    name = re.sub(r"\s*\(.*$", "", name)
    name = re.sub(r"^(AOS|PERM|I-\d+\w*)\s+", "", name, flags=re.I)
    name = re.sub(r"\s+(son|daughter|spouse|wife|husband|child) of .*$", "", name, flags=re.I)
    name = re.sub(r"\s+(EB-?\d\w*|PERM|I-\d+\w*)$", "", name, flags=re.I).strip(" -,")
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ'-]+", name) if not re.fullmatch(
        r"(aos|perm|labor|cert|employment|family|consular|processing|iv|i|ead|petition|matter|status)", w, re.I)]
    return name if len(words) >= 2 and not re.match(r"^\d", name) else ""
def _updated(text: str) -> str:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", text or "")
    if m:
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return f"{y:04d}-{int(m[1]):02d}-{int(m[2]):02d}"
    return text or ""


def _infer_category(text: str) -> str:
    for pattern, cat in CATEGORY_HINTS:
        if pattern.search(text):
            return cat
    return ""


def _infer_country(text: str) -> str:
    for pattern, col in COUNTRY_HINTS:
        if pattern.search(text):
            return col
    return ""


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", name.lower()) if len(t) > 2}


def _same_person(a: str, b: str) -> bool:
    """Same name give or take middle names ('Anil NETTIKOPPULA' and 'Anil Kumar NETTIKOPPULA')."""
    x, y = _name_tokens(a), _name_tokens(b)
    return len(x) >= 2 and len(y) >= 2 and (x <= y or y <= x)


def read(path: str | Path, columns: dict | None = None) -> list[Matter]:
    columns = columns or {}
    matters = []
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        for n, raw in enumerate(csv.DictReader(f), start=2):
            title = _pick(raw, "title", columns)
            if not title:
                continue
            client = _pick(raw, "client", columns)
            applicant = _pick(raw, "applicant", columns) or applicant_from_title(title)
            note = ""
            if not applicant:                   # e.g. "465 Labor Cert": the contact is the applicant
                applicant, client = client or title, ""
                note = "applicant name taken from the Docketwise contact, not the matter title"
            m = Matter(row=n, title=title, applicant=applicant, updated=_updated(_pick(raw, "updated", columns)),
                       petitioner=client, description=_pick(raw, "description", columns),
                       type=_pick(raw, "type", columns), status=_pick(raw, "status", columns),
                       outside_status=_pick(raw, "outside_status", columns), attorney=_pick(raw, "attorney", columns),
                       receipt_number=_pick(raw, "receipt_number", columns) or _receipt(_pick(raw, "receipts", columns)),
                       external_id=_pick(raw, "external_id", columns),
                       archived=_pick(raw, "archived", columns).lower() == "true")
            m.outside_status = {"not current": "Not current", "current": "Current"}.get(m.outside_status.lower(), "")
            if note:
                m.notes.append(note)
            if _same_person(m.petitioner, m.applicant):
                m.petitioner = ""               # the "client" is the applicant themself
            _classify(m, raw, columns)
            matters.append(m)
    matters = [m for m in _merge_people(matters) if not m.archived]   # closed unless the person has an open matter
    link_derivatives(matters)
    return matters


def _receipt(text: str) -> str:
    """'IOE0908822583 - USCIS Is currently Processing the Case, ...' -> the latest receipt number."""
    found = re.findall(r"\b[A-Z]{3}\d{10}\b", text or "")
    return found[-1] if found else ""


def _classify(m: Matter, raw: dict, columns: dict) -> None:
    text = " ".join([m.title, m.type, m.description])
    cat = _pick(raw, "category", columns)
    if cat and not DONE_STATUSES.search(m.status):
        try:
            m.category, country = split_category(cat)
        except ValueError as e:
            m.category, country = "", ""
            m.notes.append(str(e))
        if m.category == "IR":
            m.category, m.kind = "", IMMEDIATE
            return
        m.kind = PREFERENCE
        explicit = _pick(raw, "chargeability", columns)
        m.chargeability = chargeability_column(explicit) if explicit else country
        d = _pick(raw, "priority_date", columns)
        if d:
            try:
                m.priority_date = _date(d)
            except ValueError:
                m.notes.append(f"couldn't read priority date '{d}'")
        dm = DERIVATIVE.search(text)
        if dm:
            m.principal = dm[1].strip()
        return
    # The matter type decides; the title only when the type was never set.
    deciding = m.title if UNSPECIFIED.match(m.type) else m.type
    if (NOT_GREEN_CARD_TYPES.search(deciding) or not GREEN_CARD_TYPES.search(deciding)
            or (NOT_GREEN_CARD_TYPES.search(m.title) and not GREEN_CARD_TYPES.search(m.title))):
        m.kind = OTHER
        return
    if DONE_STATUSES.search(m.status):
        m.kind = DONE
        return
    if IMMEDIATE_RELATIVE.search(text) or re.search(r"i-?130 by usc spouse", m.type, re.I):
        m.kind = IMMEDIATE
        return
    m.kind = PREFERENCE
    d = _pick(raw, "priority_date", columns)
    if d:
        try:
            m.priority_date = _date(d)
        except ValueError:
            m.notes.append(f"couldn't read priority date '{d}'")
    if not m.category:
        m.category = _infer_category(text)
        if m.category == "SR":
            m.notes.append("category SR (non-minister religious worker) read from the matter; ministers are EB4")
        elif m.category:
            m.notes.append(f"category {m.category} read from the matter description")
    country = _pick(raw, "chargeability", columns)
    if country:
        m.chargeability = chargeability_column(country)
    else:
        m.chargeability = _infer_country(m.description + " " + m.title)
        if m.chargeability:
            m.notes.append("country read from the matter description")
    dm = DERIVATIVE.search(text)
    if dm:
        m.principal = dm[1].strip()


def _merge_people(matters: list[Matter]) -> list[Matter]:
    """One profile per person: an I-140 matter and a later AOS matter for the same applicant merge.
    The newest matter's status wins; dates and category come from whichever matter has them."""
    out: list[Matter] = []
    for m in matters:
        twin = None
        if m.kind != OTHER:
            twin = next((o for o in out if o.kind != OTHER and _same_person(o.applicant, m.applicant)), None)
        if twin is None:
            out.append(m)
            continue
        # A finished or immediate-relative matter for the same person settles it.
        for kind in (DONE, IMMEDIATE):
            if kind in (twin.kind, m.kind):
                twin.kind = kind
                break
        new, old = (m, twin) if m.updated >= twin.updated else (twin, m)
        for attr in ("category", "chargeability"):
            a, b = getattr(twin, attr), getattr(m, attr)
            if a and b and a != b:
                twin.notes.append(f"matters disagree on {attr}: {a} vs {b}")
        twin.priority_date = twin.priority_date or m.priority_date
        twin.category = twin.category or m.category
        twin.chargeability = twin.chargeability or m.chargeability
        twin.receipt_number = new.receipt_number or old.receipt_number
        twin.petitioner = twin.petitioner or m.petitioner
        twin.applicant = max(twin.applicant, m.applicant, key=lambda n: len(_name_tokens(n)))
        twin.type = " + ".join(dict.fromkeys(t for t in (old.type, new.type) if t))
        twin.status, twin.updated = new.status, new.updated
        twin.outside_status = new.outside_status or old.outside_status
        twin.attorney = new.attorney or old.attorney
        twin.principal = twin.principal or m.principal
        twin.archived = twin.archived and m.archived
        twin.notes += [n for n in m.notes if n not in twin.notes]
        twin.notes.append(f"combines matters '{old.title}' and '{new.title}'")
    return out


def link_derivatives(matters: list[Matter]) -> None:
    """A derivative spouse or child shares the principal's category, priority date and chargeability
    (as entered on the principal's matter). Cross-chargeability is left to the attorney."""
    principals = [p for p in matters if p.kind == PREFERENCE and not p.principal]
    for m in matters:
        if m.kind != PREFERENCE or not m.principal:
            continue
        want = _name_tokens(m.principal)
        found = [p for p in principals if want and want <= _name_tokens(p.applicant + " " + p.title)]
        if len(found) != 1:
            note = f"derivative of {m.principal}; principal's matter not found"
            if note not in m.notes:
                m.notes.append(note)
            continue
        p = found[0]
        m.priority_date = m.priority_date or p.priority_date
        m.category = m.category or p.category
        m.chargeability = m.chargeability or p.chargeability
        note = f"derivative of {p.applicant}; dates follow the principal's matter"
        if note not in m.notes:
            m.notes.append(note)


def summary(matters: list[Matter]) -> dict:
    by_kind = {}
    for m in matters:
        by_kind.setdefault(m.kind, []).append(m)
    pref = by_kind.get(PREFERENCE, [])
    return {
        "total": len(matters),
        "preference": len(pref),
        "complete": sum(1 for m in pref if m.complete),
        "immediate": len(by_kind.get(IMMEDIATE, [])),
        "finished": len(by_kind.get(DONE, [])),
        "other": len(by_kind.get(OTHER, [])),
        "missing": {k: sum(1 for m in pref if k in m.missing)
                    for k in ("priority date", "preference category", "country of chargeability")},
    }


WORKLIST_FIELDS = ["name", "priority_date", "category", "chargeability", "missing", "case_type", "case_status",
                   "petitioner", "attorney", "outside_status", "external_id", "notes"]


def write_worklist(matters: list[Matter], path: str | Path) -> int:
    """Matters still missing information, in the tracker's own CSV layout.

    Staff fill in the blanks (or re-export with the missing columns) and load the file with
    `pdtrack import`. Columns already filled are the tracker's best reading; check them.
    """
    todo = [m for m in matters if m.kind == PREFERENCE and not m.complete]
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=WORKLIST_FIELDS)
        w.writeheader()
        for m in sorted(todo, key=lambda m: m.applicant.lower()):
            w.writerow({"name": m.applicant, "priority_date": m.priority_date.isoformat() if m.priority_date else "",
                        "category": m.category, "chargeability": m.chargeability,
                        "missing": ", ".join(m.missing), "case_type": m.type, "case_status": m.status,
                        "petitioner": m.petitioner, "attorney": m.attorney, "outside_status": m.outside_status,
                        "external_id": m.key, "notes": "; ".join(m.notes)})
    return len(todo)


def sync(store, matters: list[Matter]) -> dict:
    """Add or update the complete matters in the store, matched on external_id."""
    existing = {c.external_id: c for c in store.list_clients(include_inactive=True) if c.external_id}
    added = updated = 0
    for m in matters:
        if not m.complete:
            continue
        c = m.client()
        match = existing.get(c.external_id)
        if match:
            c.id, c.active, c.beneficiary_dob = match.id, match.active, match.beneficiary_dob
            c.responsible_email = match.responsible_email
            updated += 1
        else:
            added += 1
        store.save_client(c)
    return {"added": added, "updated": updated}


__all__ = ["read", "summary", "write_worklist", "sync", "Matter", "CATEGORIES"]
