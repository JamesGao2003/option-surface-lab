# Investment thesis: sharp dips in the S&P 500 usually bounce (FINTECH 535)

Page: https://jamesgao2003.github.io/option-surface-lab/thesis/

Final Project Checkpoint 1. The thesis is that a hard few-day drop in the S&P 500 inside an uptrend is mostly forced selling, so it overshoots and a buyer who holds a few days gets paid.

The rule: buy SPY at the open after a close with 2-day RSI below 10 and price above the 200-day average; sell at the open after the first close above the 5-day average. Settings are from Connors and Alvarez (2008), not tuned.

- `build_tracker.py` runs every night in `.github/workflows/nightly-orders.yml`, right after the order planner. It pulls SPY's latest daily bars from Yahoo (Stooq as backup), re-runs the rule from 1993, and writes `tracker.json`: tonight's state, every trade, the stats by period, and the three wrong-if tests. Standard library only. History is kept in `data/` so a failed download cannot empty the chart.
- `index.html`, `app.js`, `style.css` are the page. It only reads the JSON.
- `alpha_long.json` and `research/` are from the thesis I tested first and dropped (selling Apple puts): six years of weekly option quotes from LSEG and the arithmetic. The page has a short section on why.

Run the tracker by hand: `python thesis/build_tracker.py`.
