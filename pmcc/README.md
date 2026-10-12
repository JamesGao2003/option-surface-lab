# AMZN Poor Man’s Covered Call

FINTECH 535 strategy research. Target page (deployment not yet verified): <https://jamesgao2003.github.io/option-surface-lab/pmcc/>.

A one-contract long-call diagonal is compared with a 100-share covered call, 100 shares alone, and the same long call alone. Each account starts with $50,000. Observed LSEG bid/ask bars supply the prices: buy at ask, sell at bid, and charge $0.65 per option contract per transaction. The page reads results directly from `book.js`; the full source, cash ledger and event blotter are downloadable.

## Research design disclosure

The original Friday/risk-exit strategy halted on August 14 at 15:00 New York time. Seven quotes required by its selected-position path were unavailable on August 13–14 for `AMZNH142629000.U^H26`. Follow-up requests did not recover them. See [the diagnostic evidence](diagnostics/README.md). This count describes original position requirements, not the coverage of the entire candidate universe.

The revised strategy adds an hourly 50% premium-capture exit to **every** short-call week. [The dated policy](strategy_revision.json) was recorded before computing revised performance, after the data gaps were known. No return-driven threshold search was performed. This is a different, exploratory strategy; its design benefits from hindsight about data availability. It is neither a repaired dataset nor an out-of-sample test. A later untouched sample is needed to evaluate it independently.

The original raw source remains unchanged. The original engine and halted outputs are retained in `strict_baseline/`. A zero missing-position-mark count in the revised book means all its required marks were observed; it does not mean all raw quotes exist. Neither strategy invents fills, carries stale quotes forward, or deletes an earlier trade using future information.

## Algorithm

- Sample: April 6–October 2, 2026; AMZN.O; New York time; hourly bars labeled by end period. Four equal-cash accounts; no position scaling, interest or reinvestment.
- Long call: January 21, 2028 expiry, closest $5 strike to 70% of April 6 at 11:00 spot, within 60–80%; ties lower. Select from quotes at that timestamp. Require positive uncrossed bid/ask with spread no greater than 10% of mid. Abort if this fixed opening observation is unavailable.
- Weekly short: Monday 11:00, lowest eligible $5 strike at or above 103% of spot among the first three candidates, above the long strike. Require positive uncrossed bid/ask with spread no greater than 50% of mid. Skip a missing entry or a week with a Monday/Friday market holiday.
- Take profit: after entry, check each regular hourly observation from 10:00 through 16:00. Buy back at observed ask if `ASK <= 0.50 * original_entry_BID`, before fees. Do not re-enter that week.
- Other exits: buy back Friday 15:00, or sooner at a daily 15:00 check when ITM and mid extrinsic value is at most $0.05. These mandatory/risk checks remain in force. Missing required exit data halts the run; missing held-position marks remain missing.
- Final liquidation: October 2 at 15:00; close any remaining short, then sell long calls and stock benchmark positions at bid. Halt if a required liquidation quote is unavailable.
- Assignment: the base path is conditional on no external early assignment before buyback. A long call is not stock ownership and does not automatically exercise when the short is assigned. The page separates a mechanical assignment stress scenario from observed trades.

## Reproduction

1. In an entitled LSEG CodeBook session, run `%run PMCC_CodeBook_Run.py`. The script reads data and submits no brokerage orders. Download `PMCC_source.zip` or `PMCC_source.json`; retain responses and request audit. Never upload credentials.
2. Use Python 3.9 or later. From this directory, run:

   ```sh
   python -m pip install tzdata
   python engine.py PMCC_source.json . --policy strategy_revision.json
   python validate_results.py .
   python -m unittest -v test_engine.py
   ```

   `tzdata` supplies the New York time-zone database where the operating system lacks one. The policy is an explicit input; it does not alter source configuration or prices. The validator reconciles fills, cash, positions, NAV, metrics, regressions and CSV/JSON/JavaScript agreement. Passing reconciliation alone does not prove data completeness or investment merit.
3. To reproduce the original strategy separately:

   ```sh
   python strict_baseline/engine.py PMCC_source.json strict_baseline_replay
   python strict_baseline/validate_results.py strict_baseline_replay
   ```

   Its August 14 halt is expected. Do not compare its partial result with the revised full-period return.
4. Publish this directory, including `strategy_revision.json`, `strict_baseline/` and `diagnostics/`, under the existing repository. The page uses the shared `../hw12/plotly.min.js`. Keep the earlier assignments intact. For a local preview from the repository root: `python -m http.server 8766`, then visit `http://127.0.0.1:8766/pmcc/`.

## Interpretation

Opening debit is net opening cash outlay including fees, not broker margin or the return denominator. Returns use the common $50,000 budget. Premium is cash flow, not profit. Midquotes mark NAV; exit-side bid/ask mark liquidation value. Hourly quote summaries need not be simultaneous executable prices. Complete hourly marks still cannot reveal intrabar losses. One stock, limited strike sampling, early-assignment assumptions and retrospective rule design constrain the conclusions.

References: [Fidelity diagonal call spread](https://www.fidelity.com/learning-center/investment-products/options/options-strategy-guide/long-diagonal-spread-calls), [Amazon investor FAQ](https://ir.aboutamazon.com/faqs/default.aspx), [NYSE calendar](https://www.nyse.com/markets/hours-calendars).
