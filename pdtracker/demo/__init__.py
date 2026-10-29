"""Sample data for trying the tracker: made-up clients against the real Oct and Nov 2026 bulletins."""

from __future__ import annotations

from pathlib import Path

from ..bulletin import parse_bulletin_pdf
from ..models import Client

HERE = Path(__file__).parent
BULLETINS = ["visabulletin_October2026.pdf", "visabulletin_November2026.pdf"]

# Fictional people. Priority dates sit near real cutoffs so every kind of alert shows up.
CLIENTS = [
    dict(name="Alvarez Ruiz, Sofia", category="F2A", chargeability="Mexico", priority_date="2026-04-01",
         case_type="I-130 spouse of LPR", receipt_number="IOE0912345678"),
    dict(name="Nguyen, Thi Lan", category="F1", chargeability="Vietnam", priority_date="2020-06-15",
         case_type="I-130 unmarried daughter", receipt_number="IOE0898765432"),
    dict(name="Okafor, Chinedu", category="F2B", chargeability="Nigeria", priority_date="2020-03-10",
         case_type="I-130 adult son of LPR"),
    dict(name="Santos, Maria Clara", category="F4", chargeability="Philippines", priority_date="2008-09-01",
         case_type="I-130 sibling", receipt_number="WAC0812345678"),
    dict(name="Hernandez Lopez, Jose", category="F3", chargeability="Mexico", priority_date="2001-11-20",
         case_type="I-130 married son"),
    dict(name="Patel, Rohan", category="EB2", chargeability="India", priority_date="2015-06-01",
         case_type="I-140 NIW", receipt_number="LIN1512345678"),
    dict(name="Kowalski, Anna", category="EB3", chargeability="Poland", priority_date="2024-02-10",
         case_type="PERM / I-140"),
    dict(name="Ramirez, Luis Fernando", category="EW", chargeability="Mexico", priority_date="2022-03-03",
         case_type="PERM other worker"),
    dict(name="Chen, Wei", category="EB1", chargeability="China", priority_date="2023-07-15",
         case_type="I-140 EB-1A", receipt_number="SRC2312345678"),
    dict(name="Reddy, Kavya", category="F4", chargeability="India", priority_date="2009-04-01",
         case_type="I-130 sibling"),
    dict(name="Dela Cruz, Miguel Jr.", category="F2A", chargeability="Philippines", priority_date="2026-08-10",
         case_type="I-130 child of LPR (derivative)", beneficiary_dob="2006-05-14"),
    dict(name="Li, Jun", category="EB5U", chargeability="China", priority_date="2018-04-01",
         case_type="I-526E"),
    dict(name="Garcia Mendoza, Rosa", category="F1", chargeability="Mexico", priority_date="2010-01-05",
         case_type="I-130 unmarried daughter"),
    dict(name="Haddad, Karim", category="F2B", chargeability="Lebanon", priority_date="2021-05-20",
         case_type="I-130 adult son of LPR"),
    dict(name="Torres, Elena", category="F2A", chargeability="Guatemala", priority_date="2025-11-03",
         case_type="I-130 spouse of LPR", active=False, notes="Approved, case closed"),
]


def load(store) -> None:
    """Fill an empty store with the sample clients and bulletins (October checked, November new)."""
    for d in CLIENTS:
        store.save_client(Client(**d))
    for name in BULLETINS:
        store.save_bulletin(parse_bulletin_pdf((HERE / name).read_bytes(), source=name))
    store.mark_processed("2026-10")
