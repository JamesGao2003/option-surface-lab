"""Deterministic, cash-funded PMCC research backtest. Python 3.9+; no broker API.

Input is the unmodified PMCC_CodeBook_Run.py JSON export. Quotes are observations,
not orders. Synthetic unit-test fixtures must never be used as published results.
"""
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from zoneinfo import ZoneInfo

ACCOUNTS = ('PMCC', 'covered_call', 'buy_hold', 'long_call')


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def quote(row, cap=None, allow_zero_bid=False):
    if not row or not finite(row.get('BID')) or not finite(row.get('ASK')):
        return False
    b, a = row['BID'], row['ASK']
    if not ((0 <= b if allow_zero_bid else 0 < b) and b <= a and a > 0):
        return False
    return cap is None or (a-b)/((a+b)/2) <= cap+1e-12


def mid(row):
    return (row['BID']+row['ASK'])/2 if quote(row, allow_zero_bid=True) else None


def canonical_time(value):
    t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Naive timestamps are forbidden')
    return t.astimezone(dt.timezone.utc).isoformat().replace('+00:00', 'Z')


def index(rows):
    result = {}
    for r in rows:
        t = canonical_time(r['time'])
        if t in result and result[t] != r:
            raise ValueError('Conflicting duplicate source timestamp: '+t)
        result[t] = r
    return result


def _fit(points):
    n = len(points)
    out = {'n': n, 'slope': None, 'intercept': None, 'r2': None, 'mae': None, 'points': points}
    if not n:
        return out
    xbar = statistics.fmean(p['mid'] for p in points)
    ybar = statistics.fmean(p['trade'] for p in points)
    xx = sum((p['mid']-xbar)**2 for p in points)
    yy = sum((p['trade']-ybar)**2 for p in points)
    out['mae'] = statistics.fmean(abs(p['trade']-p['mid']) for p in points)
    if n >= 2 and xx > 0:
        slope = sum((p['mid']-xbar)*(p['trade']-ybar) for p in points)/xx
        intercept = ybar-slope*xbar
        ss = sum((p['trade']-intercept-slope*p['mid'])**2 for p in points)
        out.update(slope=slope, intercept=intercept, r2=1-ss/yy if yy > 0 else None)
    return out


