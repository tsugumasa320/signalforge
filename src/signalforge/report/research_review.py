"""Publish only the current audited snapshot; never rank legacy experiment data."""
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from signalforge.report.static_html import wrap_page

SNAPSHOT=Path('data/published/research_review.json')
LABELS={'duke_stage2':'DUKE 第2ステージ・5分割','13210':'日経225 ETF保有','13060':'TOPIX ETF保有','pullback':'移動平均の押し目','donchian20':'20日ドンチャン','smooth_donchian':'改良ドンチャン'}

def load_review():
    doc=json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    if doc.get('schema_version')!=1 or doc.get('status')!='adoption_pending':
        raise ValueError('Unsupported research review; adoption requires explicit review')
    return doc

def review_banner(depth=0):
    d=load_review();prefix='../'*depth
    return f'''<section id="research-review"><h2>最新の検証状況</h2>
    <p><strong>{escape(d['headline'])}</strong></p>
    <p>監査日：{escape(d['review_date'])}。旧実験値の掲載を終了し、修正後の参考結果を掲載しています。</p>
    <p><a href="{prefix}research/index.html">最新の比較・修正内容・残る課題を見る →</a></p></section>'''

def _table(rows, labels):
    cells=''.join(f"<tr><td>{escape(labels.get(r.get('case',r['strategy']),r['strategy']))}</td><td>{r['return_pct']:+.2f}%</td><td>{r['cagr_pct']:+.2f}%</td><td>{r['max_dd_pct']:.2f}%</td></tr>" for r in rows)
    return '<div style="overflow-x:auto"><table><thead><tr><th>条件</th><th>累積リターン</th><th>年率</th><th>最大下落率</th></tr></thead><tbody>'+cells+'</tbody></table></div>'

def _bear_market_section(study):
    if not study:
        return ''
    result_rows=''.join(
        f"<tr><td>{escape(row['strategy'])}</td><td>{row['return_pct']:+.2f}%</td><td>{row['max_dd_pct']:.2f}%</td><td>¥{row['final_equity_jpy']:,.0f}</td></tr>"
        for row in study['results']
    )
    cost_rows=''.join(
        f"<tr><td>{row['cost_multiple']}倍</td><td>{row['return_pct']:+.2f}%</td><td>{row['max_dd_pct']:.2f}%</td></tr>"
        for row in study['cost_sensitivity']
    )
    def exit_cells(row, multiple):
        result=row['costs'].get(str(multiple))
        if result is None:
            return '<td>—</td><td>—</td>'
        return f"<td>{result['return_pct']:+.2f}%</td><td>{result['max_dd_pct']:.2f}%</td>"
    exit_rows=''.join(
        f"<tr><td>{escape(row['rule'])}</td>{exit_cells(row,1)}{exit_cells(row,2)}{exit_cells(row,3)}<td>{row['closed_trades']}</td></tr>"
        for row in study.get('exit_sensitivity',[])
    )
    breakout=study.get('new_high_breakout',{})
    breakout_cost_rows=''.join(
        f"<tr><td>{row['cost_multiple']}倍</td><td>{row['return_pct']:+.2f}%</td><td>{row['max_dd_pct']:.2f}%</td><td>¥{row['final_equity_jpy']:,.0f}</td></tr>"
        for row in breakout.get('results',[])
    )
    breakout_comparators=''.join(
        f"<tr><td>{escape(row['strategy'])}</td><td>{row['return_pct']:+.2f}%</td><td>{row['max_dd_pct']:.2f}%</td><td>{row['buys']}</td><td>{row['mean_invested_pct']:.1f}%</td></tr>"
        for row in breakout.get('comparators',[])
    )
    breakout_rules=''.join(
        f"<li><strong>{escape(label)}:</strong> {escape(value)}</li>"
        for label,value in (
            ('買い条件',breakout.get('rules',{}).get('entry','')),
            ('銘柄選択・資金配分',breakout.get('rules',{}).get('selection','')),
            ('売却条件',breakout.get('rules',{}).get('exit','')),
        ) if value
    )
    rules=''.join(f"<li><strong>{escape(label)}:</strong> {escape(value)}</li>" for label,value in (
        ('買い候補',study['rules']['entry']),
        ('銘柄選択・資金配分',study['rules']['selection']),
        ('売却・損切り',study['rules']['exit']),
    ))
    limitations=''.join(f"<li>{escape(note)}</li>" for note in study['limitations'])
    sample=study['sample']
    return f'''<section><h2>下落局面の追加検証</h2>
    <p>{escape(study['period']['start'])}〜{escape(study['period']['end'])}。日経225 ETF（1321）が200日線を下回る間の売買を検証しました。下回ったのは{sample['below_200_sessions']:,}/{sample['sessions']:,}営業日、区間は{sample['below_200_periods']}回です。</p>
    <div class="info-box"><strong>候補: BB下限＋RSIの反発買い</strong><p>{escape(study['status'])}</p></div>
    <div style="overflow-x:auto"><table><thead><tr><th>条件</th><th>累積リターン</th><th>最大下落率</th><th>期末資産（300万円開始）</th></tr></thead><tbody>{result_rows}</tbody></table></div>
    <p>BB案は2σです（20日ボリンジャー下限）。固定利食い目標はありません。指数が200日線を回復した翌営業日、保有120営業日到達、または2ATRの損切りで手仕舞います。</p>
    <ul>{rules}</ul>
    <h3>売買コストを増やした感度</h3>
    <div style="overflow-x:auto"><table><thead><tr><th>通常コストに対する倍率</th><th>累積リターン</th><th>最大下落率</th></tr></thead><tbody>{cost_rows}</tbody></table></div>
    <h3>利食いルールの比較</h3>
    <p>入口・2ATR損切り・120営業日上限・指数200日線回復時の退出を揃えて比較しました。固定利食いなし案と、20日中心線回復・RSI50上抜け・+1ATR/+2ATR目標を比較しています。</p>
    <div style="overflow-x:auto"><table><thead><tr><th>退出ルール</th><th colspan="2">通常コスト</th><th colspan="2">コスト2倍</th><th colspan="2">コスト3倍</th><th>売買回数</th></tr><tr><th></th><th>累積リターン</th><th>最大下落率</th><th>累積リターン</th><th>最大下落率</th><th>累積リターン</th><th>最大下落率</th><th></th></tr></thead><tbody>{exit_rows}</tbody></table></div>
    <p>通常コストではRSI50上抜けが固定利食いなしをわずかに上回りましたが、売買回数が増え、コスト2倍・3倍では下回りました。今回の探索結果だけでは採用せず、フォワード口座にも登録していません。</p>
    <h3>下落中の52週高値ブレイク</h3>
    <p>指数が200日線下でも、個別株が強い状態で252営業日高値を更新するルールを検証しました。52週高値を使う既存のDUKE第2ステージ、20日Donchianとは入口・出口条件が異なるため、以下は参考比較です。</p>
    <ul>{breakout_rules}</ul>
    <div style="overflow-x:auto"><table><thead><tr><th>52週高値＋相対強度案のコスト倍率</th><th>累積リターン</th><th>最大下落率</th><th>期末資産</th></tr></thead><tbody>{breakout_cost_rows}</tbody></table></div>
    <div style="overflow-x:auto"><table><thead><tr><th>参考比較（各戦略の元の退出設定）</th><th>累積リターン</th><th>最大下落率</th><th>買い注文</th><th>平均投資比率</th></tr></thead><tbody>{breakout_comparators}</tbody></table></div>
    <p>新規案は通常コストでも大きくマイナスで、コストを増やすとさらに悪化しました。今回の条件では採用しません。比較対象とは保有期間・退出設定が異なり、現存銘柄の調整後価格を使う探索結果です。</p>
    <p>20営業日以上続いた下落区間は{sample['episodes_20plus_sessions']}回（最長{sample['longest_episode_sessions']}営業日）。BB案がプラスだったのは{sample['bb_profitable_episodes']}回、1321の下落局面保有を上回ったのは{sample['bb_episodes_beating_1321']}回です。</p>
    <ul>{limitations}</ul>
    <p class="muted">この下落局面用の条件はフォワードテストへ登録していません。フォワード欄のBB＋RSI（指数200日線上での条件）とは別ルールです。</p></section>'''

