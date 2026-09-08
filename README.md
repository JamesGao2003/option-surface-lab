# UUUU Option Surface Lab — Assignment 1.1

An interactive static GitHub Pages app built from the supplied **corrected LSEG CodeBook cache**, `option_pipeline_data_v2.pkl`. Explore daily call and put price clouds, compare closing midpoint and last-trade prices, and inspect missing observations without interpolation.

This implementation follows the instructor's September 7 clarification: Reflex is optional, `MID_PRICE` replaces the unsupported `SETTLE`, and the final deliverable is a GitHub Pages website. `class_1.py` is an adapted entry point, not an unchanged copy of the starter.

## View and publish

Open `index.html` in a browser. Plotly and the data are embedded; there is no CDN, API login, Python server, or credential needed to view the app. The source/data downloads require the accompanying files to be in the same folder.

1. Create a public repository under your GitHub account, such as `option-surface-lab`, or use the existing course repository.
2. Upload the **contents** of this folder to the repository root and commit to `main`. Upload the extracted files, not only the ZIP. `index.html` must be directly at the repository root.
3. Open **Settings → Pages → Build and deployment → Source: Deploy from a branch**.
4. Select **main** and **/ (root)**, then **Save**.
5. Wait for Pages deployment to succeed, open the published URL, and verify the charts, date/type selectors, field toggles and 3D rotation.
6. Submit the **published site URL** on Canvas, not the GitHub profile or repository URL.

With the example repository name, the expected address is `https://KingJamesGaoLongLiveForever.github.io/option-surface-lab/`. This is an expected address, not confirmation of a deployment.

