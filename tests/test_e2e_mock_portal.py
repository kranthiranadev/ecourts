"""Runs the real browser flow against a small fake portal (the real one is not reachable from CI)."""
import base64
import threading

import pytest
from werkzeug.serving import make_server

pytest.importorskip("playwright")
from flask import Flask, redirect, request  # noqa: E402

from ecourts_calendar import captcha, config, scraper  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
ROWS = [[str(i), f"TSHY0100{i:04d}2024", f"OS/{i}/2024", f"P{i} vs R{i}", f"Court {i % 3}", f"{10 + i % 15:02d}-11-2026"] for i in range(1, 16)]


def mock_portal():
    app, state = Flask(__name__), {"logged_in": False, "attempts": 0}

    @app.route("/pdedev/", methods=["GET", "POST"])
    def login():
        err = ""
        if request.method == "POST":
            state["attempts"] += 1
            f = request.form
            if f["state"] == "36" and f["mobile"] == "9000000000" and f["password"] == "pw" and f["captcha"] == "AB12":
                state["logged_in"] = True
                return redirect("/pdedev/home")
            err = '<div class="alert-danger">Invalid Captcha</div>'
        return f"""<form method=post>{err}
            <select name=state><option value=0>Select</option><option value=36>Telangana</option></select>
            <input name=mobile placeholder='Mobile Number'><input type=password name=password>
            <img id=captcha_image src='/cap.png' width=80 height=30><input name=captcha placeholder='Enter Captcha'>
            <button type=submit>Login</button></form>"""

    @app.get("/cap.png")
    def cap():
        return PNG, 200, {"Content-Type": "image/png"}

    @app.get("/pdedev/home")
    def home():
        return "<nav><a href='/pdedev/hc'>High Court</a> <a href='/pdedev/dc'>Telangana District Court</a></nav>"

    @app.get("/pdedev/dc")
    def dc():
        return "<nav><a href='/pdedev/mycases?page=1'>My Cases</a></nav>"

    @app.get("/pdedev/mycases")
    def mycases():
        page = int(request.args["page"])
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in ROWS[(page - 1) * 10: page * 10])
        nxt = f"<a href='/pdedev/mycases?page={page + 1}'>Next</a>" if page * 10 < len(ROWS) else ""
        return (f"<table><thead><tr><th>Sr</th><th>CNR No</th><th>Case No</th><th>Parties</th><th>Court</th>"
                f"<th>Next Date</th></tr></thead><tbody>{body}</tbody></table>{nxt}")

    return app, state


@pytest.fixture
def portal(monkeypatch, tmp_path):
    app, state = mock_portal()
    server = make_server("127.0.0.1", 0, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "URL", f"http://127.0.0.1:{server.server_port}/pdedev/")
    monkeypatch.setattr(config, "MOBILE", "9000000000")
    monkeypatch.setattr(config, "PASSWORD", "pw")
    monkeypatch.setattr(config, "COURT_OPTION", "Telangana District Court")
    monkeypatch.setattr(config, "DEBUG_DIR", tmp_path)
    yield state
    server.shutdown()


def test_full_flow_with_captcha_retry(portal, monkeypatch):
    guesses = iter(["WRONG", "AB12"])
    monkeypatch.setattr(captcha, "solve", lambda img, attempt: next(guesses))
    cases = scraper.fetch_cases(log=lambda m: None)
    assert portal["attempts"] == 2
    assert len(cases) == 15
    assert cases[0]["cnr"] == "TSHY010000012024" and cases[0]["next_date"] == "2026-11-11"


def test_gives_up_after_three_attempts(portal, monkeypatch):
    monkeypatch.setattr(captcha, "solve", lambda img, attempt: "WRONG")
    with pytest.raises(scraper.LoginError, match="Invalid Captcha"):
        scraper.fetch_cases(log=lambda m: None)
    assert portal["attempts"] == 3
