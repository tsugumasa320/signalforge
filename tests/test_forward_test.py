from copy import deepcopy
from datetime import datetime
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from signalforge.paper.forward_test import JST, advance_book, create_book


def now(day):
    return datetime.fromisoformat(day+'T20:17:00+09:00')


def bar(price=1000, **changes):
    return dict(open=price, high=price*1.01, low=price*.99, close=price,
                volume=1000000, split=0, dividend=0, **changes) if not changes else {
        **bar(price), **changes}


def candidate(t='7203.T',sector='A'):
    return dict(ticker=t,sector=sector,box=900,turnover=1e9,close=1000)


def registered(strategy='duke_stage2'):
    return create_book(strategy,now('2026-11-20'),'fixed-universe')


def planned():
    return advance_book(registered(),'2026-11-24',{'7203.T':bar()},[candidate()],now('2026-11-24'))


def held():
    return advance_book(planned(),'2026-11-25',{'7203.T':bar()},[],now('2026-11-25'))


def test_next_session_fill_and_immutable_decision():
    a=planned();snapshot=deepcopy(a)
    assert not a['fills'] and a['pending'][0]['shares']==100
    b=advance_book(a,'2026-11-25',{'7203.T':bar()},[],now('2026-11-25'))
    assert a==snapshot
    assert b['fills'][0]['signal_date']=='2026-11-24'
    assert b['fills'][0]['date']=='2026-11-25'
    assert b['decisions'][0]==a['decisions'][0]
    assert advance_book(b,'2026-11-25',{},[],now('2026-11-25'))==b


def test_no_pre_registration_or_unclosed_session():
    a=registered()
    assert advance_book(a,'2026-11-20',{},[],now('2026-11-20'))==a
    with pytest.raises(ValueError,match='not closed'):
        advance_book(a,'2026-11-24',{},[],datetime(2026,11,24,12,tzinfo=JST))


def test_no_backdated_discretionary_orders():
    b=advance_book(registered(),'2026-11-24',{'7203.T':bar()},[candidate()],now('2026-11-26'),plan=False)
    assert not b['pending'] and not b['decisions']


def test_gap_cannot_overdraw_etf():
    a=advance_book(registered('nikkei_hold'),'2026-11-24',{'1321.T':bar()},[],now('2026-11-24'))
    assert a['pending'][0]['shares']%10==0
    b=advance_book(a,'2026-11-25',{'1321.T':bar(2000)},[],now('2026-11-25'))
    assert b['cash']==3000000 and not b['fills']


def test_late_decision_not_filled_in_past():
    a=advance_book(registered(),'2026-11-24',{'7203.T':bar()},[candidate()],now('2026-11-26'))
    b=advance_book(a,'2026-11-25',{'7203.T':bar()},[],now('2026-11-26'),plan=False)
    assert not b['fills'] and b['events'][-1]['type']=='late_order_rejected'


def test_missing_position_freezes_without_revaluing():
    a=held();b=advance_book(a,'2026-11-26',{},[],now('2026-11-26'))
    assert b['status']=='needs_review' and b['equity']==a['equity']


def test_split_and_dividend_exclusion():
    a=held();b=advance_book(a,'2026-11-26',{'7203.T':bar(500,split=2,dividend=10)},[],now('2026-11-26'))
    assert not b['issues']
    assert b['positions']['7203.T']['shares']==200
    assert b['cash']==a['cash']
    assert b['positions']['7203.T']['stop']==a['positions']['7203.T']['stop']/2
    assert b['decisions'][0]==a['decisions'][0]


def test_locked_stop_remains_due_after_recovery():
    a=held();b=advance_book(a,'2026-11-26',{'7203.T':bar(880,high=880,low=880)},[],now('2026-11-26'))
    assert b['pending'][0]['reason']=='deferred_standing_stop'
    c=advance_book(b,'2026-11-27',{'7203.T':bar(950)},[],now('2026-11-27'))
    assert not c['positions'] and c['fills'][-1]['side']=='sell'


