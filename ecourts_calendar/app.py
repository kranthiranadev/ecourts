"""Calendar web app + daily scheduler."""
import threading
from datetime import date, datetime, timedelta
from functools import wraps

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, Response, abort, jsonify, render_template, request

from . import config, db
from .sync import run_sync

scheduler = BackgroundScheduler(timezone=config.TIMEZONE)
RETRY_MINUTES = (20, 40)  # if the 7 PM run fails, try again 20 and 60 minutes later


def scheduled_sync(retry=0):
    if run_sync() is None and retry < len(RETRY_MINUTES):
        when = datetime.now(scheduler.timezone) + timedelta(minutes=RETRY_MINUTES[retry])
        scheduler.add_job(scheduled_sync, "date", run_date=when, args=[retry + 1], id=f"retry{retry + 1}",
                          replace_existing=True)


def start_scheduler():
    scheduler.add_job(
        scheduled_sync,
        CronTrigger(hour=config.SYNC_HOUR, minute=config.SYNC_MINUTE, timezone=config.TIMEZONE),
        id="daily_sync", replace_existing=True, misfire_grace_time=3 * 3600, coalesce=True,
    )
    scheduler.start()


def _requires_auth(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if config.APP_PASSWORD and not (auth and auth.password == config.APP_PASSWORD):
            return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="eCourts calendar"'})
        return view(*args, **kwargs)
    return wrapper


def _ics_escape(text):
    return (text or "").replace("\\", "\\\\").replace(";", "\;").replace(",", "\\,").replace("\n", "\\n")


def create_app():
    app = Flask(__name__)

    @app.get("/")
    @_requires_auth
    def index():
        return render_template("index.html")

    @app.get("/api/cases")
    @_requires_auth
    def cases():
        return jsonify(db.list_cases(include_inactive=request.args.get("all") == "1"))

    @app.post("/api/cases/<int:case_id>/date")
    @_requires_auth
    def set_date(case_id):
        body = request.get_json(force=True) or {}
        value = body.get("date") or None
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                abort(400, "date must be YYYY-MM-DD")
        try:
            db.set_manual_date(case_id, value, body.get("note"))
        except KeyError:
            abort(404)
        return jsonify(ok=True)

    @app.get("/api/cases/<int:case_id>/history")
    @_requires_auth
    def history(case_id):
        return jsonify(db.case_history(case_id))

    @app.post("/api/sync")
    @_requires_auth
    def sync_now():
        threading.Thread(target=run_sync, daemon=True).start()
        return jsonify(ok=True)

    @app.get("/api/status")
    @_requires_auth
    def status():
        job = scheduler.get_job("daily_sync") if scheduler.running else None
        return jsonify(runs=db.recent_runs(),
                       next_run=job.next_run_time.isoformat() if job and job.next_run_time else None,
                       policy=config.MANUAL_OVERRIDE_POLICY)

    @app.get("/calendar.ics")
    @_requires_auth
    def ics():
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ecourts-calendar//EN", "X-WR-CALNAME:My Court Cases"]
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        for c in db.list_cases():
            if not c["effective_date"]:
                continue
            d = date.fromisoformat(c["effective_date"])
            lines += [
                "BEGIN:VEVENT", f"UID:{c['id']}-{c['case_key']}@ecourts-calendar", f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
                f"SUMMARY:{_ics_escape((c['case_no'] or c['cnr'] or '') + ' - ' + (c['parties'] or ''))}",
                f"LOCATION:{_ics_escape(', '.join(x for x in (c['court'], c['district']) if x))}",
                f"DESCRIPTION:{_ics_escape('CNR: ' + (c['cnr'] or '-') + chr(10) + 'Stage: ' + (c['stage'] or '-') + (chr(10) + 'Manual date: ' + (c['manual_note'] or '') if c['manual_date'] else ''))}",
                "END:VEVENT",
            ]
        lines.append("END:VCALENDAR")
        return Response("\r\n".join(lines) + "\r\n", mimetype="text/calendar")

    return app
