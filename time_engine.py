"""Trading Time API: Abwicklungstage, Forex-Sessions, Zeitumstellungs-Lücken, Countdown.

Alles wird berechnet, es werden keine Fremddaten weiterverkauft:
- Börsen-Handelstage: exchange_calendars (Open Source).
- Zeitzonen und Sommerzeit: IANA tzdata (public domain).
- Abwicklungszyklen (T+1/T+2): öffentlich bekannte Marktregeln, mit Umstellungsdatum.
- Forex-Sessions: verbreitete Konvention (lokale Geschäftszeiten der Finanzplätze).
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd

import engine

UTC = dt.timezone.utc


def _now(at: dt.datetime | None) -> dt.datetime:
    if at is None:
        return dt.datetime.now(UTC)
    if at.tzinfo is None:
        raise ValueError("Time 'at' needs a UTC offset, e.g. 2026-11-27T15:00:00Z")
    return at.astimezone(UTC)


def _iso(d: dt.datetime, tz: str) -> dict:
    return {"utc": d.astimezone(UTC).isoformat(), "local": d.astimezone(ZoneInfo(tz)).isoformat()}


# ---------------------------------------------------------------- A10 Abwicklung
# (gilt ab Handelstag, Zyklus in Börsen-Handelstagen)
SETTLEMENT_RULES = {
    "XNYS": [("1900-01-01", 2), ("2024-05-28", 1)],
    "XNAS": [("1900-01-01", 2), ("2024-05-28", 1)],
    "XLON": [("1900-01-01", 2), ("2027-10-11", 1)],
    "XETR": [("1900-01-01", 2), ("2027-10-11", 1)],
    "XSWX": [("1900-01-01", 2), ("2027-10-11", 1)],
    "XTKS": [("1900-01-01", 2)],
    "XHKG": [("1900-01-01", 2)],
    "XSHG": [("1900-01-01", 1)],
    "XASX": [("1900-01-01", 2)],
}
SETTLEMENT_NOTES = {
    "XLON": "UK moves to T+1 on 11 Oct 2027 (aligned with EU and Switzerland).",
    "XETR": "EU moves to T+1 on 11 Oct 2027.",
    "XSWX": "Switzerland moves to T+1 on 11 Oct 2027.",
    "XHKG": "HKEX has consulted on T+1; still T+2 here until a date is set.",
    "XSHG": "A-shares: securities delivered T+1.",
}


def settlement_date(market: str, trade_date: str) -> dict:
    m = engine.get_market(market)
    if market.upper() not in SETTLEMENT_RULES:
        raise ValueError(f"No settlement rule for {m.code}. Use an equity market: {', '.join(SETTLEMENT_RULES)}")
    try:
        td = dt.date.fromisoformat(trade_date)
    except ValueError:
        raise ValueError("trade_date must be YYYY-MM-DD")
    cal = engine._calendar(m.calendar)
    if not cal.is_session(pd.Timestamp(td)):
        raise ValueError(f"{trade_date} is not a trading day on {m.code}")
    cycle = [c for start, c in SETTLEMENT_RULES[m.code] if td >= dt.date.fromisoformat(start)][-1]
    sd = cal.session_offset(pd.Timestamp(td), cycle).date()
    return {"market": m.code, "name": m.name, "trade_date": td.isoformat(), "cycle": f"T+{cycle}",
            "settlement_date": sd.isoformat(), "note": SETTLEMENT_NOTES.get(m.code, ""),
            "source": {"rules": "Published settlement cycles of the respective markets",
                       "holidays": engine.DATA_VERSION,
                       "caveat": "Exchange business days; currency/bank holidays can differ."}}


# ---------------------------------------------------------------- A11 Forex
FX_SESSIONS = [
    ("Sydney", "Australia/Sydney", dt.time(7, 0), dt.time(16, 0)),
    ("Tokyo", "Asia/Tokyo", dt.time(9, 0), dt.time(18, 0)),
    ("London", "Europe/London", dt.time(8, 0), dt.time(17, 0)),
    ("New York", "America/New_York", dt.time(8, 0), dt.time(17, 0)),
]
NY = ZoneInfo("America/New_York")


def fx_market_open(now: dt.datetime) -> bool:
    """Spot-FX: Sonntag 17:00 bis Freitag 17:00 New Yorker Zeit."""
    t = now.astimezone(NY)
    wd, hm = t.weekday(), t.time()
    if wd == 5:
        return False
    if wd == 4 and hm >= dt.time(17, 0):
        return False
    if wd == 6 and hm < dt.time(17, 0):
        return False
    return True


def _session_window(name, tz, start, end, local_day):
    z = ZoneInfo(tz)
    return dt.datetime.combine(local_day, start, z), dt.datetime.combine(local_day, end, z)


def fx_sessions(at: dt.datetime | None = None) -> dict:
    now = _now(at)
    market_open = fx_market_open(now)
    out = []
    for name, tz, start, end in FX_SESSIONS:
        local = now.astimezone(ZoneInfo(tz))
        o, c = _session_window(name, tz, start, end, local.date())
        is_open = market_open and local.weekday() < 5 and o <= now < c
        # nächste Eröffnung an einem Werktag, an dem der FX-Markt offen ist
        d = local.date()
        nxt = None
        for i in range(0, 10):
            cand_o, _ = _session_window(name, tz, start, end, d + dt.timedelta(days=i))
            if cand_o > now and cand_o.weekday() < 5 and fx_market_open(cand_o):
                nxt = cand_o
                break
        out.append({"session": name, "timezone": tz, "is_open": is_open,
                    "hours_local": f"{start:%H:%M}-{end:%H:%M}",
                    "today_utc": {"open": o.astimezone(UTC).isoformat(), "close": c.astimezone(UTC).isoformat()},
                    "next_open": _iso(nxt, tz) if nxt else None})
    open_names = [s["session"] for s in out if s["is_open"]]
    return {"at": now.isoformat(), "fx_market_open": market_open, "open_sessions": open_names,
            "overlap": len(open_names) >= 2, "sessions": out,
            "source": {"rules": "Spot FX trades Sun 17:00 to Fri 17:00 New York time; session hours are a "
                                "common convention (local business hours), not exchange rules.",
                       "timezones": "IANA tzdata"}}


# ---------------------------------------------------------------- A12 Zeitumstellung
PAIRS = {
    "US-EU": ("America/New_York", "Europe/Berlin"),
    "US-UK": ("America/New_York", "Europe/London"),
    "US-CH": ("America/New_York", "Europe/Zurich"),
    "EU-AU": ("Europe/Berlin", "Australia/Sydney"),
}


def _diff_hours(tz_a: str, tz_b: str, when: dt.datetime) -> float:
    a = when.astimezone(ZoneInfo(tz_a)).utcoffset().total_seconds()
    b = when.astimezone(ZoneInfo(tz_b)).utcoffset().total_seconds()
    return (b - a) / 3600


def dst_gaps(year: int, pair: str = "US-EU") -> dict:
    if pair not in PAIRS:
        raise ValueError(f"pair must be one of {', '.join(PAIRS)}")
    if not 2000 <= year <= 2100:
        raise ValueError("year must be between 2000 and 2100")
    tz_a, tz_b = PAIRS[pair]
    day = dt.datetime(year, 1, 1, 12, tzinfo=UTC)
    diffs = []
    while day.year == year:
        diffs.append((day.date(), _diff_hours(tz_a, tz_b, day)))
        day += dt.timedelta(days=1)
    normal = max(set(d for _, d in diffs), key=lambda v: sum(1 for _, x in diffs if x == v))
    periods, cur = [], None
    for d, h in diffs:
        if h != normal:
            if cur is None:
                cur = {"from": d, "to": d, "difference_hours": h}
            else:
                cur["to"] = d
        elif cur is not None:
            periods.append(cur); cur = None
    if cur:
        periods.append(cur)
    return {"pair": pair, "zones": [tz_a, tz_b], "year": year, "normal_difference_hours": normal,
            "gap_periods": [{"from": p["from"].isoformat(), "to": p["to"].isoformat(),
                             "difference_hours": p["difference_hours"],
                             "days": (p["to"] - p["from"]).days + 1} for p in periods],
            "meaning": f"During gap periods the clock difference {tz_a} -> {tz_b} is not {normal:g} h, "
                       "so foreign opening times shift by one hour in local time.",
            "source": {"timezones": "IANA tzdata (public domain)"}}


def is_dst_gap(at: dt.datetime | None = None, pair: str = "US-EU") -> dict:
    now = _now(at)
    info = dst_gaps(now.year, pair)
    tz_a, tz_b = PAIRS[pair]
    diff = _diff_hours(tz_a, tz_b, now)
    return {"pair": pair, "at": now.isoformat(), "is_gap": diff != info["normal_difference_hours"],
            "difference_hours_now": diff, "normal_difference_hours": info["normal_difference_hours"],
            "gap_periods_this_year": info["gap_periods"], "source": info["source"]}


# ---------------------------------------------------------------- A17 Countdown
def countdown(markets: str, at: dt.datetime | None = None) -> dict:
    now = _now(at)
    codes = [c.strip().upper() for c in (markets or "").split(",") if c.strip()]
    if not codes:
        raise ValueError(f"markets must list one or more codes: {', '.join(engine.MARKETS)}")
    if len(codes) > 11:
        raise ValueError("at most 11 markets per call")
    out = []
    for c in codes:
        s = engine.status(c, now)

        def secs(x):
            return None if not x else int((dt.datetime.fromisoformat(x["utc"]) - now).total_seconds())
        out.append({"market": s["market"], "name": s["name"], "is_open": s["is_open"], "state": s["state"],
                    "seconds_to_next_open": secs(s.get("next_open")),
                    "seconds_to_next_close": secs(s.get("next_close")),
                    "next_open": s.get("next_open"), "next_close": s.get("next_close")})
    return {"at": now.isoformat(), "markets": out, "open_now": [m["market"] for m in out if m["is_open"]],
            "source": {"data": engine.DATA_VERSION}}
