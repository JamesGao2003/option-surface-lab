# The Wheel on Amazon — FINTECH 535 HW 4

Page: https://jamesgao2003.github.io/option-surface-lab/wheel/

Weekly wheel on AMZN, April 6 to October 2, 2026, $50,000 starting cash.
Every Monday: flat, sell a cash-secured put at the highest strike at or below 95% of the close, expiring that Friday, as many contracts as the cash fully covers (max 2).
Assigned: buy the shares at the strike. Then every Monday sell a covered call at the lowest strike at or above max(close, assignment strike).
Called away: sell the shares at the strike, go back to puts. No rolls, no buy-backs, $0.65 per contract per order, fills at the closing bid, marks at the mid.

## Files

- `wheel_fetch_codebook.py` — the LSEG CodeBook pull (daily BID/ASK/MID_PRICE/TRDPRC_1/ACVOL_UNS for every weekly put and call in a band around each week's stock range, plus AMZN.O daily OHLC). `wheel_fetch.py` is the same script with an option to run locally against an open Workspace session (`LSEG_CONFIG=lseg-data.config.json python wheel_fetch.py`; the config with the app key is not in the repo).
- `wheel_source.json` — every response from that pull, 1,370 contracts requested, 1,223 observed, 0 failed requests. `wheel_request_audit.csv` is the per-contract audit.
- `engine.py` — the backtest. `python engine.py --source amzn` writes `book.json` / `book.js` (everything the page shows), `blotter.csv`, `ledger.csv`, `decisions.csv`, and `variants.json` / `variants.js` (the stress table: worse fills, no basis floor, 97% and 92% put strikes). `--source uuuu` runs the same engine on the Assignment 1.1 UUUU cache.
- `index.html`, `app.js`, `style.css` — the page. It uses `../pmcc/style.css` and `../hw12/plotly.min.js`, so keep the earlier assignment folders.

## Checks I ran

Cash at the end equals starting cash plus the sum of every blotter cash change. Account value on every ledger row equals cash + shares × close + option marks. Cash never goes negative and the reserved cash for the open put never exceeds cash. One daily option mark (Apr 9, the 200 put) had no closing quote and is flagged as estimated.

## Honest limits

One stock, 26 weeks, daily closes. No intraday prices, no early assignment, no queue position on the limit order. The rule variants were each run once after the base case and are reported either way.
