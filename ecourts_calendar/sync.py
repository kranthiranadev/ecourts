"""One sync run: scrape the portal and store the results."""
import threading
import traceback

from . import db, scraper

_lock = threading.Lock()


def run_sync(log=print):
    if not _lock.acquire(blocking=False):
        log("A sync is already running")
        return None
    run_id = db.start_run()
    try:
        cases = scraper.fetch_cases(log=log)
        if not cases:
            # Don't mark every case closed because a page failed to render.
            raise RuntimeError("No cases found on My Cases page (see data/debug/last_my_cases.*)")
        summary = db.upsert_cases(cases)
        msg = ", ".join(f"{k}: {v}" for k, v in summary.items())
        db.finish_run(run_id, "ok", len(cases), msg)
        log(f"Sync done - {msg}")
        return summary
    except Exception as exc:
        log(traceback.format_exc())
        db.finish_run(run_id, "failed", None, f"{type(exc).__name__}: {exc}")
        return None
    finally:
        _lock.release()
