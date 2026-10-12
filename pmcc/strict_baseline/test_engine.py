"""Synthetic regression fixtures ONLY. Never publish these as market data."""
import copy
import datetime as dt
import unittest
import json
from pathlib import Path
import tempfile
from engine import backtest, quote, export
from validate_results import validate


def fixture():
    # Synthetic stock at 100; synthetic 70-strike long and 105-strike weekly call.
    cfg = {'stock_ric': 'TEST.O', 'root': 'TEST', 'start': '2026-04-06', 'end': '2026-04-10',
      'long_expiry': '2028-01-21', 'timezone': 'America/New_York', 'interval': 'hourly',
      'entry_hour': 11, 'exit_hour': 15, 'initial_cash': 50000., 'contract_multiplier': 100,
      'long_target_moneyness': .70, 'long_min_moneyness': .60, 'long_max_moneyness': .80,
      'strike_grid': 5., 'short_target_moneyness': 1.03, 'short_candidates': 3,
      'long_max_relative_spread': .10, 'short_max_relative_spread': .50,
      'option_fee_per_contract': .65, 'known_closed_fridays': []}
    stamps = ['2026-04-06T15:00:00Z'] + ['2026-04-%02dT19:00:00Z' % d for d in range(6, 11)]
    def rows(b, a, tr):
        return [{'time': t, 'BID': b, 'ASK': a, 'TRDPRC_1': tr, 'ACVOL_UNS': 1.} for t in stamps]
    stock = rows(99.9, 100.1, 100.)
    long = {'ric': 'TEST_LONG_70', 'strike': 70., 'expiry': '2028-01-21', 'rows': rows(30.5, 31.5, 31.)}
    short = {'ric': 'TEST_SHORT_105', 'strike': 105., 'expiry': '2026-04-10', 'monday': '2026-04-06', 'rows': rows(1., 1.2, 1.1)}
    short['rows'][-1].update(BID=0., ASK=.02, TRDPRC_1=.01)
    return {'config': cfg, 'stock': stock, 'long_candidates': [copy.deepcopy(long)], 'long_contract': long,
            'short_candidates': [short], 'weeks': [{'monday': '2026-04-06', 'friday': '2026-04-10'}],
            'request_audit': [], 'provenance': {'source_kind': 'SYNTHETIC UNIT TEST FIXTURE'}, 'acquisition_error': None}


