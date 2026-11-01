"""Trading Time API mit x402-Bezahlung (USDC auf Base).

Umgebungsvariablen:
  PAY_TO              Deine Wallet-Adresse (0x...), hierhin gehen die Zahlungen. Pflicht.
  X402_NETWORK        "testnet" (Base Sepolia, Standard) oder "mainnet" (Base).
  CDP_API_KEY_ID      Coinbase-Developer-Platform-Key. Für mainnet und Bazaar-Listing nötig.
  CDP_API_KEY_SECRET  dazugehöriges Secret.
  PUBLIC_URL          Öffentliche https-Adresse des Dienstes (für die Bazaar-Beschreibung).

Start:  uvicorn paid_app:app --host 0.0.0.0 --port 8000
Gratis:  /v1/markets, /health, /docs
Bezahlt: /v1/settlement-date, /v1/fx-sessions, /v1/dst-gap, /v1/is-dst-gap, /v1/countdown
"""
import os
import re

from x402 import x402ResourceServer
from x402.extensions.bazaar import (
    OutputConfig,
    bazaar_resource_server_extension,
    declare_discovery_extension,
)
from x402.http import FacilitatorConfig, HTTPFacilitatorClient
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import PaymentOption, RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme

from app import app

NETWORKS = {"testnet": "eip155:84532", "mainnet": "eip155:8453"}
TESTNET_FACILITATOR = os.environ.get("FACILITATOR_URL", "https://x402.org/facilitator")

PAY_TO = os.environ.get("PAY_TO", "").strip()
if not re.fullmatch(r"0x[0-9a-fA-F]{40}", PAY_TO):
    raise SystemExit("PAY_TO fehlt oder ist keine gültige Wallet-Adresse (0x + 40 Hex-Zeichen).")

MODE = os.environ.get("X402_NETWORK", "testnet").lower()
if MODE not in NETWORKS:
    raise SystemExit("X402_NETWORK muss 'testnet' oder 'mainnet' sein.")
NETWORK = NETWORKS[MODE]

CDP_ID = os.environ.get("CDP_API_KEY_ID", "").strip().strip('"\'').strip()
CDP_SECRET = os.environ.get("CDP_API_KEY_SECRET", "").strip().strip('"\'').strip()
if "BEGIN" in CDP_SECRET:
    CDP_SECRET = CDP_SECRET.replace("\\n", "\n")  # PEM aus einzeiligem Feld


def _describe_cdp_keys() -> str:
    """Format der Keys beschreiben, ohne Werte preiszugeben."""
    id_kind = ("uuid" if re.fullmatch(r"[0-9a-fA-F-]{36}", CDP_ID)
               else "organizations-path" if CDP_ID.startswith("organizations/") else "other")
    if "BEGIN EC PRIVATE KEY" in CDP_SECRET:
        sec_kind = "ec-pem"
    else:
        try:
            import base64
            sec_kind = f"base64-{len(base64.b64decode(CDP_SECRET, validate=True))}bytes"
        except Exception:
            sec_kind = "unparseable"
    return f"CDP key: id={id_kind} (len {len(CDP_ID)}), secret={sec_kind} (len {len(CDP_SECRET)})"


if CDP_ID and CDP_SECRET:
    from cdp.x402 import create_facilitator_config
    print(_describe_cdp_keys(), flush=True)
    facilitator_cfg = create_facilitator_config(CDP_ID, CDP_SECRET)
elif MODE == "mainnet":
    raise SystemExit("Für mainnet werden CDP_API_KEY_ID und CDP_API_KEY_SECRET benötigt.")
else:
    facilitator_cfg = FacilitatorConfig(url=TESTNET_FACILITATOR)

server = x402ResourceServer(HTTPFacilitatorClient(facilitator_cfg))
server.register(NETWORK, ExactEvmServerScheme())
server.register_extension(bazaar_resource_server_extension)

AT_SCHEMA = {"type": "string",
             "description": "Optional ISO 8601 time with offset, e.g. 2026-10-21T08:30:00Z. Default: now."}
