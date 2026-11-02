"""Wheel backtest engine (FINTECH 535, "The Wheel").

Sources:
  --source amzn  (default)  wheel_source.json pulled from LSEG with wheel_fetch.py:
                            daily BID / ASK / MID_PRICE / TRDPRC_1 / ACVOL_UNS per weekly put and call,
                            plus AMZN.O daily OHLC.
  --source uuuu             the Assignment 1.1 UUUU cache (daily MID_PRICE / TRDPRC_1, no bid/ask).

Run:  python engine.py                      -> book.json, book.js, blotter.csv, ledger.csv, decisions.csv, variants.json
      python engine.py --haircut 0.05       -> stress run only (fills 5c worse), printed, not written
"""
import argparse, copy, csv, json, math
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

BASE_CONFIG = {
    "put_otm": 0.95,            # target put strike: highest strike at or below 95% of the close
    "put_steps_down": 2,        # if that strike has no usable quote, try up to 2 strikes lower
    "call_floor": "basis",      # covered-call strike must be >= max(close, assignment strike); "spot" ignores the basis
    "call_steps_up": 2,         # if the first call strike has no usable quote, try up to 2 strikes higher
    "min_premium": 0.05,        # never sell an option for less than 5 cents
    "fee_per_contract": 0.65,   # per contract per order; nothing charged on assignment / exercise
    "fill_rule": "sell at the closing BID when a two-sided quote exists, otherwise at the closing MID; marks at MID",
    "settlement": "stock close on the last trading day on or before the expiry date",
}
SOURCES = {
    "amzn": {"underlying": "AMZN", "stock_ric": "AMZN.O", "initial_cash": 50000.0, "max_contracts": 2, "file": "wheel_source.json"},
    "uuuu": {"underlying": "UUUU", "stock_ric": "UUUU.K", "initial_cash": 15000.0, "max_contracts": 10, "file": "../option_prices_long.csv"},
}


