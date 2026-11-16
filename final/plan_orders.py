"""Nightly order planner for the live wheel (FINTECH 535, "Final Cycle").

Runs in a GitHub Action every night at 10 PM New York time, after the course server
(Sanji) has written the day's bars into price_history.json and, once he resolves
orders, the book into mkt/positions.json.

Inputs : price_history.json (daily bars the server writes, keyed by IB conid)
         mkt/positions.json  (the book after the last session; absent = all cash)
         mkt/fills.json      (what Sanji filled; absent = nothing yet)
Outputs: open_orders.json        (repo root, what the assignment asks for)
         mkt/open_orders.json    (same file, where the Sanji spec says it lives)
         final/run_log.json      (the inputs and the decision, for the page)
         final/order_history.json (every order ever written, for the page)

Standard library only, so the Action cannot fail on a pip install.
"""
import json, math, os, statistics, sys, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONFIG = {
    "conid": 265598,                 # AAPL, from price_history.json
    "symbol": "AAPL",
    "starting_cash": 50000.0,        # used for sizing until Sanji writes positions.json
    "contracts_max": 2,
    "sigma_window": 20,              # trading days of closes for realised vol
    "put_sigma_mult": 1.3,           # put strike = 1.3 weekly sigmas below the open
    "put_pct_floor": 3,              # never closer than 3% out of the money
    "put_pct_cap": 10,               # never further than 10%
    "crash_lookback": 10,            # skip a week after a fast drop
    "crash_threshold": -0.08,
    "min_days_to_expiry": 3,         # expiry Friday must be at least this many calendar days after the session
    "fee_per_contract": 0.65,
}

