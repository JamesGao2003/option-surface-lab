"""Nightly tracker for the investment thesis (FINTECH 535, Final Project Checkpoint 1).

Thesis being tracked: a sharp few-day drop in the S&P 500 inside an uptrend overshoots, so buying it
and holding for a few days gets paid.

The rule (fixed when the thesis was written):
  signal  SPY's 2-day RSI closes below 10 while the close is above its 200-day average
  entry   buy at the next session's open
  exit    sell at the open after the first close back above the 5-day average
Returns are open to open, with any dividend that went ex while the position was held.

Runs in the same GitHub Action as final/plan_orders.py, every night at 10 PM New York.

Inputs : thesis/data/spy_daily.csv, thesis/data/spy_div.csv   (history kept in the repo, so a dead
                                                               download never empties the chart)
         Yahoo's daily chart for SPY, Stooq as the backup      (new days, when the network answers)
Outputs: the two CSV files above, extended
         thesis/tracker.json                                   (what the page reads)

Standard library only.
"""
import csv, json, math, statistics, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "thesis" / "data"
RULE = {"symbol": "SPY", "rsi_n": 2, "entry_below": 10, "exit_avg": 5, "trend_avg": 200}
COST = 0.0005                    # round trip: 2 bp of slippage at each open plus commission, on a $700 ETF with a 1 cent spread
INCEPTION = "2026-11-23"         # thesis written after this close; trades entered later are the live record
# wrong-if thresholds, fixed when the thesis was written
KILL_LAST_N = 20                 # 1. the last 20 closed trades add up to zero or less
KILL_DRAWDOWN = -0.15            # 2. the rule's own equity is 15% or more below its high
KILL_LIVE_N = 10                 # 3. my own record: average live trade at or below zero once 10 have closed


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (thesis tracker; student project)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def fetch_yahoo(symbol, query):
    """({date: (open, close)}, {ex-date: dividend}) from Yahoo's chart endpoint. Prices are as traded, not adjusted."""
    d = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/%s?%s&interval=1d&events=div" % (symbol, query)))["chart"]["result"][0]
    day = lambda t: datetime.fromtimestamp(t - 5 * 3600, timezone.utc).strftime("%Y-%m-%d")   # the bar is stamped at the New York open
    q = d["indicators"]["quote"][0]
    bars = {day(t): (float(o), float(c)) for t, o, c in zip(d.get("timestamp") or [], q.get("open") or [], q.get("close") or []) if o is not None and c is not None}
    divs = {day(int(v["date"])): float(v["amount"]) for v in ((d.get("events") or {}).get("dividends") or {}).values()}
    return bars, divs


def fetch_stooq(symbol):
    out = {}
    for line in get("https://stooq.com/q/d/l/?s=%s.us&i=d" % symbol.lower()).splitlines()[1:]:
        p = line.split(",")
        try:
            out[p[0]] = (float(p[1]), float(p[4]))
        except (IndexError, ValueError):
            pass
    return out


def read_bars():
    bars, divs = {}, {}
    if (DATA / "spy_daily.csv").exists():
        for r in list(csv.reader((DATA / "spy_daily.csv").read_text().splitlines()))[1:]:
            bars[r[0]] = (float(r[1]), float(r[2]))
    if (DATA / "spy_div.csv").exists():
        for r in list(csv.reader((DATA / "spy_div.csv").read_text().splitlines()))[1:]:
            divs[r[0]] = float(r[1])
    return bars, divs


def write_bars(bars, divs):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "spy_daily.csv").write_text("date,open,close\n" + "".join("%s,%.4f,%.4f\n" % (d, *bars[d]) for d in sorted(bars)))
    (DATA / "spy_div.csv").write_text("ex_date,dividend\n" + "".join("%s,%.4f\n" % (d, divs[d]) for d in sorted(divs)))


