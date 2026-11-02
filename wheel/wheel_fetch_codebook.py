"""FINTECH 535 - The Wheel. Data pull for LSEG CodeBook.

Run in CodeBook:   %run wheel_fetch_codebook.py
Output:            wheel_source.json  (+ wheel_options_long.csv, wheel_request_audit.csv)
Download wheel_source.json from the left file panel when it finishes.

Read-only market data. Daily bars. Python 3.8 compatible (CodeBook).
Pulls AMZN stock daily OHLC plus every weekly put and call in a strike band
around each week's stock range: puts down to 85% of the week's low, calls up
to 120% of the week's high, $2.50 grid. Fields: BID, ASK, MID_PRICE, TRDPRC_1, ACVOL_UNS.
Weeks whose Friday was a market holiday (Jun 19, Jul 3 2026) expire Thursday.
Re-running resumes from wheel_fetch_checkpoint.pkl.
"""
from pathlib import Path
import datetime as dt
import json
import math
import pickle
import re
import time

import pandas as pd

START = "2026-04-06"
END = "2026-10-02"
STOCK = "AMZN.O"
ROOT = "AMZN"
STRIKE_STEP = 2.50
PUT_LOW = 0.85    # puts down to 85% of the week's low
CALL_HIGH = 1.20  # calls up to 120% of the week's high
BATCH_SIZE = 25
FIELDS = ["BID", "ASK", "MID_PRICE", "TRDPRC_1", "ACVOL_UNS"]
STOCK_FIELDS = ["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1", "ACVOL_UNS"]
HOLIDAY_FRIDAYS = {"2026-06-19", "2026-07-03"}
OUT = Path("wheel_source.json")
CHECKPOINT = Path("wheel_fetch_checkpoint.pkl")


def parse_option_ric(ric):
    m = re.fullmatch(r"(?P<root>[A-Z]+)(?P<m>[A-X])(?P<day>\d{2})(?P<yy>\d{2})(?P<strike>\d{5})\.U\^(?P<sm>[A-L])(?P<sy>\d{2})", str(ric))
    if not m:
        raise ValueError("Unsupported option RIC: %s" % ric)
    p = m.groupdict()
    code = ord(p["m"]) - ord("A")
    if p["sm"] != chr(ord("A") + code % 12) or p["yy"] != p["sy"]:
        raise ValueError("Bad expiry suffix: %s" % ric)
    return {"underlying": p["root"], "expiry": dt.date(2000 + int(p["yy"]), code % 12 + 1, int(p["day"])),
            "type": "Call" if code < 12 else "Put", "strike": int(p["strike"]) / 100.0}


def make_option_ric(root, expiry, cents, side):
    month_code = chr(ord("A") + expiry.month - 1)
    right_code = chr(ord(month_code) + (12 if side == "Put" else 0))
    ric = "%s%s%s%05d.U^%s%s" % (root, right_code, expiry.strftime("%d%y"), cents, month_code, expiry.strftime("%y"))
    parse_option_ric(ric)
    return ric


def canonicalize(frame, requested, fields):
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = {}
    for i, column in enumerate(frame.columns):
        parts = [str(x) for x in column] if isinstance(column, tuple) else [str(column)]
        mf = [x for x in parts if x in fields]
        mr = [x for x in parts if x in requested]
        if len(mr) == 0 and len(requested) == 1:
            mr = requested
        if len(mf) != 1 or len(mr) != 1:
            raise ValueError("Unrecognized history column: %r" % (column,))
        result[(mr[0], mf[0])] = pd.to_numeric(frame.iloc[:, i], errors="coerce")
    out = pd.DataFrame(result)
    out.columns = pd.MultiIndex.from_tuples(out.columns, names=["RIC", "Field"])
    out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    out.index = out.index.normalize()
    return out.sort_index()


