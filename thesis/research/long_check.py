"""Rough alpha check on six years of real closing quotes (weeks from October 2020, after the split).

Each week, on the first session's close: sell at the BID, hold to expiry, settle against the expiry-day close.
Return is on the strike (the cash that secures a put). $0.65 per contract per leg.
Rows: the put the live rule picks, the at-the-money put, the at-the-money call, and both together (a straddle).
Output: ../alpha_long.json for the page.
"""
import json, math, statistics
from pathlib import Path
HERE = Path(__file__).parent
src = json.loads((HERE / "long_history_source.json").read_text())
FEE = 0.0065


def ok(q):
    return q.get("BID", 0) > 0 and q.get("ASK", 0) >= q["BID"]


def pick(week, right, target, tol=0.011):
    c = [q for q in week["quotes"] if q["right"] == right and ok(q)]
    if not c:
        return None
    q = min(c, key=lambda q: (abs(q["strike"] - target), q["strike"]))
    return q if abs(q["strike"] - target) <= tol * week["close_first"] else None


def summarise(rows, key="ret"):
    rets = [r[key] for r in rows]
    n = len(rets); mean = statistics.mean(rets); sd = statistics.stdev(rets)
    eq = peak = 1.0; dd = 0.0
    for r in rets:
        eq *= 1 + r; peak = max(peak, eq); dd = min(dd, eq / peak - 1)
    return {"weeks": n, "premium_pct": round(100 * statistics.mean(r["prem"] for r in rows), 3), "payoff_pct": round(100 * statistics.mean(r["pay"] for r in rows), 3),
            "mean_week_pct": round(mean * 100, 3), "ann_pct": round(mean * 52 * 100, 2), "ann_vol_pct": round(sd * math.sqrt(52) * 100, 2),
            "t_stat": round(mean / sd * math.sqrt(n), 2), "win_pct": round(100 * sum(r > 0 for r in rets) / n, 0), "worst_week_pct": round(min(rets) * 100, 2),
            "max_dd_pct": round(dd * 100, 1), "half_spread_pct_of_premium": round(100 * statistics.mean(r["hs"] for r in rows) / statistics.mean(r["bid"] for r in rows), 1),
            "avg_bid": round(statistics.mean(r["bid"] for r in rows), 2), "avg_half_spread": round(statistics.mean(r["hs"] for r in rows), 3)}


weeks = [w for w in src["weeks"] if w["quotes"]]
legs = {"rule_put": [], "atm_put": [], "atm_call": [], "straddle": []}
for w in weeks:
    c = w["close_first"]; s = w["settle"]
    base = {"week": w["first"], "expiry": w["expiry"], "close": round(c, 2), "settle": round(s, 2)}
    q = pick(w, "P", c * (1 - w["pct"] / 100))
    if q and w["ret10"] > -0.08:                       # the live crash filter: no put after an 8% drop in 10 sessions
        k = q["strike"]; pay = max(k - s, 0)
        legs["rule_put"].append({**base, "strike": k, "bid": q["BID"], "hs": (q["ASK"] - q["BID"]) / 2, "prem": q["BID"] / k, "pay": pay / k, "ret": (q["BID"] - FEE - pay) / k, "pct": w["pct"]})
    p, cl = pick(w, "P", c), pick(w, "C", c)
    if p:
        k = p["strike"]; pay = max(k - s, 0)
        legs["atm_put"].append({**base, "strike": k, "bid": p["BID"], "hs": (p["ASK"] - p["BID"]) / 2, "prem": p["BID"] / k, "pay": pay / k, "ret": (p["BID"] - FEE - pay) / k})
    if cl:
        k = cl["strike"]; pay = max(s - k, 0)
        legs["atm_call"].append({**base, "strike": k, "bid": cl["BID"], "hs": (cl["ASK"] - cl["BID"]) / 2, "prem": cl["BID"] / k, "pay": pay / k, "ret": (cl["BID"] - FEE - pay) / k})
    if p and cl and p["strike"] == cl["strike"]:
        k = p["strike"]; bid = p["BID"] + cl["BID"]; mid = (p["BID"] + p["ASK"] + cl["BID"] + cl["ASK"]) / 2; pay = abs(s - k)
        legs["straddle"].append({**base, "strike": k, "bid": round(bid, 2), "mid": round(mid, 2), "hs": mid - bid, "prem": bid / k, "pay": pay / k, "ret": (bid - 2 * FEE - pay) / k,
                                 "ret_mid": (mid - 2 * FEE - pay) / k, "implied_move_pct": round(100 * mid / k, 3), "actual_move_pct": round(100 * pay / k, 3)})
res = {"window": [weeks[0]["first"], weeks[-1]["expiry"]], "weeks_total": len(src["weeks"]), "weeks_with_quotes": len(weeks),
       "fill_rule": "first session's closing bid, held to expiry, settled at the expiry-day close; $0.65 per contract per leg; return on the strike",
       "summary": {k: summarise(v) for k, v in legs.items()}, "by_year": {}, "last2y": {}}
res["summary"]["straddle_at_mid"] = summarise(legs["straddle"], "ret_mid")
st = legs["straddle"]
res["summary"]["straddle"]["implied_move_pct"] = round(statistics.mean(r["implied_move_pct"] for r in st), 3)
res["summary"]["straddle"]["actual_move_pct"] = round(statistics.mean(r["actual_move_pct"] for r in st), 3)
res["summary"]["straddle"]["weeks_market_overpaid"] = sum(r["mid"] > r["pay"] * r["strike"] for r in st)
for k, v in legs.items():
    res["by_year"][k] = [{"year": y, "weeks": len(x), "sum_pct": round(100 * sum(r["ret"] for r in x), 2), "premium_pct": round(100 * statistics.mean(r["prem"] for r in x), 3),
                          "payoff_pct": round(100 * statistics.mean(r["pay"] for r in x), 3)} for y in sorted({r["week"][:4] for r in v}) for x in [[r for r in v if r["week"][:4] == y]]]
    res["last2y"][k] = summarise([r for r in v if r["week"] >= "2024-11-18"])
res["straddle_weeks"] = [{a: (round(b, 5) if isinstance(b, float) else b) for a, b in r.items()} for r in st]
res["rule_weeks"] = [{a: (round(b, 5) if isinstance(b, float) else b) for a, b in r.items()} for r in legs["rule_put"]]
(HERE.parent / "alpha_long.json").write_text(json.dumps(res, indent=1))
for k, v in res["summary"].items(): print(k, v)
print("last 2y"); [print("  ", k, v) for k, v in res["last2y"].items()]
for k in ("rule_put", "straddle", "atm_put", "atm_call"): print(k, [(y["year"], y["weeks"], y["sum_pct"]) for y in res["by_year"][k]])
print("worst straddle weeks", [(r["week"], r["strike"], r["bid"], round(r["pay"] * r["strike"], 2), round(100 * r["ret"], 2)) for r in sorted(st, key=lambda r: r["ret"])[:5]])
print("worst rule weeks", [(r["week"], r["strike"], r["bid"], round(100 * r["ret"], 2)) for r in sorted(legs["rule_put"], key=lambda r: r["ret"])[:5]])
print("rule avg pct", statistics.mean(r["pct"] for r in legs["rule_put"]), "avg moneyness", statistics.mean(r["strike"] / r["close"] - 1 for r in legs["rule_put"]))
