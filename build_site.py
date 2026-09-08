"""Read a trusted LSEG pickle and build an entirely static GitHub Pages site.
Usage: python build_site.py option_pipeline_data_v2.pkl
The browser uses an embedded JSON snapshot; Python loads the pickle at build time.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import pandas as pd
from plotly.offline import get_plotlyjs
from fetch_options_v2 import parse_option_ric, to_long

ROOT = Path(__file__).resolve().parent
FIELDS = ['MID_PRICE', 'TRDPRC_1']


def build(cache):
    cache = Path(cache).resolve()
    p = pd.read_pickle(cache)  # pandas compatibility loader for older CodeBook pickles
    d = to_long(p['options'])  # Re-parse the raw RICs; do not trust a premade long table.
    assert not d.duplicated(['date', 'ric']).any(), 'Duplicate contract/date rows'
    for f in FIELDS:
        d[f] = pd.to_numeric(d[f], errors='raise').astype(float)
        assert not (d[f].dropna() < 0).any(), f'Negative {f}'
        assert not d[f].dropna().isin([float('inf'), -float('inf')]).any()
    assert (pd.to_datetime(d.expiry) >= d.date).all()
    observed = d[d[FIELDS].notna().any(axis=1)].copy()
    assert not observed.empty, 'No observed prices'
    first = observed.groupby('ric').date.min()
    candidates = p.get('candidate_rics', list(d.ric.unique()))
    latest_audit = {a['ric']: a for a in p.get('request_audit', [])}
    contracts = []
    for ric in candidates:
        meta = parse_option_ric(ric)
        meta.update(ric=ric, expiry=meta['expiry'].isoformat(),
                    first_seen=first[ric].strftime('%Y-%m-%d') if ric in first else None,
                    status=latest_audit.get(ric, {}).get('status', 'unknown'))
        contracts.append(meta)
    records = []
    for row in observed.itertuples(index=False):
        records.append([row.date.strftime('%Y-%m-%d'), row.ric,
                        None if pd.isna(row.MID_PRICE) else row.MID_PRICE,
                        None if pd.isna(row.TRDPRC_1) else row.TRDPRC_1])
    stock = p['stock'].copy()
    stock_records = []
    for date, row in stock.iterrows():
        stock_records.append([pd.Timestamp(date).strftime('%Y-%m-%d')]+[
            None if pd.isna(row.get(f)) else float(row[f])
            for f in ['OPEN_PRC', 'HIGH_1', 'LOW_1', 'TRDPRC_1']])
    dates = sorted(set(d.date.dt.strftime('%Y-%m-%d')))
    default = observed.groupby('date').size().idxmax().strftime('%Y-%m-%d')
    audit = dict(candidate_count=len(candidates), observed_contracts=observed.ric.nunique(),
                 failed_requests=sum(c['status']=='request_failed' for c in contracts),
                 no_observations=sum(c['status']=='no_observations' for c in contracts),
                 mid_count=int(d.MID_PRICE.notna().sum()), trade_count=int(d.TRDPRC_1.notna().sum()),
                 calls=observed.loc[observed.type=='Call','ric'].nunique(),
                 puts=observed.loc[observed.type=='Put','ric'].nunique(),
                 duplicates=int(d.duplicated(['date','ric']).sum()), negative_prices=0,
                 stock_first=str(stock.index.min().date()), stock_last=str(stock.index.max().date()),
                 cache_sha256=hashlib.sha256(cache.read_bytes()).hexdigest())
    data = dict(ticker=p['ticker'], fetched_at=p['fetched_at'], settings=p['settings'],
                cache_name=cache.name, audit=audit, contracts=contracts,
                records=records, stock=stock_records, dates=dates, default_date=default)
    # Generate independently calculated metric reference for every state.
    stats = []
    for date in dates:
        for side in ['Call','Put']:
            eligible = [c['ric'] for c in contracts if c['type']==side and c['first_seen'] and c['first_seen']<=date<=c['expiry']]
            day = observed[(observed.date==date)&(observed.type==side)]
            both=day.MID_PRICE.notna()&day.TRDPRC_1.notna()
            n_only=int((day.MID_PRICE.notna()&day.TRDPRC_1.isna()).sum())
            stats.append(dict(date=date,side=side,denominator=len(eligible),mid_only=n_only,
                              percent=100*n_only/len(eligible) if eligible else None,
                              paired=int(both.sum()),median=float((day.loc[both,'MID_PRICE']-day.loc[both,'TRDPRC_1']).abs().median()) if both.any() else None))
    (ROOT/'metric_reference.json').write_text(json.dumps(stats,allow_nan=False,indent=2))
    (ROOT/'data_snapshot.json').write_text(json.dumps(data,allow_nan=False,separators=(',',':')))
    (ROOT/'data_quality.json').write_text(json.dumps(audit,indent=2))
    d.to_csv(ROOT/'option_prices_long.csv',index=False)
    pd.DataFrame(p.get('request_audit',[])).to_csv(ROOT/'option_request_audit.csv',index=False)
    if cache.parent != ROOT:
        shutil.copy2(cache,ROOT/cache.name)
    template=(ROOT/'template.html').read_text()
    html=template.replace('/*__CSS__*/',(ROOT/'style.css').read_text()).replace('/*__PLOTLY__*/',get_plotlyjs()).replace('/*__APP__*/',(ROOT/'app.js').read_text())
    html=html.replace('__DATA__',json.dumps(data,allow_nan=False,separators=(',',':')).replace('<','\\u003c'))
    (ROOT/'index.html').write_text(html)
    (ROOT/'.nojekyll').touch()
    print(json.dumps(audit,indent=2))
    print('Built',ROOT/'index.html','default date',default)
    return data

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('cache',nargs='?',default='option_pipeline_data_v2.pkl')
    args=parser.parse_args()
    build(args.cache)
