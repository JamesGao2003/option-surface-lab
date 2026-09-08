"""Assignment 1.1: run in LSEG CodeBook with %run fetch_options_v2.py.

V2 fixes the put expiry suffix: A-L after ^ for both calls and puts.
Reference: https://community.developers.lseg.com/discussion/110410/expired-option-data-no-reponse

Adapted from the supplied class_1.py. No Reflex installation is needed.
The fixed historical window makes reruns reproducible. The cache contains
real vendor responses only; candidates are NOT a verified listing universe.
Only load pickle files you created or otherwise trust.
"""
from pathlib import Path
import datetime as dt
import math
import pickle
import re
import time

import pandas as pd

START = "2026-06-12"
END = "2026-09-04"
STOCK = "UUUU.K"
ROOT = "UUUU"
STRIKE_STEP = 0.50
BATCH_SIZE = 25
FIELDS = ["MID_PRICE", "TRDPRC_1"]
CACHE = Path("option_pipeline_data_v2.pkl")
CHECKPOINT = Path("option_fetch_checkpoint_v2.pkl")


def parse_option_ric(ric, allow_legacy_suffix=False):
    """Parse the assignment's expired US equity option RIC convention."""
    match = re.fullmatch(
        r"(?P<root>[A-Z]+)(?P<m>[A-X])(?P<day>\d{2})(?P<yy>\d{2})"
        r"(?P<strike>\d{5})\.U\^(?P<sm>[A-X])(?P<sy>\d{2})", str(ric)
    )
    if not match:
        raise ValueError(f"Unsupported option RIC: {ric}")
    parts = match.groupdict()
    code = ord(parts["m"]) - ord("A")
    expected_suffix = chr(ord("A") + code % 12)
    permitted = {expected_suffix}
    if allow_legacy_suffix:
        permitted.add(parts["m"])  # Read old audit entries only, never generate them.
    if parts["sm"] not in permitted or parts["yy"] != parts["sy"]:
        raise ValueError(f"Incorrect expiry suffix: {ric}; expected ^{expected_suffix}{parts['yy']}")
    return {
        "underlying": parts["root"],
        "expiry": dt.date(2000 + int(parts["yy"]), code % 12 + 1, int(parts["day"])),
        "type": "Call" if code < 12 else "Put",
        "strike": int(parts["strike"]) / 100,
    }


def make_option_ric(root, expiry, cents, side):
    if side not in ("Call", "Put"):
        raise ValueError("side must be Call or Put")
    month_code = chr(ord("A") + expiry.month - 1)
    right_code = chr(ord(month_code) + (12 if side == "Put" else 0))
    ric = f"{root}{right_code}{expiry:%d%y}{cents:05d}.U^{month_code}{expiry:%y}"
    parse_option_ric(ric)
    return ric


def reuse_calls(progress, source):
    """Keep genuine call responses, never relabel invalid put responses."""
    old = pd.read_pickle(source)
    settings = progress["settings"]
    if any(old.get("settings", {}).get(k) != settings[k] for k in
           ("start", "end", "ticker", "strike_step", "fields")):
        raise RuntimeError("Existing snapshot uses different settings; refusing to mix periods.")
    calls = {ric for ric in progress["candidates"] if parse_option_ric(ric)["type"] == "Call"}
    latest = {a["ric"]: a for a in old["request_audit"]}
    done = {ric for ric in calls if latest.get(ric, {}).get("status") in ("observed", "no_observations")}
    options = old["options"]
    keep = options.columns.get_level_values("RIC").isin(done)
    if keep.any():
        progress["frames"].append(options.loc[:, keep].copy())
    progress["done"].extend(sorted(done))
    progress["audit"].extend({**latest[ric], "reused_from": str(source)} for ric in sorted(done))
    print(f"Reused {len(done)} call requests from {source}; all corrected put RICs will be requested afresh.", flush=True)


