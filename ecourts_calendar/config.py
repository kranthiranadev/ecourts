import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
DEBUG_DIR = DATA_DIR / "debug"
DB_PATH = DATA_DIR / "cases.db"


def _bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


URL = os.getenv("ECOURTS_URL", "https://filing.ecourts.gov.in/pdedev/")
STATE = os.getenv("ECOURTS_STATE", "Telangana")
MOBILE = os.getenv("ECOURTS_MOBILE", "")
PASSWORD = os.getenv("ECOURTS_PASSWORD", "")
COURT_OPTION = os.getenv("ECOURTS_COURT_OPTION", "District Court")

CAPTCHA_MODE = os.getenv("CAPTCHA_MODE", "auto").lower()
LOGIN_ATTEMPTS = int(os.getenv("LOGIN_ATTEMPTS", "3"))

SYNC_HOUR = int(os.getenv("SYNC_HOUR", "19"))
SYNC_MINUTE = int(os.getenv("SYNC_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
MANUAL_OVERRIDE_POLICY = os.getenv("MANUAL_OVERRIDE_POLICY", "reset").lower()

HEADLESS = _bool("HEADLESS", True)
CHROMIUM_PATH = os.getenv("CHROMIUM_PATH") or None  # only if not using `playwright install chromium`

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "5000"))
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