def indicators(dates, close, rule):
    """2-day RSI (Wilder smoothing) and the two moving averages, on closes as traded."""
    n = rule["rsi_n"]; rsi = [None] * len(dates); up = dn = 0.0
    for i in range(1, len(dates)):
        ch = close[i] - close[i - 1]
        up = (up * (n - 1) + max(ch, 0.0)) / n; dn = (dn * (n - 1) + max(-ch, 0.0)) / n
        if i >= 10:
            rsi[i] = 100.0 if dn == 0 else 100.0 - 100.0 / (1.0 + up / dn)

    def sma(w):
        out = [None] * len(dates); s = 0.0
        for i, c in enumerate(close):
            s += c
            if i >= w:
                s -= close[i - w]
            if i >= w - 1:
                out[i] = s / w
        return out
    return rsi, sma(rule["exit_avg"]), (sma(rule["trend_avg"]) if rule["trend_avg"] else [0.0] * len(dates))


def run_rule(dates, opn, close, divs, rule):
    """Walk the rule through history. Returns (closed trades, open position or None, pending entry flag, indicator lists)."""
    rsi, fast, slow = indicators(dates, close, rule)
    n = len(dates); trades = []; open_pos = None; pending = False
    i = max(rule["trend_avg"], 10)
    while i < n:
        if rsi[i] is not None and slow[i] is not None and rsi[i] < rule["entry_below"] and close[i] > slow[i]:
            if i == n - 1:
                pending = True                       # signal on the last bar: buy at tomorrow's open
                break
            j = i + 1; k = j
            while k < n and not close[k] > fast[k]:
                k += 1
            if k >= n - 1:                           # still held, or the exit close is the last bar and the sale is tomorrow
                open_pos = {"signal": dates[i], "in": dates[j], "entry": opn[j], "days": n - 1 - j, "exit_tomorrow": k == n - 1,
                            "mark": close[-1] / opn[j] - 1}
                break
            x = k + 1
            dv = sum(a for d, a in divs.items() if dates[j] < d <= dates[x])
            trades.append({"signal": dates[i], "in": dates[j], "out": dates[x], "entry": opn[j], "exit": opn[x], "div": dv,
                           "ret": (opn[x] + dv) / opn[j] - 1, "days": x - j, "rsi": rsi[i]})
            i = x
        else:
            i += 1
    return trades, open_pos, pending, (rsi, fast, slow)


def summarise(trades, years=None):
    r = [t["ret"] for t in trades]
    if len(r) < 2:
        return {"trades": len(r), "avg_pct": round(100 * r[0], 2) if r else None}
    sd = statistics.stdev(r)
    out = {"trades": len(r), "avg_pct": round(100 * statistics.mean(r), 2), "median_pct": round(100 * statistics.median(r), 2),
           "win_pct": round(100 * sum(x > 0 for x in r) / len(r), 0), "t_stat": round(statistics.mean(r) / sd * math.sqrt(len(r)), 1),
           "worst_pct": round(100 * min(r), 1), "best_pct": round(100 * max(r), 1), "avg_days": round(statistics.mean(t["days"] for t in trades), 1),
           "avg_win_pct": round(100 * statistics.mean([x for x in r if x > 0] or [0]), 2), "avg_loss_pct": round(100 * statistics.mean([x for x in r if x <= 0] or [0]), 2)}
    if years:
        out["per_year"] = round(len(r) / years, 1); out["sum_per_year_pct"] = round(100 * sum(r) / years, 1)
    return out


