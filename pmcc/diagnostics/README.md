# Original-data gap investigation

The diagnostic responses did **not** recover any of the seven missing quote pairs for `AMZNH142629000.U^H26`: August 13, 2026 at 17:00, 18:00, 19:00 and 20:00 UTC, and August 14 at 17:00, 18:00 and 19:00 UTC.

- `provider_responses.json` is the unchanged JSON extracted from the user's LSEG CodeBook diagnostic ZIP, completed October 12, 2026 at 18:49:26 UTC. ZIP SHA-256: `c8b4c53b4d767d8e26e07cf0b717c6cdaf7ceab0a90109075406a06a896dc66e`.
- `strict_horizon_availability.json` audits quote requirements under the original Friday/risk-exit rules. Selections after the unresolved exit are conditional data requirements, not trades booked by that baseline.
- Four queries checked expired one-minute summaries, expired hourly summaries with all fields, quote/correction events, and an unsuffixed alias. None supplied a valid quote at the seven target times.
- The event provider warned that corrections were omitted. The last paired event was August 14 at 15:02:33.912 UTC, with an earlier `SOURCE_DATETIME` of 14:17:17.618 UTC. It is not an observed executable quote at 19:00 UTC.
- The hourly response contains an identical duplicate: 14 rows are 13 unique timestamps; six paired rows are five unique paired timestamps. Raw duplicates remain preserved.

No diagnostic price replaces or fills a missing observation in `PMCC_source.json`. The separately documented 50% premium-capture policy is a retrospective strategy revision, not a data repair. Its position-aware coverage must be assessed from its own ledger and validation output. The original halted results remain in `../strict_baseline/`.
