"""PMCC research data acquisition, v1.0. Python 3.8 / LSEG CodeBook.
Run: %run PMCC_CodeBook_Run.py
Read-only market data: this script NEVER submits brokerage orders.
Download PMCC_source.zip and return it for the independently tested backtest.
No __future__, zoneinfo, credentials, synthetic quotes or dynamic imports.
"""
print('PMCC v1.0: Python is executing. Loading standard libraries ...', flush=True)
import datetime as dt
import json
import math
import time
import zipfile
from pathlib import Path
import pandas as pd
import pytz

CONFIG = {
    'version': 'pmcc-v1.0', 'stock_ric': 'AMZN.O', 'root': 'AMZN',
    'start': '2026-04-06', 'end': '2026-10-02', 'long_expiry': '2028-01-21',
    'timezone': 'America/New_York', 'interval': 'hourly',
    'timestamp_label': 'endPeriod', 'entry_hour': 11, 'exit_hour': 15,
    'initial_cash': 50000.0, 'contract_multiplier': 100,
    'long_target_moneyness': 0.70, 'long_min_moneyness': 0.60,
    'long_max_moneyness': 0.80, 'strike_grid': 5.0,
    'short_target_moneyness': 1.03, 'short_candidates': 3,
    'long_max_relative_spread': 0.10, 'short_max_relative_spread': 0.50,
    'option_fee_per_contract': 0.65,
    'known_closed_fridays': ['2026-06-19', '2026-07-03'],
    'fills': 'Buy at ask, sell at bid, same labelled hourly bar; not guaranteed executable ticks.',
    'long_rule': 'Choose closest strike to 70% of first Monday spot, among 60%-80% on $5 grid; ties lower strike. Entry quotes only.',
    'short_rule': 'Monday 11 ET; lowest eligible $5 strike >= 103% spot among first three candidates; strike exceeds long strike.',
    'exit_rule': 'Buy short back Friday 15 ET, or first 15 ET observation with ITM short and <= $0.05 mid extrinsic. No new call that week.',
    'missing_exit': 'Halt at first unavailable mandatory exit. Never discard a filled trade using future liquidity.',
    'dividends': 'AMZN has never paid cash dividends per Amazon IR FAQ; no dividends assumed in this sample.',
    'selection_disclosure': 'Stock and parameters selected retrospectively for an educational case study, not an out-of-sample investment claim.'
}
NY = pytz.timezone(CONFIG['timezone'])
FIELDS = ['BID', 'ASK', 'TRDPRC_1', 'ACVOL_UNS']
CACHE = Path('PMCC_checkpoint.json')
OUT = Path('PMCC_source.json')


def stamp(d, hour):
    return NY.localize(dt.datetime(d.year, d.month, d.day, hour)).astimezone(dt.timezone.utc).isoformat().replace('+00:00', 'Z')


def valid_quote(r, max_spread=None):
    if not r:
        return False
    b, a = r.get('BID'), r.get('ASK')
    if b is None or a is None or not (math.isfinite(b) and math.isfinite(a) and 0 < b <= a):
        return False
    return max_spread is None or (a-b)/((a+b)/2) <= max_spread + 1e-12


def normalize(frame):
    if frame is None or frame.empty:
        return []
    if not isinstance(frame.index, pd.DatetimeIndex):
        cols = [c for c in frame.columns if str(c).lower() in ('date', 'timestamp', 'datetime')]
        if len(cols) != 1:
            raise ValueError('Unrecognized timestamp index: refusing to guess.')
        frame = frame.set_index(cols[0])
    result = {}
    for idx, row in frame.iterrows():
        t = pd.Timestamp(idx)
        t = t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')
        r = {'time': t.isoformat().replace('+00:00', 'Z')}
        for field in FIELDS:
            cols = [c for c in frame.columns if field in (tuple(map(str, c)) if isinstance(c, tuple) else (str(c),))]
            if len(cols) > 1:
                raise ValueError('Ambiguous field: ' + field)
            v = row[cols[0]] if cols else None
            r[field] = None if v is None or pd.isna(v) else float(v)
            if r[field] is not None and not math.isfinite(r[field]):
                r[field] = None
        if r['time'] in result and result[r['time']] != r:
            raise ValueError('Conflicting duplicate source timestamps')
        result[r['time']] = r
    return sorted(result.values(), key=lambda x: x['time'])