class EngineTests(unittest.TestCase):
    def test_cash_fees_and_final_flat(self):
        b = backtest(fixture())
        self.assertEqual(b['status'], 'complete')
        # Long ask31.5→bid30.5 = -100; short bid1→ask.02 = +98; four .65 fees.
        self.assertAlmostEqual(b['summary']['PMCC']['ending_nav'], 49995.4)
        self.assertAlmostEqual(b['summary']['PMCC']['fees'], 2.6)
        self.assertAlmostEqual(b['summary']['covered_call']['ending_nav'], 50076.7)
        self.assertAlmostEqual(b['summary']['buy_hold']['ending_nav'], 49980.)
        self.assertTrue(all(s['realized_only'] for s in b['summary'].values()))
        self.assertTrue(all(e['cash_after'] >= 0 for e in b['blotter']))

    def test_zero_bid_exit_valid_open_invalid(self):
        self.assertFalse(quote({'BID': 0., 'ASK': .01}))
        self.assertTrue(quote({'BID': 0., 'ASK': .01}, allow_zero_bid=True))
        self.assertEqual(backtest(fixture())['status'], 'complete')

    def test_missing_exit_is_not_retroactive_skip(self):
        src = fixture()
        src['short_candidates'][0]['rows'].pop()
        b = backtest(src)
        self.assertEqual(b['status'], 'halted')
        self.assertEqual(b['summary']['PMCC']['open_short_calls'], 1)
        self.assertEqual(b['source_quality']['short_calls_opened'], 1)
        self.assertIsNone(b['summary']['PMCC']['ending_nav'])
        self.assertFalse(b['summary']['PMCC']['realized_only'])

    def test_missing_entire_exit_bar_still_halts(self):
        src = fixture()
        src['stock'].pop()
        src['short_candidates'][0]['rows'].pop()
        b = backtest(src)
        self.assertEqual(b['halt']['time'], '2026-04-10T19:00:00Z')
        self.assertEqual(b['status'], 'halted')

    def test_missing_risk_check_not_assumed_safe(self):
        src = fixture()
        src['stock'][2]['TRDPRC_1'] = 110.
        src['short_candidates'][0]['rows'][2]['ASK'] = None
        b = backtest(src)
        self.assertEqual(b['status'], 'halted')
        self.assertIn('risk check', b['halt']['reason'])

    def test_missing_otm_quote_does_not_make_risk_predicate_unknown(self):
        src = fixture()
        src['short_candidates'][0]['rows'][2]['ASK'] = None
        b = backtest(src)
        self.assertEqual(b['status'], 'complete')
        row = next(r for r in b['ledger'] if r['account'] == 'PMCC' and r['time'] == '2026-04-07T19:00:00Z')
        self.assertIsNone(row['nav'])

    def test_crossed_entry_skips_call(self):
        src = fixture()
        src['short_candidates'][0]['rows'][0].update(BID=2., ASK=1.)
        b = backtest(src)
        self.assertEqual(b['status'], 'complete')
        self.assertEqual(b['decisions'][0]['status'], 'SKIP')
        self.assertEqual(b['summary']['PMCC']['premium_received'], 0.)

    def test_first_eligible_strike_not_best_future_return(self):
        src = fixture()
        second = copy.deepcopy(src['short_candidates'][0])
        second.update(ric='TEST_SHORT_110', strike=110.)
        second['rows'][-1]['ASK'] = .001
        src['short_candidates'] = [second, src['short_candidates'][0]]
        b = backtest(src)
        self.assertEqual(b['decisions'][0]['strike'], 105.)

    def test_future_quote_mutations_do_not_change_entry(self):
        src = fixture()
        before = backtest(src)
        src['short_candidates'][0]['rows'][2]['ASK'] = None
        src['long_contract']['rows'][-1]['BID'] = 1000.
        after = backtest(src)
        early = lambda b: [e for e in b['blotter'] if e['time'] == '2026-04-06T15:00:00Z']
        self.assertEqual(early(before), early(after))
        self.assertEqual(before['decisions'][0], after['decisions'][0])

    def test_long_selection_never_uses_future_liquidity(self):
        src = fixture()
        src['long_contract']['rows'][-1]['ASK'] = None
        b = backtest(src)
        self.assertEqual(b['status'], 'halted')
        self.assertEqual(b['blotter'][0]['instrument'], 'TEST_LONG_70')
        self.assertEqual(b['summary']['PMCC']['open_long_calls'], 1)

    def test_early_risk_close_no_replacement(self):
        src = fixture()
        src['stock'][2].update(TRDPRC_1=110., BID=109.9, ASK=110.1)
        src['short_candidates'][0]['rows'][2].update(BID=5., ASK=5.08)
        b = backtest(src)
        exits = [e for e in b['blotter'] if e['account'] == 'PMCC' and e['side'] == 'BUY_TO_CLOSE']
        self.assertEqual(exits[0]['time'], '2026-04-07T19:00:00Z')
        self.assertEqual(len(exits), 1)
        self.assertEqual(sum(e['side'] == 'SELL' for e in b['blotter'] if e['account'] == 'PMCC'), 1)

    def test_cash_limit_blocks_unfunded_close(self):
        src = fixture()
        src['short_candidates'][0]['rows'][-1].update(BID=1000., ASK=1001.)
        b = backtest(src)
        self.assertEqual(b['status'], 'halted')
        self.assertIn('Cash cannot fund', b['halt']['reason'])
        self.assertFalse(any(e['side'] == 'BUY_TO_CLOSE' for e in b['blotter']))

    def test_mark_missing_is_gap_not_forward_fill(self):
        src = fixture()
        extra = {'time': '2026-04-07T16:00:00Z', 'BID': 99.9, 'ASK': 100.1, 'TRDPRC_1': 100.}
        src['stock'].append(extra)
        b = backtest(src)
        row = next(r for r in b['ledger'] if r['account'] == 'PMCC' and r['time'] == extra['time'])
        self.assertIsNone(row['nav'])
        self.assertIsNone(row['liquidation_nav'])
        self.assertIn('long_call', row['missing_marks'])

    def test_initial_debit_and_stress_reconcile(self):
        b = backtest(fixture())
        self.assertAlmostEqual(b['funding']['initial_debit']['PMCC'], 3051.3)
        stress = b['stress']['scenarios'][0]
        self.assertEqual(stress['events'][0]['shares_after'], -100)
        self.assertEqual(stress['events'][1]['shares_after'], 0)
        self.assertAlmostEqual(stress['ending_cash'], stress['cash_before']+sum(e['cash_delta'] for e in stress['events']))
        self.assertFalse(any(e['side'].startswith('ASSIGN') for e in b['blotter']))

    def test_duplicate_conflicts_rejected(self):
        src = fixture()
        extra = copy.deepcopy(src['stock'][0]); extra['BID'] = 1.
        src['stock'].append(extra)
        with self.assertRaises(ValueError): backtest(src)

    def test_short_must_be_above_long_strike(self):
        src = fixture()
        src['short_candidates'][0]['strike'] = 65.
        self.assertEqual(backtest(src)['decisions'][0]['status'], 'SKIP')

    def test_no_long_entry_no_fabricated_performance(self):
        src = fixture()
        src['long_candidates'][0]['rows'][0]['ASK'] = None
        b = backtest(src)
        self.assertEqual(b['status'], 'no_entry')
        self.assertEqual(b['blotter'], [])
        self.assertIsNone(b['summary']['PMCC']['total_return'])

    def test_independent_validator_and_corruption_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'fixture.json'
            path.write_text(json.dumps(fixture()), encoding='utf-8')
            export(path, directory)
            self.assertEqual(validate(directory)['status'], 'PASS')
            book_path = Path(directory)/'book.json'
            book = json.loads(book_path.read_text(encoding='utf-8'))
            book['ledger'][0]['cash'] += 1
            text = json.dumps(book)
            book_path.write_text(text, encoding='utf-8')
            (Path(directory)/'book.js').write_text('window.PMCC_BOOK = '+text+';', encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'Ledger cash'): validate(directory)

    def test_fee_boundary_opening_cannot_make_cash_negative(self):
        src = fixture(); src['config']['initial_cash'] = 10010.
        src['short_candidates'][0]['rows'][0].update(BID=.005, ASK=.006)
        b = backtest(src)
        self.assertEqual(b['decisions'][0]['status'], 'SKIP')
        self.assertIn('commission', b['decisions'][0]['reason'])

    def test_closed_monday_has_decision_but_no_fake_valuation(self):
        src = fixture(); src['config']['end'] = '2026-05-25'
        src['weeks'].append({'monday': '2026-05-25', 'friday': '2026-05-29'})
        b = backtest(src)
        self.assertTrue(any(d['monday'] == '2026-05-25' for d in b['decisions']))
        self.assertFalse(any(r['time'].startswith('2026-05-25') for r in b['ledger']))

    def test_append_future_observations_does_not_change_booked_path(self):
        src = fixture(); before = backtest(src)
        for rows in (src['stock'], src['long_contract']['rows'], src['short_candidates'][0]['rows']):
            rows.append({'time': '2026-12-31T19:00:00Z', 'BID': 999., 'ASK': 1000., 'TRDPRC_1': 999.})
        after = backtest(src)
        self.assertEqual(before['blotter'], after['blotter'])
        self.assertEqual(before['ledger'], after['ledger'])
        self.assertEqual(before['decisions'], after['decisions'])

    def test_long_target_tie_chooses_lower_strike(self):
        src = fixture()
        lower = copy.deepcopy(src['long_contract']); higher = copy.deepcopy(lower)
        lower.update(ric='LONG65', strike=65.)
        higher.update(ric='LONG75', strike=75.)
        for r in lower['rows']: r.update(BID=35.5, ASK=36.5)
        for r in higher['rows']: r.update(BID=25.5, ASK=26.5)
        src['long_candidates'] = [higher, lower]; src['long_contract'] = lower
        self.assertEqual(backtest(src)['blotter'][0]['instrument'], 'LONG65')

    def test_relative_spread_boundary(self):
        self.assertTrue(quote({'BID': 9.5, 'ASK': 10.5}, cap=.10))
        self.assertFalse(quote({'BID': 9.499, 'ASK': 10.501}, cap=.10))


if __name__ == '__main__':
    unittest.main()
