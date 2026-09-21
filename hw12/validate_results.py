"""Validate derived CodeBook results without executing the supplied book.js.

Usage: python validate_results.py path/to/result_directory
The full raw checkpoint is not supplied; candidate completeness cannot be proven.
"""
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np
from engine import validate_book, instant, NY, make_call_ric
from datetime import date


def validate(folder):
    folder = Path(folder)
    raw = (folder / 'book.json').read_bytes()
    b = json.loads(raw.decode('utf-8-sig'))
    assert b['schema'] == 2
    js = (folder / 'book.js').read_text(encoding='utf-8-sig').strip()
    prefix = 'window.COVERED_CALL_BOOK = '
    assert js.startswith(prefix) and js.endswith(';')
    assert json.loads(js[len(prefix):-1]) == b, 'book.js and JSON disagree'
    validate_book(b)
    close = lambda a,z: math.isclose(a,z,rel_tol=1e-10,abs_tol=1e-7)
    stockric = b['config']['stock_ric']
    assert b['config']['timestamp_label'] == 'endPeriod'
    assert len({r['time'] for r in b['decisions']}) == len(b['decisions'])
    assert len({(r['time'],r['phase']) for r in b['ledger']}) == len(b['ledger'])
    assert [r['time'] for r in b['ledger']] == sorted(r['time'] for r in b['ledger'])
    assert [r['time'] for r in b['blotter']] == sorted(r['time'] for r in b['blotter'])
    byric = {d['ric']: d for d in b['decisions'] if d['status'] == 'FILLED'}
    entries = [e for e in b['blotter'] if e['side'] == 'SELL' and e['instrument'] != stockric]
    assert len(entries) == len(byric)
    for e in entries:
        d = byric[e['instrument']]
        t = instant(e['time']).astimezone(NY)
        assert t.weekday() == 0 and t.hour == 11 and t.minute == 0
        assert e['time'] == d['time'] and e['qty'] == 1
        assert d['bid'] > 0 and d['ask'] >= d['bid']
        assert close(e['fill'], (d['bid']+d['ask'])/2) and close(e['limit'],e['fill'])
        assert 0 <= d['strike']-d['spot'] <= 15
        assert make_call_ric('AAPL',date.fromisoformat(d['expiry']),d['strike']) == d['ric']
        assert d['available_after'] >= 0
    for d in b['decisions']:
        if d['status'] == 'SKIP': assert not any(e['time'] == d['time'] for e in b['blotter'])
    for i,r in enumerate(b['ledger']):
        assert close(r['lmv'],r['shares']*r['stock_mark'])
        if r['option_mark'] is not None:
            assert close(r['option_mv'],-100*r['short_calls']*r['option_mark'])
        else: assert r['nav'] is None and r['available'] is None and r['excess'] is None
        if r['phase'] == 'pre-expiry':
            t=instant(r['time']).astimezone(NY)
            assert t.weekday()==4 and t.hour==16 and str(t.date())==r['expiry']
            assert close(r['option_mark'],max(r['stock_mark']-r['strike'],0))
            post=b['ledger'][i+1]
            assert post['phase']=='post-expiry' and close(r['nav'],post['nav'])
            event=next(e for e in b['blotter'] if e['time']==r['time'] and e['instrument']==r['option_ric'])
            expected='ASSIGN' if r['stock_mark']>r['strike'] else 'EXPIRE'
            assert event['side']==expected
            assert post['shares']==(0 if expected=='ASSIGN' else 100)
            if expected=='ASSIGN':
                delivery=next(e for e in b['blotter'] if e['time']==r['time'] and e['instrument']==stockric)
                assert close(delivery['fill'],r['strike']) and delivery['qty']==100
    pairs=b['scatter']
    assert len({(r['ric'],r['time']) for r in pairs})==len(pairs)
    for r in pairs:
        assert r['bid']>0 and r['ask']>=r['bid'] and close(r['mid'],(r['bid']+r['ask'])/2)
    x=np.array([r['mid'] for r in pairs]); y=np.array([r['trade'] for r in pairs])
    slope,intercept=np.linalg.lstsq(np.column_stack([x,np.ones(len(x))]),y,rcond=None)[0]
    r2=1-float(np.sum((y-(slope*x+intercept))**2)/np.sum((y-y.mean())**2))
    for key,value in [('slope',slope),('intercept',intercept),('r2',r2),('mae',np.mean(np.abs(y-x)))]:
        assert close(b['regression'][key],value),key
    s=b['summary']; events=b['blotter']; ledger=b['ledger']
    assert close(s['ending_cash'],s['initial_cash']+sum(e['cash_delta'] for e in events))
    assert close(s['ending_nav'],ledger[-1]['nav'])
    assert close(s['return'],s['ending_nav']/s['initial_cash']-1)
    assert close(s['premium_collected'],sum(e['cash_delta'] for e in entries))
    assert s['calls_sold']==len(entries) and s['weeks']==len(b['decisions'])
    assert s['assignments']==sum(e['side']=='ASSIGN' for e in events)
    assert s['expirations']==sum(e['side']=='EXPIRE' for e in events)
    runningpeak=s['initial_cash']; worst=0
    for r in ledger:
        if r['nav'] is not None:
            runningpeak=max(runningpeak,r['nav']);worst=min(worst,r['nav']/runningpeak-1)
    assert close(worst,s['max_drawdown'])
    # Supplied CSV values must agree with the authoritative JSON, without executing JS.
    for name in ('blotter','decisions'):
        with (folder/(name+'.csv')).open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
        assert len(rows)==len(b[name])
        for actual,expected in zip(rows,b[name]):
            for key,val in expected.items():
                got=actual[key]
                if val is None: assert got==''
                elif isinstance(val,(int,float)): assert close(float(got),val)
                else: assert got==str(val)
    return {'result':'PASS','source_sha256':hashlib.sha256(raw).hexdigest(),
            'blotter_events':len(events),'ledger_rows':len(ledger),'paired_observations':len(pairs),
            'independent_ols':{'slope':float(slope),'intercept':float(intercept),'r2':r2},
            'stock_cash_pnl':sum(e['cash_delta'] for e in events if e['instrument']==stockric),
            'minimum_available':min(r['available'] for r in ledger if r['available'] is not None),
            'minimum_excess':min(r['excess'] for r in ledger if r['excess'] is not None),
            'minimum_recorded_cash':min(r['cash'] for r in ledger),
            'limitations':['27 candidate requests failed; no-data errors do not prove unlisted contracts or absent markets.',
                '6 recorded option marks are missing; drawdown is measured on observed NAV only.',
                'Full original tape was not supplied; exhaustive chain coverage, every candidate and bar-level freshness cannot be independently established.']}


if __name__=='__main__':
    print(json.dumps(validate(sys.argv[1] if len(sys.argv)>1 else Path(__file__).parent),indent=2))
