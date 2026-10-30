# Getting started with the Priority Date Tracker on Windows

The Priority Date Tracker shows where each client stands in the green card line, using the monthly Visa Bulletin. It runs on your own computer. Your clients' information is saved on this computer only.

You don't need to know anything about computers or programming to use it. Follow the steps below in order. Setting it up takes about 10 minutes, and you only do it once.

---

## Part 1. Install it (one time)

1. **Download the installer.** Click this link:
   **[Download the Priority Date Tracker](https://github.com/notevenmex/priority-date-tracker/releases/latest/download/PriorityDateTracker-Setup.exe)**
   Your web browser saves a file called **PriorityDateTracker-Setup.exe**, usually in your **Downloads** folder.

2. **Open the file you downloaded.** In most browsers, a small box shows the download at the top right or bottom of the window. Click it. If you can't find it, open the **Downloads** folder (press the Windows key, type **Downloads**, and press Enter) and double-click **PriorityDateTracker-Setup**.

3. **If a blue box says "Windows protected your PC":** this is normal for a new program that doesn't come from a big software company. Click **More info**, then click **Run anyway**.
   If instead you see a message that your organization has blocked the program, stop here and ask the person who looks after your office computers.

4. **Click through the installer.** Click **Next**, then **Install**, then **Finish**. Leave the box **Open the Priority Date Tracker now** checked. You won't be asked for a password.

---

## Part 2. The first time it opens

1. **A black window opens** and asks for your office's name. Type it (for example, *Rivera Immigration Law*) and press the **Enter** key.

2. **Your web browser opens the tracker.** It looks like a website, but it is running on your computer. The address at the top says `localhost:8765`, which means "this computer".

3. **Leave the black window open while you work.** You can make it smaller by clicking the **–** button at its top right, so it waits at the bottom of the screen. Closing the black window turns the tracker off. That's fine when you're done for the day.

---

## Part 3. Put your clients in

Choose one way. You can also mix them.

**From Docketwise (fastest).**

1. In Docketwise, go to **Reports**, then **Matter Reports**.
2. Add these columns to the report: **applicant**, **preference_category**, **priority_date** and **final_action_date_status**.
3. Export the report. Docketwise saves a file ending in **.csv** in your **Downloads** folder.
4. In the tracker, click **Import clients** at the top.
5. Under **Upload a Docketwise matters export**, click **Choose File**, pick the file you just saved, and click **Read the export**.
6. If some clients are missing information (for example, a country), the page lists them so you can fill them in. Click **Save the completed rows** when you're done.

Do this again whenever you want to bring in new cases. Clients already in the tracker are updated, not doubled.

**By hand.** On the **Dashboard**, scroll to the bottom and click **Add a client**. Fill in what you know and click **Save client**. Every box is optional, so you can save someone with only a name and finish later. Until a client has a priority date, a category and a chargeability country, the tracker lists them as **Needs details** instead of checking them against the bulletin. To finish one, click their name.

---

## Part 4. Get this month's Visa Bulletin

1. On the **Dashboard**, click **Check for a new bulletin**. The tracker downloads the bulletin from the State Department website and compares it with last month.
2. If it says it couldn't get the bulletin, download the PDF yourself from [travel.state.gov](https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html). Then click **Enter a bulletin** at the top, and under **Upload the bulletin PDF** click **Choose File**, pick the PDF, and click **Upload and check**.

The new bulletin usually comes out in the middle of each month. From the 20th, the tracker shows a yellow reminder at the top until next month's bulletin is in.

---

## Every day after that

**Double-click the Priority Date Tracker icon** on your desktop (a blue calendar with a green check mark). You can also find it by pressing the Windows key and typing **Priority Date Tracker**.

If the tracker is already open, double-clicking the icon just shows it again in your browser.

---

## Getting a new version

When a new version is out, a box at the top of the **Dashboard** says so. To update:

1. Click **Download the update** in that box.
2. Open the file you downloaded and click through it, just like the first time you installed it (Part 1). If Windows shows the blue "Windows protected your PC" box again, click **More info**, then **Run anyway**.
3. If the tracker was open, the installer closes it for you. When the installer finishes, the tracker opens again with the new version.

Updating never touches your clients, bulletins or settings. They stay in your Documents folder.

---

## Want to practice first?

Press the Windows key, type **Priority Date Tracker**, and open **Priority Date Tracker - practice with sample data**. It opens the tracker with made-up clients. Nothing there is real, so you can click anything. Close its black window when you're done.

---

## Where your information is kept

Everything is in a folder called **Priority Date Tracker** inside your **Documents** folder. To open it, press the Windows key, type **Priority Date Tracker - office files**, and press Enter.

- **To back it up,** copy that whole folder somewhere safe, such as OneDrive.
- **Uninstalling** the tracker does not delete this folder.
- **Each computer keeps its own list.** To move to a new computer, install the tracker there, then copy this folder into that computer's **Documents** folder.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| The browser didn't open | Open your web browser yourself and type **localhost:8765** in the address bar at the top, then press Enter. |
| "This site can't be reached" | The black window was closed. Double-click the Priority Date Tracker icon again. |
| The black window says "Something went wrong" | Take a picture of the window (or press the Windows key + Shift + S) and send it to whoever set up the tracker. |
| The page says "Expired form" | Click your browser's refresh button and try again. |
| Windows says the program is blocked | Ask the person who looks after your office computers. Show them this guide. |

---

## For the person setting it up

- **No installer allowed?** Download [PriorityDateTracker-NoInstall.zip](https://github.com/notevenmex/priority-date-tracker/releases/latest/download/PriorityDateTracker-NoInstall.zip), unzip it anywhere, and double-click `PriorityDateTracker.exe` inside.
- **Settings.** The first run writes `office.yaml` in the office folder. Every option is explained in [config/office.example.yaml](../config/office.example.yaml), such as email alerts through Microsoft 365 or the column names of another case system's export.
- **Setting up many computers.** These environment variables skip or change the first-run steps: `PDTRACKER_OFFICE_NAME` (no name question), `PDTRACKER_HOME` (use another folder, for example a synced one) and `PDTRACKER_PORT` (another port than 8765, when two offices share a computer).
- **Automatic daily check.** `PriorityDateTracker.exe check` runs the same check as the button, without opening anything. To run it every morning, open the Command Prompt and paste:
  `schtasks /Create /SC DAILY /ST 09:00 /TN "Priority date check" /TR "\"%LOCALAPPDATA%\Programs\Priority Date Tracker\PriorityDateTracker.exe\" check"`
- **Publishing an update.** Raise `__version__` in `pdtracker/__init__.py` and merge to main. GitHub builds the new installer and publishes it as the newest release. Each installed copy checks for a newer release when it opens and shows the download box. Installing it over the old copy keeps the office folder. Set `PDTRACKER_UPDATE_URL` to another GitHub `releases/latest` API address to follow your own copy of the project, or to `off` to turn the check off. Version 0.1.0 had no update check, so a computer that installed 0.1.0 needs the newer installer run on it once by hand.
- **Several staff sharing one client list** need the cloud version instead. See [cloud.md](cloud.md).
- **Building it yourself.** GitHub builds the installer on every change (`.github/workflows/windows-app.yml`) and publishes it to the newest release. To build by hand on Windows: `pip install . pyinstaller`, `pyinstaller packaging/windows/pdtracker.spec`, then compile `packaging/windows/installer.iss` with Inno Setup.
