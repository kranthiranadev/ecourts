"""CLI: python -m ecourts_calendar [serve|sync|list]"""
import argparse

from . import config, db


def main():
    parser = argparse.ArgumentParser(prog="ecourts_calendar")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the calendar web app + daily scheduler (default)")
    sub.add_parser("sync", help="run one sync now (use this from cron / Task Scheduler)")
    sub.add_parser("list", help="print upcoming cases")
    args = parser.parse_args()

    if args.cmd == "sync":
        from . import captcha
        from .sync import run_sync
        captcha.INTERACTIVE = True
        raise SystemExit(0 if run_sync() is not None else 1)
    if args.cmd == "list":
        for c in db.list_cases():
            flag = " (manual)" if c["manual_date"] else ""
            print(f"{c['effective_date'] or '----------'}{flag}  {c['case_no'] or c['cnr']}  "
                  f"{c['district'] or ''} / {c['court'] or ''}  {c['parties'] or ''}")
        return
    from .app import create_app, start_scheduler
    start_scheduler()
    print(f"Calendar on http://{config.APP_HOST}:{config.APP_PORT}  "
          f"(daily sync at {config.SYNC_HOUR:02d}:{config.SYNC_MINUTE:02d} {config.TIMEZONE})")
    create_app().run(host=config.APP_HOST, port=config.APP_PORT, use_reloader=False)


if __name__ == "__main__":
    main()