# NYSE full-day closures, so "for" is always a session Sanji will resolve.
NYSE_HOLIDAYS = {
    "2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
    "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}


def ny_now():
    """Current New York wall-clock time without pytz: UTC minus 5h, or 4h in DST."""
    utc = datetime.now(timezone.utc)
    y = utc.year
    # DST: second Sunday of March 2:00 to first Sunday of November 2:00 (approximate in UTC, fine for a 10 PM run)
    mar = date(y, 3, 8); mar = mar + timedelta(days=(6 - mar.weekday()) % 7)
    nov = date(y, 11, 1); nov = nov + timedelta(days=(6 - nov.weekday()) % 7)
    dst = date(y, mar.month, mar.day) <= utc.date() < date(y, nov.month, nov.day)
    return utc + timedelta(hours=-4 if dst else -5)


def is_session(d):
    return d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS


def next_session(after):
    d = after + timedelta(days=1)
    while not is_session(d):
        d += timedelta(days=1)
    return d


def expiry_friday(session):
    """The Friday of the session's week if it is far enough away, otherwise next Friday.
    A holiday Friday moves the listed expiry to Thursday."""
    fri = session + timedelta(days=(4 - session.weekday()) % 7)
    if (fri - session).days < CONFIG["min_days_to_expiry"]:
        fri += timedelta(days=7)
    if fri.isoformat() in NYSE_HOLIDAYS:
        fri -= timedelta(days=1)
    return fri


def load_json(path, default):
    p = ROOT / path
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return default


def fetch_stooq(symbol):
    """Fallback bars from Stooq (no key) when the server's file is stale. Returns {date: close}."""
    url = f"https://stooq.com/q/d/l/?s={symbol.lower()}.us&i=d"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            text = r.read().decode()
    except Exception as exc:  # network is optional
        return {}, f"stooq unavailable: {exc}"
    out = {}
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 5:
            try:
                out[parts[0]] = float(parts[4])
            except ValueError:
                pass
    return out, "stooq ok"


def main():
    now = ny_now()
    today = now.date()
    log = {"run_at_ny": now.strftime("%Y-%m-%d %H:%M"), "config": CONFIG, "notes": []}

    # ---- 1. prices -------------------------------------------------------------------------------
    hist = load_json("price_history.json", {})
    entry = hist.get(str(CONFIG["conid"]), {})
    bars = entry.get("price_history", {}) or {}
    closes = {d: v["close"] for d, v in bars.items() if isinstance(v, dict) and v.get("close") is not None}
    source = "price_history.json (IB daily bars via the course server)"
    last_bar = max(closes) if closes else None
    stale = (last_bar is None) or ((today - date.fromisoformat(last_bar)).days > 5)
    if stale:
        fallback, note = fetch_stooq(CONFIG["symbol"])
        log["notes"].append(f"server bars stale (last {last_bar}); {note}")
        if fallback:
            closes.update({d: c for d, c in fallback.items() if d not in closes})
            source = "price_history.json plus Stooq daily closes to fill the gap"
    dates = sorted(closes)
    if len(dates) < CONFIG["sigma_window"] + 1:
        log["decision"] = "SKIP"; log["reason"] = f"only {len(dates)} closes available; need {CONFIG['sigma_window'] + 1}"
        write_outputs([], log)
        return
    last_date = dates[-1]; last_close = closes[last_date]
    rets = [math.log(closes[dates[i]] / closes[dates[i - 1]]) for i in range(len(dates) - CONFIG["sigma_window"], len(dates))]
    daily_sigma = statistics.pstdev(rets)
    weekly_sigma = daily_sigma * math.sqrt(5)
    ret_lookback = closes[last_date] / closes[dates[-1 - CONFIG["crash_lookback"]]] - 1
    log.update({"price_source": source, "last_bar": last_date, "last_close": last_close,
                "daily_sigma": round(daily_sigma, 5), "weekly_sigma": round(weekly_sigma, 5),
                "ret_%dd" % CONFIG["crash_lookback"]: round(ret_lookback, 4), "bars_used": len(dates)})

    # ---- 2. the book -----------------------------------------------------------------------------
    positions = load_json("mkt/positions.json", None)
    fills = load_json("mkt/fills.json", [])
    cash = CONFIG["starting_cash"]; shares = 0; basis = None; short_puts = 0; short_calls = 0
    if isinstance(positions, dict):
        cash = float(positions.get("cash", cash))
        for p in positions.get("positions", []) or []:
            try:
                if p.get("contract") == "underlying" and int(p.get("underlying", 0)) == CONFIG["conid"]:
                    shares += int(p.get("qty", 0)); basis = p.get("avg_price", basis)
                elif p.get("contract") == "put" and int(p.get("qty", 0)) < 0:
                    short_puts += -int(p["qty"])
                elif p.get("contract") == "call" and int(p.get("qty", 0)) < 0:
                    short_calls += -int(p["qty"])
            except (TypeError, ValueError):
                continue
        log["book"] = {"source": "mkt/positions.json", "cash": cash, "shares": shares, "basis": basis, "short_puts": short_puts, "short_calls": short_calls}
    else:
        log["book"] = {"source": "no positions.json yet; assuming all cash", "cash": cash, "shares": 0, "basis": None, "short_puts": 0, "short_calls": 0}
    log["fills_seen"] = len(fills) if isinstance(fills, list) else 0

    # ---- 3. decide -------------------------------------------------------------------------------
    # a run before the open plans today; the normal 10 PM run plans the next session
    session = today if (now.hour < 9 and is_session(today)) else next_session(today)
    expiry = expiry_friday(session)
    orders = []
    if short_puts or short_calls:
        log["decision"] = "HOLD"; log["reason"] = "an option is still open; the wheel waits for expiry"
    elif shares >= 100:
        n = shares // 100
        # covered call: the lowest $5 strike at or above max(last close, basis) -> a bare number, no chain needed
        floor_px = max(last_close, basis or 0)
        strike = math.ceil(floor_px / 5) * 5
        orders.append({"id": f"{CONFIG['symbol'].lower()}-cc-{session.isoformat()}", "for": session.isoformat(), "order_type": "lmt", "action": "SHT",
                       "qty": n, "underlying": CONFIG["conid"], "contract": "call", "expiry": expiry.isoformat(), "strike": strike, "ref": "open", "lmt_prc": "mid"})
        log["decision"] = "SELL COVERED CALL"; log["reason"] = f"long {shares} shares at {basis}; call strike {strike} is the first $5 strike at or above max(close {last_close:.2f}, basis)"
    elif ret_lookback <= CONFIG["crash_threshold"]:
        log["decision"] = "SKIP"; log["reason"] = f"{CONFIG['symbol']} fell {ret_lookback:.1%} in {CONFIG['crash_lookback']} sessions; not selling a put into a fast drop this week"
    else:
        pct = CONFIG["put_sigma_mult"] * weekly_sigma * 100
        pct = int(round(min(CONFIG["put_pct_cap"], max(CONFIG["put_pct_floor"], pct))))
        est_strike = last_close * (1 - pct / 100)
        n = max(0, min(CONFIG["contracts_max"], int(cash // (est_strike * 100))))
        if n == 0:
            log["decision"] = "SKIP"; log["reason"] = f"cash {cash:,.0f} cannot secure one put near {est_strike:.0f}"
        else:
            orders.append({"id": f"{CONFIG['symbol'].lower()}-csp-{session.isoformat()}", "for": session.isoformat(), "order_type": "lmt", "action": "SHT",
                           "qty": n, "underlying": CONFIG["conid"], "contract": "put", "expiry": expiry.isoformat(), "strike": f"pct:-{pct}", "ref": "open", "lmt_prc": "mid"})
            log["decision"] = "SELL CASH-SECURED PUT"
            log["reason"] = (f"weekly sigma {weekly_sigma:.1%} x {CONFIG['put_sigma_mult']} = {CONFIG['put_sigma_mult'] * weekly_sigma:.1%}, "
                             f"clamped to {pct}% below the open; {n} contract(s) secured by about ${est_strike * 100 * n:,.0f} of ${cash:,.0f} cash")
    log["session"] = session.isoformat(); log["expiry"] = expiry.isoformat()
    write_outputs(orders, log)


def write_outputs(orders, log):
    txt = json.dumps(orders, indent=2) + "\n"
    (ROOT / "open_orders.json").write_text(txt)
    (ROOT / "mkt").mkdir(exist_ok=True)
    (ROOT / "mkt" / "open_orders.json").write_text(txt)
    log["orders"] = orders
    (ROOT / "final" / "run_log.json").write_text(json.dumps(log, indent=2) + "\n")
    hist_path = ROOT / "final" / "order_history.json"
    history = load_json("final/order_history.json", [])
    history = [h for h in history if h.get("run_at_ny") != log["run_at_ny"]]
    history.append({"run_at_ny": log["run_at_ny"], "decision": log.get("decision"), "reason": log.get("reason"),
                    "last_close": log.get("last_close"), "weekly_sigma": log.get("weekly_sigma"), "orders": orders})
    hist_path.write_text(json.dumps(history[-400:], indent=2) + "\n")
    print(json.dumps(log, indent=1))


if __name__ == "__main__":
    main()
