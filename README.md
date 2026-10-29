# Priority Date Tracker

Tracks each client's place in the green card line against the monthly Visa Bulletin, for any immigration law office. It stores each client's preference category, chargeability country and priority date, reads every new bulletin (both the Final Action and Dates for Filing charts), and tells the office when a client becomes current, when a cutoff moves backward, who is getting close, and which beneficiaries are about to turn 21. Each report also lists every cutoff that changed since the previous month, whether or not a client is affected.

Everything office-specific lives in one YAML config file per office. Nothing is hardcoded to a person, tenant or folder.

## Two ways to run it

| | Local version | Cloud version |
|---|---|---|
| Runs on | One office PC (Windows, Mac or Linux) | An Azure Function in the office's own Azure subscription |
| Client data lives in | A SQLite file next to the config | A SharePoint list in the office's Microsoft 365 |
| Staff enter clients in | A local web page (`pdtrack serve`), the command line, or a CSV import | The SharePoint list itself, in a browser, Teams or the Lists app |
| Monthly check | Windows Task Scheduler or cron runs `pdtrack check` | Built-in daily timer |
| Alerts | Report file, plus optional 365 email or Teams webhook | 365 email and/or Teams webhook |
| Needs Microsoft 365 setup | No (only for email alerts) | Yes, an app registration |
| Good for | Trying it out, or an office that wants data on one machine | Several staff, several locations, nothing to keep switched on |

Both versions run the same code. The only difference is the `storage.backend` setting and how the check is scheduled. See [docs/local.md](docs/local.md) and [docs/cloud.md](docs/cloud.md).

## See it with sample data

```
pip install .
pdtrack demo          # opens the dashboard with made-up clients and the real Oct/Nov 2026 bulletins
```

The dashboard shows who just became current or lost their place, who is close, age-out checks, every client's status against both charts with search and filters, and the bulletin grid with each cutoff's change since last month.

## Quick start (local)

```
pip install .
cp config/office.example.yaml config/myoffice.yaml     # set office.name, leave storage as sqlite
pdtrack -c config/myoffice.yaml add --name "Garcia, Maria" --category F2A --country Mexico --pd 2022-06-01
pdtrack -c config/myoffice.yaml check --print
pdtrack -c config/myoffice.yaml serve                  # opens the web page
```

## Getting data in, by hand or automatically

Both versions take manual input, and both are built around three plug-in points so automatic sources can be added without touching the core:

- **Bulletin source** (`pdtracker/bulletin.py`): `state_dept` downloads the bulletin PDF from travel.state.gov (falling back to the web page) and reads both charts from it. Staff can also add the PDF themselves: upload it on the local web page, drop it in a watched folder (a local folder or a SharePoint folder), run `pdtrack bulletin load file.pdf`, or post it to the cloud `/api/bulletin` endpoint. If next month's bulletin isn't in by the reminder day (the 20th by default), the tracker asks staff for it. If the State Department moves its files, the URLs are in config.
- **Client feed** (`pdtracker/importers.py`): `pdtrack import` reads a CSV export from any case management system, using a column mapping in config. A direct sync from a database or API is a small class with a `rows()` method.
- **Store** (`pdtracker/stores.py`): SQLite and SharePoint lists today. Pointing the tracker at a case system's own database means writing one more store with the same nine methods.

See [docs/how-it-works.md](docs/how-it-works.md) for the rules the tracker applies and how to add a source.

## Layout

```
config/office.example.yaml   template for a new office
pdtracker/categories.py      preference categories and chargeability columns
pdtracker/models.py          client and bulletin records
pdtracker/bulletin.py        travel.state.gov scraper and manual bulletin files
pdtracker/evaluate.py        current / waiting, retrogression, approaching, age-out
pdtracker/render.py          the monthly report
pdtracker/stores.py          SQLite and in-memory stores
pdtracker/sharepoint.py      SharePoint list store and list setup
pdtracker/importers.py       CSV import and export
pdtracker/notify.py          report file, 365 email, webhook
pdtracker/tracker.py         the monthly check, shared by every version
pdtracker/dashboard.py       dashboard layout for the local web page
pdtracker/demo/              sample clients and the Oct/Nov 2026 bulletins for 'pdtrack demo'
pdtracker/webui.py           local web page
pdtracker/cli.py             pdtrack command
cloud/azure-function/        cloud version
tests/                       pytest suite, runs offline
```

Run the tests with `pip install '.[dev]' && pytest`.

This is a tracking aid. Staff should confirm cutoffs against the published bulletin before advising a client.
