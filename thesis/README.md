# Investment thesis: protection on Apple costs more than the drops it covers (FINTECH 535)

Page: https://jamesgao2003.github.io/option-surface-lab/thesis/

Final Project Checkpoint 1. The thesis is that out-of-the-money puts on Apple are overpriced, so the cash-secured put the nightly wheel sells keeps part of its premium over time.

- `build_tracker.py` runs every night in `.github/workflows/nightly-orders.yml`, right after the order planner. It reads the Apple VIX (Cboe VXAPL, from FRED, Yahoo for the newest day) and Apple's closes (`price_history.json` from the course server), and writes `tracker.json`: implied against realised volatility, the gap, and the three wrong-if tests. Standard library only. History is kept in `data/` so a failed download cannot empty the chart.
- `alpha_long.json` is the rough alpha check: six years of real weekly option quotes from LSEG. `research/fetch_long_history.py` pulled them (needs a logged-in Workspace session), `research/long_check.py` does the arithmetic.
- `index.html`, `app.js`, `style.css` are the page. It only reads the two JSON files.

Run the tracker by hand: `python thesis/build_tracker.py`.
