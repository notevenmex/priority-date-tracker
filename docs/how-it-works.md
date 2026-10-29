# How the tracker decides

## Current or not

A priority date is current when it is earlier than the cutoff for the client's category and chargeability column. "C" means everyone is current and "U" means no visas are available. A country without its own column uses the "All Chargeability Areas" column. Each client is checked against both charts:

- **Final Action Dates:** when a visa can actually be issued or an I-485 approved.
- **Dates for Filing:** when an I-485 can be filed (if USCIS accepts this chart that month) or documents sent to the NVC.

The report's "I-485 filing open" uses whichever chart USCIS accepts that month. That choice is recorded per bulletin; until it is, the office default in config is used and the report says it is unconfirmed.

## What gets flagged

- **Newly current:** current this month under a chart, and not last month.
- **Moved backward:** current last month, not current now (retrogression for that client). Category-level backward moves are also listed with the clients they affect.
- **Close to current:** waiting, and within `alerts.approaching_days` of the Final Action cutoff.
- **Age-out check:** a beneficiary date of birth is on file and the person turns 21 within `alerts.cspa_warning_days`. This is a reminder to do the CSPA calculation, not the calculation itself.

Category changes (for example F2B becoming F1 when the petitioner naturalizes, or an F2A child aging into F2B) are made by editing the client's category; the priority date normally carries over, and the next check uses the new category.

## Every change between months

Besides client alerts, each report has an "Everything that changed" section: every category and country whose cutoff moved since the previous bulletin, in both charts, backward moves first, with the number of the office's clients in each. A change in which chart USCIS accepts for filing is listed too. The email subject counts cutoffs that moved back even when no client is affected.

## Getting the bulletin, and asking for it

The tracker looks for a new bulletin in this order: a PDF staff dropped in the watched folder, then the PDF on travel.state.gov, then the bulletin web page. If next month's bulletin isn't on file by the reminder day, it asks staff to add it and repeats every few days until it is. A failed download is reported in that reminder rather than stopping the check.

## Alerts happen once per bulletin

Each bulletin is marked processed after its check, so a daily schedule doesn't repeat alerts. `check --force` re-runs one.

## What "system specific" can mean

The local version is the system-specific option in the sense of "runs on the office's own machine". If the office instead wants the tracker built around one practice management system (Clio, Docketwise, INSZoom, LollyLaw, eImmigration and so on), the plug-in points below are where that goes, and the core stays portable.

## Adding an automatic source

- **Another bulletin source:** any object with `latest()` and `fetch(month)` returning a `Bulletin`. See `StateDeptSource` in `pdtracker/bulletin.py`.
- **A case system's export:** usually just a column mapping under `import.columns`. For an API or database, write a class with a `rows()` method that yields dicts with the tracker's field names, and call `importers.sync(store, feed)`. Rows with `external_id` update in place.
- **A case system as the store:** implement the methods of `Store` in `pdtracker/stores.py` (list, get, save and delete clients; save, get and list bulletins; processed flags; and `record_statuses` to write results back).

## Known limits

- The PDF reader is tested against the real October and November 2026 bulletins (in `tests/fixtures`). The web page reader is tested only on a sample page built to match the published layout. If the State Department changes either layout, reading fails with a clear message, and staff can still type the dates in.
- The tracker doesn't compute CSPA age, cross-chargeability, or eligibility to retain a priority date. Those stay with the attorney.
