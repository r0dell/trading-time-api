# Trading Time API (v0.1)

Zeit- und Kalenderfragen rund ums Trading, alles berechnet aus Börsenkalendern und Zeitzonen.

| Endpunkt | Liefert | Preis |
|---|---|---|
| `/v1/settlement-date?market=XNYS&trade_date=2026-11-25` | Valuta (T+1/T+2) mit Börsenfeiertagen, inkl. Umstellung EU/UK/CH auf T+1 am 11.10.2027 | 0.0205 USDC |
| `/v1/fx-sessions?at=…` | offene Forex-Sessions (Sydney, Tokio, London, New York), Überlappung, nächste Eröffnung | 0.0225 USDC |
| `/v1/dst-gap?year=2027&pair=US-EU` | Wochen mit verschobener Zeitdifferenz durch Sommerzeit | 0.0245 USDC |
| `/v1/is-dst-gap?at=…` | ist dieser Zeitpunkt in einer Zeitumstellungs-Lücke? | 0.0245 USDC |
| `/v1/countdown?markets=XNYS,XETR,CME_EQUITY` | offen/zu und Sekunden bis Öffnung/Schluss für mehrere Märkte | 0.0405 USDC |
| `/v1/markets`, `/docs`, `/health` | Marktliste, Doku | gratis |

Datenbasis: `exchange_calendars` (Open Source), IANA-Zeitzonen (public domain), öffentliche Abwicklungsregeln.
Forex-Session-Zeiten sind eine verbreitete Konvention, keine Börsenregel.

Die Preise unterscheiden sich je Funktion, damit Einnahmen den einzelnen Agenten zugeordnet werden können.
Tests: `python -m pytest -q`
