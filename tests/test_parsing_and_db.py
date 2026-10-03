import importlib

import pytest

from ecourts_calendar import config, scraper


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cases.db")
    from ecourts_calendar import db as dbmod
    return importlib.reload(dbmod)


@pytest.mark.parametrize("text,expected", [
    ("15-10-2026", "2026-10-15"), ("5/1/2027", "2027-01-05"), ("2026-12-03", "2026-12-03"),
    ("07 Nov 2026", "2026-11-07"), ("07-November-2026", "2026-11-07"), ("", None), ("Disposed", None),
    ("31-02-2026", None),
])
def test_parse_date(text, expected):
    assert scraper.parse_date(text) == expected


def test_parse_table_maps_columns_and_groups():
    headers = ["Sr No", "CNR Number", "Case Type/Case No/Year", "Petitioner vs Respondent", "Court Name", "Next Hearing Date", "Stage"]
    rows = [
        ["Hyderabad"],
        ["1", "TSHY010012342024", "OS/12/2024", "A vs B", "I Addl Junior Civil Judge", "15-10-2026", "Evidence"],
        ["Ranga Reddy"],
        ["2", "TSRR020045672023", "CC/45/2023", "State vs C", "II Metropolitan Magistrate", "16/10/2026", "Hearing"],
    ]
    cases = scraper.parse_table(headers, rows)
    assert len(cases) == 2
    first = cases[0]
    assert first["cnr"] == "TSHY010012342024"
    assert first["case_no"] == "OS/12/2024"
    assert first["parties"] == "A vs B"
    assert first["court"] == "I Addl Junior Civil Judge"
    assert first["next_date"] == "2026-10-15"
    assert first["stage"] == "Evidence"
    assert first["district"] == "Hyderabad"
    assert cases[1]["district"] == "Ranga Reddy"


def _case(date, cnr="TSHY010012342024"):
    return {"cnr": cnr, "case_no": "OS/12/2024", "court": "Court 1", "district": "Hyderabad", "next_date": date}


def test_manual_override_reset_when_portal_changes(db, monkeypatch):
    monkeypatch.setattr(config, "MANUAL_OVERRIDE_POLICY", "reset")
    assert db.upsert_cases([_case("2026-10-15")])["new"] == 1
    cid = db.list_cases()[0]["id"]
    db.set_manual_date(cid, "2026-10-20", "told by clerk")
    assert db.list_cases()[0]["effective_date"] == "2026-10-20"

    db.upsert_cases([_case("2026-10-15")])  # portal unchanged -> manual stays
    assert db.list_cases()[0]["effective_date"] == "2026-10-20"

    s = db.upsert_cases([_case("2026-11-01")])  # portal posts a new date -> it wins
    assert s["overrides_reset"] == 1
    c = db.list_cases()[0]
    assert c["effective_date"] == "2026-11-01" and c["manual_date"] is None
    assert len(db.case_history(cid)) == 4


def test_manual_override_keep_policy(db, monkeypatch):
    monkeypatch.setattr(config, "MANUAL_OVERRIDE_POLICY", "keep")
    db.upsert_cases([_case("2026-10-15")])
    cid = db.list_cases()[0]["id"]
    db.set_manual_date(cid, "2026-10-20")
    db.upsert_cases([_case("2026-11-01")])
    assert db.list_cases()[0]["effective_date"] == "2026-10-20"
    db.set_manual_date(cid, None)
    assert db.list_cases()[0]["effective_date"] == "2026-11-01"


def test_missing_case_marked_closed(db):
    db.upsert_cases([_case("2026-10-15"), _case("2026-10-16", cnr="TSRR020045672023")])
    s = db.upsert_cases([_case("2026-10-15")])
    assert s["closed"] == 1
    assert len(db.list_cases()) == 1 and len(db.list_cases(include_inactive=True)) == 2
