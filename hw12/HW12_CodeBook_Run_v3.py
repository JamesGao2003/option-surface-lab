print("HW12 v3: Python is executing this file.", flush=True)
"""HW 1.2: deterministic, price-only covered-call account. No live orders.

Input: LSEG hourly bars explicitly labelled endPeriod, UTC ISO timestamps.
Output: booked-event blotter, marked ledger, quote/trade regression, skip audit.
"""
import json
import math
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import pytz

NY = pytz.timezone('America/New_York')
MULT = 100


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def quote(row):
    """Positive two-sided non-crossed market; missing/locked-zero markets fail."""
    b, a = row.get('BID'), row.get('ASK')
    return (a + b) / 2 if finite(b) and finite(a) and 0 < b <= a else None


def instant(s):
    value = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('All bar timestamps must include UTC offset.')
    return value.astimezone(timezone.utc)


def iso(t):
    return t.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def local_at(d, hour):
    return NY.localize(datetime(d.year, d.month, d.day, hour), is_dst=None).astimezone(timezone.utc)


def make_call_ric(root, expiry, strike):
    import re
    if not re.fullmatch('[A-Z]+', root):
        raise ValueError('Unsupported root')
    cents = Decimal(str(strike)) * 100
    if cents != cents.to_integral_value() or not 0 < cents <= 99999:
        raise ValueError('Strike must fit five integer cent digits.')
    code = chr(ord('A') + expiry.month - 1)
    # HW 1.2 explicitly uses an unpadded day (different from the old HW 1.1 starter).
    return f'{root}{code}{expiry.day}{expiry:%y}{int(cents):05d}.U^{code}{expiry:%y}'


def regression(pairs):
    if len(pairs) < 2:
        return {'n': len(pairs), 'slope': None, 'intercept': None, 'r2': None, 'mae': None}
    xs, ys = [p['mid'] for p in pairs], [p['trade'] for p in pairs]
    xbar, ybar = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x-xbar)**2 for x in xs)
    syy = sum((y-ybar)**2 for y in ys)
    if sxx == 0:
        return {'n': len(pairs), 'slope': None, 'intercept': None, 'r2': None,
                'mae': sum(abs(x-y) for x,y in zip(xs,ys)) / len(xs)}
    slope = sum((x-xbar)*(y-ybar) for x,y in zip(xs,ys)) / sxx
    intercept = ybar - slope*xbar
    sse = sum((y-intercept-slope*x)**2 for x,y in zip(xs,ys))
    return {'n': len(pairs), 'slope': slope, 'intercept': intercept,
            'r2': 1-sse/syy if syy > 0 else None,
            'mae': sum(abs(x-y) for x,y in zip(xs,ys)) / len(xs)}


