"""Freeze the latest audited local study for Pages; CI only reads this snapshot."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]

def bear_market_snapshot():
    base=ROOT/'data/research/bear_regime_20261122'
    comparison=json.loads((base/'comparison.json').read_text())
    benchmark=json.loads((base/'benchmark_1321.json').read_text())
    costs=json.loads((base/'bb_cost_sensitivity.json').read_text())
    exit_test=json.loads((base/'bb_exit_sensitivity.json').read_text())
    breakout=json.loads((base/'52w_breakout_rs.json').read_text())
    audit=json.loads((base/'data_audit.json').read_text())
    sustained=json.loads((base/'sustained_episodes.json').read_text())
    inverse=json.loads((base/'inverse_1571.json').read_text())
    bb=next(row for row in comparison['stock_results'] if row['strategy']=='bb_rsi_120')
    market=next(row for row in benchmark['results'] if row['cost_multiple']==1)
    cost_rows=[{'cost_multiple':row['cost_multiple'],'return_pct':row['return_pct'],
                'max_dd_pct':row['max_dd_pct']} for row in costs['results']]
    exit_rows={}
    for row in exit_test['results']:
        item=exit_rows.setdefault(row['name'],{
            'name':row['name'],'rule':row['rule'],'closed_trades':row['closed_trades'],'costs':{}})
        item['costs'][str(row['cost_multiple'])]={
            'return_pct':row['return_pct'],'max_dd_pct':row['max_dd_pct']}
    breakout_rows=[{
        'cost_multiple':row['cost_multiple'],'return_pct':row['return_pct'],
        'max_dd_pct':row['max_dd_pct'],'final_equity_jpy':row['final_equity_jpy'],
        'buys':row['buys'],'closed_trades':row['closed_trades'],
        'mean_invested_pct':row['mean_invested_pct'],
    } for row in breakout['results']]
    existing={row['strategy']:row for row in comparison['stock_results']}
    return {
      'period':{'start':comparison['contract']['period'][0],'end':comparison['contract']['period'][1]},
      'market_rule':'1321終値が200日単純移動平均を下回る局面だけ個別株を売買。上回った日の判定後、翌営業日始値で手仕舞い。',
      'sample':{'sessions':comparison['sample_days'],'below_200_sessions':comparison['regime_days'],
                'below_200_periods':market['below_sma200_periods'],
                'episodes_20plus_sessions':sustained['summary']['episodes'],
                'longest_episode_sessions':max(row['sessions'] for row in sustained['episodes']),
                'bb_profitable_episodes':sustained['summary']['bb_profitable_episodes'],
                'bb_episodes_beating_1321':sustained['summary']['bb_episodes_beating_1321']},
      'results':[
        {'strategy':'BB下限＋RSI（下落局面だけ）','return_pct':bb['return_pct'],
         'max_dd_pct':bb['max_dd_pct'],'final_equity_jpy':bb['return_pct']/100*3_000_000+3_000_000},
        {'strategy':'1321を200日線下だけ保有','return_pct':market['return_pct'],
         'max_dd_pct':market['max_drawdown_pct'],'final_equity_jpy':market['final_equity']},
        {'strategy':'現金待機','return_pct':comparison['cash_reference']['return_pct'],
         'max_dd_pct':comparison['cash_reference']['max_dd_pct'],
         'final_equity_jpy':comparison['cash_reference']['final_equity']},
        {'strategy':'1571インバースを200日線下で保有','return_pct':inverse['return_pct'],
         'max_dd_pct':inverse['max_dd_pct'],'final_equity_jpy':inverse['final_equity']},
      ],
      'cost_sensitivity':cost_rows,
      'exit_sensitivity':list(exit_rows.values()),
      'new_high_breakout':{
        'results':breakout_rows,
        'comparators':[
          {'strategy':'DUKE第2ステージ（252日高値＋上昇条件）',
           'return_pct':existing['duke_stage2']['return_pct'],
           'max_dd_pct':existing['duke_stage2']['max_dd_pct'],
           'buys':existing['duke_stage2']['buys'],
           'mean_invested_pct':existing['duke_stage2']['mean_invested_pct']},
          {'strategy':'20日高値ブレイク（Donchian）',
           'return_pct':existing['donchian20']['return_pct'],
           'max_dd_pct':existing['donchian20']['max_dd_pct'],
           'buys':existing['donchian20']['buys'],
           'mean_invested_pct':existing['donchian20']['mean_invested_pct']},
        ],
        'rules':{
          'entry':'1321が200日線下。個別株が過去252営業日の高値を終値で更新し、個別株の200日線上かつ200日線が21営業日前より上、60営業日リターンが1321を上回る。売買代金代理値5億円以上。',
          'selection':'60営業日超過リターン順。最大5銘柄、1銘柄20%、同業種最大2。',
          'exit':'買値から2ATR下の損切り。個別株が50日線を終値で下回る、1321が200日線を回復する、または120営業日保有で翌営業日始値に売却。',
        },
        'limitations':breakout['limitations'],
        'strategy_source_sha256':breakout['source_sha256'],
      },
      'rules':{
        'entry':'日経225が200日線下。個別株終値が前日時点の20日ボリンジャー下限（−2σ）以下、RSI14が30以下。',
        'selection':'売買代金代理値5億円以上から売買代金順。最大5銘柄、1銘柄20%、同業種最大2。',
        'exit':'固定利食い目標なし。買値から2ATR下で損切り、最大120営業日保有、または指数が200日線を回復した後の翌営業日始値で手仕舞い。',
      },
      'status':'探索候補。現行フォワード口座には未登録。フォワード掲載中のBB案（指数200日線上の条件）とは別ルール。',
      'limitations':[
        '現存銘柄の過去株価を使う探索で、生存者・過去の構成銘柄バイアスが残る。',
        '2016〜2026年8月のみ。200日線下は702/2,603営業日、20日以上続いた区間は10回で、複数年の下げ相場を十分検証していない。',
        '調整後価格・端数株、売買代金代理値を使う。企業行動・実際の売買単位を完全再現していない。',
        '同じ過去期間で多数の候補を探索した結果で、独立した未見データの確認ではない。',
      ],
      'sources':{
        name:{'path':str((base/name).relative_to(ROOT)),
              'sha256':hashlib.sha256((base/name).read_bytes()).hexdigest()}
        for name in ('comparison.json','benchmark_1321.json','bb_cost_sensitivity.json','bb_exit_sensitivity.json','52w_breakout_rs.json',
                     'data_audit.json','sustained_episodes.json','inverse_1571.json')
      },
    }

def matched_regime_snapshot():
    """The audited, same-account comparison for the 200-day regime switch."""
    base=ROOT/'data/research/regime_strategy_comparison_20261122'
    comparison=json.loads((base/'comparison.json').read_text())
    audit=json.loads((base/'data_audit.json').read_text())
    rows={(r['regime'],r['strategy']):r for r in comparison['results']}
    def metrics(row):
        return {k:row[k] for k in ('return_pct','cagr_pct','max_dd_pct','final_equity',
                                     'buys','closed_trades') if k in row}
    costs=[]
    for multiple in (1,2,3):
        switch=next(r for r in comparison['cost_sensitivity']
                    if r['cost_multiple']==multiple and r['regime']=='switch')
        index=next(r for r in comparison['cost_sensitivity']
                   if r['cost_multiple']==multiple and r['regime']=='all'
                   and r['strategy']=='1321_buy_hold')
        costs.append({'cost_multiple':multiple,'switch':metrics(switch),
                      '1321_buy_hold':metrics(index)})
    splits=[]
    for window in ('2016_2020','2021_2026'):
        switch=next(r for r in comparison['period_splits']
                    if r['window']==window and r['regime']=='switch')
        index=next(r for r in comparison['period_splits']
                   if r['window']==window and r['regime']=='all'
                   and r['strategy']=='1321_buy_hold')
        splits.append({'window':window,'switch':metrics(switch),
                       '1321_buy_hold':metrics(index)})
    contract=comparison['contract']
    return {
      'period':{'start':contract['period'][0],'end':contract['period'][1]},
      'universe_size':audit['stock_count'],
      'sessions':comparison['state_sessions'],
      'account':{k:contract[k] for k in ('initial_cash','max_positions',
          'per_name_planned_weight','duke_tranches','sector_limit',
          'turnover_proxy_yen','fee_each_side','slippage_each_side',
          'fractional_adjusted_research_shares')},
      'regime_leaders':[
        {'regime':'上昇局面','strategy':'DUKE第2ステージ',
         **metrics(rows[('bull','duke_stage2')]),
         'benchmark':{'strategy':'1321上昇局面保有',
                      **metrics(rows[('bull','1321_conditional_hold')])}},
        {'regime':'下落局面','strategy':'BB下限＋RSI',
         **metrics(rows[('bear','bb_rsi_120')]),
         'benchmark':{'strategy':'1321下落局面保有',
                      **metrics(rows[('bear','1321_conditional_hold')])}},
      ],
      'whole_period':{
        'switch':metrics(comparison['switch']),
        '1321_buy_hold':metrics(rows[('all','1321_buy_hold')]),
      },
      'cost_sensitivity':costs,
      'period_splits':splits,
      'engine_parity':comparison['engine_parity'],
      'limitations':contract['limitations'],
      'source':{'path':str((base/'comparison.json').relative_to(ROOT)),
                'sha256':hashlib.sha256((base/'comparison.json').read_bytes()).hexdigest()},
    }

def regime_forward_status():
    state=ROOT/'data/paper/forward_tests'
    ids=('duke_bull_bb_bear_sma150','duke_bull_bb_bear','duke_bull_bb_bear_sma250')
    labels=(
      'SMA150：1321終値が150日線より上ならDUKE、下ならBB＋RSI。',
      'SMA200：1321終値が200日線より上ならDUKE、下ならBB＋RSI。',
      'SMA250：1321終値が250日線より上ならDUKE、下ならBB＋RSI。',
    )
    books=[json.loads((state/f'{key}.json').read_text()) for key in ids]
    filled=sum(bool(book.get('fills')) for book in books)
    if filled==0 and all(book.get('status')=='waiting_for_first_session' for book in books):
        status='3口座を登録済み。全口座が初回取引日待ちで、約定はまだありません。'
    else:
        status=f'3口座を登録済み。約定記録のある口座は{filled}/3です。'
    return {'status':status,'variants':list(labels)}

def main():
    paths={'comparison':ROOT/'data/research/long_stocks_guarded/comparison.json','audit':ROOT/'data/research/duke_long_audit_guarded/audit.json','data_audit':ROOT/'data/research/long_stocks_guarded/data_audit.json'}
    docs={k:json.loads(p.read_text()) for k,p in paths.items()}
    comp=docs['comparison'];audit=docs['audit']
    assert comp['contract']['membership_guard'] and audit['plan']['membership_guard']
    def row(r):return {k:r[k] for k in ['strategy','return_pct','cagr_pct','max_dd_pct']}
    target=ROOT/'data/published/research_review.json'
    previous=json.loads(target.read_text()) if target.exists() else {}
    regime_switch=previous.get('regime_switch')
    if regime_switch:
        regime_switch['forward']=regime_forward_status()
    output={'schema_version':1,'review_date':'2026-11-22','status':'adoption_pending','headline':'同条件の長期比較ではSMA200の地合い切替が+355.96%、1321買い持ちが+319.28%。ただし高コストと後半期間では指数に劣後し、実運用の最適戦略とは未確認です。','period':{'start':'2016-01-04','end':'2026-08-28'},'stock_count':docs['data_audit']['stock_count'],
      'method':'初期300万円・最大5銘柄・1銘柄20%・同業種2まで。調整後価格と端数購入を使い、翌日始値で売買。財務条件なしのDUKE第2ステージ・5分割を含む4戦略を固定。',
      'limitations':['過去の上場廃止銘柄が不足し、生存者バイアスが残る。','当時の100株単位・生株価・実売買代金・業種を完全には再現していない。','配当・権利・株式交換など企業行動の処理は未完了。','期間はすべて過去に確認済みで、未見データによる検証ではない。'],
      'fix':'新しい銘柄コードに前身企業の古い価格が接続されていたため、保存マスターで新たに登場したコードの初出前履歴を使わない制限を追加。月次観測なので完全な上場日復元ではありません。',
      'long_results':sorted([row(r) for r in comp['results'] if r['window']=='long'],key=lambda x:-x['return_pct']),
      'sensitivity':[dict(case=r['case'],**row(r)) for r in audit['long_sensitivity']],
      'recent_units':[dict(case=r['case'],**row(r)) for r in audit['recent_bridge']],
      'recent_period':'2025-08-28〜2026-08-28','paper_note':'DUKE第2ステージ・BB下限＋RSI（120日保有）・RSI回復（120日保有）と、比較用の日経225 ETF・TOPIX ETFを登録しました。追加2戦略は直近の広範囲検証でプラスでしたが、指数超過・長期優位性は未確認です。各300万円で登録後の判断から観測します。単元株と配当を除く価格ベースで再検証するため、長期参考比較と同じ成績を再現する保証はありません。',
      'bear_market':bear_market_snapshot(),
      'matched_comparison':matched_regime_snapshot(),
      'regime_switch':regime_switch,
      'sources':{**{k:{'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for k,p in paths.items()},'bear_market':'data/research/bear_regime_20261122/','matched_comparison':matched_regime_snapshot()['source']} }
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(target)
if __name__=='__main__':main()
