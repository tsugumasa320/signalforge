"""Append-only daily decisions and fills for the research-selected forward cohort.

No historical account replay. Daily OHLC fills are estimates; dividends are
excluded from every account. Corporate actions not understood stop the account.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

JST=ZoneInfo('Asia/Tokyo')
VERSION=1
FEE=.00105
SLIP=.0003
REGIME_SWITCHES={'duke_bull_bb_bear':200,'duke_bull_bb_bear_sma150':150,'duke_bull_bb_bear_sma250':250}
SPECS={
    'duke_stage2': {'label':'DUKE 第2ステージ・5分割','ticker':None,'lot':100},
    'bb_rsi_120': {'label':'BB下限＋RSI・120日保有','ticker':None,'lot':100},
    'duke_bull_bb_bear': {'label':'地合い切替 SMA200：上昇DUKE／下落BB＋RSI','ticker':None,'lot':100},
    'duke_bull_bb_bear_sma150': {'label':'地合い切替 SMA150：上昇DUKE／下落BB＋RSI','ticker':None,'lot':100},
    'duke_bull_bb_bear_sma250': {'label':'地合い切替 SMA250：上昇DUKE／下落BB＋RSI','ticker':None,'lot':100},
    'rsi_recovery_120': {'label':'200日線上のRSI回復・120日保有','ticker':None,'lot':100},
    'nikkei_hold': {'label':'日経225 ETF保有','ticker':'1321.T','lot':10},
    'topix_hold': {'label':'TOPIX ETF保有','ticker':'1306.T','lot':10},
}
RULES={'version':VERSION,'initial_cash':3000000.,'max_positions':5,'position_weight':.2,
       'tranches':5,'max_sector':2,'min_turnover':500000000.,'fee':FEE,'slip':SLIP,
       'max_hold_sessions':252,'dividends':'excluded','unit_policy':'stocks_100_etfs_10',
       'entry':'duke_stage2_no_fund_prior_volume_and_box_v1','regime':'1321_above_SMA200',
       'stop':'max(entry*0.9,prior_box_low); breakeven after high>=entry*1.2 from following session'}

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def rules_for(strategy):
    rules=deepcopy(RULES)
    if strategy in REGIME_SWITCHES:
        sessions=REGIME_SWITCHES[strategy]
        rules.update(regime=f'1321 close > SMA{sessions}: DUKE; < SMA{sessions}: BB+RSI; equal/missing: cash; exit on regime change at next open',
                     stop='DUKE: max(entry*0.9,prior_box_low), breakeven after high>=entry*1.2; BB: entry-2*prior ATR14',
                     max_hold_sessions='DUKE 252 / BB 120; 100-share lots; no fixed take profit',
                     entry=f'duke_stage2_above_SMA{sessions}_else_bb_lower_RSI30_below_SMA{sessions}_v1')
    if strategy in ('bb_rsi_120','rsi_recovery_120'):
        rules.update(tranches=1,max_hold_sessions=120,entry=strategy+'_v1',
                     stop='entry - 2 * prior ATR14',take=None,breakeven=False)
    return rules


def create_book(strategy,now,universe_hash):
    if strategy not in SPECS:raise ValueError(strategy)
    return {'schema_version':VERSION,'strategy':strategy,'label':SPECS[strategy]['label'],
            'created_at':now.isoformat(),'start_date':now.astimezone(JST).date().isoformat(),
            'rules':rules_for(strategy),'rules_hash':fingerprint(rules_for(strategy)),'universe_hash':universe_hash,
            'cash':RULES['initial_cash'],'positions':{},'pending':[], 'last_session':None,
            'decisions':[],'fills':[],'equity':[],'events':[],'issues':[], 'status':'waiting_for_first_session'}


def good_bar(bar):
    if not bar:return False
    try:
        o,h,l,c,v=[float(bar[k]) for k in ['open','high','low','close','volume']]
        return all(math.isfinite(x) for x in [o,h,l,c,v]) and 0<l<=min(o,c)<=max(o,c)<=h and v>0
    except (KeyError,TypeError,ValueError):return False


def tradable(bar):return good_bar(bar) and float(bar['high'])>float(bar['low'])


def issue(book,day,ticker,reason):
    record={'date':day,'ticker':ticker,'reason':reason}
    if record not in book['issues']:book['issues'].append(record)
    book['status']='needs_review'


def advance_book(original,day,bars,candidates,now,*,coverage=1.,plan=True,regime=None):
    """Process only an unprocessed session; candidates must use data through day.

    In a catch-up run, plan=False on all but the latest session. Standing stops
    can fill on missed days; no newly inferred historical discretionary orders.
    """
    if original['rules_hash']!=fingerprint(rules_for(original['strategy'])):raise ValueError('Forward rules changed; create a new cohort')
    if day<=original['start_date'] or (original['last_session'] and day<=original['last_session']):return deepcopy(original)
    b=deepcopy(original)
    close_time=pd.Timestamp(day+' 16:00',tz=JST)
    if pd.Timestamp(now)<close_time:raise ValueError('Session has not closed')
    if b['issues']:return b
    spec=SPECS[b['strategy']];positions=b['positions']
    mixed=b['strategy'] in REGIME_SWITCHES
    duke=b['strategy']=='duke_stage2'
    rules=rules_for(b['strategy'])
    # Apply observed split ratios to held shares and already-recorded orders.
    for ticker in set(positions)|{p['ticker'] for p in b['pending']}:
        bar=bars.get(ticker)
        if ticker in positions and not good_bar(bar):issue(b,day,ticker,'missing_held_bar');continue
        factor=float((bar or {}).get('split',0) or 1)
        if not math.isfinite(factor) or factor<=0:issue(b,day,ticker,'invalid_split');continue
        if factor!=1:
            if ticker in positions:
                p=positions[ticker];p['shares']*=factor
                for field in ['entry','stop','mark']:p[field]/=factor
                if not math.isclose(p['shares'],round(p['shares']),abs_tol=1e-6):issue(b,day,ticker,'fractional_split_settlement')
            for order in b['pending']:
                if order['ticker']==ticker:
                    order['shares']*=factor
                    if order.get('box') is not None:order['box']/=factor
                    if order.get('atr') is not None:order['atr']/=factor
            b['events'].append({'date':day,'ticker':ticker,'type':'split','factor':factor})
        if ticker in positions and good_bar(bar):
            p=positions[ticker]
            if abs(float(bar['close'])/p['mark']-1)>.4:issue(b,day,ticker,'large_unexplained_price_change')
            if float(bar.get('dividend',0) or 0):b['events'].append({'date':day,'ticker':ticker,'type':'dividend_excluded','per_share':bar['dividend']})
    if b['issues']:return b
    def sell(ticker,price,reason):
        p=positions.pop(ticker);price*=1-SLIP;gross=p['shares']*price;fee=gross*FEE
        b['cash']+=gross-fee
        b['fills'].append({'date':day,'ticker':ticker,'side':'sell','shares':p['shares'],'price':price,'fee':fee,'reason':reason,'pnl':gross-fee-p['spent'],'strategy_kind':p.get('kind','duke' if duke else 'bb'),'recorded_at':now.isoformat()})
    carry=[];sold=set()
    for order in b['pending']:
        ticker=order['ticker'];bar=bars.get(ticker)
        open_time=pd.Timestamp(day+' 09:00',tz=JST)
        if not order.get('standing') and pd.Timestamp(order['recorded_at'])>=open_time:
            b['events'].append({'date':day,'ticker':ticker,'type':'late_order_rejected'});continue
        if order['side']=='sell':
            if ticker in positions and tradable(bar):sell(ticker,float(bar['open']),order['reason']);sold.add(ticker)
            elif ticker in positions:carry.append(order)
            continue
        if not tradable(bar) or ticker in sold:
            b['events'].append({'date':day,'ticker':ticker,'type':'unfilled_open'});continue
        shares=order['shares'];lot=spec['lot'];kind=order.get('kind','duke' if duke else 'bb')
        price=float(bar['open'])*(1+SLIP);spent=shares*price*(1+FEE)
        existing_kind=positions.get(ticker,{}).get('kind','duke' if duke else 'bb')
        if (not math.isclose(shares/lot,round(shares/lot),abs_tol=1e-6) or spent>b['cash']+1e-6
                or (ticker in positions and (kind!='duke' or existing_kind!='duke' or price<=positions[ticker]['entry']))):
            b['events'].append({'date':day,'ticker':ticker,'type':'size_cash_or_add_rejected'});continue
        b['cash']-=spent
        if ticker in positions:
            p=positions[ticker];total=p['shares']+shares
            p['entry']=(p['entry']*p['shares']+shares*price)/total;p['shares']=total;p['spent']+=spent;p['tranches']+=1
            p['stop']=max(p['stop'],p['entry']*.9,p['entry'] if p['armed'] else 0)
        else:
            position_duke=kind=='duke'
            stop=(max(price*.9,order['box']) if position_duke else price-2*order['atr']) if spec['ticker'] is None else 0.
            positions[ticker]={'kind':kind,'shares':shares,'entry':price,'spent':spent,'sector':order['sector'],'budget':order['budget'],
                'stop':stop,'armed':False,'tranches':1,'age':0,'mark':price}
        b['fills'].append({'date':day,'ticker':ticker,'side':'buy','shares':shares,'price':price,'fee':shares*price*FEE,'signal_date':order['signal_date'],'decision_recorded_at':order['recorded_at'],'strategy_kind':kind,'recorded_at':now.isoformat()})
    b['pending']=carry
    for ticker,p in list(positions.items()):
        bar=bars[ticker];p['age']+=1
        if spec['ticker'] is None and tradable(bar) and float(bar['low'])<=p['stop']:
            sell(ticker,min(float(bar['open']),p['stop']),'standing_stop');continue
        if spec['ticker'] is None and float(bar['low'])<=p['stop'] and not any(o['ticker']==ticker for o in carry):
            # A standing stop remains triggered when a locked session cannot fill.
            carry.append({'ticker':ticker,'side':'sell','shares':p['shares'],
                          'reason':'deferred_standing_stop','standing':True,
                          'signal_date':day,'recorded_at':now.isoformat()})
        p['mark']=float(bar['close'])
    equity=b['cash']+sum(p['shares']*p['mark']*(1-SLIP)*(1-FEE) for p in positions.values())
    b['equity'].append({'date':day,'equity':equity,'cash':b['cash'],'positions':len(positions),'coverage':coverage,'recorded_at':now.isoformat()})
    b['last_session']=day;b['status']='observing' if coverage>=.95 else 'data_incomplete'
    if b['cash']<-.0001 or len(positions)>(1 if spec['ticker'] else 5):raise AssertionError('capital constraint')
    if not plan:return b
    stamp=now.isoformat();orders=[]
    for ticker,p in positions.items():
        bar=bars[ticker]
        position_kind=p.get('kind','duke' if duke else 'bb')
        if position_kind=='duke' and float(bar['high'])>=p['entry']*1.2:
            p['armed']=True;p['stop']=max(p['stop'],p['entry'])
        max_hold=(252 if position_kind=='duke' else 120) if mixed else rules['max_hold_sessions']
        regime_mismatch=(mixed and ((position_kind=='duke' and regime!='bull') or
                                    (position_kind=='bb' and regime!='bear')))
        if spec['ticker'] is None and (p['age']>=max_hold or regime_mismatch) and not any(o['ticker']==ticker for o in carry):
            reason='regime_change' if regime_mismatch else 'max_hold'
            orders.append({'ticker':ticker,'side':'sell','shares':p['shares'],'reason':reason,'signal_date':day,'recorded_at':stamp})
    reserve=b['cash'];planned=set(positions)
    def buy(ticker,budget,sector,box,atr=None,kind=None):
        nonlocal reserve
        bar=bars.get(ticker)
        if not good_bar(bar):return
        price=float(bar['close'])*(1+SLIP)
        shares=math.floor(min(budget,reserve)/(price*(1+FEE)*spec['lot']))*spec['lot']
        if shares<=0:return
        orders.append({'ticker':ticker,'side':'buy','shares':shares,'budget':budget,'sector':sector,'box':box,'signal_date':day,'recorded_at':stamp})
        if kind is not None:orders[-1]['kind']=kind
        if atr is not None:orders[-1]['atr']=atr
        reserve-=shares*price*(1+FEE);planned.add(ticker)
    if coverage>=.95:
        if spec['ticker']:
            if not positions:buy(spec['ticker'],equity,'ETF',None)
        else:
            exiting={o['ticker'] for o in carry+orders if o['side']=='sell'}
            for ticker,p in positions.items():
                position_kind=p.get('kind','duke' if duke else 'bb')
                if (position_kind=='duke' and (duke or mixed) and ticker not in exiting
                        and p['tranches']<5 and p['mark']>p['entry']):
                    buy(ticker,p['budget'],p['sector'],p['stop'],kind='duke' if mixed else None)
            sectors={t:p['sector'] for t,p in positions.items()}
            for c in sorted(candidates,key=lambda c:(-c['turnover'],c['ticker'])):
                ticker=c['ticker'];sector=c['sector'];kind=c.get('kind','duke' if duke else 'bb')
                if ticker in planned or len(planned)>=5 or sum(sectors.get(t)==sector for t in planned)>=2:continue
                tranches=5 if kind=='duke' else 1
                buy(ticker,equity*.2/tranches,sector,c.get('box'),c.get('atr'),kind='duke' if mixed else None);sectors[ticker]=sector
    b['pending']+=orders
    b['decisions'].append({'date':day,'recorded_at':stamp,'coverage':coverage,'candidates':deepcopy(candidates) if not spec['ticker'] else [],'orders':deepcopy(orders),'rules_hash':b['rules_hash'],'cash':b['cash']})
    return b


def duke_candidates(frames,universe,day,*,market_sma=200):
    """Use split-normalized, dividend-unadjusted history through this close only."""
    bench=frames['1321.T']['close'].loc[:day]
    if len(bench)<max(252,market_sma) or bench.iloc[-1]<=bench.rolling(market_sma).mean().iloc[-1]:return []
    out=[]
    for ticker,meta in universe.items():
        f=frames.get(ticker)
        if f is None:continue
        f=f.loc[:day]
        if len(f)<253 or str(f.index[-1].date())!=day:continue
        c,h,l,v=f.close,f.high,f.low,f.volume
        if not np.isfinite(f[['open','high','low','close','volume']].tail(253).to_numpy()).all():continue
        s50=c.rolling(50).mean();s150=c.rolling(150).mean();s200=c.rolling(200).mean()
        hi=h.rolling(252).max().shift().iloc[-1];box=l.shift().rolling(60).min().iloc[-1]
        rs=c.pct_change(30,fill_method=None).iloc[-1]-bench.pct_change(30,fill_method=None).iloc[-1]
        # Raw current close equals normalized close on the newest session.
        checks=[c.iloc[-1]>s150.iloc[-1]>s200.iloc[-1],c.iloc[-1]>s200.iloc[-1],s200.iloc[-1]>s200.shift(21).iloc[-1],
            s50.iloc[-1]>s150.iloc[-1],s50.iloc[-1]>s200.iloc[-1],c.iloc[-1]>=l.rolling(252).min().iloc[-1]*1.25,
            c.iloc[-1]>=h.rolling(252).max().iloc[-1]*.75,c.iloc[-1]>=s50.iloc[-1]*.9,rs>0,c.iloc[-1]>hi,
            h.shift().rolling(20).max().iloc[-1]<hi,(h.shift().rolling(60).max().iloc[-1]-box)/c.iloc[-1]<=.4,
            (v/v.rolling(20).mean()).shift().iloc[-1]>=1.5,c.iloc[-1]>f.open.iloc[-1],c.iloc[-1]*v.iloc[-1]>=5e8]
        if all(checks):out.append({'ticker':ticker,'sector':meta['sector_tse'],'box':float(box),'turnover':float(c.iloc[-1]*v.iloc[-1]),'close':float(c.iloc[-1])})
    return out


def market_regime(frames,day,sessions=200):
    f=frames.get('1321.T')
    if f is None:return None
    bench=f.loc[:day,'close']
    if len(bench)<sessions or str(bench.index[-1].date())!=day:return None
    average=float(bench.tail(sessions).mean());close=float(bench.iloc[-1])
    return 'bull' if close>average else 'bear' if close<average else 'neutral'


def strategy_candidates(strategy,frames,universe,day,*,require_bull=True):
    """Frozen existing mean-reversion entries, using close-known indicators.

    Preserve the research's one-bar lag for RSI, EMA, BB and ATR; the RSI
    crossing compares the two previously completed RSI values.
    """
    if strategy=='duke_stage2':return duke_candidates(frames,universe,day)
    if strategy in REGIME_SWITCHES:
        sessions=REGIME_SWITCHES[strategy]
        regime=market_regime(frames,day,sessions)
        if regime=='bull':return [{**c,'kind':'duke'} for c in duke_candidates(frames,universe,day,market_sma=sessions)]
        if regime=='bear':return [{**c,'kind':'bb'} for c in strategy_candidates('bb_rsi_120',frames,universe,day,require_bull=False)]
        return []
    if SPECS[strategy]['ticker']:return []
    bench=frames['1321.T']['close'].loc[:day]
    if len(bench)<200 or str(bench.index[-1].date())!=day:return []
    if require_bull and bench.iloc[-1]<=bench.tail(200).mean():return []
    out=[]
    for ticker,meta in universe.items():
        f=frames.get(ticker)
        if f is None:continue
        f=f.loc[:day]
        required=201 if strategy=='rsi_recovery_120' else 21
        if len(f)<required or str(f.index[-1].date())!=day:continue
        if not np.isfinite(f[['open','high','low','close','volume']].to_numpy()).all():continue
        c,h,l=f.close,f.high,f.low
        if not good_bar(f.iloc[-1].to_dict()) or c.iloc[-1]*f.volume.iloc[-1]<5e8:continue
        previous=c.shift()
        atr=pd.concat([h-l,(h-previous).abs(),(l-previous).abs()],axis=1).max(axis=1).rolling(14).mean().shift().iloc[-1]
        if not np.isfinite(atr) or atr<=0:continue
        delta=c.diff()
        gain=delta.clip(lower=0).rolling(14).mean()
        loss=(-delta.clip(upper=0)).rolling(14).mean()
        rsi=(100-100/(1+gain/loss.replace(0,np.nan))).shift()
        if strategy=='bb_rsi_120':
            lower=(c.rolling(20).mean()-2*c.rolling(20).std()).shift().iloc[-1]
            entry=c.iloc[-1]<=lower and rsi.iloc[-1]<=30
        else:
            ema=c.ewm(span=200,adjust=False).mean().shift().iloc[-1]
            entry=rsi.iloc[-2]<35<=rsi.iloc[-1] and c.iloc[-1]>ema
        if entry:out.append({'ticker':ticker,'sector':meta['sector_tse'],'atr':float(atr),
                             'turnover':float(c.iloc[-1]*f.volume.iloc[-1]),'close':float(c.iloc[-1])})
    return out


def save_book(path,book):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(book,ensure_ascii=False,indent=2,allow_nan=False)+'\n');temporary.replace(path)