def test_coverage_sector_and_position_limits():
    cs=[candidate(str(i),str(i//3)) for i in range(9)]
    bars={c['ticker']:bar() for c in cs}
    a=advance_book(registered(),'2026-11-24',bars,cs,now('2026-11-24'))
    assert len(a['pending'])==5
    assert sum(o['sector']=='0' for o in a['pending'])==2
    b=advance_book(registered(),'2026-11-24',bars,cs,now('2026-11-24'),coverage=.94)
    assert not b['pending'] and b['status']=='data_incomplete'


def test_raw_split_units():
    spec=importlib.util.spec_from_file_location('runner',Path(__file__).parents[1]/'scripts/run_forward_tests.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    f=pd.DataFrame([bar(500),bar(500,split=2)],index=pd.to_datetime(['2026-11-24','2026-11-25']))
    assert runner.raw_bar(f,'2026-11-24')['close']==1000
    assert runner.raw_bar(f,'2026-11-25')['close']==500


def test_cached_future_sessions_are_rejected():
    spec=importlib.util.spec_from_file_location('runner',Path(__file__).parents[1]/'scripts/run_forward_tests.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    f=pd.DataFrame([bar(500)],index=pd.to_datetime(['2026-11-25']))
    with pytest.raises(ValueError,match='future sessions'):
        runner.completed_frames({'7203.T':f},now('2026-11-24'))


def test_bb_candidate_without_box():
    """Regression: BB candidates lack 'box' but have 'atr'; must not cause TypeError."""
    bb_candidate = dict(ticker='7203.T', sector='A', atr=50.0, turnover=1e9, close=1000, kind='bb')
    a = advance_book(registered('duke_bull_bb_bear'), '2026-11-24', {'7203.T': bar(), '1321.T': bar()},
                     [bb_candidate], now('2026-11-24'))
    assert len(a['pending']) == 1
    order = a['pending'][0]
    assert order['ticker'] == '7203.T'
    assert order.get('box') is None
    assert order.get('atr') == 50.0
    assert order.get('kind') == 'bb'
    
    b = advance_book(a, '2026-11-25', {'7203.T': bar(), '1321.T': bar()}, [], now('2026-11-25'))
    assert len(b['fills']) == 1
    assert b['fills'][0]['side'] == 'buy'
    assert b['fills'][0]['strategy_kind'] == 'bb'
    assert '7203.T' in b['positions']
    pos = b['positions']['7203.T']
    assert pos['kind'] == 'bb'
    assert pos['stop'] == pytest.approx(1000 * (1 + 0.0003) - 2 * 50.0, abs=0.01)


def test_duke_candidate_with_box():
    """DUKE candidates have 'box' and no 'atr'."""
    duke_candidate = dict(ticker='7203.T', sector='A', box=900.0, turnover=1e9, close=1000, kind='duke')
    a = advance_book(registered('duke_bull_bb_bear'), '2026-11-24', {'7203.T': bar(), '1321.T': bar()},
                     [duke_candidate], now('2026-11-24'))
    assert len(a['pending']) == 1
    order = a['pending'][0]
    assert order['ticker'] == '7203.T'
    assert order.get('box') == 900.0
    assert order.get('atr') is None
    assert order.get('kind') == 'duke'
    
    b = advance_book(a, '2026-11-25', {'7203.T': bar(), '1321.T': bar()}, [], now('2026-11-25'))
    assert len(b['fills']) == 1
    assert b['fills'][0]['strategy_kind'] == 'duke'
    assert '7203.T' in b['positions']
    pos = b['positions']['7203.T']
    assert pos['kind'] == 'duke'
    assert pos['stop'] == max(1000 * (1 + 0.0003) * 0.9, 900.0)


def test_etf_without_box_or_atr():
    """ETF positions have no stop, so box=None is acceptable."""
    a = advance_book(registered('nikkei_hold'), '2026-11-24', {'1321.T': bar()}, [], now('2026-11-24'))
    assert len(a['pending']) == 1
    order = a['pending'][0]
    assert order.get('box') is None
    assert order.get('atr') is None
    
    b = advance_book(a, '2026-11-25', {'1321.T': bar()}, [], now('2026-11-25'))
    assert '1321.T' in b['positions']
    assert b['positions']['1321.T']['stop'] == 0.0


def test_ticker_names_loaded():
    """Company names are loaded from universe.json and ETFs."""
    from signalforge.report.forward_test_page import _load_ticker_names
    
    names = _load_ticker_names()
    # Check ETF names are present
    assert '1321.T' in names
    assert '1306.T' in names
    assert '日経225' in names['1321.T']
    assert 'TOPIX' in names['1306.T']
    # If universe.json exists, check some stock names are loaded
    if Path('config/forward/universe.json').exists():
        assert len(names) > 2  # More than just the 2 ETFs


def test_yahoo_jp_links_in_holdings():
    """Holdings display includes Yahoo! Finance links and company names."""
    from signalforge.report.forward_test_page import export_forward_pages
    import tempfile
    
    # Create a minimal forward test state
    state_dir = Path('data/paper/forward_tests')
    state_dir.mkdir(parents=True, exist_ok=True)
    
    test_book = create_book('nikkei_hold', now('2026-11-20'), 'fixed-universe')
    test_book = advance_book(test_book, '2026-11-24', {'1321.T': bar()}, [], now('2026-11-24'))
    test_book = advance_book(test_book, '2026-11-25', {'1321.T': bar()}, [], now('2026-11-25'))
    
    test_path = state_dir / 'nikkei_hold.json'
    import json
    test_path.write_text(json.dumps(test_book, ensure_ascii=False))
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            export_forward_pages(out)
            
            html_file = out / 'forward' / 'nikkei_hold.html'
            assert html_file.exists()
            
            content = html_file.read_text()
            # Check that Yahoo! Finance link is present
            assert 'finance.yahoo.co.jp/quote/1321.T' in content
            # Check that company name is present (not just ticker)
            assert '日経225' in content
    finally:
        if test_path.exists():
            test_path.unlink()
