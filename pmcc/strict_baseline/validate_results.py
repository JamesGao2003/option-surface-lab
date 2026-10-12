"""Independent replay and output audit; does not call the backtest engine."""
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


def equal(left, right, context):
    if left is None or right is None:
        assert left is right, context+': null mismatch'
    else:
        assert math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-7), context+': %r != %r' % (left, right)


def valid(row, opening=False, cap=None):
    if not row: return False
    b, a = row.get('BID'), row.get('ASK')
    if not isinstance(b, (float, int)) or not isinstance(a, (float, int)): return False
    if not (math.isfinite(b) and math.isfinite(a) and 0 <= b <= a and a > 0): return False
    if opening and b == 0: return False
    return cap is None or (a-b)/((a+b)*.5) <= cap+1e-12


def validate(directory):
    folder = Path(directory)
    raw = (folder/'PMCC_source.json').read_bytes()
    source = json.loads(raw)
    book = json.loads((folder/'book.json').read_text(encoding='utf-8'))
    script = (folder/'book.js').read_text(encoding='utf-8').strip()
    assert script.startswith('window.PMCC_BOOK = ') and script.endswith(';'), 'Unexpected JS wrapper'
    assert json.loads(script[len('window.PMCC_BOOK = '):-1]) == book, 'JS/JSON disagreement'
    assert book['provenance']['source_sha256'] == hashlib.sha256(raw).hexdigest(), 'Raw source hash mismatch'
    cfg = source['config']; ny = ZoneInfo(cfg['timezone']); fee = cfg['option_fee_per_contract']; initial = cfg['initial_cash']
    metadata = {}; tapes = {cfg['stock_ric']: {r['time']: r for r in source['stock']}}
    for c in source['long_candidates']+source['short_candidates']+([source['long_contract']] if source.get('long_contract') else []):
        metadata[c['ric']] = c
        tapes[c['ric']] = {r['time']: r for r in c['rows']}
    positions = {a: {} for a in book['summary']}
    cash = {a: initial for a in positions}; fees = {a: 0. for a in positions}
    events = book['blotter']; ledger = book['ledger']; checks = []
    assert [e['id'] for e in events] == list(range(1, len(events)+1)), 'Event sequence'
    assert all(x['time'] <= y['time'] for x, y in zip(events, events[1:])), 'Chronological events'
    assert all(x['time'] <= y['time'] for x, y in zip(ledger, ledger[1:])), 'Chronological ledger'
    def replay(e):
        a, ric, qty, side = e['account'], e['instrument'], e['qty'], e['side']
        quote = tapes[ric].get(e['time'])
        assert valid(quote, opening=side == 'SELL' and e['kind'] == 'option'), 'Fill without valid bid/ask'
        px = quote['ASK'] if side in ('BUY', 'BUY_TO_CLOSE') else quote['BID']
        equal(e['fill'], px, 'Side-of-market fill')
        option = e['kind'] == 'option'; commission = fee*qty if option else 0.
        equal(e['fee'], commission, 'Fee')
        assert qty == (1 if option else 100), 'Wrong quantity'
        signed = qty if side in ('BUY', 'BUY_TO_CLOSE') else -qty
        holding = positions[a].get(ric, 0)
        if side == 'SELL' and option:
            assert holding == 0, 'Duplicate short'
            if a == 'PMCC':
                longs = [metadata[k] for k, v in positions[a].items() if k in metadata and v == 1]
                assert len(longs) == 1 and longs[0]['expiry'] > metadata[ric]['expiry'] and longs[0]['strike'] < metadata[ric]['strike'], 'Invalid diagonal coverage'
            elif a == 'covered_call': assert positions[a].get(cfg['stock_ric']) == 100, 'Uncovered short in CC'
            else: raise AssertionError('Short in control account')
        if side == 'BUY_TO_CLOSE':
            assert holding == -1, 'Close absent short'
            clock = dt.datetime.fromisoformat(e['time'].replace('Z', '+00:00')).astimezone(ny)
            assert clock.hour == cfg['exit_hour'] and clock.minute == 0, 'Wrong short exit clock'
            c = metadata[ric]
            if str(clock.date()) != c['expiry']:
                spot = tapes[cfg['stock_ric']][e['time']]['TRDPRC_1']
                assert spot > c['strike'] and (quote['BID']+quote['ASK'])/2-(spot-c['strike']) <= .05+1e-12, 'Early close rule not satisfied'
        if side == 'SELL_TO_CLOSE': assert holding == 1, 'Close absent long'
        delta = -signed*px*(100 if option else 1)-commission
        equal(e['cash_delta'], delta, 'Cash delta')
        cash[a] += delta; fees[a] += commission; positions[a][ric] = holding+signed
        equal(e['cash_after'], cash[a], 'Cash replay')
        assert cash[a] >= -1e-8, 'Borrowing despite cash-funded rule'
    cursor = 0
    for r in ledger:
        while cursor < len(events) and events[cursor]['time'] <= r['time']:
            replay(events[cursor]); cursor += 1
        a = r['account']; equal(r['cash'], cash[a], 'Ledger cash')
        shares = positions[a].get(cfg['stock_ric'], 0); equal(r['shares'], shares, 'Shares')
        active = {k: v for k, v in positions[a].items() if k in metadata and v}
        assert sum(v > 0 for v in active.values()) == r['long_calls'], 'Long count'
        assert sum(v < 0 for v in active.values()) == r['short_calls'], 'Short count'
        nav = cash[a]; liquidation = cash[a]; missing = []
        for instrument, quantity in [(cfg['stock_ric'], shares)]+list(active.items()):
            if not quantity: continue
            q = tapes[instrument].get(r['time'])
            if not valid(q):
                missing.append('stock' if instrument == cfg['stock_ric'] else ('long_call' if quantity > 0 else 'short_call'))
                continue
            unit = 1 if instrument == cfg['stock_ric'] else 100
            nav += quantity*unit*(q['BID']+q['ASK'])/2
            liquidation += quantity*unit*(q['BID'] if quantity > 0 else q['ASK'])
            if unit == 100: liquidation -= abs(quantity)*fee
        equal(r['nav'], None if missing else nav, 'NAV')
        equal(r['liquidation_nav'], None if missing else liquidation, 'Liquidation NAV')
        assert sorted(r['missing_marks']) == sorted(missing), 'Missing-mark audit'
    assert cursor == len(events), 'Events after last ledger snapshot'
    checks.append('Every event matched source-side quote, fee and position; cash replay and every NAV/liquidation NAV reconciled.')
    long_entries = [e for e in events if e['account'] == 'PMCC' and e['side'] == 'BUY']
    if long_entries:
        e = long_entries[0]; spot = tapes[cfg['stock_ric']][e['time']]['TRDPRC_1']; grid = cfg['strike_grid']
        possible = []
        for c in source['long_candidates']:
            q = next((r for r in c['rows'] if r['time'] == e['time']), None)
            if cfg['long_min_moneyness']*spot-1e-9 <= c['strike'] <= cfg['long_max_moneyness']*spot+1e-9 and c['expiry'] == cfg['long_expiry'] and abs(c['strike']/grid-round(c['strike']/grid)) < 1e-8 and valid(q, opening=True, cap=cfg['long_max_relative_spread']) and q['ASK'] >= max(spot-c['strike'], 0)-.01:
                possible.append(c)
        chosen = min(possible, key=lambda c: (abs(c['strike']-spot*cfg['long_target_moneyness']), c['strike'], c['ric']))
        assert chosen['ric'] == e['instrument'], 'Long choice does not match entry-only rule'
    for d in book['decisions']:
        if d['status'] != 'SELL': continue
        t = d['time']; spot = tapes[cfg['stock_ric']][t]['TRDPRC_1']; grid = cfg['strike_grid']
        anchor = math.ceil(spot*cfg['short_target_moneyness']/grid)*grid
        selected_long = next(e for e in events if e['account'] == 'PMCC' and e['side'] == 'BUY')['instrument']
        possible = []
        for c in source['short_candidates']:
            offset = (c['strike']-anchor)/grid
            if c['monday'] == d['monday'] and c['expiry'] == d['friday'] and c['strike'] > metadata[selected_long]['strike'] and 0 <= offset < cfg['short_candidates'] and abs(offset-round(offset)) < 1e-8 and valid(tapes[c['ric']].get(t), opening=True, cap=cfg['short_max_relative_spread']):
                possible.append(c)
        expected = sorted(possible, key=lambda c: (c['strike'], c['ric']))[0]
        assert expected['ric'] == d['ric'], 'Entry selection is not lowest eligible strike'
    checks.append('Long and short entry choices recomputed from entry-time quotes, without future-liquidity screening.')
    for a, s in book['summary'].items():
        account_rows = [r for r in ledger if r['account'] == a]
        final_nav = account_rows[-1]['nav'] if account_rows else None
        equal(s['ending_nav'], final_nav, 'Summary NAV')
        equal(s['net_pnl'], None if final_nav is None else final_nav-initial, 'PnL')
        equal(s['total_return'], None if final_nav is None else final_nav/initial-1, 'Return')
        equal(s['cash'], cash[a], 'Summary cash'); equal(s['fees'], fees[a], 'Summary fees')
        peak, dd = initial, 0.
        for r in account_rows:
            if r['nav'] is not None:
                peak = max(peak, r['nav']); dd = min(dd, r['nav']/peak-1)
        if any(r['nav'] is not None for r in account_rows): equal(s['max_drawdown'], dd, 'Drawdown')
        if book['status'] == 'complete': assert not any(positions[a].values()), 'Complete account is not flat'
    for table in ('blotter', 'ledger', 'decisions', 'requests'):
        with (folder/(table+'.csv')).open(encoding='utf-8', newline='') as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == len(book[table]), table+' CSV length'
        for actual, expected in zip(rows, book[table]):
            for key, value in expected.items():
                rendered = json.dumps(value, separators=(',', ':')) if isinstance(value, (dict, list)) else ('' if value is None else str(value))
                assert actual[key] == rendered, table+' CSV mismatch '+key
    checks.append('Summary, all CSV exports, JSON/JavaScript identity and unmodified source SHA-256 verified.')
    for label, fit in [('pooled', book['scatter'])]+list(book.get('regression_by_leg', {}).items()):
        points = fit['points']; assert fit['n'] == len(points), 'Regression count'
        for p in points:
            row = tapes[p['ric']][p['time']]
            equal(p['mid'], (row['BID']+row['ASK'])/2, 'Scatter mid')
            equal(p['trade'], row['TRDPRC_1'], 'Scatter print')
        if fit['slope'] is not None:
            n = len(points); sx = sum(p['mid'] for p in points); sy = sum(p['trade'] for p in points)
            sxx = sum(p['mid']**2 for p in points); sxy = sum(p['mid']*p['trade'] for p in points)
            slope = (n*sxy-sx*sy)/(n*sxx-sx*sx); intercept = (sy-slope*sx)/n
            equal(fit['slope'], slope, label+' slope'); equal(fit['intercept'], intercept, label+' intercept')
            sse = sum((p['trade']-intercept-slope*p['mid'])**2 for p in points)
            sst = sum((p['trade']-sy/n)**2 for p in points)
            equal(fit['r2'], 1-sse/sst if sst else None, label+' R2')
    checks.append('Every scatter point traces to source; separate long/short and pooled regressions independently recomputed.')
    result = {'status': 'PASS', 'source_sha256': hashlib.sha256(raw).hexdigest(), 'book_sha256': hashlib.sha256((folder/'book.json').read_bytes()).hexdigest(),
              'book_status': book['status'], 'events': len(events), 'ledger_rows': len(ledger), 'checks': checks,
              'limitations': ['Audit verifies reproducibility from supplied API response data, not the provider entitlement, original exchange tape, or tick-level executability.',
                              'American-option assignment is not observed by this source; the base assignment assumption remains a model limitation.']}
    (folder/'validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit('Usage: python validate_results.py result_directory')
    print(json.dumps(validate(sys.argv[1]), indent=2))
