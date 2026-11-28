"""Current append-only forward accounts, deliberately excluding replayed books."""
from pathlib import Path
from html import escape
import json
from datetime import datetime,timezone
from signalforge.report.static_html import wrap_page
from signalforge.report.yahoo_jp import yahoo_jp_anchor
from signalforge.paper.forward_test import REGIME_SWITCHES

STATE=Path('data/paper/forward_tests')
STATUS={'waiting_for_first_session':'開始後の取引日待ち','observing':'観測中','data_incomplete':'データ不足・新規注文停止','data_unavailable':'データ取得待ち','needs_review':'要確認・更新停止'}

# Common ETF names (not in universe.json)
ETF_NAMES = {
    '1321.T': '日経225連動型上場投信',
    '1306.T': 'TOPIX連動型上場投信',
}

def _load_ticker_names():
    """Load ticker to company name mapping from universe.json and ETFs."""
    names = dict(ETF_NAMES)
    try:
        universe_path = Path('config/forward/universe.json')
        if universe_path.exists():
            universe_doc = json.loads(universe_path.read_text())
            for stock in universe_doc.get('stocks', []):
                ticker = stock.get('ticker')
                name = stock.get('name')
                if ticker and name:
                    names[ticker] = name
    except (json.JSONDecodeError, OSError):
        pass
    return names

def books():return [json.loads(p.read_text()) for p in sorted(STATE.glob('*.json'))]

def summary_html(depth=0):
    rows=[];prefix='../'*depth
    for b in books():
        eq=b['equity'][-1] if b['equity'] else None
        ret=f"{(eq['equity']/b['rules']['initial_cash']-1)*100:+.2f}%" if eq else '—（観測前）'
        money=f"¥{(eq['equity'] if eq else b['cash']):,.0f}"
        rows.append(f"<tr><td><a href='{prefix}forward/{b['strategy']}.html'>{escape(b['label'])}</a></td><td>{escape(STATUS.get(b['status'],b['status']))}</td><td>{escape(b['start_date'])}</td><td>{escape(b['last_session'] or '—')}</td><td>{money}</td><td>{ret}</td><td>{len(b['fills'])}</td></tr>")
    return '<div style="overflow-x:auto"><table><thead><tr><th>戦略</th><th>状態</th><th>登録日</th><th>最終観測日</th><th>評価額</th><th>リターン</th><th>約定件数</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'

