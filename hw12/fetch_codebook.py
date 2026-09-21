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


if __name__=='__main__':
    # Standard file execution: engine.py is in the same directory.
    from engine import instant, local_at, finite, quote, make_call_ric, export_book
    main_codebook()