MARKETS_DESC = "XNYS, XNAS, XLON, XETR, XSWX, XTKS, XHKG, XSHG, XASX, CME_EQUITY, EUREX_INDEX"
SVC = "Trading Time API"


def pay(price: str) -> PaymentOption:
    return PaymentOption(scheme="exact", pay_to=PAY_TO, price=price, network=NETWORK)


def route(price, desc, tags, inp, schema, required, example):
    return RouteConfig(
        accepts=pay(price), description=desc, mime_type="application/json", service_name=SVC, tags=tags,
        extensions=declare_discovery_extension(
            input=inp, input_schema={"properties": schema, "required": required},
            output=OutputConfig(example=example)))


S = lambda d: {"type": "string", "description": d}
PAIR = S("Zone pair: US-EU, US-UK, US-CH or EU-AU. Default US-EU.")

# Preise je Agent unterscheiden sich, damit der Einnahmen-Monitor zuordnen kann:
# A10 = 0.0010, A11 = 0.0011, A12 = 0.0012, A17 = 0.0020 USDC
routes = {
    "GET /v1/settlement-date": route(
        "$0.0205", "Returns the settlement date (T+1 or T+2) of a stock trade on a given exchange, skipping "
                  "exchange holidays, including the 2027 move of EU, UK and Switzerland to T+1.",
        ["finance", "settlement", "calendar", "trading"],
        {"market": "XNYS", "trade_date": "2026-11-25"},
        {"market": S("Exchange: XNYS, XNAS, XLON, XETR, XSWX, XTKS, XHKG, XSHG, XASX"),
         "trade_date": S("Trade date YYYY-MM-DD")}, ["market", "trade_date"],
        {"market": "XNYS", "trade_date": "2026-11-25", "cycle": "T+1", "settlement_date": "2026-11-27"}),
    "GET /v1/fx-sessions": route(
        "$0.0225", "Returns which forex trading sessions (Sydney, Tokyo, London, New York) are open at a given "
                   "time, whether sessions overlap, and the next opening of each session.",
        ["finance", "forex", "sessions", "trading"],
        {"at": "2026-10-21T08:30:00Z"}, {"at": AT_SCHEMA}, [],
        {"fx_market_open": True, "open_sessions": ["Tokyo", "London"], "overlap": True}),
    "GET /v1/dst-gap": route(
        "$0.0245", "Returns the weeks of a year in which the clock difference between the US and Europe (or "
                   "other pairs) is shifted by daylight-saving changes, so foreign market opens move by one hour.",
        ["finance", "timezone", "daylight-saving", "calendar"],
        {"year": "2027", "pair": "US-EU"}, {"year": S("Calendar year, e.g. 2027"), "pair": PAIR}, ["year"],
        {"pair": "US-EU", "normal_difference_hours": 6,
         "gap_periods": [{"from": "2027-03-14", "to": "2027-03-27", "difference_hours": 5}]}),
    "GET /v1/is-dst-gap": route(
        "$0.0245", "Returns whether a given time falls inside a daylight-saving gap between the US and Europe "
                   "and the current clock difference in hours.",
        ["finance", "timezone", "daylight-saving"],
        {"at": "2027-03-20T12:00:00Z", "pair": "US-EU"}, {"at": AT_SCHEMA, "pair": PAIR}, [],
        {"pair": "US-EU", "is_gap": True, "difference_hours_now": 5, "normal_difference_hours": 6}),
    "GET /v1/countdown": route(
        "$0.0405", "Returns open/closed state and seconds until the next open and close for several stock "
                  "exchanges and futures markets in one call.",
        ["finance", "market-hours", "countdown", "trading"],
        {"markets": "XNYS,XETR,CME_EQUITY"}, {"markets": S("Comma-separated market codes: " + MARKETS_DESC),
                                              "at": AT_SCHEMA}, ["markets"],
        {"open_now": ["XETR", "CME_EQUITY"], "markets": [{"market": "XNYS", "is_open": False,
                                                           "seconds_to_next_open": 5400}]}),
}

app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
app.title = f"Trading Time API ({MODE})"