def run_backtest(tape):
    cfg = tape['config']
    if cfg.get('timestamp_label') != 'endPeriod':
        raise ValueError('Require explicitly end-labelled hourly bars; no implicit timestamp shift.')
    initial = float(cfg.get('initial_cash', 30000))
    if not math.isfinite(initial) or initial <= 0:
        raise ValueError('Initial cash must be positive and finite.')
    start, end = date.fromisoformat(cfg['start']), date.fromisoformat(cfg['end'])
    entry_hour = int(cfg.get('entry_hour_ny', 11))
    stock = {}
    for r in tape['stock']:
        t = instant(r['time'])
        if t in stock:
            raise ValueError('Duplicate stock timestamp')
        p = r.get('TRDPRC_1')
        if finite(p) and p > 0:
            stock[t] = dict(r)
    contracts = {}
    options = {}
    for c in tape['contracts']:
        if c['ric'] in contracts:
            raise ValueError('Duplicate contract')
        expiry = date.fromisoformat(c['expiry'])
        if make_call_ric(cfg['root'], expiry, c['strike']) != c['ric']:
            raise ValueError('RIC metadata mismatch: '+c['ric'])
        contracts[c['ric']] = c
    for r in tape['options']:
        if r['ric'] not in contracts:
            raise ValueError('Unknown option RIC')
        key = r['ric'], instant(r['time'])
        if key in options:
            raise ValueError('Duplicate option timestamp')
        options[key] = r
    # No quote joining across timestamps; regression uses only current-bar observations.
    pairs, excluded_no_volume = [], 0
    for (ric,t), r in sorted(options.items()):
        m, trade = quote(r), r.get('TRDPRC_1')
        local = t.astimezone(NY)
        if not (start <= local.date() <= end and local.weekday() < 5 and 10 <= local.hour <= 16):
            continue
        if m is None or not finite(trade) or trade < 0:
            continue
        # A zero bar-volume return contradicts a fresh trade. Do not count it as a print.
        if finite(r.get('ACVOL_UNS')) and r['ACVOL_UNS'] <= 0:
            excluded_no_volume += 1
            continue
        spot_row = stock.get(t)
        if not spot_row:
            continue
        c = contracts[ric]
        if abs(c['strike'] / spot_row['TRDPRC_1'] - 1) > .10:
            continue
        if local.date() > date.fromisoformat(c['expiry']):
            continue
        pairs.append({'time': iso(t), 'ric': ric, 'mid': m, 'trade': trade,
                      'bid': r['BID'], 'ask': r['ASK']})

    cash, shares, short = initial, 0, None
    blotter, ledger, decisions, unresolved = [], [], [], []
    premium, assignments, expires = 0., 0, 0
    first_stock = None
    next_id = 1

    def book(t, ric, side, qty, fill, delta, note, limit=None, group=None):
        nonlocal cash, next_id
        cash += delta
        blotter.append({'id': next_id, 'time': iso(t), 'instrument': ric, 'side': side,
                        'qty': qty, 'limit': limit, 'fill': fill, 'cash_delta': delta,
                        'cash_after': cash, 'note': note, 'group': group})
        next_id += 1

    def mark(t, spot, phase='hourly', option_override=None):
        option_mark = 0 if short is None else (option_override if option_override is not None else quote(options.get((short['ric'], t), {})))
        lmv = shares * spot
        omv = -MULT * option_mark if short and option_mark is not None else (None if short else 0)
        nav = cash + lmv + omv if omv is not None else None
        ledger.append({'time': iso(t), 'phase': phase, 'cash': cash, 'shares': shares,
                       'short_calls': int(short is not None), 'option_ric': short['ric'] if short else None,
                       'strike': short['strike'] if short else None, 'expiry': short['expiry'] if short else None,
                       'stock_mark': spot, 'option_mark': option_mark, 'lmv': lmv, 'option_mv': omv,
                       'nav': nav, 'initial': .50*lmv, 'maintenance': .25*lmv,
                       'available': nav-.5*lmv if nav is not None else None,
                       'excess': nav-.25*lmv if nav is not None else None,
                       'mark_status': 'observed' if omv is not None else 'missing option bid/ask; NAV unknown',
                       'benchmark_nav': initial + 100*(spot-first_stock) if first_stock is not None else initial})

    # Weekly decisions are predeclared by calendar, not triggered by favourable future returns.
    mondays = []
    d = start
    while d <= end:
        if d.weekday() == 0 and d+timedelta(days=4) <= end:
            mondays.append(d)
        d += timedelta(days=1)
    entry_times = {local_at(d, entry_hour): d for d in mondays}
    times = sorted({t for t in stock if start <= t.astimezone(NY).date() <= end
                    and t.astimezone(NY).weekday() < 5 and 10 <= t.astimezone(NY).hour <= 16} | set(entry_times))
    for t in times:
        local = t.astimezone(NY)
        if short and t > local_at(date.fromisoformat(short['expiry']), 16):
            unresolved.append({'time': iso(t), 'reason': 'Missing expiry 16:00 stock print; settlement unknown. Backtest stops here.', 'ric': short['ric']})
            break
        sr = stock.get(t)
        if t in entry_times:
            friday = (entry_times[t]+timedelta(days=4)).isoformat()
            decision = {'time': iso(t), 'expiry': friday, 'status': 'SKIP', 'ric': None,
                        'reason': '', 'spot': sr['TRDPRC_1'] if sr else None}
            decisions.append(decision)
            if short:
                decision['reason'] = 'Existing call remains open; no roll or overlapping short call.'
            elif sr is None:
                decision['reason'] = 'No stock print at fixed Monday decision time (holiday or missing tape); no delayed entry.'
            else:
                s = sr['TRDPRC_1']
                candidates = []
                for c in contracts.values():
                    # Query grid uses ONLY this Monday's observed spot, never later highs/lows.
                    if c['expiry'] != friday or not (0 <= c['strike']-s <= cfg.get('max_otm_dollars', 15)):
                        continue
                    r = options.get((c['ric'],t), {})
                    m = quote(r)
                    if m is not None:
                        candidates.append((c,m,r))
                candidates.sort(key=lambda x: (x[0]['strike'],x[0]['ric']))
                if not candidates:
                    decision['reason'] = 'No contemporaneous positive, non-crossed BID/ASK on the declared OTM strike grid; week skipped.'
                else:
                    c,m,r = candidates[0]
                    nav_before = cash+shares*s
                    # Buying at the stock mark and shorting at its mark do not create equity.
                    available_after = nav_before-.50*100*s
                    decision.update({'ric':c['ric'],'strike':c['strike'],'mid':m,
                                     'bid':r['BID'],'ask':r['ASK'],'available_after':available_after})
                    if available_after < -1e-8:
                        decision['reason'] = 'Insufficient Reg T available funds after proposed entry; no legs booked.'
                    else:
                        if shares == 0:
                            book(t,cfg['stock_ric'],'BUY',100,s,-100*s,'ENTRY: flat → buy 100 shares; covered combo passed Reg T.',group=friday)
                            shares=100
                            if first_stock is None: first_stock=s
                        elif shares != 100:
                            raise AssertionError('Unsupported share count')
                        book(t,c['ric'],'SELL',1,m,100*m,'WRITE: smallest quoted strike ≥ spot on $2.50 grid; Friday expiry; simulated limit at contemporaneous mid.',limit=m,group=friday)
                        short=dict(c);premium+=100*m
                        decision.update(status='FILLED',reason='Covered call written at mid; buy stock only when flat.')
        if sr is None:
            continue
        s = sr['TRDPRC_1']
        if short and t == local_at(date.fromisoformat(short['expiry']),16):
            intrinsic=max(s-short['strike'],0)
            mark(t,s,phase='pre-expiry',option_override=intrinsic)
            c=short
            if s > c['strike']:
                book(t,c['ric'],'ASSIGN',1,0,0,'EXPIRY ITM: remove short call through physical assignment; stock proceeds recorded once on paired SELL.',group=c['expiry'])
                book(t,cfg['stock_ric'],'SELL',100,c['strike'],100*c['strike'],'ASSIGNMENT DELIVERY: sell covered 100 shares at strike; book becomes flat.',group=c['expiry'])
                shares=0;assignments+=1
            else:
                book(t,c['ric'],'EXPIRE',1,0,0,'EXPIRY OTM/ATM: call expires at zero; keep the existing 100 shares. Exact ATM treated as unexercised.',group=c['expiry'])
                expires+=1
            short=None
            mark(t,s,phase='post-expiry')
        else:
            mark(t,s,phase='after-entry' if t in entry_times and decisions[-1]['status']=='FILLED' else 'hourly')

    if short and not unresolved:
        unresolved.append({'time': ledger[-1]['time'] if ledger else None, 'reason':'Sample ended without a usable expiry stock print; short call remains unresolved.', 'ric':short['ric']})
    navs=[r['nav'] for r in ledger if r['nav'] is not None]
    peak=initial;drawdown=0
    for n in navs:
        peak=max(peak,n);drawdown=min(drawdown,n/peak-1)
    last=ledger[-1] if ledger else None
    fees_sensitivity = sum(r['qty']*.65 for r in blotter if r['side']=='SELL' and r['instrument']!=cfg['stock_ric'])
    slippage_cost=sum(100*(d['mid']-d['bid']) for d in decisions if d['status']=='FILLED')
    result={'schema':2,'status':'ready' if ledger and not unresolved else 'incomplete',
            'config':cfg,'provenance':tape.get('provenance',{}),'blotter':blotter,'ledger':ledger,
            'decisions':decisions,'unresolved':unresolved,'regression':regression(pairs),
            'scatter':pairs,'quality':{'missing_option_marks':sum(r['nav'] is None for r in ledger),
            'negative_available_marks':sum(r['available'] is not None and r['available'] < -1e-8 for r in ledger),
            'negative_excess_marks':sum(r['excess'] is not None and r['excess'] < -1e-8 for r in ledger),
            'zero_volume_pairs_excluded':excluded_no_volume,
            'request_failures':len([r for r in tape.get('request_audit',[]) if r['status']=='error'])},
            'summary':{'initial_cash':initial,'ending_nav':last['nav'] if last else None,
            'ending_cash':cash,'ending_shares':shares,'calls_sold':sum(d['status']=='FILLED' for d in decisions),
            'weeks':len(mondays),'skipped_weeks':sum(d['status']=='SKIP' for d in decisions),
            'premium_collected':premium,'assignments':assignments,'expirations':expires,
            'return':last['nav']/initial-1 if last and last['nav'] is not None else None,
            'max_drawdown':drawdown,'benchmark_ending_nav':last['benchmark_nav'] if last else None,
            'bid_fill_cost_same_path':slippage_cost,'commission_cost_at_065':fees_sensitivity},
            'request_audit':tape.get('request_audit',[])}
    validate_book(result)
    return result


