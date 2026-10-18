"""Rechen-Engine für Börsen-Handelszeiten und Feiertage.

Aktien: Sessions direkt aus der Open-Source-Bibliothek exchange_calendars.
Futures: Handelstage und verkürzte Tage aus exchange_calendars, die
Session-Zeiten aber aus eigenen Tabellen, weil die Bibliothek
Globex/T7-Nachtsessions nur vereinfacht abbildet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache

import exchange_calendars as xc
import pandas as pd

DATA_VERSION = f"exchange_calendars {xc.__version__}"


@dataclass(frozen=True)
class Market:
    code: str
    name: str
    kind: str          # "equity" | "futures"
    calendar: str      # exchange_calendars-Code für Handelstage
    tz: str
    note: str = ""


MARKETS: dict[str, Market] = {m.code: m for m in [
    Market("XNYS", "New York Stock Exchange", "equity", "XNYS", "America/New_York",
           "Regular session only (no pre-/post-market)."),
    Market("XNAS", "Nasdaq", "equity", "XNAS", "America/New_York",
           "Regular session only (no pre-/post-market)."),
    Market("XLON", "London Stock Exchange", "equity", "XLON", "Europe/London"),
    Market("XETR", "Xetra (Deutsche Börse)", "equity", "XETR", "Europe/Berlin"),
    Market("XSWX", "SIX Swiss Exchange", "equity", "XSWX", "Europe/Zurich"),
    Market("XTKS", "Japan Exchange Group (Tokyo)", "equity", "XTKS", "Asia/Tokyo",
           "Includes lunch break."),
    Market("XHKG", "Hong Kong Exchanges", "equity", "XHKG", "Asia/Hong_Kong",
           "Includes lunch break."),
    Market("XSHG", "Shanghai Stock Exchange", "equity", "XSHG", "Asia/Shanghai",
           "Includes lunch break."),
    Market("XASX", "Australian Securities Exchange", "equity", "XASX", "Australia/Sydney"),
    Market("CME_EQUITY", "CME Globex equity index futures (ES, NQ, MES, MNQ, YM, RTY)",
           "futures", "CMES", "America/Chicago",
           "Globex session 17:00-16:00 CT with daily halt 16:00-17:00 CT. "
           "Early-close times on holidays follow exchange_calendars and should be "
           "checked against the CME holiday calendar."),
    Market("EUREX_INDEX", "Eurex equity index futures (FDAX, FESX, FSMI)",
           "futures", "XEUR", "Europe/Berlin",
           "T7 trading hours 01:10-22:00 CET/CEST incl. Asian hours."),
]}

# Eigene Session-Zeiten für Futures (lokale Zeit)
FUTURES_HOURS = {
    # open am Vortag 17:00, close 16:00, Bibliotheks-Normalschluss 17:00
    "CME_EQUITY": dict(open=time(17, 0), open_prev_day=True, close=time(16, 0),
                       lib_normal_close=time(17, 0)),
    "EUREX_INDEX": dict(open=time(1, 10), open_prev_day=False, close=time(22, 0),
                        lib_normal_close=time(22, 0)),
}


class UnknownMarket(ValueError):
    pass


def get_market(code: str) -> Market:
    m = MARKETS.get(code.upper())
    if not m:
        raise UnknownMarket(f"Unknown market '{code}'. Known: {', '.join(MARKETS)}")
    return m


@lru_cache(maxsize=None)
def _calendar(code: str):
    return xc.get_calendar(code)


@lru_cache(maxsize=None)
def schedule(code: str) -> pd.DataFrame:
    """Session-Tabelle (UTC) mit Spalten open, break_start, break_end, close, early_close."""
    m = get_market(code)
    cal = _calendar(m.calendar)
    lib = cal.schedule.copy()
    lib_close_local = lib["close"].dt.tz_convert(m.tz)

    if m.kind == "equity":
        normal = lib_close_local.dt.time.mode().iloc[0]
        lib["early_close"] = lib_close_local.dt.time < normal
        return lib

    h = FUTURES_HOURS[m.code]
    rows = []
    for day, row in lib.iterrows():
        d = day.date()
        open_day = d - timedelta(days=1) if h["open_prev_day"] else d
        open_ts = pd.Timestamp(datetime.combine(open_day, h["open"])).tz_localize(m.tz)
        lib_close = row["close"].tz_convert(m.tz)
        early = lib_close.time() < h["lib_normal_close"]
        close_ts = lib_close if early else pd.Timestamp(
            datetime.combine(d, h["close"])).tz_localize(m.tz)
        rows.append((day, open_ts.tz_convert("UTC"), pd.NaT, pd.NaT,
                     close_ts.tz_convert("UTC"), early))
    df = pd.DataFrame(rows, columns=["session", "open", "break_start", "break_end",
                                     "close", "early_close"]).set_index("session")
    return df


def _bounds(code: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    s = schedule(code)
    return s["open"].iloc[0], s["close"].iloc[-1]


def _to_utc(at: datetime | None) -> pd.Timestamp:
    if at is None:
        return pd.Timestamp.now(tz="UTC")
    ts = pd.Timestamp(at)
    if ts.tzinfo is None:
        raise ValueError("Timestamp needs a timezone offset, e.g. 2026-11-26T15:00:00Z")
    return ts.tz_convert("UTC")


def _check_range(code: str, ts: pd.Timestamp):
    first, last = _bounds(code)
    if not (first <= ts <= last):
        raise ValueError(f"Time outside covered range {first.date()} .. {last.date()}")


def _fmt(ts, tz: str) -> dict | None:
    if ts is None or pd.isna(ts):
        return None
    return {"utc": ts.tz_convert("UTC").isoformat(), "local": ts.tz_convert(tz).isoformat()}


def status(code: str, at: datetime | None = None) -> dict:
    m = get_market(code)
    ts = _to_utc(at)
    _check_range(code, ts)
    s = schedule(code)
    # letzte Session, die vor ts geöffnet hat
    started = s[s["open"] <= ts]
    state, session = "closed", None
    if len(started):
        row = started.iloc[-1]
        session = started.index[-1]
        if ts < row["close"]:
            if pd.notna(row["break_start"]) and row["break_start"] <= ts < row["break_end"]:
                state = "break"
            else:
                state = "open"
    result = {
        "market": m.code,
        "name": m.name,
        "at": _fmt(ts, m.tz),
        "is_open": state == "open",
        "state": state,
        "timezone": m.tz,
    }
    if state != "closed":
        row = s.loc[session]
        result["session"] = {
            "trading_day": session.date().isoformat(),
            "open": _fmt(row["open"], m.tz),
            "close": _fmt(row["close"], m.tz),
            "early_close": bool(row["early_close"]),
        }
    result.update(next_events(code, at=ts))
    result["source"] = source(m)
    return result


def next_events(code: str, at: datetime | None = None) -> dict:
    m = get_market(code)
    ts = _to_utc(at)
    s = schedule(code)
    # Alle Öffnungs-/Schliesszeitpunkte inkl. Pausen
    opens = pd.concat([s["open"], s["break_end"].dropna()]).sort_values()
    closes = pd.concat([s["close"], s["break_start"].dropna()]).sort_values()
    nxt_open = opens[opens > ts]
    nxt_close = closes[closes > ts]
    return {
        "next_open": _fmt(nxt_open.iloc[0], m.tz) if len(nxt_open) else None,
        "next_close": _fmt(nxt_close.iloc[0], m.tz) if len(nxt_close) else None,
    }


def _holiday_names(m: Market) -> dict:
    cal = _calendar(m.calendar)
    names = {}
    try:
        hc = cal.regular_holidays
        if hc is not None:
            for d, n in hc.holidays(start="2000-01-01", end="2035-12-31",
                                    return_name=True).items():
                names[pd.Timestamp(d).date()] = n
    except Exception:
        pass
    return names


def holidays(code: str, start: str, end: str) -> dict:
    m = get_market(code)
    s = schedule(code)
    rng = pd.date_range(start, end, freq="D")
    if len(rng) > 800:
        raise ValueError("Range too long (max ~2 years)")
    first, last = s.index[0], s.index[-1]
    if rng[0] < first or rng[-1] > last:
        raise ValueError(f"Range outside covered range {first.date()} .. {last.date()}")
    names = _holiday_names(m)
    sessions = set(s.index)
    weekend = (5, 6) if m.code != "XTAE" else (4, 5)
    closed = [{"date": d.date().isoformat(), "name": names.get(d.date())}
              for d in rng if d.weekday() not in weekend and d not in sessions]
    early = [{"date": d.date().isoformat(), "close": _fmt(r["close"], m.tz)}
             for d, r in s.loc[rng[0]:rng[-1]].iterrows() if r["early_close"]]
    return {"market": m.code, "timezone": m.tz, "start": start, "end": end,
            "closed_days": closed, "early_closes": early, "source": source(m)}


def source(m: Market) -> dict:
    return {"data": DATA_VERSION,
            "session_hours": "exchange_calendars" if m.kind == "equity"
            else "own table (see note)",
            "note": m.note or None}


def list_markets() -> list[dict]:
    out = []
    for m in MARKETS.values():
        first, last = _bounds(m.code)
        out.append({"code": m.code, "name": m.name, "type": m.kind, "timezone": m.tz,
                    "covered_from": first.date().isoformat(),
                    "covered_to": last.date().isoformat(), "note": m.note or None})
    return out
