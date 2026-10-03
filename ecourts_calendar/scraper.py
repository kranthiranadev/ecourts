"""Logs in to the eCourts e-filing portal and reads the 'My Cases' list.

The portal's HTML could not be inspected while writing this, so every step uses
tolerant, label-based lookups and saves a screenshot + HTML to data/debug/ when
something can't be found. If a step fails, open those files and adjust the
selector lists below.
"""
import re
from datetime import date, datetime

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from . import captcha, config

# ---- selectors (edit these if the portal layout differs) -------------------
MOBILE_INPUTS = [
    "input[name*='mobile' i]", "input[id*='mobile' i]", "input[placeholder*='mobile' i]",
    "input[name*='phone' i]", "input[id*='phone' i]", "input[placeholder*='phone' i]",
    "input[name*='user' i]", "input[id*='user' i]", "input[type='tel']",
]
PASSWORD_INPUTS = ["input[type='password']"]
CAPTCHA_IMAGES = ["img[src*='captcha' i]", "img[id*='captcha' i]", "img[alt*='captcha' i]", "img[class*='captcha' i]"]
CAPTCHA_INPUTS = ["input[name*='captcha' i]", "input[id*='captcha' i]", "input[placeholder*='captcha' i]"]
SUBMIT_BUTTONS = [
    "button[type='submit']", "input[type='submit']",
    "button:has-text('Login')", "button:has-text('Sign in')", "a:has-text('Login')",
]
MY_CASES = re.compile(r"my\s*cases", re.I)
NEXT_PAGE = ["a.paginate_button.next:not(.disabled)", "li.next:not(.disabled) a", "a:has-text('Next')"]
# ----------------------------------------------------------------------------


class LoginError(Exception):
    pass


def _first_visible(page, selectors, timeout=0):
    for sel in selectors:
        loc = page.locator(sel)
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    return el
            except Exception:
                pass
    if timeout:
        page.wait_for_timeout(timeout)
        return _first_visible(page, selectors)
    return None