def validate_book(book):
    """Independent event replay: catch double cash, naked shorts, and ledger drift."""
    cash=book['summary']['initial_cash'];shares=0;calls=0;by_time={}
    for e in book['blotter']:
        by_time.setdefault(e['time'],[]).append(e)
    for r in book['ledger']:
        if r['phase']=='pre-expiry':
            pass # expiry events are posted only before post-expiry mark
        else:
            for e in by_time.pop(r['time'],[]):
                stock=e['instrument']==book['config']['stock_ric']
                if stock and e['side']=='BUY':
                    assert shares==0 and e['qty']==100
                    shares+=e['qty'];expected=-e['qty']*e['fill']
                elif stock and e['side']=='SELL':
                    shares-=e['qty'];expected=e['qty']*e['fill']
                elif e['side']=='SELL':
                    assert shares==100 and calls==0 and e['qty']==1
                    calls+=e['qty'];expected=100*e['fill']
                elif e['side'] in ('ASSIGN','EXPIRE'):
                    assert calls==1;calls-=e['qty'];expected=0
                else:raise AssertionError('Unexpected event')
                assert abs(expected-e['cash_delta'])<1e-7
                cash+=expected
                assert abs(cash-e['cash_after'])<1e-7
        assert shares==r['shares'] and calls==r['short_calls']
        assert shares>=calls*100
        assert abs(cash-r['cash'])<1e-7
        assert abs(r['initial']-.5*r['lmv'])<1e-7
        assert abs(r['maintenance']-.25*r['lmv'])<1e-7
        if r['nav'] is not None:
            assert abs(r['nav']-(cash+r['lmv']+r['option_mv']))<1e-7
            assert abs(r['available']-(r['nav']-r['initial']))<1e-7
            assert abs(r['excess']-(r['nav']-r['maintenance']))<1e-7
    assert not by_time


