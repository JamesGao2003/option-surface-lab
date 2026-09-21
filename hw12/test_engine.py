"""Scenario fixtures only, never substituted for LSEG observations."""
import copy
import unittest
from datetime import date,timedelta
from engine import run_backtest,make_call_ric,local_at,iso,regression


def fixture():
    cfg={'root':'AAPL','stock_ric':'AAPL.O','start':'2026-07-13','end':'2026-07-24',
         'timestamp_label':'endPeriod','entry_hour_ny':11,'initial_cash':10000,'max_otm_dollars':15}
    stock=[];contracts=[];options=[]
    for mon,entry,close,strike in [(date(2026,7,13),100,99,100),(date(2026,7,20),102,110,102.5)]:
        fri=mon+timedelta(days=4);ric=make_call_ric('AAPL',fri,strike)
        contracts.append({'ric':ric,'strike':strike,'expiry':str(fri)})
        stock += [{'time':iso(local_at(mon,11)),'TRDPRC_1':entry},
                  {'time':iso(local_at(mon+timedelta(days=1),11)),'TRDPRC_1':entry+1},
                  {'time':iso(local_at(fri,16)),'TRDPRC_1':close}]
        options += [{'time':iso(local_at(mon,11)),'ric':ric,'BID':1,'ASK':3,'TRDPRC_1':2.2},
                    {'time':iso(local_at(mon+timedelta(days=1),11)),'ric':ric,'BID':.5,'ASK':1.5,'TRDPRC_1':1.1}]
    return {'config':cfg,'stock':stock,'contracts':contracts,'options':options}


class EngineTests(unittest.TestCase):
    def test_new_york_dst_conversion(self):
        self.assertEqual(iso(local_at(date(2026,7,13),11)), '2026-07-13T15:00:00Z')
        self.assertEqual(iso(local_at(date(2026,1,12),11)), '2026-01-12T16:00:00Z')

    def test_expire_keep_shares_then_assign_once(self):
        b=run_backtest(fixture());s=b['summary']
        self.assertEqual(s['calls_sold'],2);self.assertEqual(s['assignments'],1)
        self.assertEqual(s['expirations'],1);self.assertEqual(s['ending_cash'],10650)
        self.assertEqual(s['ending_nav'],10650);self.assertEqual(s['ending_shares'],0)
        self.assertEqual(len([r for r in b['blotter'] if r['side']=='BUY']),1)
        self.assertEqual(sum(r['cash_delta'] for r in b['blotter']),650)
        first=b['ledger'][0]
        self.assertEqual(first['cash'],200);self.assertEqual(first['nav'],10000)
        self.assertEqual(first['initial'],5000);self.assertEqual(first['maintenance'],2500)
        # Physical delivery must conserve account equity at the expiry mark.
        for i,r in enumerate(b['ledger']):
            if r['phase']=='pre-expiry':self.assertEqual(r['nav'],b['ledger'][i+1]['nav'])

    def test_no_quote_no_stock_leg(self):
        t=fixture();t['options']=[];b=run_backtest(t)
        self.assertEqual(b['blotter'],[]);self.assertEqual(b['summary']['ending_cash'],10000)
        self.assertEqual(b['summary']['skipped_weeks'],2)

    def test_crossed_quote_invalid(self):
        t=fixture()
        for r in t['options']:r['BID']=4;r['ASK']=1
        self.assertEqual(run_backtest(t)['summary']['calls_sold'],0)

    def test_insufficient_initial_funds_rejects_atomic_combo(self):
        t=fixture();t['config']['initial_cash']=4000;b=run_backtest(t)
        self.assertFalse(b['blotter']);self.assertIn('Insufficient',b['decisions'][0]['reason'])

    def test_missing_mark_never_fills_forward(self):
        t=fixture();t['options']=[r for r in t['options'] if r['time']!=iso(local_at(date(2026,7,14),11))]
        b=run_backtest(t);row=next(r for r in b['ledger'] if r['time']==iso(local_at(date(2026,7,14),11)))
        self.assertIsNone(row['nav']);self.assertEqual(row['cash'],200)

    def test_missing_expiry_stops_future_entries(self):
        t=fixture();t['stock']=[r for r in t['stock'] if r['time']!=iso(local_at(date(2026,7,17),16))]
        b=run_backtest(t);self.assertEqual(b['status'],'incomplete');self.assertEqual(b['summary']['calls_sold'],1)
        self.assertEqual(b['summary']['assignments'],0);self.assertTrue(b['unresolved'])

    def test_atm_expiry_is_expire(self):
        t=fixture();t['stock'][2]['TRDPRC_1']=100;b=run_backtest(t)
        self.assertEqual(b['blotter'][2]['side'],'EXPIRE')

    def test_monday_holiday_skips_no_tuesday_entry(self):
        t=fixture();t['stock']=t['stock'][1:];b=run_backtest(t)
        self.assertEqual(b['decisions'][0]['status'],'SKIP');self.assertEqual(b['summary']['calls_sold'],1)

    def test_select_lowest_current_quoted_strike_not_itm(self):
        t=fixture();c={'ric':make_call_ric('AAPL',date(2026,7,17),97.5),'strike':97.5,'expiry':'2026-07-17'}
        t['contracts'].append(c);t['options'].append({'ric':c['ric'],'time':t['stock'][0]['time'],'BID':3,'ASK':5,'TRDPRC_1':4})
        self.assertEqual(run_backtest(t)['decisions'][0]['strike'],100)

    def test_hourly_mark_does_not_change_cash(self):
        b=run_backtest(fixture());self.assertEqual(b['ledger'][0]['cash'],b['ledger'][1]['cash'])
        self.assertNotEqual(b['ledger'][0]['nav'],b['ledger'][1]['nav'])

    def test_regression_known_line(self):
        r=regression([{'mid':x,'trade':2*x+1} for x in [1,2,3,4]])
        self.assertEqual(r['slope'],2);self.assertEqual(r['intercept'],1);self.assertEqual(r['r2'],1)
        self.assertIsNone(regression([])['r2'])

    def test_zero_volume_trade_excluded(self):
        t=fixture()
        for r in t['options']:r['ACVOL_UNS']=0
        b=run_backtest(t);self.assertEqual(b['regression']['n'],0);self.assertEqual(b['summary']['calls_sold'],2)

    def test_rics_unpadded_day(self):
        self.assertEqual(make_call_ric('AAPL',date(2026,6,5),190),'AAPLF52619000.U^F26')

    def test_unlabelled_tape_rejected(self):
        t=fixture();t['config']['timestamp_label']='startPeriod'
        with self.assertRaises(ValueError):run_backtest(t)


if __name__=='__main__':unittest.main()