def main():
    notes = []
    bars, divs = read_bars()
    try:
        # the first run on an empty folder pulls everything; after that only the last three months are refreshed
        new, nd = fetch_yahoo(RULE["symbol"], "range=3mo" if len(bars) > 1000 else "period1=725846400&period2=4102444800")
        added = sum(1 for d in new if d not in bars)
        bars.update(new); divs.update(nd)
        notes.append("Yahoo %s: %d bars read, %d new, last %s" % (RULE["symbol"], len(new), added, max(new) if new else "none"))
    except Exception as exc:
        notes.append("Yahoo %s unavailable (%s)" % (RULE["symbol"], type(exc).__name__))
        try:
            new = fetch_stooq(RULE["symbol"])
            fresh = {d: v for d, v in new.items() if d not in bars and d > max(bars)}
            bars.update(fresh)
            notes.append("Stooq backup: %d new bars, last %s" % (len(fresh), max(new) if new else "none"))
        except Exception as exc2:
            notes.append("Stooq unavailable too (%s); using the stored history" % type(exc2).__name__)
    if len(bars) < 300:
        print("not enough price history to run the rule"); sys.exit(1)
    write_bars(bars, divs)

    dates = sorted(bars); opn = [bars[d][0] for d in dates]; close = [bars[d][1] for d in dates]
    trades, open_pos, pending, (rsi, fast, slow) = run_rule(dates, opn, close, divs, RULE)
    span = lambda a, b: (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days / 365.25
    all_years = span(dates[RULE["trend_avg"]], dates[-1])

    # ---- the record ------------------------------------------------------------------------------
    eq = 1.0; peak = 1.0; worst_dd = 0.0; curve = []
    for t in trades:
        eq *= 1 + t["ret"] - COST; peak = max(peak, eq); t["equity"] = eq; t["dd"] = eq / peak - 1
        worst_dd = min(worst_dd, t["dd"]); curve.append({"date": t["out"], "equity": round(eq, 4)})
    periods = [("Before the rule was published", "1993-01-01", "2008-12-31"), ("After publication", "2009-01-01", "2019-12-31"),
               ("2020 to the thesis date", "2020-01-01", INCEPTION), ("Last two years before the thesis", "2024-11-23", INCEPTION)]
    by_period = []
    for label, a, b in periods:
        sub = [t for t in trades if a <= t["in"] <= b]
        if sub:
            by_period.append(dict(label=label, start=max(a, dates[RULE["trend_avg"]]), end=min(b, dates[-1]), **summarise(sub, span(max(a, dates[RULE["trend_avg"]]), min(b, dates[-1])))))
    by_year = []
    for y in sorted({t["in"][:4] for t in trades}):
        sub = [t for t in trades if t["in"][:4] == y]
        by_year.append({"year": y, "trades": len(sub), "sum_pct": round(100 * sum(t["ret"] for t in sub), 1), "wins": sum(t["ret"] > 0 for t in sub)})
    held_days = sum(t["days"] for t in trades); sessions = len(dates) - RULE["trend_avg"]
    all_ret = [opn[i + 1] / opn[i] - 1 for i in range(RULE["trend_avg"], len(dates) - 1)]
    stats = dict(summarise(trades, all_years), start=dates[RULE["trend_avg"]], end=dates[-1], years=round(all_years, 1),
                 time_in_market_pct=round(100 * held_days / sessions, 1), per_day_held_bp=round(1e4 * sum(t["ret"] for t in trades) / held_days, 1),
                 per_day_always_in_bp=round(1e4 * statistics.mean(all_ret), 1), equity_multiple_after_costs=round(eq, 2),
                 worst_drawdown_pct=round(100 * worst_dd, 1), cost_per_round_trip_bp=round(1e4 * COST, 1),
                 cost_per_year_pct=round(100 * COST * len(trades) / all_years, 2), losing_years=[y["year"] for y in by_year if y["sum_pct"] < 0])
    worst = sorted(trades, key=lambda t: t["ret"])[:5]

    # the same idea with the dials turned: is it one lucky setting?
    variants = []
    for label, change in (("RSI(2) below 5", {"entry_below": 5}), ("RSI(2) below 10 (the rule)", {}), ("RSI(2) below 15", {"entry_below": 15}), ("RSI(2) below 20", {"entry_below": 20}),
                          ("Exit above the 3-day average", {"exit_avg": 3}), ("Exit above the 10-day average", {"exit_avg": 10}),
                          ("Trend filter: 100-day average", {"trend_avg": 100}), ("No trend filter", {"trend_avg": 0})):
        tr, _, _, _ = run_rule(dates, opn, close, divs, dict(RULE, **change))
        variants.append(dict(label=label, **summarise([t for t in tr if t["in"] >= dates[RULE["trend_avg"]]], all_years)))

    # ---- wrong-if tests, checked every night -----------------------------------------------------
    last_n = trades[-KILL_LAST_N:]; sum_last = sum(t["ret"] for t in last_n)
    roll = [sum(t["ret"] for t in trades[i - KILL_LAST_N + 1:i + 1]) for i in range(KILL_LAST_N - 1, len(trades))]
    live = [t for t in trades if t["in"] > INCEPTION]
    live_avg = statistics.mean(t["ret"] for t in live) if live else None
    tests = [
        {"id": "last20", "label": "The last %d closed trades add up to 0 or less" % KILL_LAST_N, "value": "%+.1f%%" % (100 * sum_last),
         "threshold": "0% or less", "tripped": sum_last <= 0, "as_of": last_n[-1]["out"],
         "history": "true after %.0f%% of trades since 1993" % (100 * sum(x <= 0 for x in roll) / len(roll))},
        {"id": "drawdown", "label": "The rule's equity is 15% or more below its high", "value": "%.1f%%" % (100 * trades[-1]["dd"]),
         "threshold": "-15% or worse", "tripped": trades[-1]["dd"] <= KILL_DRAWDOWN, "as_of": trades[-1]["out"],
         "history": "worst so far %.1f%%" % (100 * worst_dd)},
        {"id": "live", "label": "My live trades average 0 or less once %d have closed" % KILL_LIVE_N,
         "value": ("%+.2f%% over %d" % (100 * live_avg, len(live))) if live else "no live trade closed yet",
         "threshold": "0% or less", "tripped": len(live) >= KILL_LIVE_N and live_avg <= 0, "as_of": dates[-1], "history": "%d of %d so far" % (len(live), KILL_LIVE_N)},
    ]

    # ---- tonight ---------------------------------------------------------------------------------
    i = len(dates) - 1; above = close[i] > slow[i]
    if open_pos:
        state = "IN A TRADE"
        detail = ("Bought at the %s open at %.2f, now %+.1f%% after %d session%s. " % (open_pos["in"], open_pos["entry"], 100 * open_pos["mark"], open_pos["days"] + 1, "" if open_pos["days"] == 0 else "s")
                  + ("Today's close is back above the 5-day average, so it sells at tomorrow's open." if open_pos["exit_tomorrow"] else "It sells at the open after the first close above the 5-day average (%.2f)." % fast[i]))
    elif pending:
        state = "BUY AT THE NEXT OPEN"
        detail = "RSI(2) closed at %.1f, below 10, with the close above the 200-day average. The rule buys at the next open." % rsi[i]
    elif not above:
        state = "SWITCHED OFF"
        detail = "SPY closed at %.2f, below its 200-day average of %.2f, so the rule takes no new trades until it closes back above." % (close[i], slow[i])
    else:
        state = "WAITING"
        detail = "SPY is above its 200-day average and RSI(2) is %.1f. The rule buys after a close with RSI(2) below 10." % rsi[i]
    tonight = {"date": dates[i], "close": round(close[i], 2), "rsi2": round(rsi[i], 1), "avg5": round(fast[i], 2), "avg200": round(slow[i], 2),
               "above_trend": above, "pct_from_avg200": round(100 * (close[i] / slow[i] - 1), 1), "state": state, "detail": detail,
               "open_trade": open_pos and {k: (round(v, 4) if isinstance(v, float) else v) for k, v in open_pos.items()}}

    cut = lambda t: {"signal": t["signal"], "in": t["in"], "out": t["out"], "entry": round(t["entry"], 2), "exit": round(t["exit"], 2), "div": round(t["div"], 2),
                     "ret_pct": round(100 * t["ret"], 2), "days": t["days"], "rsi": round(t["rsi"], 1), "live": t["in"] > INCEPTION}
    first = max(0, len(dates) - 320)
    out = {
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "inception": INCEPTION, "rule": RULE,
        "definition": "Buy SPY at the open after a close with 2-day RSI below 10 and price above the 200-day average; sell at the open after the first close above the 5-day average.",
        "notes": notes, "tonight": tonight, "stats": stats, "by_period": by_period, "by_year": by_year, "variants": variants, "tests": tests,
        "worst_trades": [cut(t) for t in worst], "trades": [cut(t) for t in trades], "equity": curve,
        "series": [{"date": dates[k], "close": round(close[k], 2), "avg200": round(slow[k], 2), "avg5": round(fast[k], 2), "rsi2": round(rsi[k], 1)} for k in range(first, len(dates))],
        "live": {"trades": len(live), "avg_pct": None if live_avg is None else round(100 * live_avg, 2), "sum_pct": round(100 * sum(t["ret"] for t in live), 2)},
    }
    (ROOT / "thesis" / "tracker.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("updated_utc", "notes", "tonight", "stats", "by_period", "tests")}, indent=1))


if __name__ == "__main__":
    main()
