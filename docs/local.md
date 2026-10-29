# Local version (one office PC)

Everything stays on one machine: client data in a SQLite file, reports in a folder.

## Install

Needs Python 3.10 or newer.

```
pip install .                   # add '.[m365]' if you want email alerts through Microsoft 365
cp config/office.example.yaml config/myoffice.yaml
```

In `config/myoffice.yaml`, set `office.name` and leave `storage.backend: sqlite`. The database goes to `data/priority-dates.db` next to the config file unless you change `storage.sqlite_path`. Include that file in the office's normal backups, since it holds client names and dates.

## Enter clients

Any of these work, and they can be mixed:

- **Web page:** `pdtrack -c config/myoffice.yaml serve` opens `http://localhost:8765`. Add, edit or stop tracking clients, enter a bulletin by hand, and run a check. Only the PC it runs on can open it.
- **Command line:** `pdtrack -c config/myoffice.yaml add --name "Reyes, Ana" --category F4 --country Philippines --pd 2005-01-01 --dob 2007-04-02 --email attorney@example.com`. Run `pdtrack -c ... codes` to see the category and country codes.
- **CSV import:** export from your case system (or a spreadsheet) and run `pdtrack -c ... import clients.csv`. Map your column headers to tracker fields under `import.columns` in the config. Rows with an `external_id` (for example the matter number) update the same client on the next import, so re-importing a fresh export each month keeps things in sync.

Chargeability is normally the country of birth. Countries without their own bulletin column count as "all other countries". If a client is cross-charged to a spouse's or parent's country, enter that country instead.

## Get the bulletin

- **Automatic** (`bulletin.source: state_dept`): `pdtrack check` downloads the newest bulletin PDF from travel.state.gov (next month's once it's out, usually mid-month), reads both charts, compares it with the previous bulletin and writes a report to `reports/`. `bulletin.format` chooses the PDF, the web page, or `auto` (PDF first).
- **Staff add the PDF:** download it from travel.state.gov, then upload it on the web page's **Enter a bulletin** screen, drop it in the `bulletin.inbox_dir` folder (picked up on the next check), or run `pdtrack -c ... bulletin load visabulletin_December2026.pdf`. The month is read from the PDF.
- **Type the dates:** **Enter a bulletin** also has a grid prefilled with last month's dates, so you only change what moved. Or use `pdtrack -c ... bulletin template --month 2026-12 > dec.json`, fill it in, and `pdtrack -c ... bulletin load dec.json`.

If next month's bulletin still isn't in by `bulletin.reminder_day` (the 20th by default), each check sends a reminder every `reminder_every_days` with the PDF link and where to put it, by email or webhook if those are set up and on screen when run by hand. The web page shows the same reminder. Set `reminder_day: 0` to turn it off.

Each report lists every cutoff that changed since the previous bulletin in both charts, backward moves first, and marks the ones that affect your clients.

Each month USCIS says which chart it accepts for I-485 filings. Until you record it, the office default in `bulletin.uscis_chart_default` is used and the report says so. Record it with the web form or `pdtrack -c ... bulletin set-chart --month 2026-12 --family dates_for_filing --employment final_action`.

## Run it monthly

`check` only alerts once per bulletin, so it is safe to schedule daily.

Windows (Task Scheduler, daily at 9am):

```
schtasks /Create /SC DAILY /ST 09:00 /TN "Priority date check" /TR "pdtrack -c C:\pdtracker\config\myoffice.yaml check"
```

Mac or Linux (cron): `0 9 * * * pdtrack -c /path/to/config/myoffice.yaml check`

## Alerts

- A markdown report per bulletin is always written to `alerts.report_dir`.
- **Email** through the office's Microsoft 365: fill in `microsoft365.tenant_id` and `client_id`, set `alerts.email.enabled: true`, and follow the app registration steps in [cloud.md](cloud.md) (only the `Mail.Send` permission is needed). The office report goes to `alerts.email.recipients`, and each responsible attorney also gets a short note about their own clients.
- **Teams, Power Automate or Slack:** create a workflow with an incoming webhook trigger, put its URL in an environment variable, and name that variable in `alerts.webhook_url_env`.

## Several offices on one machine

Use one config file per office. Each has its own database path, report folder and secret variable names.