def canonicalize(frame, requested, fields):
    """Normalize multi-RIC MultiIndex or single-RIC flat history columns.

    Unknown shapes raise rather than silently assigning prices to a RIC.
    Missing observations stay missing, including absent requested fields.
    """
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = {}
    for i, column in enumerate(frame.columns):
        parts = [str(x) for x in column] if isinstance(column, tuple) else [str(column)]
        matched_fields = [x for x in parts if x in fields]
        matched_rics = [x for x in parts if x in requested]
        if len(matched_rics) == 0 and len(requested) == 1:
            matched_rics = requested
        if len(matched_fields) != 1 or len(matched_rics) != 1:
            raise ValueError(f"Unrecognized history column: {column!r}")
        key = (matched_rics[0], matched_fields[0])
        values = pd.to_numeric(frame.iloc[:, i], errors="coerce")
        if key in result and not values.equals(result[key]):
            raise ValueError(f"Conflicting duplicate history column: {key}")
        result[key] = values
    out = pd.DataFrame(result)
    out.columns = pd.MultiIndex.from_tuples(out.columns, names=["RIC", "Field"])
    out.index = pd.to_datetime(out.index)
    # Daily vendor timestamps represent session dates; do not shift time zones.
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    out.index = out.index.normalize()
    if out.index.has_duplicates:
        raise ValueError("Duplicate daily timestamps; inspect the vendor response")
    return out.sort_index()


def atomic_pickle(payload, path):
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(path)


def to_long(options, allow_legacy_suffix=False):
    chunks = []
    if options.empty:
        return pd.DataFrame(columns=["date", "ric", "underlying", "expiry", "type", "strike", *FIELDS])
    for ric in options.columns.get_level_values("RIC").unique():
        contract = options.xs(ric, axis=1, level="RIC").reindex(columns=FIELDS).copy()
        contract.index.name = "date"
        contract = contract.reset_index()
        contract["ric"] = ric
        for key, value in parse_option_ric(ric, allow_legacy_suffix).items():
            contract[key] = value
        # Preserve both-missing rows within the requested history, but remove
        # post-expiry dates. Pre-listing status is unknown without reference data.
        contract = contract[contract["date"].dt.date <= parse_option_ric(ric, allow_legacy_suffix)["expiry"]]
        chunks.append(contract)
    return pd.concat(chunks, ignore_index=True)[
        ["date", "ric", "underlying", "expiry", "type", "strike", *FIELDS]
    ].sort_values(["date", "ric"]).reset_index(drop=True)