def save_checkpoint(progress):
    tmp = CHECKPOINT.with_suffix(".tmp")
    with tmp.open("wb") as h:
        pickle.dump(progress, h, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(CHECKPOINT)


def run():
    import lseg.data as ld
    print("Connecting to the CodeBook data session...", flush=True)
    ld.open_session()
    try:
        raw_stock = ld.get_history(universe=[STOCK], fields=STOCK_FIELDS, start=(pd.Timestamp(START) - pd.Timedelta(days=7)).strftime("%Y-%m-%d"), end=END, interval="daily")
        stock = canonicalize(raw_stock, [STOCK], STOCK_FIELDS).xs(STOCK, axis=1, level="RIC")
        stock = stock.loc[(stock.index >= pd.Timestamp(START)) & (stock.index <= pd.Timestamp(END))]
        if stock.empty:
            raise RuntimeError("No stock data returned; check your data access.")
        print("Stock rows: %d (%s to %s)" % (len(stock), stock.index.min().date(), stock.index.max().date()), flush=True)

        # one expiry per week: Friday, or Thursday when the Friday is a holiday
        expiries = []
        for fri in pd.date_range(START, END, freq="W-FRI"):
            exp = fri - pd.Timedelta(days=1) if fri.strftime("%Y-%m-%d") in HOLIDAY_FRIDAYS else fri
            expiries.append(exp)
        step_c = int(round(STRIKE_STEP * 100))
        candidates = []
        week_bands = []
        for exp in expiries:
            wk_start = exp - pd.Timedelta(days=exp.weekday())
            wk = stock.loc[(stock.index >= wk_start) & (stock.index <= exp)]
            if wk.empty:
                continue
            lo_p = max(step_c, int(math.floor(wk["LOW_1"].min() * PUT_LOW / STRIKE_STEP) * step_c))
            hi_p = int(math.ceil(wk["HIGH_1"].max() / STRIKE_STEP) * step_c)
            lo_c = int(math.floor(wk["LOW_1"].min() / STRIKE_STEP) * step_c)
            hi_c = int(math.ceil(wk["HIGH_1"].max() * CALL_HIGH / STRIKE_STEP) * step_c)
            week_bands.append({"expiry": exp.strftime("%Y-%m-%d"), "put_strikes": [lo_p / 100.0, hi_p / 100.0], "call_strikes": [lo_c / 100.0, hi_c / 100.0]})
            for c in range(lo_p, hi_p + 1, step_c):
                candidates.append(make_option_ric(ROOT, exp.date(), c, "Put"))
            for c in range(lo_c, hi_c + 1, step_c):
                candidates.append(make_option_ric(ROOT, exp.date(), c, "Call"))
        settings = {"start": START, "end": END, "stock": STOCK, "root": ROOT, "strike_step": STRIKE_STEP, "fields": FIELDS,
                    "put_low": PUT_LOW, "call_high": CALL_HIGH, "interval": "daily", "holiday_fridays": sorted(HOLIDAY_FRIDAYS)}
        progress = {"settings": settings, "candidates": candidates, "done": [], "frames": [], "audit": []}
        if CHECKPOINT.exists():
            old = pd.read_pickle(CHECKPOINT)
            if old["settings"] == settings and old["candidates"] == candidates:
                progress = old
                print("Resuming from checkpoint: %d done" % len(progress["done"]), flush=True)
        done = set(progress["done"])
        remaining = [r for r in candidates if r not in done]
        print("Expiries: %d; candidate RICs: %d; remaining: %d" % (len(expiries), len(candidates), len(remaining)), flush=True)

        def request(batch):
            time.sleep(0.2)
            raw = ld.get_history(universe=batch, fields=FIELDS, start=START, end=END, interval="daily")
            return canonicalize(raw, batch, FIELDS)

        def record(frame, batch):
            if not frame.empty:
                progress["frames"].append(frame)
            for ric in batch:
                returned = (not frame.empty) and (ric in frame.columns.get_level_values("RIC"))
                sub = frame.xs(ric, axis=1, level="RIC").reindex(columns=FIELDS) if returned else pd.DataFrame(columns=FIELDS)
                counts = dict(("n_%s" % f, int(sub[f].notna().sum())) for f in FIELDS)
                a = {"ric": ric, "status": "observed" if any(counts.values()) else "no_observations"}
                a.update(counts)
                progress["audit"].append(a)
                progress["done"].append(ric)

        t0 = time.time()
        for s in range(0, len(remaining), BATCH_SIZE):
            batch = remaining[s:s + BATCH_SIZE]
            try:
                record(request(batch), batch)
            except Exception as e:
                print("Batch failed (%s): %s; trying one by one." % (type(e).__name__, str(e)[:300]), flush=True)
                for ric in batch:
                    try:
                        record(request([ric]), [ric])
                    except Exception as e2:
                        progress["audit"].append({"ric": ric, "status": "request_failed", "error": "%s: %s" % (type(e2).__name__, str(e2)[:300])})
                        print("FAILED %s: %s" % (ric, str(e2)[:200]), flush=True)
            save_checkpoint(progress)
            print("Processed %d/%d (%.0f s)" % (min(s + BATCH_SIZE, len(remaining)), len(remaining), time.time() - t0), flush=True)

        options = pd.concat(progress["frames"], axis=1) if progress["frames"] else pd.DataFrame()
        if not options.empty:
            options = options.loc[:, ~options.columns.duplicated()].sort_index()
        rows = []
        for ric in (options.columns.get_level_values("RIC").unique() if not options.empty else []):
            meta = parse_option_ric(ric)
            sub = options.xs(ric, axis=1, level="RIC").reindex(columns=FIELDS)
            for d, r in sub.iterrows():
                if d.date() > meta["expiry"]:
                    continue
                if r.isna().all():
                    continue
                row = {"date": d.strftime("%Y-%m-%d"), "ric": ric, "expiry": meta["expiry"].strftime("%Y-%m-%d"),
                       "type": meta["type"], "strike": meta["strike"]}
                for f in FIELDS:
                    v = r[f]
                    row[f] = None if pd.isna(v) else float(v)
                rows.append(row)
        stock_rows = []
        for d, r in stock.iterrows():
            row = {"date": d.strftime("%Y-%m-%d")}
            for f in STOCK_FIELDS:
                v = r.get(f)
                row[f] = None if (v is None or pd.isna(v)) else float(v)
            stock_rows.append(row)
        failures = [a for a in progress["audit"] if a["status"] == "request_failed"]
        payload = {"settings": settings, "fetched_at": dt.datetime.utcnow().isoformat() + "Z", "provider": "LSEG Workspace CodeBook",
                   "library": "lseg.data %s" % getattr(ld, "__version__", "?"), "stock": stock_rows, "options": rows,
                   "candidates": candidates, "week_bands": week_bands, "request_audit": progress["audit"],
                   "unresolved": len(failures)}
        OUT.write_text(json.dumps(payload, separators=(",", ":")))
        pd.DataFrame(rows).to_csv("wheel_options_long.csv", index=False)
        pd.DataFrame(progress["audit"]).to_csv("wheel_request_audit.csv", index=False)
        n_obs = len(set(r["ric"] for r in rows))
        print("Observed contracts: %d of %d candidates; option rows: %d; unresolved requests: %d" % (n_obs, len(candidates), len(rows), len(failures)), flush=True)
        print("Saved %s (%.1f MB). Download it from the left file panel." % (OUT.resolve(), OUT.stat().st_size / 1e6), flush=True)
        return payload
    finally:
        ld.close_session()


if __name__ == "__main__":
    payload = run()
