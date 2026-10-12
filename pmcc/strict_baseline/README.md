# Preserved original strategy

These original files were copied before the hourly 50% take-profit strategy was run. Their source data and original results are unchanged. The original Friday/risk-exit simulation halts on August 14, 2026 at 15:00 New York time because its required short-call buyback quote is missing.

This is an audit trail, not a completed full-period comparison. Do not replace its missing observation with a later quote or an assumed zero-price close.

From the parent PMCC directory, reproduce it separately:

```sh
python strict_baseline/engine.py PMCC_source.json strict_baseline_replay
python strict_baseline/validate_results.py strict_baseline_replay
```

The revised strategy and its explicit research-design disclosure are in the parent directory.
