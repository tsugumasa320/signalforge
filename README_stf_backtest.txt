STF氏型・日本株モメンタムのバックテスト
======================================

事前に固定したルールは src/signalforge/research/stf/rules.py にある。
結果を見てから、このファイルの基本ルール（A〜E）を書き換えない。
感度分析は sensitivity_specs() に分離してある。

実行
----

  cd /Users/tsugumasayutani/Documents/GitHub/signalforge
  # APIキーはチャットに貼らず、.env の JQUANTS_API_KEY を使う
  uv run python -m signalforge.research.stf fetch --rpm 20
  uv run python -m signalforge.research.stf run

出力: data/stf/report/ （summary.csv, yearly_returns.csv, monthly_returns.csv,
equity_curves.csv, equity_curves.svg, drawdowns.svg, contributors.csv, metrics.json）

約定
----

月末の終値までで銘柄とウェイトを決め、翌営業日の始値で売買する。
当日終値では約定させない。

スコア（固定）
------------

相対20日 = 銘柄の20本リターン − ベンチマークの20営業日リターン
相対60日 = 同じく60日
スコア = 0.5 * 相対20日 + 0.5 * 相対60日
同点は、相対60日が大きい方、次に20日平均売買代金が大きい方、次にコード昇順。

ベンチマーク
------------

公式TOPIXは現在のAPIプランで取得できない。
代わりに TOPIX連動ETF 1306（J-Quantsコード 13060）の調整済終値を使う。
これは分配落ちで下がるため、配当なしTOPIXより低く、超過リターンを大きく見せうる。

データ期間
----------

依頼期間は 2017-03-01 〜 2025-12-31、ウォームアップは 2016-11-01 以降。
この環境の J-Quants 契約は約2年分しか返せない。fetch は契約期間と依頼期間の
重なる部分だけを取る。2017〜2024年夏は、プランを上げてから同じコマンドを
再実行するまで未検証である。
