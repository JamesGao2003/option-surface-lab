# HW 1.2 — Covered Call Backtest

The graded artifact is `hw12/index.html` on GitHub Pages. The current book is the supplied LSEG CodeBook result retrieved September 21, 2026 UTC. It has 6 calls, 20 booked events, 349 ledger marks and 1,766 regression pairs. Ending NAV is $29,315.50 (-2.2817%); R² is 0.99907151. There are 27 failed candidate requests and 6 missing option marks, disclosed on the page. All actual positions settle, but source coverage is incomplete.

## Reproduce

1. Upload `HW12_CodeBook_Run_v3.py` to LSEG Workspace CodeBook (Python 3.8 compatible).
2. In a notebook, run `%run HW12_CodeBook_Run_v3.py`. The existing CodeBook session supplies authorization; no API key is embedded in this repository.
3. Download `HW12_results.zip`, inspect its summary, and replace `hw12/book.js` with its `book.js`. Keep the result JSON and CSV files for review.
4. Confirm actual calls, settlements and a usable regression before publishing. Read the weekly skip audit and investigate request errors.
5. Open `index.html` through a static server or GitHub Pages. No Node build is needed. Plotly is bundled locally, with its license.

The fetcher checkpoints each request. Rerunning resumes the same declared settings and retries failed requests. The checkpoint is a local pickle created by the script; never load an untrusted pickle. Do not commit the raw checkpoint.

## Fixed experiment

- Instrument: AAPL.O, 100 shares and at most one short Friday call.
- Window: 2026-07-13 through 2026-09-18, ten scheduled weeks.
- Decision: Monday 11:00 America/New_York. Missing Monday stock print means a skipped week, not a Tuesday substitute.
- Entry universe: a $2.50 strike grid based solely on that Monday's stock print. Select the lowest strike at or above spot, at most $15 OTM, with a positive non-crossed quote. This is an explicitly sampled grid, not an exhaustive expired chain.
- Fill: stock at the reported print; option limit and simulated fill at that bar's midpoint. No valid two-sided quote means neither new leg is booked.
- Expiry: Friday 16:00 stock print. ITM physically delivers the shares at strike; OTM/ATM expires with shares retained. Missing expiry print stops the account as incomplete. No roll or buy-to-close.
- Capital: $30,000 initial cash. Assignment model: initial margin 50% of stock market value, maintenance 25%, no additional charge for the fully covered call. Reject entries that would leave negative initial-margin room.
- Marking: same-label hourly stock and option observations. Missing option marks remain null; no interpolation or carry-forward valuation. Intrinsic value is used immediately before expiry settlement.

Hourly timestamps use the content API's explicit `summaryTimestampLabel=endPeriod`. A shared bar label does not prove tick-level simultaneity. The price-only base case excludes dividends, fees, interest, corporate-action adjustments, taxes and early exercise. Bid-fill and $0.65 commission sensitivities are cash-impact diagnostics for the same trade path, not full re-optimizations.

## Validation

Run `python -m unittest test_engine -v` from this directory. Scenario fixtures cover retained shares after expiry, physical assignment, cash conservation, missing and crossed quotes, insufficient capital, missing valuation and settlement, holiday skip, strike selection and known-line regression. These synthetic scenarios exist only in tests; they are not the published dataset.

Every real build also independently replays the blotter and checks positions, cash deltas, coverage, NAV and both margin equations. Review source quality and actual plots in addition to these mechanical checks. The published Data page intentionally displays **Data connection required**.

## Sources

- [Assignment](https://jakevestal.github.io/535_fintech/assignment.html)
- [LSEG intraday timestamp conventions](https://community.developers.lseg.com/discussion/132431/difference-in-intraday-timestamp-between-rd-get-history-vs-ek-get-timeseries)



## Actual-result validation

`python validate_results.py .` independently checks 20 cash events, 349 ledger rows, option coverage, entry quotes, expiry delivery, summary values and the OLS fit using NumPy least squares. Supplied JSON and JS are preserved exactly. `ledger.csv` is regenerated directly from JSON because a separate ledger CSV was not supplied. `validation.json` records the source SHA-256 and limitations. Install numpy and pytz for local validation. Raw stock/options checkpoint was not supplied, so source freshness and exhaustive strike selection cannot be independently established.