def export_book(tape, directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    book=run_backtest(tape)
    raw=json.dumps(book,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    (directory/'book.json').write_text(raw,encoding='utf-8')
    (directory/'book.js').write_text('window.COVERED_CALL_BOOK = '+raw.replace('<','\\u003c')+';\n',encoding='utf-8')
    import csv
    for name in ('blotter','ledger','decisions'):
        rows=book[name]
        if rows:
            fields=list(dict.fromkeys(k for r in rows for k in r))
            with (directory/(name+'.csv')).open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    return book


"""Run in Workspace CodeBook. Downloads quotes only; NEVER places live orders.
This file is combined with engine.py into a single pasteable cell for the user.
"""
from pathlib import Path
import datetime as dt
import hashlib
import json
import math
import pickle
import time
import pandas as pd

# Fixed, reproducible ten-week window. All selected expiries precede this delivery.
SETTINGS = {'stock_ric':'AAPL.O','root':'AAPL','start':'2026-07-13','end':'2026-09-18',
            'interval':'hourly','timestamp_label':'endPeriod','entry_hour_ny':11,
            'strike_step':2.5,'max_otm_dollars':15,'initial_cash':30000,
            'model':'Monday 11:00 New York, nearest valid quoted OTM/ATM call on $2.50 grid, hold to Friday expiry',
            'dividends':'Excluded: price-only account; no total-return claim',
            'fees':'Zero base-case fees; $0.65 per written contract sensitivity',
            'early_assignment':'Ignored; exercise only at Friday close per assignment',
            'marking':'Contemporaneous hourly midpoint; missing quote gives unknown NAV, never forward fill'}
CACHE = Path('hw12_lseg_checkpoint.pkl')
OUT = Path('hw12_results')
REQUEST_FIELDS = ['TRDPRC_1','BID','ASK','ACVOL_UNS']


def normalized_response(frame, fields):
    if frame is None or frame.empty:
        return []
    if not isinstance(frame.index,pd.DatetimeIndex):
        date_cols=[c for c in frame.columns if str(c).lower() in ('date','timestamp','datetime')]
        if not date_cols:
            raise ValueError('Unrecognized historical-pricing index; no timestamp guessing.')
        frame=frame.set_index(date_cols[0])
    out=[]
    for idx,row in frame.iterrows():
        t=pd.Timestamp(idx)
        # LSEG historical pricing intraday response timestamps are UTC.
        if t.tzinfo is None:t=t.tz_localize('UTC')
        else:t=t.tz_convert('UTC')
        record={'time':t.isoformat().replace('+00:00','Z')}
        for f in fields:
            columns=[c for c in frame.columns if f in (tuple(map(str,c)) if isinstance(c,tuple) else (str(c),))]
            if len(columns)>1:raise ValueError('Ambiguous single-instrument field '+f)
            v=row[columns[0]] if columns else None
            if v is None or pd.isna(v):record[f]=None
            else:
                number=float(v)
                record[f]=number if math.isfinite(number) else None
        out.append(record)
    # Exact duplicates can occur at provider pagination boundaries; conflicts fail.
    by_time={}
    for r in out:
        if r['time'] in by_time and r!=by_time[r['time']]:
            raise ValueError('Conflicting same-time source bars')
        by_time[r['time']]=r
    return sorted(by_time.values(),key=lambda r:r['time'])


def acquire():
    print('[1/4] Loading LSEG library ...', flush=True)
    try:
        import refinitiv.data as ld
        from refinitiv.data.content import historical_pricing as hp
        library='refinitiv.data'
    except ImportError:
        import lseg.data as ld
        from lseg.data.content import historical_pricing as hp
        library='lseg.data'
    print('[1/4] Library loaded: '+library, flush=True)
    if CACHE.exists():
        print('Reading saved checkpoint; completed requests will be reused.', flush=True)
        cache=pd.read_pickle(CACHE) # Resume only this trusted, self-created checkpoint.
        if cache.get('config')!=SETTINGS:
            raise RuntimeError('Checkpoint settings differ. Rename the old cache before a new experiment.')
    else:
        cache={'config':SETTINGS,'stock':[],'contracts':[],'options':[],
               'request_audit':[],'completed':[],
               'provenance':{'provider':'LSEG Workspace / CodeBook','library':library,
                'retrieved_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                'api':'historical_pricing.summaries.Definition; summaryTimestampLabel=endPeriod',
                'source_kind':'actual LSEG responses; no illustrative prices'}}

    def save():
        temporary=CACHE.with_suffix('.tmp')
        with temporary.open('wb') as f:pickle.dump(cache,f,pickle.HIGHEST_PROTOCOL)
        temporary.replace(CACHE)

    def history(ric,start,end,fields):
        started=time.monotonic()
        print(f'REQUEST {ric} | {start} to {end}', flush=True)
        result=hp.summaries.Definition(universe=ric,fields=fields,interval=hp.Intervals.HOURLY,
                  start=start,end=end,count=10000,
                  extended_params={'summaryTimestampLabel':'endPeriod'}).get_data()
        df=result.data.df
        print(f'RESPONSE {ric} | {0 if df is None else len(df)} rows | {time.monotonic()-started:.1f}s', flush=True)
        return normalized_response(df,fields)

    print('[2/4] Opening Workspace session ...', flush=True)
    ld.open_session()
    print('[2/4] Workspace session opened.', flush=True)
    try:
        print('[3/4] Loading hourly stock observations ...', flush=True)
        if not cache['stock']:
            cache['stock']=history(SETTINGS['stock_ric'],SETTINGS['start']+'T00:00:00Z',
                                  SETTINGS['end']+'T23:59:59Z',['TRDPRC_1','BID','ASK'])
            if not any(r.get('TRDPRC_1') is not None for r in cache['stock']):
                raise RuntimeError('No stock prints returned. Check CodeBook session / entitlements before continuing.')
            save()
        stock_by_time={instant(r['time']):r for r in cache['stock']}
        requests=[]
        for monday in pd.date_range(SETTINGS['start'],SETTINGS['end'],freq='W-MON'):
            expiry=monday.date()+dt.timedelta(days=4)
            if expiry>dt.date.fromisoformat(SETTINGS['end']):continue
            r=stock_by_time.get(local_at(monday.date(),SETTINGS['entry_hour_ny']))
            if not r or not finite(r.get('TRDPRC_1')) or r['TRDPRC_1']<=0:
                print(str(monday.date())+': no Monday 11:00 stock print; scheduled skip.',flush=True)
                continue
            spot=r['TRDPRC_1'];step=SETTINGS['strike_step'];anchor=math.floor(spot/step)*step
            # A small near-money sample built from Monday's spot only: two ITM levels
            # for quote/trade diagnostics and a declared $15 OTM entry band.
            for i in range(-2,8):
                strike=round(anchor+i*step,2)
                if strike<=0 or strike>spot+SETTINGS['max_otm_dollars']:continue
                ric=make_call_ric(SETTINGS['root'],expiry,strike)
                requests.append({'ric':ric,'expiry':str(expiry),'strike':strike,
                                 'start':str(monday.date())+'T00:00:00Z',
                                 'end':str(expiry)+'T23:59:59Z'})
        if not requests:
            raise RuntimeError('No Monday 11:00 UTC-aligned stock observations. Inspect timestamp labels before proceeding.')
        cache['contracts']=[{k:r[k] for k in ('ric','expiry','strike')} for r in requests]
        pending=[r for r in requests if r['ric'] not in set(cache['completed'])]
        print('[4/4] Loading expired-call observations ...', flush=True)
        print(f"Stock loaded. {len(requests)} near-money candidate requests, {len(pending)} pending. Missing candidates are expected.",flush=True)
        for i,r in enumerate(pending,1):
            status='error';rows=[];error=None
            for attempt in range(2):
                try:
                    rows=history(r['ric'],r['start'],r['end'],REQUEST_FIELDS)
                    status='observed' if any(quote(x) is not None or finite(x.get('TRDPRC_1')) for x in rows) else 'empty'
                    error=None;break
                except Exception as exc:
                    error=str(exc)[:500]
                    print(f'Request failed: {r["ric"]}, attempt {attempt+1}/2 ({type(exc).__name__}).', flush=True)
                    if attempt==0:time.sleep(1)
            cache['request_audit']=[a for a in cache['request_audit'] if a['ric']!=r['ric']]
            cache['request_audit'].append({'ric':r['ric'],'status':status,'rows':len(rows),'error':error})
            if status!='error':
                cache['options']=[o for o in cache['options'] if o['ric']!=r['ric']]
                cache['options'].extend({'ric':r['ric'],**o} for o in rows)
                cache['completed'].append(r['ric'])
            save()
            print(f"[{i}/{len(pending)}] {r['ric']}: {status}, {len(rows)} bars",flush=True)
            time.sleep(.15)
        cache['provenance']['cache_sha256']=hashlib.sha256(CACHE.read_bytes()).hexdigest()
        cache['provenance']['completed_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        return cache
    finally:
        print('Closing data session ...', flush=True)
        ld.close_session()
        print('Data session closed.', flush=True)


def main_codebook():
    print('HW12 runner v3 started (Python 3.8 compatible). Progress is printed before every network request.', flush=True)
    tape=acquire()
    print('Building the account and checking all booked cash events ...', flush=True)
    result=export_book(tape,OUT)
    print('\nACCOUNT BUILT AND EVENT-REPLAY CHECKED',flush=True)
    print(json.dumps({'status':result['status'],'summary':result['summary'],
                     'regression':result['regression'],'quality':result['quality']},indent=2),flush=True)
    import zipfile
    archive=Path('HW12_results.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.iterdir()):
            if p.is_file():z.write(p,p.name)
    try:
        from IPython.display import display,FileLink
        display(FileLink(str(archive)))
    except ImportError:
        print('Download '+str(archive))
    return result



if __name__ == "__main__":
    main_codebook()