def nan(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def load(source, path=None):
    """Return (stock DataFrame indexed by date with close/open/high/low[/volume], quotes dict, meta)."""
    if source == "uuuu":
        opt = pd.read_csv(ROOT / "option_prices_long.csv")
        snap = json.load(open(ROOT / "data_snapshot.json"))
        stock = pd.DataFrame(snap["stock"], columns=["date", "open", "high", "low", "close"])
        stock["date"] = pd.to_datetime(stock["date"]); stock = stock.set_index("date").sort_index()
        quotes = {}
        for r in opt.itertuples(index=False):
            mid = None if nan(r.MID_PRICE) else float(r.MID_PRICE)
            trd = None if nan(r.TRDPRC_1) else float(r.TRDPRC_1)
            quotes[(pd.Timestamp(r.date), pd.Timestamp(r.expiry), r.type, float(r.strike))] = {"bid": None, "ask": None, "mid": mid, "trade": trd, "vol": None, "ric": r.ric}
        meta = {"provider": "LSEG Workspace CodeBook", "file": "option_prices_long.csv + data_snapshot.json (Assignment 1.1 cache)", "fields": ["MID_PRICE", "TRDPRC_1"], "bar": "daily close", "has_bid_ask": False, "audit": None}
        return stock, quotes, meta
    src = json.load(open(path or (HERE / SOURCES["amzn"]["file"])))
    stock = pd.DataFrame(src["stock"]).rename(columns={"OPEN_PRC": "open", "HIGH_1": "high", "LOW_1": "low", "TRDPRC_1": "close", "ACVOL_UNS": "volume"})
    stock["date"] = pd.to_datetime(stock["date"]); stock = stock.set_index("date").sort_index()
    stock = stock.dropna(subset=["close"])
    quotes = {}
    for r in src["options"]:
        bid, ask, mid = r.get("BID"), r.get("ASK"), r.get("MID_PRICE")
        if nan(mid) and not nan(bid) and not nan(ask):
            mid = (bid + ask) / 2
        quotes[(pd.Timestamp(r["date"]), pd.Timestamp(r["expiry"]), r["type"], float(r["strike"]))] = {
            "bid": None if nan(bid) else float(bid), "ask": None if nan(ask) else float(ask), "mid": None if nan(mid) else float(mid),
            "trade": None if nan(r.get("TRDPRC_1")) else float(r["TRDPRC_1"]), "vol": None if nan(r.get("ACVOL_UNS")) else float(r["ACVOL_UNS"]), "ric": r["ric"]}
    audit = src.get("request_audit", [])
    meta = {"provider": src.get("provider", "LSEG Workspace"), "library": src.get("library"), "fetched_at": src.get("fetched_at"), "file": "wheel_source.json",
            "fields": src["settings"]["fields"], "bar": "daily close", "has_bid_ask": True,
            "audit": {"candidates": len(src.get("candidates", [])), "observed": sum(1 for a in audit if a.get("status") == "observed"),
                      "no_observations": sum(1 for a in audit if a.get("status") == "no_observations"),
                      "request_failed": sum(1 for a in audit if a.get("status") == "request_failed")},
            "settings": src["settings"]}
    return stock, quotes, meta


def run(source="amzn", haircut=0.0, call_floor=None, path=None, config_overrides=None):
    cfg = copy.deepcopy(BASE_CONFIG); cfg.update(SOURCES[source]); cfg.pop("file", None)
    if call_floor: cfg["call_floor"] = call_floor
    if config_overrides: cfg.update(config_overrides)
    stock, quotes, meta = load(source, path)
    days = list(stock.index)
    close = stock["close"]
    strikes = sorted({k[3] for k in quotes})
    expiries = sorted({k[1] for k in quotes})
    has_ba = meta["has_bid_ask"]

    def q(d, exp, typ, k):
        return quotes.get((d, exp, typ, k))

    def usable(qq):
        """A quote we are willing to sell on. Returns (fill, reason)."""
        if qq is None: return None, "no quote"
        if has_ba:
            b, a = qq["bid"], qq["ask"]
            if b is None or a is None: return None, "one-sided quote"
            if b <= 0: return None, "zero bid"
            if a < b: return None, "crossed quote"
            if b < cfg["min_premium"]: return None, "bid %.2f under 5c" % b
            if qq["mid"] and (a - b) / qq["mid"] > 0.5: return None, "spread %.0f%% of mid" % (100 * (a - b) / qq["mid"])
            return b, "bid"
        m = qq["mid"]
        if m is None: return None, "no quote"
        if m < cfg["min_premium"]: return None, "mid %.3f under 5c" % m
        return m, "mid"

    def mark_of(d, exp, typ, k):
        qq = q(d, exp, typ, k)
        return None if (qq is None or qq["mid"] is None) else qq["mid"]

    def week_expiry(d):
        cands = [e for e in expiries if d < e <= d + pd.Timedelta(days=6) and e.isocalendar()[1] == d.isocalendar()[1]]
        return cands[0] if cands else None

    def settle_day(exp):
        prior = [x for x in days if x <= exp]
        return prior[-1] if prior else None

    # entry day = first trading day of each ISO week
    entry_days, seen = [], set()
    for d in days:
        w = (d.isocalendar()[0], d.isocalendar()[1])
        if w not in seen:
            seen.add(w); entry_days.append(d)

    cash = cfg["initial_cash"]; shares = 0; basis = None
    short_put = None; short_call = None
    blotter, ledger, decisions, cycles = [], [], [], []
    counter = {"id": 0}
    tot = {"premium": 0.0, "fees": 0.0}
    stats = {"puts_sold": 0, "puts_expired": 0, "puts_assigned": 0, "calls_sold": 0, "calls_expired": 0, "calls_called_away": 0, "weeks_skipped": 0, "weeks_holding_without_call": 0}
    est_marks = {"n": 0}
    cycle = None  # current wheel cycle: starts when puts are sold from flat, ends when called away

    def book(d, instrument, side, qty, fill, cash_delta, note, limit=None, fee=0.0, group=None, bid=None, ask=None, trade=None):
        nonlocal cash
        counter["id"] += 1; cash += cash_delta
        blotter.append({"id": counter["id"], "date": d.strftime("%Y-%m-%d"), "instrument": instrument, "side": side, "qty": qty,
                        "bid": bid, "ask": ask, "trade_print": trade, "limit": limit, "fill": fill, "fee": round(fee, 2),
                        "cash_delta": round(cash_delta, 2), "cash_after": round(cash, 2), "note": note, "week": group})

    bh_shares, bh_cash, bh_started = 0, cfg["initial_cash"], False
    first_entry = entry_days[0]

    for d in days:
        spot = float(close.loc[d]); events = []
        if not bh_started and d >= first_entry:
            bh_shares = int(bh_cash // spot); bh_cash -= bh_shares * spot; bh_started = True
        # ---- 1. settle expiring options --------------------------------------------------------
        for which in ("put", "call"):
            pos = short_put if which == "put" else short_call
            if not pos or settle_day(pos["expiry"]) != d: continue
            k, n, wk = pos["strike"], pos["qty"], pos["expiry"].strftime("%Y-%m-%d")
            if which == "put":
                if spot < k:
                    book(d, pos["ric"], "ASSIGN", n, 0.0, 0.0, "Put finished in the money (close %.2f < %.2f strike): assigned %d x 100 shares" % (spot, k, n), group=wk)
                    book(d, cfg["stock_ric"], "BUY", n * 100, k, -k * n * 100, "Shares put to us at the %.2f strike; effective basis %.2f after the put premium" % (k, k - pos["premium"]), group=wk)
                    shares += n * 100; basis = k; stats["puts_assigned"] += 1; events.append("assigned")
                    if cycle: cycle["assigned"] = d.strftime("%Y-%m-%d"); cycle["basis"] = k
                else:
                    book(d, pos["ric"], "EXPIRE", n, 0.0, 0.0, "Put finished out of the money (close %.2f >= %.2f): kept $%s premium" % (spot, k, format(pos["premium"] * n * 100, ",.0f")), group=wk)
                    stats["puts_expired"] += 1; events.append("put expired")
                    if cycle: cycle["puts_expired"] = cycle.get("puts_expired", 0) + 1
                short_put = None
            else:
                if spot > k:
                    book(d, pos["ric"], "ASSIGN", n, 0.0, 0.0, "Call finished in the money (close %.2f > %.2f): shares called away" % (spot, k), group=wk)
                    book(d, cfg["stock_ric"], "SELL", n * 100, k, k * n * 100, "Shares delivered at the %.2f strike (bought at %.2f)" % (k, basis), group=wk)
                    stock_pnl = (k - basis) * n * 100
                    shares -= n * 100; stats["calls_called_away"] += 1; events.append("called away")
                    if cycle:
                        cycle.update({"called_away": d.strftime("%Y-%m-%d"), "call_strike": k, "stock_pnl": round(stock_pnl, 2),
                                      "total_pnl": round(cycle["premium"] - cycle["fees"] + stock_pnl, 2)})
                        cycles.append(cycle); cycle = None
                    if shares == 0: basis = None
                else:
                    book(d, pos["ric"], "EXPIRE", n, 0.0, 0.0, "Call finished out of the money (close %.2f <= %.2f): kept the shares and $%s premium" % (spot, k, format(pos["premium"] * n * 100, ",.0f")), group=wk)
                    stats["calls_expired"] += 1; events.append("call expired")
                short_call = None
        # ---- 2. Monday: sell the next option ------------------------------------------------------
        if d in entry_days:
            exp = week_expiry(d)
            wk = exp.strftime("%Y-%m-%d") if exp is not None else None
            if exp is None:
                decisions.append({"date": d.strftime("%Y-%m-%d"), "status": "SKIP", "side": "-", "strike": None, "spot": spot, "reason": "no expiry listed for this week in the data"})
                stats["weeks_skipped"] += 1
            elif shares == 0 and short_put is None:
                cands = [k for k in strikes if k <= spot * cfg["put_otm"]][::-1][: cfg["put_steps_down"] + 1]
                chosen, tried = None, []
                for k in cands:
                    qq = q(d, exp, "Put", k); fill, why = usable(qq)
                    if fill is None: tried.append("%.2f: %s" % (k, why)); continue
                    chosen = (k, qq, fill); break
                if chosen is None:
                    decisions.append({"date": d.strftime("%Y-%m-%d"), "status": "SKIP", "side": "PUT", "strike": None, "spot": spot, "reason": "no usable put quote around %.0f%% of spot (%s)" % (100 * cfg["put_otm"], "; ".join(tried) or "no strikes that low")})
                    stats["weeks_skipped"] += 1
                else:
                    k, qq, fill = chosen
                    n = min(cfg["max_contracts"], int(cash // (k * 100)))
                    if n <= 0:
                        decisions.append({"date": d.strftime("%Y-%m-%d"), "status": "SKIP", "side": "PUT", "strike": k, "spot": spot, "reason": "cash %.0f cannot secure one %.2f put" % (cash, k)})
                        stats["weeks_skipped"] += 1
                    else:
                        fill = round(fill - haircut, 4); fee = cfg["fee_per_contract"] * n
                        if cycle is None: cycle = {"start": d.strftime("%Y-%m-%d"), "contracts": n, "premium": 0.0, "fees": 0.0, "puts_sold": 0, "calls_sold": 0}
                        cycle["puts_sold"] += 1; cycle["premium"] += fill * n * 100; cycle["fees"] += fee
                        book(d, qq["ric"], "SELL", n, fill, fill * n * 100 - fee, "Sold %d cash-secured %.2f put%s expiring %s; $%s set aside" % (n, k, "s" if n > 1 else "", exp.strftime("%b %d"), format(k * n * 100, ",.0f")),
                             limit=fill, fee=fee, group=wk, bid=qq["bid"], ask=qq["ask"], trade=qq["trade"])
                        short_put = {"ric": qq["ric"], "strike": k, "expiry": exp, "qty": n, "premium": fill, "open": d, "last_mark": qq["mid"] if qq["mid"] is not None else fill}
                        tot["premium"] += fill * n * 100; tot["fees"] += fee; stats["puts_sold"] += 1
                        decisions.append({"date": d.strftime("%Y-%m-%d"), "status": "SOLD PUT", "side": "PUT", "strike": k, "spot": spot, "reason": "%.0f%% of spot -> %.2f; %d contract%s; fill %.2f (%s)" % (100 * k / spot, k, n, "s" if n > 1 else "", fill, "bid" if has_ba else "mid")})
                        events.append("sold put")
            elif shares > 0 and short_call is None:
                floor_k = max(spot, basis) if cfg["call_floor"] == "basis" else spot
                cands = [k for k in strikes if k >= floor_k][: cfg["call_steps_up"] + 1]
                chosen, tried = None, []
                for k in cands:
                    qq = q(d, exp, "Call", k); fill, why = usable(qq)
                    if fill is None: tried.append("%.2f: %s" % (k, why)); continue
                    chosen = (k, qq, fill); break
                if chosen is None:
                    decisions.append({"date": d.strftime("%Y-%m-%d"), "status": "HOLD", "side": "CALL", "strike": None, "spot": spot, "reason": "spot %.2f vs basis %.2f; nothing worth selling at or above the basis (%s)" % (spot, basis, "; ".join(tried) or "no strikes listed that high")})
                    stats["weeks_holding_without_call"] += 1
                else:
                    k, qq, fill = chosen
                    n = shares // 100; fill = round(fill - haircut, 4); fee = cfg["fee_per_contract"] * n
                    if cycle is not None:
                        cycle["calls_sold"] += 1; cycle["premium"] += fill * n * 100; cycle["fees"] += fee
                    book(d, qq["ric"], "SELL", n, fill, fill * n * 100 - fee, "Sold %d covered %.2f call%s expiring %s against %d shares (basis %.2f)" % (n, k, "s" if n > 1 else "", exp.strftime("%b %d"), shares, basis),
                         limit=fill, fee=fee, group=wk, bid=qq["bid"], ask=qq["ask"], trade=qq["trade"])
                    short_call = {"ric": qq["ric"], "strike": k, "expiry": exp, "qty": n, "premium": fill, "open": d, "last_mark": qq["mid"] if qq["mid"] is not None else fill}
                    tot["premium"] += fill * n * 100; tot["fees"] += fee; stats["calls_sold"] += 1
                    decisions.append({"date": d.strftime("%Y-%m-%d"), "status": "SOLD CALL", "side": "CALL", "strike": k, "spot": spot, "reason": "floor max(spot %.2f, basis %.2f) -> %.2f; fill %.2f (%s)" % (spot, basis, k, fill, "bid" if has_ba else "mid")})
                    events.append("sold call")
        # ---- 3. mark the book at the close -------------------------------------------------------
        def mark(pos, typ):
            if pos is None: return 0.0, None, None
            if settle_day(pos["expiry"]) <= d: return 0.0, 0.0, "settled"
            m = mark_of(d, pos["expiry"], typ, pos["strike"])
            intrinsic = max(0.0, pos["strike"] - spot) if typ == "Put" else max(0.0, spot - pos["strike"])
            if m is None:
                m = max(intrinsic, pos["last_mark"]); est_marks["n"] += 1; status = "estimated"
            else:
                status = "observed"
            pos["last_mark"] = m
            return -m * pos["qty"] * 100, m, status
        put_mv, put_mark, put_st = mark(short_put, "Put")
        call_mv, call_mark, call_st = mark(short_call, "Call")
        stock_mv = shares * spot
        nav = cash + stock_mv + put_mv + call_mv
        bh_nav = bh_cash + bh_shares * spot if bh_started else cfg["initial_cash"]
        def pos_out(p, m, st):
            return None if p is None else {"ric": p["ric"], "strike": p["strike"], "expiry": p["expiry"].strftime("%Y-%m-%d"), "qty": p["qty"], "sold_at": p["premium"], "mark": m, "mark_status": st}
        ledger.append({"date": d.strftime("%Y-%m-%d"), "close": spot, "cash": round(cash, 2), "shares": shares, "basis": basis,
                       "short_put": pos_out(short_put, put_mark, put_st), "short_call": pos_out(short_call, call_mark, call_st),
                       "stock_mv": round(stock_mv, 2), "option_mv": round(put_mv + call_mv, 2), "nav": round(nav, 2),
                       "cash_reserved": round(short_put["strike"] * short_put["qty"] * 100, 2) if short_put else 0.0,
                       "bh_nav": round(bh_nav, 2), "events": ", ".join(events)})

    if cycle is not None:  # open cycle at the end of the sample
        cycle.update({"open_at_end": True, "shares": shares, "unrealized_stock_pnl": round((float(close.iloc[-1]) - basis) * shares, 2) if shares else 0.0})
        cycles.append(cycle)

    # ---- metrics ---------------------------------------------------------------------------------
    L = pd.DataFrame(ledger); L["date"] = pd.to_datetime(L["date"]); L = L.set_index("date")
    nav = L["nav"].loc[first_entry:]; bh = L["bh_nav"].loc[first_entry:]

    def metrics(s):
        r = s.pct_change().dropna(); n = len(s) - 1
        total = s.iloc[-1] / s.iloc[0] - 1
        sd = r.std(ddof=1) if len(r) > 1 else float("nan")
        return {"start": round(float(s.iloc[0]), 2), "end": round(float(s.iloc[-1]), 2), "total_return": round(float(total), 4),
                "annualized_return": round(float((1 + total) ** (252 / n) - 1), 4) if n else None,
                "annualized_vol": round(float(sd * math.sqrt(252)), 4) if sd == sd else None,
                "sharpe_rf0": round(float(r.mean() / sd * math.sqrt(252)), 2) if sd and sd > 0 else None,
                "max_drawdown": round(float((s / s.cummax() - 1).min()), 4), "trading_days": int(n),
                "worst_day": round(float(r.min()), 4) if len(r) else None, "best_day": round(float(r.max()), 4) if len(r) else None}
    last_close = float(close.iloc[-1])
    summary = {"wheel": metrics(nav), "buy_hold": metrics(bh),
               "premium_collected": round(tot["premium"], 2), "fees_paid": round(tot["fees"], 2),
               "net_pnl": round(float(nav.iloc[-1]) - cfg["initial_cash"], 2),
               "realized_stock_pnl": round(sum(c.get("stock_pnl", 0.0) for c in cycles if "stock_pnl" in c), 2),
               "ending_cash": round(cash, 2), "ending_shares": shares, "ending_basis": basis,
               "unrealized_stock_pnl": round((last_close - basis) * shares, 2) if shares else 0.0,
               "open_option_liability": round(float(L["option_mv"].iloc[-1]), 2),
               "days_in_stock": int((L["shares"] > 0).sum()), "days_total": int(len(L)), "estimated_marks": est_marks["n"],
               "bh_shares": bh_shares, "bh_cash_left": round(bh_cash, 2), "haircut": haircut, "weeks": len(entry_days), **stats}

    # ---- fill-assumption evidence ------------------------------------------------------------------
    rows = [(k, v) for k, v in quotes.items()]
    near = [(k, v) for k, v in rows if k[0] in close.index and 0.9 <= k[3] / float(close.loc[k[0]]) <= 1.1 and 0 < (k[1] - k[0]).days <= 7]
    ev = {"near_money_front_week_rows": len(near)}
    if has_ba:
        two = [v for k, v in near if v["bid"] is not None and v["ask"] is not None and v["bid"] > 0 and v["mid"]]
        spreads = np.array([(v["ask"] - v["bid"]) for v in two]); rel = np.array([(v["ask"] - v["bid"]) / v["mid"] for v in two])
        ev.update({"two_sided_share": round(len(two) / max(1, len(near)), 4), "median_spread": round(float(np.median(spreads)), 4) if len(two) else None,
                   "median_rel_spread": round(float(np.median(rel)), 4) if len(two) else None, "p90_rel_spread": round(float(np.percentile(rel, 90)), 4) if len(two) else None})
        tv = [v for v in two if v["trade"] is not None]
        if tv:
            x = np.array([v["mid"] for v in tv]); y = np.array([v["trade"] for v in tv])
            inside = np.mean([(v["bid"] - 1e-9 <= v["trade"] <= v["ask"] + 1e-9) for v in tv])
            ev.update({"trade_pairs": len(tv), "trade_inside_quote_share": round(float(inside), 4), "trade_at_or_below_bid_share": round(float(np.mean(y <= np.array([v["bid"] for v in tv]) + 1e-9)), 4),
                       "r2_mid_vs_trade": round(float(np.corrcoef(x, y)[0, 1] ** 2), 4), "median_abs_gap": round(float(np.median(np.abs(y - x))), 4),
                       "scatter": [[round(float(a), 3), round(float(b), 3)] for a, b in zip(x, y)]})
    else:
        both = [v for k, v in rows if v["mid"] is not None and v["trade"] is not None]
        x = np.array([v["mid"] for v in both]); y = np.array([v["trade"] for v in both])
        ev.update({"trade_pairs": len(both), "r2_mid_vs_trade": round(float(np.corrcoef(x, y)[0, 1] ** 2), 4), "median_abs_gap": round(float(np.median(np.abs(y - x))), 4),
                   "share_trade_below_mid": round(float((y < x).mean()), 4), "mid_only_rows": int(sum(1 for k, v in rows if v["mid"] is not None and v["trade"] is None)),
                   "scatter": [[round(float(a), 3), round(float(b), 3)] for a, b in zip(x, y)]})
    sold = []
    for b in blotter:
        if b["side"] == "SELL" and b["instrument"] != cfg["stock_ric"]:
            sold.append({"date": b["date"], "ric": b["instrument"], "bid": b["bid"], "ask": b["ask"], "fill": b["fill"], "trade_print": b["trade_print"]})
    ev["sold_contracts"] = sold

    book_out = {"config": cfg, "summary": summary, "blotter": blotter, "decisions": decisions, "cycles": cycles, "ledger": ledger,
                "stock": [{"date": d.strftime("%Y-%m-%d"), "open": None if nan(stock.loc[d, "open"]) else float(stock.loc[d, "open"]), "high": None if nan(stock.loc[d, "high"]) else float(stock.loc[d, "high"]),
                           "low": None if nan(stock.loc[d, "low"]) else float(stock.loc[d, "low"]), "close": float(stock.loc[d, "close"])} for d in days],
                "fill_evidence": ev, "provenance": meta, "sample": {"start": days[0].strftime("%Y-%m-%d"), "end": days[-1].strftime("%Y-%m-%d"), "first_entry": first_entry.strftime("%Y-%m-%d")}}
    return book_out


def write(book, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(book, allow_nan=False, separators=(",", ":"))
    (out_dir / "book.json").write_text(txt)
    (out_dir / "book.js").write_text("window.WHEEL_BOOK = " + txt + ";")
    with open(out_dir / "blotter.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(book["blotter"][0].keys())); w.writeheader(); w.writerows(book["blotter"])
    flat = []
    for row in book["ledger"]:
        fr = {k: v for k, v in row.items() if k not in ("short_put", "short_call")}
        for name in ("short_put", "short_call"):
            p = row[name]
            for fld in ("ric", "strike", "expiry", "qty", "sold_at", "mark", "mark_status"):
                fr["%s_%s" % (name, fld)] = p[fld] if p else None
        flat.append(fr)
    with open(out_dir / "ledger.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(flat[0].keys())); w.writeheader(); w.writerows(flat)
    with open(out_dir / "decisions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(book["decisions"][0].keys())); w.writeheader(); w.writerows(book["decisions"])


def brief(name, s):
    w = s["wheel"]
    return "%-16s end %9.2f  ret %+6.2f%%  sharpe %5s  maxDD %6.2f%%  puts %d (assigned %d)  calls %d (called %d)  skipped %d  hold-no-call %d" % (
        name, w["end"], 100 * w["total_return"], w["sharpe_rf0"], 100 * w["max_drawdown"], s["puts_sold"], s["puts_assigned"], s["calls_sold"], s["calls_called_away"], s["weeks_skipped"], s["weeks_holding_without_call"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="amzn", choices=list(SOURCES))
    ap.add_argument("--path", default=None, help="path to wheel_source.json (amzn source)")
    ap.add_argument("--haircut", type=float, default=0.0)
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args()
    base = run(a.source, haircut=a.haircut, path=a.path)
    if a.haircut == 0:
        write(base, Path(a.out))
        variants = {"base": base["summary"],
                    "no_basis_floor": run(a.source, call_floor="spot", path=a.path)["summary"],
                    "haircut_5c": run(a.source, haircut=0.05, path=a.path)["summary"],
                    "haircut_10c": run(a.source, haircut=0.10, path=a.path)["summary"],
                    "put_otm_97": run(a.source, path=a.path, config_overrides={"put_otm": 0.97})["summary"],
                    "put_otm_92": run(a.source, path=a.path, config_overrides={"put_otm": 0.92})["summary"]}
        (Path(a.out) / "variants.json").write_text(json.dumps(variants, indent=1))
        (Path(a.out) / "variants.js").write_text("window.WHEEL_VARIANTS = " + json.dumps(variants, separators=(",", ":")) + ";")
        for k, v in variants.items(): print(brief(k, v))
        print("buy&hold        end %9.2f  ret %+6.2f%%  sharpe %5s  maxDD %6.2f%%" % (base["summary"]["buy_hold"]["end"], 100 * base["summary"]["buy_hold"]["total_return"], base["summary"]["buy_hold"]["sharpe_rf0"], 100 * base["summary"]["buy_hold"]["max_drawdown"]))
    else:
        print(brief("haircut", base["summary"]))
    print("blotter", len(base["blotter"]), "decisions", len(base["decisions"]), "estimated marks", base["summary"]["estimated_marks"])
    for dd in base["decisions"]: print(" ", dd["date"], dd["status"], dd.get("strike"), "|", dd["reason"])
