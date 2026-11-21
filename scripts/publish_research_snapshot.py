"""Freeze the latest audited local study for Pages; CI only reads this snapshot."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]

def main():
    paths={'comparison':ROOT/'data/research/long_stocks_guarded/comparison.json','audit':ROOT/'data/research/duke_long_audit_guarded/audit.json','data_audit':ROOT/'data/research/long_stocks_guarded/data_audit.json'}
    docs={k:json.loads(p.read_text()) for k,p in paths.items()}
    comp=docs['comparison'];audit=docs['audit']
    assert comp['contract']['membership_guard'] and audit['plan']['membership_guard']
    def row(r):return {k:r[k] for k in ['strategy','return_pct','cagr_pct','max_dd_pct']}
    output={'schema_version':1,'review_date':'2026-11-21','status':'adoption_pending','headline':'DUKEの採用判断は保留。長期成績は参考研究です。','period':{'start':'2016-01-04','end':'2026-08-28'},'stock_count':docs['data_audit']['stock_count'],
      'method':'初期300万円・最大5銘柄・1銘柄20%・同業種2まで。調整後価格と端数購入を使い、翌日始値で売買。財務条件なしのDUKE第2ステージ・5分割を含む4戦略を固定。',
      'limitations':['過去の上場廃止銘柄が不足し、生存者バイアスが残る。','当時の100株単位・生株価・実売買代金・業種を完全には再現していない。','配当・権利・株式交換など企業行動の処理は未完了。','期間はすべて過去に確認済みで、未見データによる検証ではない。'],
      'fix':'新しい銘柄コードに前身企業の古い価格が接続されていたため、保存マスターで新たに登場したコードの初出前履歴を使わない制限を追加。月次観測なので完全な上場日復元ではありません。',
      'long_results':sorted([row(r) for r in comp['results'] if r['window']=='long'],key=lambda x:-x['return_pct']),
      'sensitivity':[dict(case=r['case'],**row(r)) for r in audit['long_sensitivity']],
      'recent_units':[dict(case=r['case'],**row(r)) for r in audit['recent_bridge']],
      'recent_period':'2025-08-28〜2026-08-28','paper_note':'ペーパーは別途継続中の仮想フォワード口座です。今回の研究結果による戦略の入れ替えは行っていません。研究用DUKEと同じ条件とは限りません。',
      'sources':{k:{'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for k,p in paths.items()}}
    target=ROOT/'data/published/research_review.json';target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(target)
if __name__=='__main__':main()