def export_forward_pages(out):
    directory=out/'forward';directory.mkdir(parents=True,exist_ok=True)
    selection=json.loads(Path('config/forward/selection.json').read_text())
    ticker_names = _load_ticker_names()
    for b in books():
        evidence=selection['strategies'].get(b['strategy'])
        rationale=''
        if evidence:
            rationale=f"<section><h2>追加した根拠（過去の参考検証）</h2><p>{escape(selection['period'])}：リターン {evidence['return_pct']:+.2f}%、最大下落 {evidence['max_dd_pct']:.2f}%、決済 {evidence['closed_trades']}件。未解決の企業行動・期末評価フラグなし。</p><p>広範囲の検証でプラスを残した、DUKEと異なる反発型の候補です。{escape(selection['note'])} この数値をフォワード成績には加算しません。</p></section>"
        fills=''.join(f"<tr><td>{escape(f['date'])}</td><td>{yahoo_jp_anchor(f['ticker'], label=ticker_names.get(f['ticker'], f['ticker']))}</td><td>{'DUKE' if f.get('strategy_kind')=='duke' else 'BB＋RSI' if f.get('strategy_kind')=='bb' else '—'}</td><td>{'買い' if f['side']=='buy' else '売り'}</td><td>{f['shares']:,.0f}</td><td>{f['price']:,.2f}</td><td>{f['fee']:,.2f}</td></tr>" for f in reversed(b['fills']))
        pending=''.join(f"<li>{yahoo_jp_anchor(o['ticker'], label=ticker_names.get(o['ticker'], o['ticker']))}：{'買い' if o['side']=='buy' else '売り'} {o['shares']:,.0f}株／口（判断日 {escape(o['signal_date'])}）</li>" for o in b['pending']) or '<li>注文なし</li>'
        held=''.join(f"<li>{yahoo_jp_anchor(t, label=ticker_names.get(t, t))}：{'DUKE' if p.get('kind')=='duke' else 'BB＋RSI' if p.get('kind')=='bb' else ''} {p['shares']:,.0f}株／口・評価単価 {p['mark']:,.2f}円</li>" for t,p in b['positions'].items()) or '<li>保有なし</li>'
        issues=''.join(f"<li>{escape(i['date'])} {escape(i['ticker'])}：{escape(i['reason'])}</li>" for i in b['issues'])
        if b['strategy'] in REGIME_SWITCHES:
            market_sma=REGIME_SWITCHES[b['strategy']]
            duke_rule=f'日経225 ETFが{market_sma}日線より上のときだけ、DUKE第2ステージで買います。財務条件は使わず、持ち合い後の52週高値突破・前日の出来高増・売買代金5億円以上を条件にします。最大5銘柄、1銘柄20%を5分割、同業種2銘柄まで。損切り線または252取引日で売却します。'
            reversion_rule=f'日経225 ETFが{market_sma}日線より下のときだけ、終値が前日時点の20日ボリンジャーバンド下限（−2σ）以下、前日のRSI14が30以下の銘柄を買います。最大5銘柄、1銘柄20%を一括購入し、前日時点のATR14の2倍で損切り、120取引日で売却します。固定利確はありません。地合いが変わったら翌始値で売却し、{market_sma}日線が不明または同値の日は現金とします。'
        else:
            duke_rule='DUKEは日経225 ETFが200日線より上のとき、移動平均線が上昇基調の銘柄から、持ち合い後の52週高値突破・前日の出来高増・売買代金5億円以上を選びます。利益がある場合に分割して追加し、損切り線または252取引日で売却します。'
            reversion_rule='BB下限＋RSIは終値が前日時点の20日ボリンジャーバンド下限（−2σ）以下、前日のRSI14が30以下で購入候補。RSI回復は前々日から前日にRSI14が35を上抜き、当日終値が前日時点の200日EMAより上の銘柄を選びます。RSIは単純平均式です。両戦略とも日経225 ETFが200日線より上・売買代金5億円以上が条件。最大5銘柄・同業種2銘柄・100株単位・1銘柄20%を一括購入。追加購入・固定利確なし、前日時点のATR14の2倍で損切り、最大120取引日で売却します。'
        body=f'''<section><h2>{escape(b['label'])}</h2><p>登録日：{escape(b['start_date'])}。状態：{escape(STATUS.get(b['status'],b['status']))}</p>
        <p>登録後の取引日から判断を記録し、保存した注文を次の取引日の始値で仮想約定します。初期資金は各300万円。過去の研究リターンを引き継ぎません。</p>
        {summary_html(1)}</section>{rationale}<section><h2>売買条件</h2><p>DUKEは財務条件なし・第2ステージ・最大5銘柄・1銘柄20%を5分割・同業種2銘柄まで・100株単位。日経225とTOPIXは各ETFを10口単位で購入して保有します。全口座で配当・分配金を除いた価格ベースの成績です。</p>
        <p>片道費用0.105%・滑り0.03%。日足による約定推定で、実際の約定記録ではありません。分割は保存データで調整し、欠損や不明な大幅変動が出た口座は要確認として停止します。</p>
        <p>{escape(duke_rule)}</p>
        <p>{escape(reversion_rule)}</p>
        <p>個別株3戦略の対象は登録時の国内株一覧全件。毎回の取得率が95%未満なら新規注文を停止します。長期参考比較とは数量・配当調整の条件が異なり、実用的な条件での再検証です。</p></section>
        <section><h2>保有</h2><ul>{held}</ul><h2>次回の注文</h2><ul>{pending}</ul></section>
        <section><h2>約定記録</h2><div style="overflow-x:auto"><table><thead><tr><th>日付</th><th>銘柄</th><th>戦略種別</th><th>売買</th><th>数量</th><th>価格</th><th>費用</th></tr></thead><tbody>{fills or '<tr><td colspan="7">まだ約定はありません</td></tr>'}</tbody></table></div></section>
        <section><h2>確認が必要な事項</h2><ul>{issues or '<li>記録された停止理由はありません。企業行動を完全に検証したことを意味しません。</li>'}</ul></section>
        <p><a href="{b['strategy']}.json">判断・注文・約定の記録</a></p>'''
        (directory/f"{b['strategy']}.json").write_text(json.dumps(b,ensure_ascii=False,indent=2)+'\n')
        (directory/f"{b['strategy']}.html").write_text(wrap_page(title='フォワードテスト — '+b['label'],subtitle='日々の判断と仮想約定を保存',body=body,generated=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),nav_active='paper',depth=1))