[Official GitHub Pages instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

## Rebuild from the cache

Use Python 3.10+ locally, from this folder:

```bash
python -m pip install -r requirements.txt
python class_1.py --cache option_pipeline_data_v2.pkl
```

`build_site.py` uses `pandas.read_pickle` for compatibility with the older pandas objects in CodeBook; only load trusted pickle files. It parses the raw `options` column RICs to regenerate one row per contract/date, rather than trusting the premade long table.

GitHub Pages does not execute Python or unpickle data. Python loads the pickle **at build time**; the browser uses the derived JSON snapshot embedded in HTML. This preserves the cache → parse → visualize workflow on static hosting.

## Fetch in CodeBook

Upload the standalone **fetch_options_v2.py**, then run:

```python
%run fetch_options_v2.py
```

The period is June 12–September 4, 2026. The instructor's full-window stock-high/low strike band, Friday expiries, $0.50 spacing, batched requests and single-RIC fallback are retained. The requested fields are `MID_PRICE` and `TRDPRC_1`. Checkpointing, strict identifier validation, request-error messages, tidy export and session cleanup are added.

The corrected put RIC uses M–X in the base to encode option type/month, but **A–L after `^` for both calls and puts**. For example, `UUUUT142601500.U^H26` is the August 14, 2026 $15 put. The earlier collector incorrectly repeated `T` after `^`; that error was corrected and all 221 put candidates were requested again. The resulting cache now contains put prices and zero unresolved requests. Existing call responses were retained.

[LSEG's official explanation of the expired put suffix](https://community.developers.lseg.com/discussion/110410/expired-option-data-no-reponse).

A fresh run fetches both types. In the original CodeBook folder, V2 can reuse completed calls from the old cache and resume using `option_fetch_checkpoint_v2.pkl`. Its output is `option_pipeline_data_v2.pkl`, or `option_pipeline_data_partial_v2.pkl` if requests remain unresolved. A completed matching V2 cache is reused without refetching. `fetch_options.py` is a compatibility wrapper; use the standalone V2 file for CodeBook uploads.

## Dataset and quality checks

- **442** synthetic candidate RICs requested.
- **361** contracts with at least one observed price: **182 calls + 179 puts**.
- **81** candidates returned with no observed price; these are not established listed series and are not zero-priced contracts.
- **0** unresolved requests.
- **8,314** observed `MID_PRICE` values; **6,701** observed `TRDPRC_1` values.
- **0** duplicate contract/date keys; **0** negative observed prices; no nonfinite observed prices.
- The corrected cache's stock observations cover June 12–September 4; a date without a same-day stock price would display `N/A`.
- The 182 calls and their original observed field values are preserved exactly in the corrected snapshot.

`data_quality.json` is generated from the cache. The companion notebook `data_quality_audit.ipynb` contains inspectable key checks. `VALIDATION.md` describes the software checks and their limits.

The Friday generator and high/low strike band define a sampled request universe. Completing its requests does **not** establish an exhaustive historical option chain. No corporate-action history was supplied, so split-adjusted contract coverage is unverified. Returned daily prices do not establish intraday executable fills, quote freshness, spreads or trade timestamps.

## Headline metric definitions

Headline statistics always use the selected **date and option type**, independent of which price trace is visible.

Let S(t) contain contracts with a first observed price on or before t and expiration on or after t. This is a **sampled active-series proxy** using first observation as an inferred listing start; it may miss listed contracts before their first returned price.

- Mid without trade = `100 × count(MID_PRICE present AND TRDPRC_1 missing on t) / |S(t)|`.
- Median gap = `median(abs(MID_PRICE − TRDPRC_1))` over same-contract, same-date pairs with both fields.
- Sampled active contracts with both fields missing on t remain in the denominator.
- Zero denominator or no paired prices produces `N/A`, not zero.
- A recorded `0.0` is retained as a valid price; no missing values are filled or carried forward.

**The exact percentage across all historically listed contracts is not identifiable from this cache.** The page labels and explains its sample proxy. Synthetic candidates and all-null response columns are not counted as proof of listing. Authoritative historical listing intervals would be required to replace this approximation.

At the default Call / July 10 selection: **125** sampled active series, **36** mid-only, **28.8%**, **73** paired observations, and a median absolute gap of **$0.035**. The corresponding put metrics are independently calculated from the new put observations.

`metric_reference.json` contains Python reference values for every date/type state; JavaScript computes the page metrics separately from the embedded observations. Run `node validate_site.cjs` after rebuilding to compare them.

## Charts and written analysis

The 3D cloud plots actual price observations by calendar days to expiry, strike and price. Expiry day is included. MID_PRICE uses blue circles, TRDPRC_1 uses orange diamonds. Dates, option types and fields can be switched; the 3D view supports rotation.

The coverage matrix uses the entire requested unexpired candidate grid for the selected type, a deliberately different universe from the headline sample metric. It distinguishes both fields, mid only, trade only, no observation and request failure. The comparison chart plots only pairs with both prices against the equality diagonal. The stock candlestick chart supplies context.

The first sentence beneath the 3D plot is calculated from the selected date's actual observations: densest expiry slice, observed strike range, empty requested cells and unresolved requests. The other two explain the danger of interpolating on a $0.50 grid and the intended next-week roles of the two fields. No interpolated sheet is drawn; it is optional in the instructor example and not required by the supplied task.

The field interpretations follow the assignment: MID_PRICE is a potentially stale closing NBBO midpoint and provisional mark; TRDPRC_1 is a last recorded trade, not a closing mark or proof of an executable fill at another time.

## Files

- `class_1.py`: assignment entry point.
- `fetch_options_v2.py`: standalone corrected pipeline and strict RIC parser.
- `fetch_options.py`: compatibility wrapper; legacy parsing is for auditing old data only.
- `build_site.py`: cache validation, parsing, exports and HTML generation.
- `template.html`, `style.css`, `app.js`: editable site sources.
- `index.html`: complete static app.
- `option_pipeline_data_v2.pkl`: exact corrected source cache.
- `option_prices_long.csv`, `option_request_audit.csv`: tidy data and request audit.
- `data_snapshot.json`, `data_quality.json`, `metric_reference.json`: generated evidence.
- `data_quality_audit.ipynb`, `validate_site.cjs`, `VALIDATION.md`: reproducible checks.
- `提交步骤.md`: Chinese submission and presentation guide.
