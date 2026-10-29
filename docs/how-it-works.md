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

## Alerts happen once per bulletin

Each bulletin is marked processed after its check, so a daily schedule doesn't repeat alerts. `check --force` re-runs one.

## What "system specific" can mean

The local version is the system-specific option in the sense of "runs on the office's own machine". If the office instead wants the tracker built around one practice management system (Clio, Docketwise, INSZoom, LollyLaw, eImmigration and so on), the plug-in points below are where that goes, and the core stays portable.

## Adding an automatic source

- **Another bulletin source:** any object with `latest()` and `fetch(month)` returning a `Bulletin`. See `StateDeptSource` in `pdtracker/bulletin.py`.
- **A case system's export:** usually just a column mapping under `import.columns`. For an API or database, write a class with a `rows()` method that yields dicts with the tracker's field names, and call `importers.sync(store, feed)`. Rows with `external_id` update in place.
- **A case system as the store:** implement the methods of `Store` in `pdtracker/stores.py` (list, get, save and delete clients; save, get and list bulletins; processed flags; and `record_statuses` to write results back).

## Known limits

- The travel.state.gov parser was written against the bulletin's published layout and tested on a sample page built to match it, because this build couldn't reach the live site. Check the first automatic fetch against the real bulletin. If the layout changes, the fetch fails with a clear message and manual entry keeps working.
- The tracker doesn't compute CSPA age, cross-chargeability, or eligibility to retain a priority date. Those stay with the attorney.
