"""HTTP-API: Trading Time API (Abwicklung, Forex-Sessions, Zeitumstellung, Countdown)."""
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

import engine
import time_engine as te

app = FastAPI(
    title="Trading Time API",
    version="0.1.0",
    description=("Settlement dates (T+1/T+2), forex session clock, daylight-saving gap weeks between the US "
                 "and Europe, and a multi-market open/close countdown. Computed from exchange calendars and "
                 "IANA time zones. Every response names its source."),
)


def _run(fn, *args):
    try:
        return fn(*args)
    except engine.UnknownMarket as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v1/markets", summary="Supported markets")
def markets():
    return engine.list_markets()


@app.get("/v1/settlement-date", summary="Settlement date of a stock trade (T+1/T+2, holiday-aware)")
def settlement(market: str = Query(..., examples=["XNYS"]), trade_date: str = Query(..., examples=["2026-11-25"])):
    return _run(te.settlement_date, market, trade_date)


@app.get("/v1/fx-sessions", summary="Which forex sessions are open, overlaps, next opens")
def fx(at: Optional[datetime] = Query(None, description="ISO time with offset; default now")):
    return _run(te.fx_sessions, at)


@app.get("/v1/dst-gap", summary="Weeks in a year when US/Europe clock differences shift")
def dst_gap(year: int = Query(..., examples=[2027]), pair: str = Query("US-EU", examples=["US-CH"])):
    return _run(te.dst_gaps, year, pair)


@app.get("/v1/is-dst-gap", summary="Is a time inside a daylight-saving gap?")
def is_gap(at: Optional[datetime] = None, pair: str = Query("US-EU")):
    return _run(te.is_dst_gap, at, pair)


@app.get("/v1/countdown", summary="Open/close countdown for several markets in one call")
def cd(markets: str = Query(..., examples=["XNYS,XETR,CME_EQUITY"]), at: Optional[datetime] = None):
    return _run(te.countdown, markets, at)


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True, "data": engine.DATA_VERSION}
