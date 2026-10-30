"""Priority date tracking against the monthly Visa Bulletin.

The core (categories, models, evaluate, bulletin parsing) has no I/O. Storage, bulletin
sources and notifiers are pluggable so the same logic runs on an office PC (SQLite) or in
the cloud (SharePoint lists from an Azure Function).
"""

__version__ = "0.2.0"
