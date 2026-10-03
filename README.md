# eCourts Cases Calendar

Every day at **7 PM IST** this logs in to the eCourts e-filing portal
(<https://filing.ecourts.gov.in/pdedev/>), selects **Telangana → District Court**, opens **My Cases** and
saves every case's next hearing date into a local calendar. You can change any date by hand.

What you get:

- **Calendar view** (month / list) and **list view**, grouped by date, district or court, with filters and search.
- **Change date** on any case, or drag it to another day on the calendar. Your dates show in orange,
  with the portal's date underneath.
- **History** of every date change for each case, from the portal or from you.
- **Daily sync at 19:00 IST.** If it fails, it tries again 20 and 60 minutes later. There is also a **Sync now** button.
- **.ics export** (`/calendar.ics`) so you can import the dates into Google Calendar or your phone.
- Cases that drop off *My Cases* (disposed or transferred) are marked closed, not deleted.

## Setup (on your own PC or a server in India)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env                 # then put your mobile number and password in .env
```

`.env` is in `.gitignore`. **Never commit your password.**

### First run (do this once, with the browser visible)

```bash
HEADLESS=false python -m ecourts_calendar sync
```

You can watch the login. If the captcha OCR guesses wrong, the terminal shows the captcha image path
and asks you to type it. After the run, check `data/debug/last_my_cases.png`.

### Run the calendar and the daily schedule

```bash
python -m ecourts_calendar serve     # open http://127.0.0.1:5000
```

The 7 PM sync only runs while `serve` is running. To run it in the background:

- **Linux:** a systemd service or `@reboot` cron entry running `python -m ecourts_calendar serve`.
  You can also leave `serve` off and schedule only the sync: `0 19 * * * cd /path/to/ecourts && .venv/bin/python -m ecourts_calendar sync`
- **Windows:** in Task Scheduler, create a task that runs `.venv\Scripts\python.exe -m ecourts_calendar serve` at log-on.

Other commands: `python -m ecourts_calendar list` prints the upcoming dates in the terminal.

## Manual dates vs. portal dates

`MANUAL_OVERRIDE_POLICY` in `.env` decides what happens when you set a date by hand and the portal later posts a date:

| policy | portal date unchanged | portal posts a **new** date |
|---|---|---|
| `reset` (default) | your date stays | the portal's date replaces yours (yours is kept in history) |
| `keep` | your date stays | your date stays until you click "Use portal date" |

## When something breaks

Each failed step saves a screenshot and the page HTML to `data/debug/`. These files help:

- `login_fields_not_found.*`: the login form layout differs. Edit `MOBILE_INPUTS` etc. at the top of `ecourts_calendar/scraper.py`.
- `login_failed_attempt*.png`: shows the error the portal gave, usually a wrong captcha.
- `my_cases_not_found.*` or `last_my_cases.*`: the page after login.
- `otp_required.*`: the portal asked for an OTP, which can't be automated.

The sync status and its last error appear at the top of the web page.

## Tests

```bash
pip install pytest
python -m pytest tests
```

`tests/test_e2e_mock_portal.py` runs the whole browser flow against a fake portal. The fake portal
covers login, a wrong captcha with retry, the District Court link, My Cases and pagination.