def aliases(expiry, strike):
    code = 'ABCDEFGHIJKL'[expiry.month-1]
    yy = expiry.strftime('%y')
    expired = expiry < dt.datetime.now(dt.timezone.utc).date()
    base = [CONFIG['root'] + code + d + yy + ('%05d' % round(strike*100)) + '.U'
            for d in (str(expiry.day), '%02d' % expiry.day)]
    suffix = '^' + code + yy
    # Provider aliases are tried in a fixed order, with every response retained.
    variants = [s+suffix for s in base] + base if expired else base
    return list(dict.fromkeys(variants))


def main():
    print('Loading LSEG data library ...', flush=True)
    try:
        import refinitiv.data as ld
        from refinitiv.data.content import historical_pricing as hp
        library = 'refinitiv.data'
    except ImportError:
        import lseg.data as ld
        from lseg.data.content import historical_pricing as hp
        library = 'lseg.data'
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding='utf-8'))
        if cache.get('config') != CONFIG:
            raise ValueError('Checkpoint belongs to different settings. Rename it before starting this experiment.')
        print('Resuming saved requests; failed requests will be retried.', flush=True)
    else:
        cache = {'config': CONFIG, 'responses': {}, 'request_audit': [],
                 'provenance': {'provider': 'LSEG Workspace CodeBook', 'library': library,
                  'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'source_kind': 'actual API responses, not modelled prices'}}

    def save():
        tmp = CACHE.with_suffix('.tmp')
        tmp.write_text(json.dumps(cache, allow_nan=False, separators=(',', ':')), encoding='utf-8')
        tmp.replace(CACHE)

    def request(ric, first, last):
        key = '|'.join([ric, first, last])
        cached = cache['responses'].get(key)
        if cached is not None:
            return cached
        print('REQUEST ' + key, flush=True)
        began = time.monotonic()
        try:
            response = hp.summaries.Definition(universe=ric, fields=FIELDS,
                interval=hp.Intervals.HOURLY, start=first, end=last, count=10000,
                extended_params={'summaryTimestampLabel': 'endPeriod'}).get_data()
            rows = normalize(response.data.df)
            if len(rows) >= 10000:
                raise ValueError('Possible response truncation; refusing incomplete request.')
            cache['responses'][key] = rows
            audit = {'ric': ric, 'start': first, 'end': last, 'status': 'observed' if rows else 'empty',
                     'rows': len(rows), 'seconds': round(time.monotonic()-began, 2)}
        except Exception as exc:
            rows = []
            audit = {'ric': ric, 'start': first, 'end': last, 'status': 'error', 'rows': 0,
                     'error_type': type(exc).__name__, 'error': str(exc)[:400]}
        cache['request_audit'].append(audit)
        save()
        print('  ' + audit['status'] + ': ' + str(len(rows)) + ' rows', flush=True)
        return rows

    def contract(expiry, strike, first, last, entry):
        attempted = []
        fallback = None
        for ric in aliases(expiry, strike):
            rows = request(ric, first, last)
            attempted.append(ric)
            c = {'ric': ric, 'expiry': str(expiry), 'strike': strike, 'rows': rows,
                 'attempted_aliases': list(attempted), 'selection_quote_time': entry}
            if fallback is None or (not fallback['rows'] and rows):
                fallback = c
            r = next((r for r in rows if r['time'] == entry), None)
            if valid_quote(r):
                return c
        fallback['attempted_aliases'] = attempted
        return fallback

    print('Opening authenticated Workspace session ...', flush=True)
    ld.open_session()
    tape = {'config': CONFIG, 'stock': [], 'long_candidates': [], 'long_contract': None,
            'short_candidates': [], 'weeks': [], 'request_audit': [], 'provenance': cache['provenance']}
    error = None
    try:
        mondays = [d.date() for d in pd.date_range(CONFIG['start'], CONFIG['end'], freq='W-MON')]
        stock = {}
        print('STEP 1: stock history in weekly requests.', flush=True)
        for monday in mondays:
            friday = monday + dt.timedelta(days=4)
            first, last = str(monday)+'T00:00:00Z', str(friday)+'T23:59:59Z'
            tape['weeks'].append({'monday': str(monday), 'friday': str(friday)})
            for r in request(CONFIG['stock_ric'], first, last):
                stock[r['time']] = r
        tape['stock'] = sorted(stock.values(), key=lambda r: r['time'])
        entry = stamp(mondays[0], CONFIG['entry_hour'])
        entry_stock = stock.get(entry)
        if not entry_stock or not entry_stock.get('TRDPRC_1') or not valid_quote(entry_stock):
            raise ValueError('No usable first-Monday stock print AND bid/ask. Send PMCC_source.zip for diagnosis; do not change dates to chase returns.')
        spot = entry_stock['TRDPRC_1']
        grid = CONFIG['strike_grid']
        strikes = [float(k) for k in range(int(math.ceil(spot*0.60/grid)*grid), int(math.floor(spot*0.80/grid)*grid)+1, int(grid))]
        strikes.sort(key=lambda k: (abs(k-spot*0.70), k))
        expiry = dt.date.fromisoformat(CONFIG['long_expiry'])
        print('STEP 2: long-call entry candidates (spot ' + str(spot) + ').', flush=True)
        for k in strikes:
            c = contract(expiry, k, CONFIG['start']+'T00:00:00Z', CONFIG['start']+'T23:59:59Z', entry)
            tape['long_candidates'].append(c)
        selected = None
        for c in tape['long_candidates']:
            q = next((r for r in c['rows'] if r['time'] == entry), None)
            if valid_quote(q, CONFIG['long_max_relative_spread']) and q['ASK'] >= max(spot-c['strike'], 0)-0.01:
                selected = c
                break
        if selected is None:
            raise ValueError('No eligible long call at entry. Raw attempts are saved; no model price substituted.')
        print('Selected long at ENTRY ONLY: '+selected['ric'], flush=True)
        long_rows = {r['time']: r for r in selected['rows']}
        for monday in mondays:
            friday = monday + dt.timedelta(days=4)
            for r in request(selected['ric'], str(monday)+'T00:00:00Z', str(friday)+'T23:59:59Z'):
                long_rows[r['time']] = r
        tape['long_contract'] = dict(selected)
        tape['long_contract']['rows'] = sorted(long_rows.values(), key=lambda r: r['time'])
        print('STEP 3: short-call candidates. Selection uses Monday data only.', flush=True)
        for n, monday in enumerate(mondays, 1):
            friday = monday + dt.timedelta(days=4)
            if str(friday) in CONFIG['known_closed_fridays']:
                print(str(monday)+': predeclared holiday-Friday skip.', flush=True)
                continue
            t = stamp(monday, CONFIG['entry_hour'])
            s = stock.get(t)
            if not s or not s.get('TRDPRC_1'):
                print(str(monday)+': missing Monday observation; skip.', flush=True)
                continue
            anchor = math.ceil(s['TRDPRC_1']*CONFIG['short_target_moneyness']/grid)*grid
            for offset in range(CONFIG['short_candidates']):
                c = contract(friday, float(anchor+offset*grid), str(monday)+'T00:00:00Z', str(friday)+'T23:59:59Z', t)
                c['monday'] = str(monday)
                tape['short_candidates'].append(c)
            print('WEEK ' + str(n) + '/' + str(len(mondays)) + ' complete.', flush=True)
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
        print('ACQUISITION INCOMPLETE: '+error, flush=True)
    finally:
        tape['request_audit'] = cache['request_audit']
        tape['provenance']['completed_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        tape['acquisition_error'] = error
        OUT.write_text(json.dumps(tape, allow_nan=False, separators=(',', ':')), encoding='utf-8')
        with zipfile.ZipFile('PMCC_source.zip', 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(OUT, OUT.name)
            z.writestr('rules.json', json.dumps(CONFIG, indent=2))
        print('SAVED PMCC_source.zip | stock rows: '+str(len(tape['stock']))+
              ' | short candidates: '+str(len(tape['short_candidates'])), flush=True)
        try:
            ld.close_session()
        except Exception:
            pass
        try:
            from IPython.display import display, FileLink
            display(FileLink('PMCC_source.zip'))
        except ImportError:
            print('Right-click PMCC_source.zip in the file browser and Download.', flush=True)
    return tape


if __name__ == '__main__':
    main()
