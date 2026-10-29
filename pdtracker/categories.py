"""Preference categories and chargeability columns as the Visa Bulletin names them."""

from __future__ import annotations

import re

FAMILY = {
    "F1": "F1 Unmarried sons and daughters of U.S. citizens",
    "F2A": "F2A Spouses and children of permanent residents",
    "F2B": "F2B Unmarried sons and daughters (21+) of permanent residents",
    "F3": "F3 Married sons and daughters of U.S. citizens",
    "F4": "F4 Brothers and sisters of adult U.S. citizens",
}

EMPLOYMENT = {
    "EB1": "EB-1 Priority workers",
    "EB2": "EB-2 Advanced degree / exceptional ability",
    "EB3": "EB-3 Skilled workers and professionals",
    "EW": "EB-3 Other workers",
    "EB4": "EB-4 Special immigrants",
    "SR": "EB-4 Certain religious workers",
    "EB5U": "EB-5 Unreserved",
    "EB5R": "EB-5 Set aside: rural",
    "EB5H": "EB-5 Set aside: high unemployment",
    "EB5I": "EB-5 Set aside: infrastructure",
}

CATEGORIES = {**FAMILY, **EMPLOYMENT}

# Bulletin columns. ROW is "All Chargeability Areas Except Those Listed".
COUNTRIES = {
    "ROW": "All other countries",
    "CHINA": "China (mainland born)",
    "INDIA": "India",
    "MEXICO": "Mexico",
    "PHILIPPINES": "Philippines",
    "ESGH": "El Salvador, Guatemala, Honduras",
}

_CATEGORY_ALIASES = {
    "EB3OW": "EW", "EB3OTHERWORKERS": "EW", "OW": "EW", "OTHERWORKERS": "EW", "EB3OTHER": "EW",
    "EB4R": "SR", "RELIGIOUS": "SR", "CERTAINRELIGIOUSWORKERS": "SR",
    "EB5": "EB5U", "EB5UNRESERVED": "EB5U",
    "EB5RURAL": "EB5R", "EB5HIGHUNEMPLOYMENT": "EB5H", "EB5INFRASTRUCTURE": "EB5I",
    "F2": "F2A",
}

_COUNTRY_ALIASES = {
    "CHINA": "CHINA", "CHINAMAINLAND": "CHINA", "CHINAMAINLANDBORN": "CHINA", "PRC": "CHINA", "CN": "CHINA",
    "INDIA": "INDIA", "IN": "INDIA",
    "MEXICO": "MEXICO", "MX": "MEXICO",
    "PHILIPPINES": "PHILIPPINES", "PH": "PHILIPPINES", "PHILIPPINE": "PHILIPPINES",
    "ELSALVADOR": "ESGH", "GUATEMALA": "ESGH", "HONDURAS": "ESGH", "ESGH": "ESGH",
    "ROW": "ROW", "ALL": "ROW", "OTHER": "ROW", "": "ROW",
}

IMMEDIATE_RELATIVES = {"IR", "IR1", "IR2", "IR5", "CR1", "CR2", "IMMEDIATERELATIVE"}


def _squash(text: str) -> str:
    text = text.upper().replace("É", "E")
    return re.sub(r"[^A-Z0-9]", "", text)


def normalize_category(text: str) -> str:
    key = _squash(text)
    if key in CATEGORIES:
        return key
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    if key in IMMEDIATE_RELATIVES:
        raise ValueError(f"'{text}' is an immediate relative category, which has no visa queue to track.")
    known = ", ".join(CATEGORIES)
    raise ValueError(f"Unknown category '{text}'. Use one of: {known}")


def chargeability_column(country: str) -> str:
    """Map a country name or code to the bulletin column it is charged to.

    Countries without their own column fall under ROW. Chargeability is normally the
    country of birth; cross-chargeability is a legal call the staff enter by hand.
    """
    key = _squash(country)
    if key in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[key]
    for alias, column in _COUNTRY_ALIASES.items():
        if alias and len(alias) > 3 and key.startswith(alias):
            return column
    return "ROW"


def is_family(category: str) -> bool:
    return category in FAMILY
