"""Tests der Trading Time API. Start: python -m pytest -q"""
from fastapi.testclient import TestClient

from app import app

c = TestClient(app)


def get(path, **params):
    r = c.get(path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_settlement_us_t1_over_thanksgiving():
    r = get("/v1/settlement-date", market="XNYS", trade_date="2026-11-25")
    assert r["cycle"] == "T+1" and r["settlement_date"] == "2026-11-27"


def test_settlement_six_t2_over_christmas():
    r = get("/v1/settlement-date", market="XSWX", trade_date="2026-12-23")
    assert r["cycle"] == "T+2" and r["settlement_date"] == "2026-12-29"


def test_settlement_eu_switch_to_t1_2027():
    before = get("/v1/settlement-date", market="XETR", trade_date="2027-10-08")
    after = get("/v1/settlement-date", market="XETR", trade_date="2027-10-11")
    assert before["cycle"] == "T+2" and after["cycle"] == "T+1"
    assert after["settlement_date"] == "2027-10-12"


def test_settlement_rejects_holiday():
    assert c.get("/v1/settlement-date", params={"market": "XNYS", "trade_date": "2026-11-26"}).status_code == 400


def test_fx_london_tokyo_overlap():
    r = get("/v1/fx-sessions", at="2026-10-21T08:30:00Z")
    assert r["fx_market_open"] and set(r["open_sessions"]) == {"Tokyo", "London"} and r["overlap"]


def test_fx_closed_on_saturday():
    r = get("/v1/fx-sessions", at="2026-10-24T12:00:00Z")
    assert r["fx_market_open"] is False and r["open_sessions"] == []


def test_dst_gaps_2027_us_eu():
    r = get("/v1/dst-gap", year=2027, pair="US-EU")
    assert r["normal_difference_hours"] == 6
    g = r["gap_periods"]
    assert g[0]["from"] == "2027-03-14" and g[0]["to"] == "2027-03-27"
    assert g[1]["from"] == "2027-10-31" and g[1]["to"] == "2027-11-06"


def test_is_dst_gap():
    assert get("/v1/is-dst-gap", at="2027-03-20T12:00:00Z")["is_gap"] is True
    assert get("/v1/is-dst-gap", at="2027-05-20T12:00:00Z")["is_gap"] is False


def test_countdown():
    r = get("/v1/countdown", markets="XNYS,XETR", at="2026-10-19T12:00:00Z")
    m = {x["market"]: x for x in r["markets"]}
    assert m["XETR"]["is_open"] and not m["XNYS"]["is_open"]
    assert m["XNYS"]["seconds_to_next_open"] == 5400


def test_errors():
    assert c.get("/v1/countdown", params={"markets": "FOO"}).status_code == 404
    assert c.get("/v1/dst-gap", params={"year": 2027, "pair": "XX"}).status_code == 400
