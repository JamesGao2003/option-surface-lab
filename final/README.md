# Final Cycle: the wheel, run nightly (FINTECH 535)

Page: https://jamesgao2003.github.io/option-surface-lab/final/

Every night at 10 PM New York a GitHub Action (`.github/workflows/nightly-orders.yml`) runs `final/plan_orders.py`.
The script reads `price_history.json` (daily AAPL bars the course server writes) and `mkt/positions.json` (the book Sanji writes; all cash until he does),
computes 20-day realised volatility, and writes the next session's order in the Sanji language to `open_orders.json` at the repo root (and a copy in `mkt/`).
Flat: sell a cash-secured put 1.3 weekly sigmas below the open (clamped 3% to 10%), Friday expiry, limit at mid. Long shares: sell a covered call at the first $5 strike at or above max(close, basis).
An open option, or an 8% drop over 10 sessions, means no new order. `final/run_log.json` and `final/order_history.json` feed the page. Standard library only.

Run it by hand: `python final/plan_orders.py`, or Actions → Nightly order refresh → Run workflow.
