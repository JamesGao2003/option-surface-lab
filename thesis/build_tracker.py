"""Nightly tracker for the investment thesis (FINTECH 535, Final Project Checkpoint 1).

Thesis being tracked: Apple's options are priced for more movement than Apple delivers.
Tracker: Cboe's Apple VIX (VXAPL, the 30-day implied volatility) against Apple's own
21-session realised volatility, and the gap between them.

Runs in the same GitHub Action as final/plan_orders.py, every night at 10 PM New York.

Inputs : thesis/data/vxapl.csv, thesis/data/aapl_close.csv   (history kept in the repo, so a dead
                                                              download never empties the chart)
         price_history.json                                   (the course server's AAPL bars)
         FRED VXAPLCLS, Yahoo ^VXAPL and AAPL                 (new days, when the network answers)
Outputs: the two CSV files above, extended
         thesis/tracker.json                                  (what the page reads)

Standard library only.
"""
import csv, io, json, math, statistics, urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "thesis" / "data"
CONID = "265598"                 # AAPL in price_history.json
WINDOW = 21                      # sessions in one option month
INCEPTION = "2026-11-23"         # thesis written after this close; the live record counts from here
# wrong-if thresholds, fixed when the thesis was written (the page explains why they are slow ones)
KILL_YEAR_WINDOW = 250           # 1. one-year average of the settled gap at or below zero
KILL_YEAR_AVG = 0.0
KILL_SHARE_WINDOW = 120          # 2. the gap was positive on fewer than half of the last 120 sessions
KILL_SHARE = 50.0
KILL_LIVE_MIN = 42               # 3. my own record: average gap since inception at or below zero, once two option months exist
KILL_LIVE_AVG = 0.0


def read_csv(path):
    out = {}
    if path.exists():
        for row in csv.reader(path.read_text().splitlines()[1:]):
            if len(row) >= 2:
                try:
                    out[row[0]] = float(row[1])
                except ValueError:
                    pass
    return out


def write_csv(path, header, series):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [header] + ["%s,%s" % (d, ("%.4f" % series[d]).rstrip("0").rstrip(".")) for d in sorted(series)]
    path.write_text("\n".join(lines) + "\n")


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (thesis tracker; student project)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def fetch_fred(series):
    """{date: value} from FRED's public CSV. No key needed."""
    out = {}
    for row in csv.reader(io.StringIO(get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series))):
        if len(row) == 2 and row[0][:2] in ("19", "20"):
            try:
                out[row[0]] = float(row[1])
            except ValueError:      # FRED writes "." on holidays
                pass
    return out


def fetch_yahoo(symbol, rng):
    """{date: close} from Yahoo's chart endpoint."""
    d = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d" % (symbol, rng)))["chart"]["result"][0]
    out = {}
    for t, c in zip(d.get("timestamp") or [], d["indicators"]["quote"][0].get("close") or []):
        if c is not None:
            # the bar's timestamp is the New York open; five hours back from UTC lands on the right calendar day all year
            out[datetime.fromtimestamp(t - 5 * 3600, timezone.utc).strftime("%Y-%m-%d")] = float(c)
    return out


