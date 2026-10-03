"""SQLite storage for cases, manual date overrides, date history and sync runs."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY,
    case_key TEXT UNIQUE NOT NULL,
    cnr TEXT,
    case_no TEXT,
    parties TEXT,
    district TEXT,
    court TEXT,
    establishment TEXT,
    stage TEXT,
    scraped_date TEXT,          -- next hearing date from the portal (YYYY-MM-DD)
    manual_date TEXT,           -- your override (YYYY-MM-DD), wins over scraped_date
    manual_note TEXT,
    manual_updated_at TEXT,
    raw_json TEXT,
    first_seen TEXT,
    last_seen TEXT,
    active INTEGER DEFAULT 1    -- 0 when the case no longer appears in My Cases
);
CREATE TABLE IF NOT EXISTS date_history (
    id INTEGER PRIMARY KEY,
    case_id INTEGER REFERENCES cases(id),
    old_date TEXT,
    new_date TEXT,
    source TEXT,                -- 'portal' or 'manual'
    note TEXT,
    changed_at TEXT
);
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    status TEXT,                -- running / ok / failed
    cases_found INTEGER,
    message TEXT
);
"""

FIELDS = ("cnr", "case_no", "parties", "district", "court", "establishment", "stage")


def now():
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def case_key(case):
    """Stable identity for a case: CNR when present, else case no + court."""
    if case.get("cnr"):
        return case["cnr"].strip().upper()
    return "|".join((case.get(f) or "").strip().lower() for f in ("case_no", "district", "court"))


def upsert_cases(cases):
    """Store a fresh scrape. Returns a summary of what changed."""
    summary = {"new": 0, "date_changed": 0, "unchanged": 0, "closed": 0, "overrides_reset": 0}
    seen = set()
    ts = now()
    with connect() as conn:
        for case in cases:
            key = case_key(case)
            if not key.strip("|") or key in seen:
                continue
            seen.add(key)
            row = conn.execute("SELECT * FROM cases WHERE case_key=?", (key,)).fetchone()
            values = {f: case.get(f) for f in FIELDS}
            new_date = case.get("next_date")
            raw = json.dumps(case.get("raw", {}), ensure_ascii=False)
            if row is None:
                cur = conn.execute(
                    f"INSERT INTO cases (case_key, {', '.join(FIELDS)}, scraped_date, raw_json, first_seen, last_seen, active)"
                    f" VALUES (?, {', '.join('?' * len(FIELDS))}, ?, ?, ?, ?, 1)",
                    (key, *values.values(), new_date, raw, ts, ts),
                )
                conn.execute(
                    "INSERT INTO date_history (case_id, old_date, new_date, source, changed_at) VALUES (?, NULL, ?, 'portal', ?)",
                    (cur.lastrowid, new_date, ts),
                )
                summary["new"] += 1
                continue

            manual_date, manual_note = row["manual_date"], row["manual_note"]
            if new_date != row["scraped_date"]:
                summary["date_changed"] += 1
                conn.execute(
                    "INSERT INTO date_history (case_id, old_date, new_date, source, changed_at) VALUES (?, ?, ?, 'portal', ?)",
                    (row["id"], row["scraped_date"], new_date, ts),
                )
                if manual_date and config.MANUAL_OVERRIDE_POLICY == "reset":
                    conn.execute(
                        "INSERT INTO date_history (case_id, old_date, new_date, source, note, changed_at)"
                        " VALUES (?, ?, ?, 'manual', 'manual date cleared: portal posted a new date', ?)",
                        (row["id"], manual_date, new_date, ts),
                    )
                    manual_date = manual_note = None
                    summary["overrides_reset"] += 1
            else:
                summary["unchanged"] += 1
            conn.execute(
                f"UPDATE cases SET {', '.join(f + '=?' for f in FIELDS)}, scraped_date=?, manual_date=?, manual_note=?,"
                " raw_json=?, last_seen=?, active=1 WHERE id=?",
                (*values.values(), new_date, manual_date, manual_note, raw, ts, row["id"]),
            )

        # Cases that disappeared from My Cases (disposed / transferred) are kept but marked inactive.
        if seen:
            placeholders = ",".join("?" * len(seen))
            cur = conn.execute(
                f"UPDATE cases SET active=0 WHERE active=1 AND case_key NOT IN ({placeholders})", tuple(seen)
            )
            summary["closed"] = cur.rowcount
    return summary


def set_manual_date(case_id, date, note=None):
    """Set (or clear, with date=None) your own date for a case."""
    ts = now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise KeyError(case_id)
        old = row["manual_date"] or row["scraped_date"]
        conn.execute(
            "UPDATE cases SET manual_date=?, manual_note=?, manual_updated_at=? WHERE id=?",
            (date or None, (note or None) if date else None, ts if date else None, case_id),
        )
        conn.execute(
            "INSERT INTO date_history (case_id, old_date, new_date, source, note, changed_at) VALUES (?, ?, ?, 'manual', ?, ?)",
            (case_id, old, date or row["scraped_date"], note or ("override cleared" if not date else None), ts),
        )


def list_cases(include_inactive=False):
    with connect() as conn:
        sql = "SELECT *, COALESCE(manual_date, scraped_date) AS effective_date FROM cases"
        if not include_inactive:
            sql += " WHERE active=1"
        sql += " ORDER BY effective_date IS NULL, effective_date, district, court"
        return [dict(r) for r in conn.execute(sql)]


def case_history(case_id):
    with connect() as conn:
        return [
            dict(r)
            for r in conn.execute("SELECT * FROM date_history WHERE case_id=? ORDER BY id DESC", (case_id,))
        ]


def start_run():
    with connect() as conn:
        return conn.execute("INSERT INTO sync_runs (started_at, status) VALUES (?, 'running')", (now(),)).lastrowid


def finish_run(run_id, status, cases_found=None, message=None):
    with connect() as conn:
        conn.execute(
            "UPDATE sync_runs SET finished_at=?, status=?, cases_found=?, message=? WHERE id=?",
            (now(), status, cases_found, message, run_id),
        )


def recent_runs(limit=10):
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?", (limit,))]
