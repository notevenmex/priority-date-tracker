# Cloud version (Azure Function + SharePoint)

Clients live in a SharePoint list in the office's own Microsoft 365, so staff edit them in a browser, Teams or the Lists app with their normal 365 login. An Azure Function in the office's own Azure subscription checks for the new bulletin daily, writes each client's status back into the list, and sends alerts once per bulletin. Nothing runs on an office PC and no data leaves the office's tenant and subscription.

Cost on the Azure Functions Consumption plan is typically zero to a few dollars a month at this volume.

## 1. Register the app (needs a Global Admin, about 10 minutes)

1. **entra.microsoft.com → Applications → App registrations → New registration.** Name it `Priority Date Tracker`, single tenant.
2. Copy the **Application (client) ID** and **Directory (tenant) ID** into the office's config under `microsoft365`.
3. **Certificates & secrets → New client secret.** Save the value in a password manager. It goes in an app setting or Key Vault, never in the config file.
4. **API permissions → Microsoft Graph → Application permissions**, then **Grant admin consent**:

| Permission | Used for |
|---|---|
| `Sites.Selected` (recommended) or `Sites.ReadWrite.All` | reading and updating the two lists |
| `Mail.Send` | alert emails (optional) |

With `Sites.Selected`, grant the app write access to just the one site ([how](https://learn.microsoft.com/graph/api/site-post-permissions)). Limit `Mail.Send` to the sender mailbox with an [application access policy](https://learn.microsoft.com/graph/auth-limit-mailbox-access).

## 2. Create the lists

Pick a SharePoint site that only case staff can open, put its hostname and path in the config, set `storage.backend: sharepoint`, then from any machine with the package installed:

```
pip install '.[m365]'
export PDTRACKER_CLIENT_SECRET='...'
pdtrack -c config/myoffice.yaml provision-sharepoint
```

This creates **Priority Dates** (one row per client) and **Visa Bulletins** (one row per month, used by the tracker). Also create the folder named in `microsoft365.bulletin_folder` (default `Visa Bulletin PDFs`) in the site's Documents library: staff can drop a bulletin PDF there and the next daily check picks it up. Re-running it is safe. Staff fill in Title (client name), Category, Chargeability and PriorityDate; the other columns are optional. The tracker fills in FinalActionStatus, FilingStatus and StatusMonth, so the list doubles as the dashboard. Add a view grouped by FinalActionStatus if that helps.

Existing clients can be loaded once from a CSV with `pdtrack -c config/myoffice.yaml import clients.csv`.

## 3. Deploy the function

Needs the Azure CLI and Azure Functions Core Tools.

```
az group create -n pdtracker-rg -l eastus
az storage account create -n <uniquestorage> -g pdtracker-rg -l eastus --sku Standard_LRS
az functionapp create -n <unique-app-name> -g pdtracker-rg --storage-account <uniquestorage> \
  --consumption-plan-location eastus --runtime python --runtime-version 3.11 --functions-version 4 --os-type linux

az functionapp config appsettings set -n <unique-app-name> -g pdtracker-rg --settings \
  "PDTRACKER_SCHEDULE=0 0 14 * * *" \
  "PDTRACKER_CONFIG_YAML=$(cat config/myoffice.yaml)" \
  "PDTRACKER_CLIENT_SECRET=<secret or @Microsoft.KeyVault(...) reference>"

cd cloud/azure-function
./build.sh
func azure functionapp publish <unique-app-name> --python
```

`PDTRACKER_SCHEDULE` is a six-field cron in UTC; the example runs daily at 14:00 UTC. The bulletin usually comes out mid-month, and the tracker only alerts once per bulletin. Each run first looks in the SharePoint drop folder, then at travel.state.gov. If next month's bulletin isn't in by `bulletin.reminder_day`, the run emails the office asking someone to drop the PDF in the folder.

## 4. Endpoints

All need the function key (`?code=...` or the `x-functions-key` header). Get it with `az functionapp keys list`.

| Call | What it does |
|---|---|
| `POST /api/check` | run the check now. Body (optional): `{"force": true}` or `{"month": "2026-12"}` |
| `GET /api/status` | every active client's status against the newest bulletin, as JSON |
| `POST /api/bulletin` | add a bulletin: the PDF itself (`Content-Type: application/pdf`, checked right away) or the JSON from `pdtrack bulletin template`, which can also record the USCIS chart choice |

A Power Automate flow or a Teams button can call these.

## Updating an office

Edit the YAML, then update the `PDTRACKER_CONFIG_YAML` app setting. To update the code, run `build.sh` and publish again.