def main():
    notes = []
    iv = read_csv(DATA / "vxapl.csv")
    px = read_csv(DATA / "aapl_close.csv")

    for name, fn in (("FRED VXAPLCLS", lambda: fetch_fred("VXAPLCLS")), ("Yahoo ^VXAPL", lambda: fetch_yahoo("%5EVXAPL", "5d"))):
        try:
            new = fn()
            added = sum(1 for d in new if d not in iv)
            if name.startswith("FRED"):
                iv.update(new)                      # FRED is the series of record
            else:
                iv.update({d: v for d, v in new.items() if d not in iv})   # Yahoo only fills days FRED has not posted yet
            notes.append("%s: %d days read, %d new" % (name, len(new), added))
        except Exception as exc:
            notes.append("%s unavailable (%s); using the stored history" % (name, type(exc).__name__))

    try:
        new = fetch_yahoo("AAPL", "3mo")
        added = sum(1 for d in new if d not in px)
        px.update({d: v for d, v in new.items() if d not in px})
        notes.append("Yahoo AAPL: %d days read, %d new" % (len(new), added))
    except Exception as exc:
        notes.append("Yahoo AAPL unavailable (%s)" % type(exc).__name__)
    # the course server's bars win where both exist: they are what the order planner trades on
    try:
        bars = json.loads((ROOT / "price_history.json").read_text()).get(CONID, {}).get("price_history", {})
        server = {d: float(v["close"]) for d, v in bars.items() if isinstance(v, dict) and v.get("close") is not None}
        px.update(server)
        notes.append("price_history.json: %d server bars, last %s" % (len(server), max(server) if server else "none"))
    except Exception as exc:
        notes.append("price_history.json unreadable (%s)" % type(exc).__name__)

    write_csv(DATA / "vxapl.csv", "date,vxapl", iv)
    write_csv(DATA / "aapl_close.csv", "date,close", px)

    # ---- the series ------------------------------------------------------------------------------
    dates = sorted(d for d in px if d >= "2010-05-01")
    logret = {dates[i]: math.log(px[dates[i]] / px[dates[i - 1]]) for i in range(1, len(dates))}
    rows = []
    last_iv = None; last_iv_age = 99
    for i, d in enumerate(dates):
        if d in iv:
            last_iv, last_iv_age = iv[d], 0
        else:
            last_iv_age += 1
        v = last_iv if last_iv_age <= 3 else None            # carry a missing print at most three sessions
        rv = None
        if i >= WINDOW:
            rv = statistics.stdev(logret[x] for x in dates[i - WINDOW + 1:i + 1]) * math.sqrt(252) * 100
        rows.append({"date": d, "close": px[d], "iv": v, "rv": rv})
    for i, r in enumerate(rows):
        # settled gap: what the market implied 21 sessions ago, minus what Apple then did. Known only on day i.
        past = rows[i - WINDOW]["iv"] if i >= WINDOW else None
        r["implied_then"] = past
        r["gap_settled"] = (past - r["rv"]) if (past is not None and r["rv"] is not None) else None
        r["gap_live"] = (r["iv"] - r["rv"]) if (r["iv"] is not None and r["rv"] is not None) else None
    settled = [r for r in rows if r["gap_settled"] is not None]
    run = 0.0; pos = 0
    for j, r in enumerate(settled):
        run += r["gap_settled"]; pos += r["gap_settled"] > 0
        if j >= KILL_YEAR_WINDOW:
            run -= settled[j - KILL_YEAR_WINDOW]["gap_settled"]
        if j >= KILL_SHARE_WINDOW:
            pos -= settled[j - KILL_SHARE_WINDOW]["gap_settled"] > 0
        r["gap_avg250"] = run / KILL_YEAR_WINDOW if j >= KILL_YEAR_WINDOW - 1 else None
        r["share120"] = 100.0 * pos / KILL_SHARE_WINDOW if j >= KILL_SHARE_WINDOW - 1 else None

    # ---- history table ---------------------------------------------------------------------------
    by_year = {}
    for r in settled:
        by_year.setdefault(r["date"][:4], []).append(r)
    years = [{"year": y, "implied": round(statistics.mean(x["implied_then"] for x in v), 1), "realised": round(statistics.mean(x["rv"] for x in v), 1),
              "gap": round(statistics.mean(x["gap_settled"] for x in v), 1), "share_positive": round(100 * sum(x["gap_settled"] > 0 for x in v) / len(v), 0),
              "days": len(v)} for y, v in sorted(by_year.items())]
    gaps = [r["gap_settled"] for r in settled]
    stats = {"from": settled[0]["date"], "to": settled[-1]["date"], "days": len(settled), "mean_gap": round(statistics.mean(gaps), 2),
             "median_gap": round(statistics.median(gaps), 2), "share_positive": round(100 * sum(g > 0 for g in gaps) / len(gaps), 1),
             "mean_implied": round(statistics.mean(r["implied_then"] for r in settled), 1), "mean_realised": round(statistics.mean(r["rv"] for r in settled), 1),
             "gap_sd": round(statistics.stdev(gaps), 2)}
    yr = [r["gap_avg250"] for r in settled if r.get("gap_avg250") is not None]; sh = [r["share120"] for r in settled if r.get("share120") is not None]
    stats["year_avg_tripped_share"] = round(100 * sum(v <= KILL_YEAR_AVG for v in yr) / len(yr), 1)
    stats["share_tripped_share"] = round(100 * sum(v < KILL_SHARE for v in sh) / len(sh), 1)
    recent = [r for r in settled if r["date"] >= "%d%s" % (int(settled[-1]["date"][:4]) - 2, settled[-1]["date"][4:])]
    stats["last2y_mean_gap"] = round(statistics.mean(r["gap_settled"] for r in recent), 2)
    stats["last2y_share_positive"] = round(100 * sum(r["gap_settled"] > 0 for r in recent) / len(recent), 1)

    # ---- wrong-if tests, checked every night -----------------------------------------------------
    last = rows[-1]; last_settled = settled[-1]
    month_ends = [a for a, b in zip(settled, settled[1:] + [None]) if b is None or b["date"][:7] != a["date"][:7]]
    live = [r for r in settled if r["date"] > INCEPTION]       # months that ended after the thesis was written
    live_avg = statistics.mean(r["gap_settled"] for r in live) if live else None
    tests = [
        {"id": "year_avg", "label": "One-year average of the settled gap is at or below 0",
         "value": None if last_settled.get("gap_avg250") is None else round(last_settled["gap_avg250"], 2), "unit": "vol points",
         "threshold": "0 or less", "tripped": last_settled.get("gap_avg250") is not None and last_settled["gap_avg250"] <= KILL_YEAR_AVG,
         "as_of": last_settled["date"]},
        {"id": "share", "label": "The gap was positive on fewer than half of the last %d sessions" % KILL_SHARE_WINDOW,
         "value": None if last_settled.get("share120") is None else round(last_settled["share120"], 1), "unit": "% of sessions",
         "threshold": "below 50", "tripped": last_settled.get("share120") is not None and last_settled["share120"] < KILL_SHARE,
         "as_of": last_settled["date"]},
        {"id": "live", "label": "Average settled gap since I wrote this is at or below 0, once %d sessions have passed" % KILL_LIVE_MIN,
         "value": None if live_avg is None else round(live_avg, 2), "unit": "vol points (%d of %d sessions so far)" % (len(live), KILL_LIVE_MIN),
         "threshold": "0 or less", "tripped": len(live) >= KILL_LIVE_MIN and live_avg <= KILL_LIVE_AVG,
         "as_of": last_settled["date"]},
    ]

    def cut(r):
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()}
    out = {
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "inception": INCEPTION,
        "definition": "gap = Apple VIX (30-day implied volatility) minus Apple's 21-session realised volatility, both annualised, in volatility points. "
                      "Settled gap compares the Apple VIX from 21 sessions ago with the volatility realised since then.",
        "notes": notes,
        "latest": cut(last), "latest_settled": cut(last_settled),
        "stats": stats, "years": years, "tests": tests,
        "series": [cut(r) for r in rows if r["date"] >= "%d-01-01" % (int(last["date"][:4]) - 3)],
        "live": [cut(r) for r in rows if r["date"] >= INCEPTION],
        "monthly": [{"month": m["date"][:7], "gap": round(m["gap_settled"], 2)} for m in month_ends[-36:]],
    }
    (ROOT / "thesis" / "tracker.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("updated_utc", "notes", "latest", "latest_settled", "stats", "tests")}, indent=1))


if __name__ == "__main__":
    main()