def export_research_review(output_dir):
    d=load_review();notes=''.join(f'<li>{escape(n)}</li>' for n in d['limitations'])
    body=f'''<section><h1>最新の戦略検証</h1><p>監査日：{escape(d['review_date'])}</p>
    <div class="info-box"><strong>{escape(d['headline'])}</strong><p>実運用の推奨順位ではありません。指数を上回る再現性は未確認です。</p></div></section>
    <section><h2>修正後の長期比較 — 参考値</h2><p>{escape(d['period']['start'])}〜{escape(d['period']['end'])}・保存済み個別株{d['stock_count']:,}銘柄</p><p>{escape(d['method'])}</p>
    <ul>{notes}</ul>{_table(d['long_results'],LABELS)}</section>
    {_bear_market_section(d.get('bear_market'))}
    <section><h2>今回修正した問題</h2><p>{escape(d['fix'])}</p><p>修正前の数値は掲載していません。成績の上昇だけでは信頼性が確認されたことにはなりません。</p></section>
    <section><h2>利益が少数銘柄に偏っていないか</h2><p>事後的に利益上位の銘柄を除いて再計算した感度分析です。将来使える銘柄選定ルールではなく、この結果だけで戦略を否定するものでもありません。</p>
    {_table(d['sensitivity'],{'baseline':'DUKE・修正後','without_top1':'利益最大の1銘柄を除外','without_top3':'利益上位3銘柄を除外'})}</section>
    <section><h2>100株単位と端数購入は別の結果になる</h2><p>{escape(d['recent_period'])}。同じ生株価・当時の月次マスター・戦略で数量条件だけを変更。長期表とはデータ・計算条件が異なります。</p>
    {_table(d['recent_units'],{'raw_price_board_lots':'100株単位','raw_price_fractional':'端数購入を許可'})}</section>
    <section><h2>フォワードテストの状況</h2><p>{escape(d['paper_note'])}</p><p><a href="../index.html#paper">フォワード成績を見る</a></p></section>
    <p class="muted">監査結果はフォワードテストの成績とは別に更新します。<a href="snapshot.json">公開用スナップショットと出典ハッシュ</a></p>'''
    directory=output_dir/'research';directory.mkdir(parents=True,exist_ok=True)
    (directory/'snapshot.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    path=directory/'index.html';path.write_text(wrap_page(title='最新の検証状況 — SignalForge',subtitle='採用判断は保留・長期成績は参考研究',body=body,generated=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),nav_active='research',depth=1),encoding='utf-8')
    return path