def backtest(source):
    cfg = dict(source['config'])
    ny = ZoneInfo(cfg.get('timezone', 'America/New_York'))
    initial = float(cfg['initial_cash'])
    mult = int(cfg.get('contract_multiplier', 100))
    fee = float(cfg.get('option_fee_per_contract', .65))
    if mult != 100 or initial <= 0 or fee < 0:
        raise ValueError('This model requires 100-share contracts and positive initial cash')
    start_date, end_date = [dt.date.fromisoformat(cfg[x]) for x in ('start', 'end')]
    # Published 2026 US equity-market holidays inside this fixed study. Monday
    # decisions remain in the audit, but no fictitious closed-session mark is added.
    calendar_closed = set(cfg.get('known_closed_fridays', [])) | set(cfg.get('market_closed_dates', ['2026-05-25', '2026-09-07']))
    def stamp(day, hour):
        day = dt.date.fromisoformat(day) if isinstance(day, str) else day
        return dt.datetime.combine(day, dt.time(hour), ny).astimezone(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
    def local(t):
        return dt.datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(ny)
    start, end = stamp(start_date, cfg['entry_hour']), stamp(end_date, cfg['exit_hour'])
    stock = index(source.get('stock', []))
    contracts = {}
    for c in source.get('long_candidates', []) + source.get('short_candidates', []) + ([source['long_contract']] if source.get('long_contract') else []):
        old = contracts.get(c['ric'])
        if old and (old['strike'] != c['strike'] or old['expiry'] != c['expiry']):
            raise ValueError('Conflicting instrument metadata')
        contracts[c['ric']] = dict(c, tape=index(c.get('rows', [])))
    states = {a: {'cash': initial, 'shares': 0, 'long': None, 'short': None, 'fees': 0., 'premium_received': 0.} for a in ACCOUNTS}
    book = {'schema_version': 1, 'status': 'complete', 'config': cfg,
            'provenance': dict(source.get('provenance', {})), 'summary': {},
            'blotter': [], 'ledger': [], 'decisions': [], 'requests': source.get('request_audit', []),
            'funding': {}, 'stress': {'scenarios': []}, 'halt': None,
            'methodology': {'fills': 'Buy at ask; sell at bid; option fee per contract on every leg. Quotes are same-label hourly observations, not guaranteed simultaneous or executable ticks.',
              'marks': 'Contemporaneous bid/ask mid; liquidation NAV uses bid for longs, ask for shorts and includes option close fees. Missing quotes produce gaps, never forward-filled.',
              'capital': 'Four independent $50,000 accounts; no borrowing. PMCC is a debit diagonal spread, not stock-covered. No portfolio-margin or stock-covered Reg T assumption.',
              'assignment': 'Base path assumes no early assignment before rule-based close. Daily checks cannot eliminate overnight or intraday American-option assignment risk. Separate explicit assignment/exercise stress.',
              'benchmark': 'Same-call-schedule covered call holds 100 shares and uses the PMCC short trades. Buy-and-hold and long-call-only enter and exit on the same horizon. Common initial cash, no interest or dividends.',
              'selection': 'Fixed stock, dates and rules are a retrospective case study; entry decisions never use later quote availability or realized returns.',
              'metrics': 'No annualization. Observed-NAV drawdown may understate true drawdown where marks are missing. Daily returns only use complete adjacent weekdays (Friday to Monday allowed); holiday bridges are excluded.'}}
    book['methodology']['capital'] = book['methodology']['capital'].replace('$50,000', '${:,.0f}'.format(initial))
    def halt(t, reason):
        book['status'] = 'halted'
        book['halt'] = {'time': t, 'reason': reason,
                        'unresolved_accounts': [a for a, s in states.items() if s['long'] or s['short'] or s['shares']]}
    def event(a, t, instrument, side, qty, price, rule, kind, strike=None, expiry=None):
        s = states[a]
        commission = fee*qty if kind == 'option' else 0.
        direction = 1 if side in ('SELL', 'SELL_TO_CLOSE') else -1
        delta = direction*price*qty*(mult if kind == 'option' else 1)-commission
        if s['cash']+delta < -1e-8:
            raise AssertionError('Attempted unfunded event: '+a+' '+side)
        s['cash'] += delta
        s['fees'] += commission
        book['blotter'].append({'id': len(book['blotter'])+1, 'order_sequence': len(book['blotter'])+1, 'phase': 'BOOKED', 'account': a, 'time': t,
            'instrument': instrument, 'kind': kind, 'side': side, 'qty': qty,
            'fill': price, 'fee': commission, 'cash_delta': delta, 'cash_after': s['cash'],
            'strike': strike, 'expiry': expiry, 'rule': rule})
    def opt_event(a, t, c, side, price, rule):
        event(a, t, c['ric'], side, 1, price, rule, 'option', c['strike'], c['expiry'])
    def long_close(a, t, reason):
        s = states[a]
        c = s['long']
        q = c['tape'].get(t)
        if not quote(q, allow_zero_bid=True) or s['cash']+q['BID']*mult-fee < -1e-8:
            return False
        opt_event(a, t, c, 'SELL_TO_CLOSE', q['BID'], reason)
        s['long'] = None
        return True
    def snapshot(t):
        stock_row = stock.get(t)
        sm = mid(stock_row)
        for a, s in states.items():
            lc, sc = s['long'], s['short']
            lq = lc['tape'].get(t) if lc else None
            sq = sc['tape'].get(t) if sc else None
            lm, cm = mid(lq) if lc else 0., mid(sq) if sc else 0.
            missing = []
            if s['shares'] and sm is None: missing.append('stock')
            if lc and lm is None: missing.append('long_call')
            if sc and cm is None: missing.append('short_call')
            nav = None if missing else s['cash']+s['shares']*(sm or 0)+mult*(lm-cm)
            liq = None if missing else s['cash']+s['shares']*(stock_row['BID'] if s['shares'] else 0)+mult*((lq['BID'] if lc else 0)-(sq['ASK'] if sc else 0))-fee*(bool(lc)+bool(sc))
            book['ledger'].append({'time': t, 'account': a, 'phase': 'POST_EVENTS', 'order_sequence': len(book['blotter']), 'contract_multiplier': mult, 'cash': s['cash'], 'shares': s['shares'],
                'long_calls': int(bool(lc)), 'short_calls': int(bool(sc)),
                'long_ric': lc['ric'] if lc else None, 'long_strike': lc['strike'] if lc else None, 'long_expiry': lc['expiry'] if lc else None,
                'short_ric': sc['ric'] if sc else None, 'short_strike': sc['strike'] if sc else None, 'short_expiry': sc['expiry'] if sc else None,
                'stock_mark': sm, 'long_mark': lm, 'short_mark': cm, 'nav': nav,
                'liquidation_nav': liq, 'fees_cumulative': s['fees'], 'missing_marks': missing})
    sq0 = stock.get(start)
    spot0 = sq0.get('TRDPRC_1') if sq0 else None
    long = None
    grid = cfg['strike_grid']
    candidates = sorted(source.get('long_candidates', []), key=lambda c: (abs(c['strike']-(spot0 or 0)*cfg['long_target_moneyness']), c['strike'], c['ric']))
    for c in candidates:
        q = index(c.get('rows', [])).get(start)
        if finite(spot0) and spot0 > 0 and cfg['long_min_moneyness']*spot0-1e-9 <= c['strike'] <= cfg['long_max_moneyness']*spot0+1e-9 and abs(c['strike']/grid-round(c['strike']/grid)) < 1e-8 and c['expiry'] == cfg['long_expiry'] and quote(q, cfg['long_max_relative_spread']) and q['ASK'] >= max(spot0-c['strike'], 0)-.01:
            long = contracts[c['ric']]
            break
    if not quote(sq0) or long is None:
        book.update(status='no_entry', halt={'time': start, 'reason': 'No eligible first-Monday stock and long-call entry quote; dates were not changed to seek a result.'})
        book['decisions'].append({'time': start, 'monday': str(start_date), 'status': 'NO_ENTRY', 'ric': None, 'strike': None, 'reason': book['halt']['reason']})
    elif source.get('long_contract', {}).get('ric') != long['ric']:
        raise ValueError('Extractor-selected long disagrees with entry-only independent selection')
    elif dt.date.fromisoformat(long['expiry']) <= end_date:
        raise ValueError('Long expiry must follow the final liquidation date')
    else:
        lq0 = long['tape'].get(start)
        if not quote(lq0, cfg['long_max_relative_spread']):
            raise ValueError('Selected long historical tape lacks its valid entry observation')
        if lq0['ASK']*mult+fee > initial or sq0['ASK']*100 > initial:
            book.update(status='no_entry', halt={'time': start, 'reason': 'Initial cash cannot fund both comparison designs; no trades booked.'})
        else:
            for a in ('PMCC', 'long_call'):
                opt_event(a, start, long, 'BUY', lq0['ASK'], 'Initial entry: closest eligible 70%-of-spot strike; buy long call at ask.')
                states[a]['long'] = long
            for a in ('covered_call', 'buy_hold'):
                event(a, start, cfg['stock_ric'], 'BUY', 100, sq0['ASK'], 'Comparison enters 100 shares at stock ask.', 'stock')
                states[a]['shares'] = 100
            weeks = source.get('weeks', [])
            entry_weeks = {stamp(w['monday'], cfg['entry_hour']): w for w in weeks}
            # Mandatory times are retained even when the API has no row at that time.
            timeline = {t for t in stock if start <= t <= end and 10 <= local(t).hour <= 16 and local(t).minute == 0}
            timeline.update(entry_weeks)
            timeline.add(end)
            for w in weeks:
                monday = dt.date.fromisoformat(w['monday'])
                for i in range(5):
                    d = monday+dt.timedelta(days=i)
                    if str(d) not in calendar_closed:
                        timeline.add(stamp(d, cfg['exit_hour']))
            first_short_done = False
            for t in sorted(t for t in timeline if start <= t <= end):
                current_stock = stock.get(t)
                spot = current_stock.get('TRDPRC_1') if current_stock else None
                pm = states['PMCC']
                active = pm['short']
                if active and local(t).hour == cfg['exit_hour']:
                    q = active['tape'].get(t)
                    expiry_close = t == stamp(active['expiry'], cfg['exit_hour'])
                    if expiry_close and not quote(q, allow_zero_bid=True):
                        halt(t, 'Mandatory short-call exit quote unavailable: '+active['ric'])
                    elif not expiry_close and (not finite(spot) or (spot > active['strike'] and mid(q) is None)):
                        # A missing observation prevents the stated daily assignment-risk rule from being evaluated.
                        halt(t, 'Daily early-assignment-risk check unavailable; cannot assume it passed: '+active['ric'])
                    elif expiry_close or (spot > active['strike'] and mid(q)-max(spot-active['strike'], 0) <= .05+1e-12):
                        reason = 'Friday 15 ET scheduled buy-to-close.' if expiry_close else 'Daily 15 ET ITM call with mid extrinsic <= $0.05: close, no replacement this week.'
                        debit = q['ASK']*mult+fee
                        if any(states[a]['cash'] < debit-1e-8 for a in ('PMCC', 'covered_call')):
                            halt(t, 'Cash cannot fund required short-call close; unresolved position, no unfunded fill.')
                        else:
                            for a in ('PMCC', 'covered_call'):
                                opt_event(a, t, active, 'BUY_TO_CLOSE', q['ASK'], reason)
                                states[a]['short'] = None
                if book['status'] == 'halted':
                    snapshot(t)
                    break
                if t in entry_weeks:
                    w = entry_weeks[t]
                    decision = {'time': t, 'monday': w['monday'], 'friday': w['friday'], 'status': 'SKIP', 'ric': None, 'strike': None, 'spot': spot, 'reason': ''}
                    if w['friday'] in cfg.get('known_closed_fridays', []):
                        decision['reason'] = 'Predeclared closed-Friday week; no substituted expiry.'
                    elif not finite(spot) or spot <= 0:
                        decision['reason'] = 'Missing Monday stock print.'
                    elif not pm['long'] or pm['short']:
                        decision['reason'] = 'No available long-call coverage.'
                    else:
                        anchor = math.ceil(spot*cfg['short_target_moneyness']/grid)*grid
                        chosen = None
                        for c in sorted((c for c in source.get('short_candidates', []) if c.get('monday') == w['monday']), key=lambda c: (c['strike'], c['ric'])):
                            q = contracts[c['ric']]['tape'].get(t)
                            offset = (c['strike']-anchor)/grid
                            if c['expiry'] == w['friday'] and c['strike'] > pm['long']['strike'] and 0 <= offset < cfg['short_candidates'] and abs(offset-round(offset)) < 1e-8 and quote(q, cfg['short_max_relative_spread']):
                                chosen = contracts[c['ric']]
                                break
                        if chosen is None:
                            decision['reason'] = 'None of the three predeclared strikes has an eligible Monday bid/ask; no future-liquidity screening.'
                        elif any(states[a]['cash']+chosen['tape'][t]['BID']*mult-fee < -1e-8 for a in ('PMCC', 'covered_call')):
                            decision['reason'] = 'Opening premium does not fund its commission from available cash; skip both matched strategies.'
                        else:
                            q = chosen['tape'][t]
                            # Opening receives premium. Every subsequent debit must be funded
                            # when it occurs; the long call is not assigned stock-margin credit.
                            for a in ('PMCC', 'covered_call'):
                                opt_event(a, t, chosen, 'SELL', q['BID'], 'Monday 11 ET: lowest eligible of first three $5 strikes >= 103% of spot, above long strike.')
                                states[a]['short'] = chosen
                                states[a]['premium_received'] += q['BID']*mult
                            decision.update(status='SELL', ric=chosen['ric'], strike=chosen['strike'], expiry=chosen['expiry'], bid=q['BID'], ask=q['ASK'], reason='Entry-only rule satisfied; short sold at bid, fee charged.')
                            if not first_short_done:
                                first_short_done = True
                                cash0 = pm['cash']
                                lk, sk = pm['long']['strike'], chosen['strike']
                                mark_long = mid(pm['long']['tape'].get(t))
                                events = [
                                    {'side': 'ASSIGN_SHORT_CALL', 'cash_delta': mult*sk, 'shares_after': -100, 'long_calls_after': 1, 'short_calls_after': 0},
                                    {'side': 'ELECT_EXERCISE_LONG', 'cash_delta': -mult*lk, 'shares_after': 0, 'long_calls_after': 0, 'short_calls_after': 0}]
                                book['stress']['scenarios'].append({'name': 'Immediate assignment and voluntary long exercise at first short entry', 'time': t,
                                    'assumption': 'Mechanical off-path stress, including possible voluntary assignment while OTM; not a claim of observed assignment. Assignment first creates 100 short shares. Long exercise is an explicit election, not automatic. Both settle together in this scenario; broker permission, settlement timing, borrow and exercise fees are not modelled.',
                                    'events': events, 'short_strike': sk, 'long_strike': lk, 'cash_before': cash0,
                                    'assignment_receipt': mult*sk, 'exercise_payment': mult*lk,
                                    'ending_cash': cash0+mult*(sk-lk), 'pnl_vs_initial_cash': cash0+mult*(sk-lk)-initial,
                                    'exercise_funding_if_assignment_proceeds_unavailable': max(mult*lk-cash0, 0),
                                    'long_extrinsic_sacrificed': mult*max(mark_long-max(spot-lk, 0), 0) if mark_long is not None else None,
                                    'short_stock_notional_before_exercise': mult*spot})
                    book['decisions'].append(decision)
                if t == start:
                    debits = {a: initial-states[a]['cash'] for a in ACCOUNTS}
                    book['funding'] = {'initial_debit': debits, 'cash_buffer': {a: states[a]['cash'] for a in ACCOUNTS},
                        'capital_saving_vs_cc': 1-debits['PMCC']/debits['covered_call'] if debits['covered_call'] > 0 else None,
                        'stock_purchase_cost': 100*sq0['ASK'], 'long_purchase_cost': mult*lq0['ASK']+fee,
                        'note': 'Initial net booked outlay, including any first-Monday call premium and fees. Capital saving does not imply equal risk; all results use identical starting cash. Remaining cash is reserved; no broker margin entitlement is assumed.'}
                if t == end:
                    if states['PMCC']['short']:
                        halt(t, 'Short still open at final horizon; cannot report a fully realized result.')
                    elif not quote(long['tape'].get(t), allow_zero_bid=True):
                        halt(t, 'Final long-call liquidation quote unavailable; retained unresolved long.')
                    elif not quote(current_stock, allow_zero_bid=True):
                        halt(t, 'Final stock bid/ask unavailable; comparison liquidation cannot be booked.')
                    else:
                        for a in ('PMCC', 'long_call'):
                            if not long_close(a, t, 'Final horizon: sell long call at bid; do not assume exercise.'):
                                halt(t, 'Final long-call sale could not be funded after fees.')
                                break
                        if book['status'] != 'halted':
                            for a in ('covered_call', 'buy_hold'):
                                event(a, t, cfg['stock_ric'], 'SELL', 100, current_stock['BID'], 'Final horizon: sell comparison stock at bid.', 'stock')
                                states[a]['shares'] = 0
                if str(local(t).date()) not in calendar_closed:
                    snapshot(t)
                if book['status'] == 'halted':
                    break
    horizon = book['ledger'][-1]['time'] if book['ledger'] else start
    by_time = {}
    for row in book['ledger']:
        by_time.setdefault(row['time'], {})[row['account']] = row
    common_times = [t for t, rows in by_time.items() if len(rows) == len(ACCOUNTS) and all(r['nav'] is not None for r in rows.values())]
    book['last_common_mark'] = None
    if common_times:
        common = max(common_times)
        book['last_common_mark'] = {'time': common, 'accounts': {a: {
            'nav': r['nav'], 'pnl': r['nav']-initial, 'return': r['nav']/initial-1,
            'liquidation_nav': r['liquidation_nav']} for a, r in by_time[common].items()},
            'note': 'Last simultaneous complete mark for comparison only. This does not book liquidation or replace an unresolved final quote.'}
    for a in ACCOUNTS:
        rows = [r for r in book['ledger'] if r['account'] == a]
        observed = [r for r in rows if r['nav'] is not None]
        peak, dd = initial, 0.
        for r in observed:
            peak = max(peak, r['nav'])
            dd = min(dd, r['nav']/peak-1)
        final = rows[-1] if rows else None
        final_nav = final['nav'] if final else None
        daily = [r for r in rows if local(r['time']).hour == cfg['exit_hour']]
        returns = []
        for left, right in zip(daily, daily[1:]):
            ld, rd = local(left['time']).date(), local(right['time']).date()
            delta = (rd-ld).days
            adjacent = delta == 1 or (ld.weekday() == 4 and rd.weekday() == 0 and delta == 3)
            if adjacent and left['nav'] is not None and right['nav'] is not None and left['nav'] > 0:
                returns.append(right['nav']/left['nav']-1)
        s = states[a]
        account_events = [e for e in book['blotter'] if e['account'] == a]
        leg_cash = {'stock': 0., 'long_call': 0., 'short_calls': 0.}
        for e in account_events:
            leg = 'stock' if e['kind'] == 'stock' else ('long_call' if e['expiry'] == cfg['long_expiry'] else 'short_calls')
            leg_cash[leg] += e['cash_delta']
        book['summary'][a] = {'initial_cash': initial, 'ending_nav': final_nav, 'ending_liquidation_nav': final['liquidation_nav'] if final else None,
            'total_return': final_nav/initial-1 if final_nav is not None else None, 'net_pnl': final_nav-initial if final_nav is not None else None,
            'max_drawdown': dd if observed else None, 'fees': s['fees'], 'cash': s['cash'], 'premium_received': s['premium_received'],
            'start_time': start, 'end_time': horizon, 'planned_end_time': end, 'complete': book['status'] == 'complete',
            'open_shares': s['shares'], 'open_long_calls': int(bool(s['long'])), 'open_short_calls': int(bool(s['short'])),
            'missing_mark_rows': sum(bool(r['missing_marks']) for r in rows), 'observed_mark_rows': len(observed),
            'daily_return_count': len(returns), 'mean_observed_daily_return': statistics.fmean(returns) if returns else None,
            'cash_flow_by_leg': leg_cash, 'minimum_cash': min([initial]+[e['cash_after'] for e in account_events]),
            'short_close_cost': sum(e['fill']*mult for e in account_events if e['side'] == 'BUY_TO_CLOSE'),
            'early_risk_closes': sum(e['side'] == 'BUY_TO_CLOSE' and local(e['time']).date().isoformat() != e['expiry'] for e in account_events),
            'realized_only': not (s['shares'] or s['long'] or s['short']) and final_nav is not None}
    points = []
    # Quote diagnostics use observed candidate calls, never their presence to select entries.
    seen = set()
    for c in source.get('short_candidates', []) + ([source['long_contract']] if source.get('long_contract') else []):
        for r in c.get('rows', []):
            t = canonical_time(r['time'])
            key = (c['ric'], t)
            if key not in seen and start <= t <= horizon and mid(r) is not None and finite(r.get('TRDPRC_1')) and r['TRDPRC_1'] > 0:
                points.append({'time': t, 'ric': c['ric'], 'leg': 'long' if c['expiry'] == cfg['long_expiry'] else 'short', 'mid': mid(r), 'trade': r['TRDPRC_1']})
                seen.add(key)
    book['scatter'] = _fit(points)
    book['regression_by_leg'] = {leg: _fit([p for p in points if p['leg'] == leg]) for leg in ('long', 'short')}
    book['scatter']['caveat'] = 'Bar last-trade prints need not be contemporaneous with bar bid/ask and may be stale. R² is diagnostic, not proof that a mid fill is executable; the backtest pays the displayed spread.'
    book['execution_sensitivity'] = []
    for slippage in (.01, .05):
        accounts = {}
        for a in ACCOUNTS:
            extra = sum(mult*(slippage if e['side'] in ('BUY', 'BUY_TO_CLOSE') else min(slippage, e['fill']))
                        for e in book['blotter'] if e['account'] == a and e['kind'] == 'option')
            nav = book['summary'][a]['ending_nav']
            accounts[a] = {'extra_cost': extra, 'ending_nav': nav-extra if nav is not None else None}
        book['execution_sensitivity'].append({'name': '${:.2f} adverse option fill per share'.format(slippage),
            'per_share_slippage': slippage, 'accounts': accounts,
            'assumption': 'Fixed booked trade schedule; option buys pay this much above ask and sells receive this much below bid, floored at zero. A cost attribution, not a rerun of eligibility or a guarantee that stressed trades remain fundable.'})
    book['source_quality'] = {'acquisition_error': source.get('acquisition_error'),
        'request_count': len(book['requests']), 'request_errors': sum(r.get('status') == 'error' for r in book['requests']),
        'empty_requests': sum(r.get('status') == 'empty' for r in book['requests']), 'stock_rows': len(stock),
        'long_candidate_count': len(source.get('long_candidates', [])), 'short_candidate_count': len(source.get('short_candidates', [])),
        'scheduled_weeks': len(source.get('weeks', [])), 'decided_weeks': len(book['decisions']),
        'short_calls_opened': sum(d['status'] == 'SELL' for d in book['decisions']),
        'skipped_weeks': sum(d['status'] == 'SKIP' for d in book['decisions']),
        'missing_mark_rows': sum(bool(r['missing_marks']) for r in book['ledger']),
        'limitations': ['Candidate strikes are a fixed sampled grid, not an independently reconstructed historical full option chain.',
                       'API errors and empty responses are data-availability failures, not evidence that the market did not trade.',
                       'Source timestamps are hourly end labels. Neither synchronized tick quotes nor actual executable orders are observed.',
                       'Acquisition may use current symbology aliases to retrieve old observations; decisions use only the entry-time quotes.',
                       'Base case does not model stochastic early assignment, borrow or financing; explicit daily risk checks and separate stress make this limitation visible.']}
    return book


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, separators=(',', ':')) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def export(source_path, output_dir):
    path, out = Path(source_path), Path(output_dir)
    raw = path.read_bytes()
    source = json.loads(raw)
    book = backtest(source)
    book['provenance']['source_sha256'] = hashlib.sha256(raw).hexdigest()
    book['provenance']['source_file'] = 'PMCC_source.json'
    book['provenance']['engine_version'] = 'pmcc-engine-1.0'
    out.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(book, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    (out/'book.json').write_text(encoded, encoding='utf-8')
    (out/'book.js').write_text('window.PMCC_BOOK = '+encoded+';\n', encoding='utf-8')
    for table in ('blotter', 'ledger', 'decisions', 'requests'):
        write_csv(out/(table+'.csv'), book[table])
    (out/'PMCC_source.json').write_bytes(raw)
    return book


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python engine.py PMCC_source.json output_directory')
    result = export(sys.argv[1], sys.argv[2])
    print(json.dumps({'status': result['status'], 'summary': result['summary'], 'halt': result['halt']}, indent=2))