def _dump(page, name):
    """Save screenshot + HTML for troubleshooting."""
    config.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(config.DEBUG_DIR / f"{name}.png"), full_page=True)
        (config.DEBUG_DIR / f"{name}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


def _select_option_containing(page, text):
    """Pick the <select> option whose label contains `text`. Returns True if done."""
    return page.evaluate(
        """(text) => {
            for (const sel of document.querySelectorAll('select')) {
                for (const opt of sel.options) {
                    if (opt.text.trim().toLowerCase().includes(text.toLowerCase())) {
                        sel.value = opt.value;
                        sel.dispatchEvent(new Event('input', {bubbles: true}));
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                }
            }
            return false;
        }""",
        text,
    )


def _logged_in(page):
    return _first_visible(page, PASSWORD_INPUTS) is None or page.get_by_text(MY_CASES).count() > 0


def login(page, log):
    if not config.MOBILE or not config.PASSWORD:
        raise LoginError("ECOURTS_MOBILE / ECOURTS_PASSWORD are not set in .env")

    last_error = "unknown"
    for attempt in range(1, config.LOGIN_ATTEMPTS + 1):
        log(f"Login attempt {attempt}/{config.LOGIN_ATTEMPTS}")
        page.goto(config.URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=30000)

        if not _select_option_containing(page, config.STATE):
            log(f"  warning: no dropdown option '{config.STATE}' found on login page")
        page.wait_for_timeout(1000)  # state change may reload captcha / fields

        mobile = _first_visible(page, MOBILE_INPUTS, timeout=3000)
        password = _first_visible(page, PASSWORD_INPUTS)
        if not mobile or not password:
            _dump(page, "login_fields_not_found")
            raise LoginError("Could not find mobile/password fields (see data/debug/login_fields_not_found.*)")
        mobile.fill(config.MOBILE)
        password.fill(config.PASSWORD)

        img = _first_visible(page, CAPTCHA_IMAGES)
        box = _first_visible(page, CAPTCHA_INPUTS)
        if img and box:
            page.wait_for_timeout(500)
            text = captcha.solve(img.screenshot(), attempt)
            if not text:
                last_error = "captcha could not be read"
                log(f"  {last_error}")
                continue
            log(f"  captcha guess: {text}")
            box.fill(text)
        else:
            log("  no captcha found on page, submitting without it")

        submit = _first_visible(page, SUBMIT_BUTTONS)
        if submit:
            submit.click()
        else:
            password.press("Enter")
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PWTimeout:
            pass
        page.wait_for_timeout(1500)

        if _logged_in(page):
            log("  logged in")
            return
        if page.locator("input[name*='otp' i], input[id*='otp' i]").count():
            _dump(page, "otp_required")
            raise LoginError("Portal is asking for an OTP; this can't be automated")
        last_error = _page_error(page) or "login rejected (wrong captcha?)"
        log(f"  failed: {last_error}")
        _dump(page, f"login_failed_attempt{attempt}")

    raise LoginError(f"Login failed after {config.LOGIN_ATTEMPTS} attempts: {last_error}")


def _page_error(page):
    for sel in (".alert-danger", ".error", ".text-danger", "[role='alert']", ".swal2-html-container"):
        loc = page.locator(sel)
        for i in range(loc.count()):
            text = loc.nth(i).inner_text().strip()
            if text:
                return text[:200]
    return None


def open_my_cases(page, log):
    # Close any post-login popup/modal that blocks clicks.
    for sel in (".modal.show .close", ".modal.show button:has-text('Close')", ".swal2-confirm"):
        if page.locator(sel).count():
            try:
                page.locator(sel).first.click(timeout=2000)
            except Exception:
                pass

    opt = re.compile(re.escape(config.COURT_OPTION), re.I)
    target = page.get_by_role("link", name=opt).or_(page.get_by_role("button", name=opt)).or_(page.get_by_text(opt))
    if target.count():
        log(f"Selecting '{config.COURT_OPTION}'")
        target.first.click()
        page.wait_for_load_state("networkidle", timeout=30000)
    elif _select_option_containing(page, config.COURT_OPTION):
        log(f"Selected '{config.COURT_OPTION}' from dropdown")
        page.wait_for_load_state("networkidle", timeout=30000)
    else:
        log(f"  warning: '{config.COURT_OPTION}' option not found, continuing")

    link = page.get_by_role("link", name=MY_CASES).or_(page.get_by_text(MY_CASES))
    if not link.count():
        _dump(page, "my_cases_not_found")
        raise RuntimeError("Could not find 'My Cases' (see data/debug/my_cases_not_found.*)")
    log("Opening My Cases")
    link.first.click()
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_selector("table", timeout=60000)


_EXTRACT_JS = """() => {
    // Pick the biggest table on the page = the cases list.
    let best = null, bestRows = 0;
    for (const t of document.querySelectorAll('table')) {
        const n = t.querySelectorAll('tbody tr').length;
        if (n > bestRows) { best = t; bestRows = n; }
    }
    if (!best) return {headers: [], rows: []};
    let headers = [...best.querySelectorAll('thead th')].map(th => th.innerText.trim());
    if (!headers.length) {
        const first = best.querySelector('tr');
        headers = first ? [...first.children].map(c => c.innerText.trim()) : [];
    }
    const rows = [...best.querySelectorAll('tbody tr')].map(tr => [...tr.children].map(td => td.innerText.trim()));
    return {headers, rows};
}"""


def read_all_pages(page, log):
    # DataTables: try to show all rows on one page.
    for sel in ("select[name$='_length']", ".dataTables_length select"):
        if page.locator(sel).count():
            page.evaluate(
                """(sel) => { const s = document.querySelector(sel);
                    const best = [...s.options].sort((a, b) => (+b.value === -1 ? 1e9 : +b.value) - (+a.value === -1 ? 1e9 : +a.value))[0];
                    s.value = best.value; s.dispatchEvent(new Event('change', {bubbles: true})); }""",
                sel,
            )
            page.wait_for_timeout(1500)
            break

    cases, seen_pages = [], set()
    for _ in range(200):
        data = page.evaluate(_EXTRACT_JS)
        fingerprint = str(data["rows"][:3])
        if fingerprint in seen_pages:
            break
        seen_pages.add(fingerprint)
        cases.extend(parse_table(data["headers"], data["rows"]))
        nxt = _first_visible(page, NEXT_PAGE)
        if not nxt:
            break
        nxt.click()
        page.wait_for_timeout(1500)
    log(f"Read {len(cases)} cases")
    return cases


# ---- parsing (pure functions, unit-tested) ---------------------------------

# Order matters: the first field whose keywords match a header claims that column.
COLUMN_KEYWORDS = [
    ("cnr", ("cnr",)),
    ("next_date", ("next date", "next hearing", "hearing date", "listing date", "date of listing", "ndoh", "next")),
    ("district", ("district",)),
    ("establishment", ("establishment",)),
    ("stage", ("stage", "status", "purpose")),
    ("parties", ("part", "petitioner", "litigant", "title", " vs", "v/s")),
    ("court", ("court", "judge", "bench")),
    ("case_no", ("case no", "case number", "case", "filing no", "efiling", "e-filing")),
]

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(text):
    """Return YYYY-MM-DD for common Indian date formats, else None."""
    if not text:
        return None
    text = text.strip()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
        if m:
            d, mo, y = map(int, m.groups())
        else:
            m = re.search(r"(\d{1,2})[\s-]*([A-Za-z]{3})[A-Za-z]*[\s,-]*(\d{4})", text)
            if not m or m.group(2).lower() not in _MONTHS:
                return None
            d, mo, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def map_columns(headers):
    mapping = {}
    norm = [" " + re.sub(r"\s+", " ", h).strip().lower() for h in headers]
    for field, keywords in COLUMN_KEYWORDS:
        for i, h in enumerate(norm):
            if i in mapping.values():
                continue
            if any(k in h for k in keywords):
                mapping[field] = i
                break
    if "next_date" not in mapping:  # fall back to any column mentioning 'date'
        for i, h in enumerate(norm):
            if "date" in h and i not in mapping.values():
                mapping["next_date"] = i
                break
    return mapping


def parse_table(headers, rows):
    mapping = map_columns(headers)
    cases, group = [], None
    for cells in rows:
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        # A single-cell row (colspan) is a group heading, e.g. a district or court name.
        if len([c for c in cells if c]) == 1 and len(cells) < max(len(headers), 2):
            group = next(c for c in cells if c)
            continue
        if len(cells) == 1 and "no data" in cells[0].lower():
            continue
        case = {f: (cells[i] if i < len(cells) else None) or None for f, i in mapping.items()}
        case["next_date"] = parse_date(case.get("next_date"))
        if case.get("cnr"):
            case["cnr"] = case["cnr"].split()[0]
        if group and not case.get("district"):
            case["district"] = group
        case["raw"] = dict(zip(headers or [f"col{i}" for i in range(len(cells))], cells))
        if group:
            case["raw"]["_group"] = group
        cases.append(case)
    return cases


# ---- entry point -----------------------------------------------------------

def fetch_cases(log=print):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS, executable_path=config.CHROMIUM_PATH)
        context = browser.new_context(viewport={"width": 1366, "height": 900}, locale="en-IN",
                                      timezone_id=config.TIMEZONE)
        page = context.new_page()
        try:
            login(page, log)
            open_my_cases(page, log)
            cases = read_all_pages(page, log)
            _dump(page, "last_my_cases")
            return cases
        except Exception:
            _dump(page, f"error_{datetime.now():%Y%m%d_%H%M%S}")
            raise
        finally:
            browser.close()
