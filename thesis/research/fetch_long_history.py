"""LSEG pull for the thesis page: six years of weeks (after the August 2020 split), three contracts per week.

For each week: the put the live rule would pick (1.3 weekly sigmas below, clamped 3% to 10%), the at-the-money put
and the at-the-money call, all measured from the first session's close because the fill is that day's closing quote.
Strike grids changed over the years ($1, $2.50, $5), so each target asks for its neighbours on all three.

Needs LSEG_CONFIG. Output: long_history_source.json.
"""
import datetime as dt, json, math, os, time
from pathlib import Path
import pandas as pd
import lseg.data as ld

STOCK, ROOT = "AAPL.O", "AAPL"
FIELDS = ["BID", "ASK", "TRDPRC_1", "ACVOL_UNS"]

START, END = "2020-10-05", "2026-11-20"
OUT = Path(__file__).with_name("long_history_source.json")


def opt_ric(expiry, strike, right):
    """Expired-option RIC: root, month letter (A-L calls, M-X puts), DDYY, strike x 100, then ^ month letter and year."""
    m = chr(ord("A") + expiry.month - 1)
    return "%s%s%s%05d.U^%s%s" % (ROOT, chr(ord(m) + (12 if right == "P" else 0)), expiry.strftime("%d%y"), int(round(strike * 100)), m, expiry.strftime("%y"))


def flat(frame, rics):
    """{ric: {date: {field: value}}} from whatever column shape get_history returns."""
    out = {}
    if frame is None or frame.empty:
        return out
    for col in frame.columns:
        parts = [str(x) for x in col] if isinstance(col, tuple) else [str(col)]
        f = [p for p in parts if p in FIELDS]; r = [p for p in parts if p in rics] or (rics if len(rics) == 1 else [])
        if len(f) != 1 or len(r) != 1:
            continue
        for d, v in pd.to_numeric(frame[col], errors="coerce").items():
            if pd.notna(v):
                out.setdefault(r[0], {}).setdefault(pd.Timestamp(d).strftime("%Y-%m-%d"), {})[f[0]] = float(v)
    return out


def near(target):
    return sorted({round(target), math.floor(target / 2.5) * 2.5, math.ceil(target / 2.5) * 2.5, round(target / 5) * 5})


def main():
    ld.open_session(config_name=os.environ["LSEG_CONFIG"])
    weeks = []
    try:
        raw = ld.get_history(universe=[STOCK], fields=["OPEN_PRC", "TRDPRC_1"], interval="daily", start="2020-09-01", end=END)
        raw.index = pd.to_datetime(raw.index).normalize()
        st = raw.apply(pd.to_numeric, errors="coerce").dropna(subset=["TRDPRC_1"]).sort_index()
        st.columns = [str(c[-1]) if isinstance(c, tuple) else str(c) for c in st.columns]
        closes = st["TRDPRC_1"]
        print("stock rows", len(st), st.index[0].date(), st.index[-1].date(), "first close", float(closes.iloc[0]), flush=True)
        wk = st.index.to_period("W-FRI"); t0 = time.time()
        todo = sorted(set(wk[st.index >= pd.Timestamp(START)]))
        for n, w in enumerate(todo):
            days = st.index[wk == w]
            first, last = days[0], days[-1]
            i = st.index.get_loc(first)
            if i < 21 or len(days) < 3:
                continue
            hist = closes.iloc[:i]                                # through the prior session, as the nightly run sees it
            r = (hist / hist.shift(1)).apply(math.log).iloc[-20:]
            wsig = float(r.std(ddof=0) * math.sqrt(5)); ret10 = float(hist.iloc[-1] / hist.iloc[-11] - 1)
            pct = int(round(min(10, max(3, 1.3 * wsig * 100))))
            c = float(closes.loc[first]); exp = last.date()
            rics = {}
            for k in near(c * (1 - pct / 100)):
                rics[opt_ric(exp, k, "P")] = ("P", k, "rule")
            for k in near(c):
                rics.setdefault(opt_ric(exp, k, "P"), ("P", k, "atm")); rics[opt_ric(exp, k, "C")] = ("C", k, "atm")
            names = list(rics); quotes = {}; err = None
            try:
                time.sleep(0.12)
                quotes = flat(ld.get_history(universe=names, fields=FIELDS, start=first.strftime("%Y-%m-%d"), end=first.strftime("%Y-%m-%d"), interval="daily"), names)
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, str(e)[:160])
            d = first.strftime("%Y-%m-%d")
            weeks.append({"first": d, "expiry": last.strftime("%Y-%m-%d"), "close_first": c, "settle": float(closes.loc[last]), "weekly_sigma": wsig, "ret10": ret10,
                          "pct": pct, "asked": len(names), "error": err,
                          "quotes": [{"right": rics[x][0], "strike": rics[x][1], "ric": x, **quotes[x][d]} for x in names if d in quotes.get(x, {})]})
            if n % 25 == 0:
                print("week %d/%d %s: %d of %d quoted (%.0fs) %s" % (n + 1, len(todo), d, len(weeks[-1]["quotes"]), len(names), time.time() - t0, err or ""), flush=True)
    finally:
        ld.close_session()
    OUT.write_text(json.dumps({"fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "provider": "LSEG Workspace desktop session, lseg.data", "fields": FIELDS,
                               "window": [START, END], "weeks": weeks}, indent=1))
    print("saved; weeks with quotes:", sum(1 for w in weeks if w["quotes"]), "of", len(weeks))


if __name__ == "__main__":
    main()