def run():
    import lseg.data as ld

    settings = dict(start=START, end=END, ticker_stock=STOCK, ticker=ROOT,
                    strike_step=STRIKE_STEP, fields=FIELDS, schema_version=3)
    if CACHE.exists():
        existing = pd.read_pickle(CACHE)
        if existing.get("settings") == settings and existing.get("complete"):
            print(f"Using completed cache: {CACHE.resolve()}", flush=True)
            print("Download this file and send it back for the website analysis.")
            return existing
        raise RuntimeError("An older/different cache exists. Rename it before running this script; do not reuse a SETTLE-only cache.")

    print("Connecting to the CodeBook data session...", flush=True)
    ld.open_session()
    try:
        stock_fields = ["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1"]
        raw_stock = ld.get_history(universe=[STOCK], fields=stock_fields,
                                   start=START, end=END, interval="daily")
        stock_frame = canonicalize(raw_stock, [STOCK], stock_fields)
        if stock_frame.empty:
            raise RuntimeError("No stock data returned; check your data access.")
        stock = stock_frame.xs(STOCK, axis=1, level="RIC")
        low, high = stock["LOW_1"].min(), stock["HIGH_1"].max()
        if not (pd.notna(low) and pd.notna(high) and 0 < low <= high):
            raise RuntimeError("Missing or invalid stock high/low range.")
        # Same full-window strike band as the instructor's starter.
        step_cents = round(STRIKE_STEP * 100)
        lo = max(step_cents, math.floor(low / STRIKE_STEP) * step_cents)
        hi = math.ceil(high / STRIKE_STEP) * step_cents
        candidates = []
        for expiry in pd.date_range(START, END, freq="W-FRI"):
            for cents in range(lo, hi + 1, step_cents):
                for offset in (0, 12):
                    candidates.append(make_option_ric(ROOT, expiry, cents, "Put" if offset else "Call"))
        progress = {"settings": settings, "candidates": candidates, "done": [], "frames": [], "audit": []}
        if CHECKPOINT.exists():
            progress = pd.read_pickle(CHECKPOINT)
            if progress["settings"] != settings or progress["candidates"] != candidates:
                raise RuntimeError("Checkpoint settings differ; rename the checkpoint before restarting.")
        else:
            for old_path in (Path("option_pipeline_data_partial.pkl"), Path("option_pipeline_data.pkl")):
                if old_path.exists():
                    reuse_calls(progress, old_path)
                    break
        done = set(progress["done"])
        remaining = [ric for ric in candidates if ric not in done]
        print(f"Window: {START} to {END}; candidate RICs: {len(candidates)}; remaining: {len(remaining)}", flush=True)
        print("Candidates may never have been listed; empty responses are not zero prices.", flush=True)

        def request(batch):
            time.sleep(0.2)
            raw = ld.get_history(universe=batch, fields=FIELDS,
                                 start=START, end=END, interval="daily")
            return canonicalize(raw, batch, FIELDS)

        def record(frame, batch):
            if not frame.empty:
                progress["frames"].append(frame)
            for ric in batch:
                returned = not frame.empty and ric in frame.columns.get_level_values("RIC")
                sub = frame.xs(ric, axis=1, level="RIC").reindex(columns=FIELDS) if returned else pd.DataFrame(columns=FIELDS)
                counts = {f"n_{field}": int(sub[field].notna().sum()) for field in FIELDS}
                progress["audit"].append(dict(ric=ric, status="observed" if any(counts.values()) else "no_observations", **counts))
                progress["done"].append(ric)

        for start in range(0, len(remaining), BATCH_SIZE):
            batch = remaining[start:start + BATCH_SIZE]
            try:
                frame = request(batch)
                record(frame, batch)
            except Exception as batch_error:
                print(f"Batch failed ({type(batch_error).__name__}): {str(batch_error)[:600]}; trying individual RICs.", flush=True)
                for ric in batch:
                    try:
                        record(request([ric]), [ric])
                    except Exception as error:
                        # Keep failed requests unresolved so rerunning retries them.
                        progress["audit"].append(dict(ric=ric, status="request_failed", error_type=type(error).__name__, error_message=str(error)))
                        print(f"FAILED {ric}: {type(error).__name__}: {str(error)[:600]}", flush=True)
            atomic_pickle(progress, CHECKPOINT)
            print(f"Processed {min(start + BATCH_SIZE, len(remaining))}/{len(remaining)} remaining candidates; checkpoint saved.", flush=True)

        options = pd.concat(progress["frames"], axis=1) if progress["frames"] else pd.DataFrame()
        if not options.empty:
            options = options.loc[:, ~options.columns.duplicated()].sort_index()
        long = to_long(options)
        counts = {field: int(long[field].notna().sum()) for field in FIELDS}
        failures = len(candidates) - len(set(progress["done"]))
        payload = dict(stock=stock, options=options, ticker=ROOT, settings=settings,
                       fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                       candidate_rics=candidates, request_audit=progress["audit"],
                       long=long, listing_universe_verified=False,
                       complete=(failures == 0 and all(counts.values())))
        # Keep the teacher's expected payload keys, plus provenance and audit.
        output = CACHE if payload["complete"] else Path("option_pipeline_data_partial_v2.pkl")
        atomic_pickle(payload, output)
        long.to_csv("option_prices_long_v2.csv", index=False)
        pd.DataFrame(progress["audit"]).to_csv("option_request_audit_v2.csv", index=False)
        n_observed = long.loc[long[FIELDS].notna().any(axis=1), "ric"].nunique()
        print(f"Observed contracts: {n_observed}; MID observations: {counts['MID_PRICE']}; trade observations: {counts['TRDPRC_1']}; unresolved requests: {failures}", flush=True)
        print(f"Saved: {output.resolve()}", flush=True)
        if not payload["complete"]:
            print("INCOMPLETE: send this output summary and the partial cache for diagnosis. Do not treat missing MID/trade access as market illiquidity.", flush=True)
        else:
            print("Download option_pipeline_data_v2.pkl from the left file panel and send it back.", flush=True)
        return payload
    finally:
        ld.close_session()


if __name__ == "__main__":
    payload = run()
