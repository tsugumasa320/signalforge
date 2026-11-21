#!/usr/bin/env python3
"""Initialize or advance the new forward cohort. Never backfill pre-start PnL."""
from pathlib import Path
import argparse
from datetime import datetime
import json
import pandas as pd
import yfinance as yf
from signalforge.paper.forward_test import (JST,SPECS,create_book,advance_book,strategy_candidates,save_book,fingerprint,good_bar)

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'data/paper/forward_tests'
CACHE=ROOT/'data/forward_cache'
UNIVERSE=ROOT/'config/forward/universe.json'


def clean_history(df):
    if df.empty:return None
    d=df.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume','Dividends':'dividend','Stock Splits':'split'}).copy()
    d.index=pd.to_datetime(d.index).tz_localize(None).normalize()
    d=d[~d.index.duplicated(keep='last')].sort_index()
    for k in ['dividend','split']:
        if k not in d:d[k]=0.
    return d[['open','high','low','close','volume','dividend','split']].dropna(subset=['close'])


def download(tickers,now):
    CACHE.mkdir(parents=True,exist_ok=True);frames={};failures=[]
    for offset in range(0,len(tickers),80):
        batch=tickers[offset:offset+80]
        try:
            data=yf.download(batch,period='2y',interval='1d',auto_adjust=False,actions=True,repair=True,
                             group_by='ticker',threads=8,progress=False,timeout=20)
        except Exception as exc:
            failures.extend(batch);print('download batch failed',type(exc).__name__,flush=True);continue
        for ticker in batch:
            try:
                raw=data[ticker] if isinstance(data.columns,pd.MultiIndex) else data
                d=clean_history(raw)
                if d is None or d.empty:raise ValueError('empty')
                # Exclude an unfinished current session and any future timestamps.
                last_allowed=pd.Timestamp(now.astimezone(JST).date())
                if now.astimezone(JST).hour<16:last_allowed-=pd.Timedelta(days=1)
                d=d.loc[d.index<=last_allowed]
                if d.empty:raise ValueError('unfinished')
                frames[ticker]=d;d.to_pickle(CACHE/f'{ticker}.pkl')
            except (KeyError,ValueError):failures.append(ticker)
        print(f'forward history {min(offset+80,len(tickers))}/{len(tickers)}; available={len(frames)}',flush=True)
    return frames,failures


def raw_bar(frame,day):
    """Undo Yahoo's retrospective split scaling to recover that session's units."""
    if frame is None or pd.Timestamp(day) not in frame.index:return None
    row=frame.loc[day];future=frame.loc[frame.index>pd.Timestamp(day),'split'].replace(0,1).prod()
    out={k:float(row[k]*future) for k in ['open','high','low','close']}
    out.update(volume=float(row['volume']),split=float(row['split']),dividend=float(row['dividend']))
    return out


def completed_frames(frames,now):
    local=now.astimezone(JST)
    end=pd.Timestamp(local.date())
    if local.hour<16:end-=pd.Timedelta(days=1)
    # A future cache may already incorporate future splits in its historical
    # price units. Truncating it would not remove that adjustment.
    if any(not f.empty and f.index.max()>end for f in frames.values()):
        raise ValueError('Cache contains unfinished or future sessions; fetch fresh data')
    return {t:f for t,f in frames.items() if not f.empty}


def main():
    p=argparse.ArgumentParser();p.add_argument('--init',action='store_true');p.add_argument('--cached',action='store_true');args=p.parse_args()
    now=datetime.now(JST);universe_doc=json.loads(UNIVERSE.read_text());universe={r['ticker']:r for r in universe_doc['stocks']}
    universe_hash=fingerprint(universe_doc);books={}
    for key in SPECS:
        path=STATE/f'{key}.json'
        if path.exists():books[key]=json.loads(path.read_text())
        elif args.init:books[key]=create_book(key,now,universe_hash);save_book(path,books[key])
        else:raise RuntimeError('Initialize the forward cohort explicitly before running')
        if books[key]['universe_hash']!=universe_hash:raise RuntimeError('Universe changed; review and start a new cohort explicitly')
    if args.init:
        print('registered',', '.join(books),'at',now.isoformat());return
    tickers=sorted(set(universe)|{'1306.T','1321.T'})
    if args.cached:
        frames={t:pd.read_pickle(CACHE/f'{t}.pkl') for t in tickers if (CACHE/f'{t}.pkl').exists()};failures=[]
    else:frames,failures=download(tickers,now)
    frames=completed_frames(frames,now)
    CACHE.mkdir(parents=True,exist_ok=True)
    if '1321.T' not in frames or frames['1321.T'].empty:
        for key,b in books.items():b['status']='data_unavailable';b['last_attempt_at']=now.isoformat();save_book(STATE/f'{key}.json',b)
        raise RuntimeError('Benchmark calendar unavailable; all accounts unchanged')
    calendar=frames['1321.T'].index
    last_allowed=pd.Timestamp(now.date()) if now.hour>=16 else pd.Timestamp(now.date())-pd.Timedelta(days=1)
    calendar=calendar[calendar<=last_allowed]
    if calendar.empty:raise RuntimeError('No completed session')
    latest=str(calendar[-1].date())
    coverage=sum(t in frames and str(frames[t].index[-1].date())==latest for t in universe)/len(universe)
    for key,b in books.items():
        candidates=strategy_candidates(key,frames,universe,latest)
        for date in calendar:
            day=str(date.date())
            if day<=b['start_date'] or (b['last_session'] and day<=b['last_session']):continue
            relevant=set(b['positions'])|{o['ticker'] for o in b['pending']}
            if day==latest:relevant|={c['ticker'] for c in candidates}
            relevant|={'1306.T','1321.T'}
            bars={t:raw_bar(frames.get(t),day) for t in relevant}
            cov=coverage if SPECS[key]['ticker'] is None else float(good_bar(bars.get(SPECS[key]['ticker'])))
            updated=advance_book(b,day,bars,candidates if day==latest else [],now,coverage=cov,plan=day==latest)
            if updated!=b:
                updated.setdefault('observations',[]).append({'date':day,'recorded_at':now.isoformat(),'bars':bars,'coverage':cov,'universe_hash':universe_hash})
            b=updated
            if b['issues']:break
        b['last_attempt_at']=now.isoformat();b['latest_data_session']=latest;b['coverage']=coverage if SPECS[key]['ticker'] is None else float(good_bar(raw_bar(frames.get(SPECS[key]['ticker']),latest)))
        save_book(STATE/f'{key}.json',b)
        print(key,b['status'],'last session',b['last_session'],'fills',len(b['fills']),flush=True)
    (CACHE/'last_run.json').write_text(json.dumps({'at':now.isoformat(),'as_of':latest,'coverage':coverage,'failed':failures,'universe_hash':universe_hash},indent=2))

if __name__=='__main__':main()
