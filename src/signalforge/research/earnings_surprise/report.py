"""CSV, Excel, markdown, and equity chart for one study run."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from signalforge.research.earnings_surprise.config import (
    ACCOUNT_JPY,
    HEADLINE_HOLD,
    HEADLINE_STOP,
    HOLDS,
    RULES_VERSION,
    STOPS,
)
from signalforge.research.earnings_surprise.metrics import (
    capital_stats,
    find_book,
    grouped,
    is_headline,
    liquidity_bucket,
    month_key,
    regime_bucket,
    runup_bucket,
    stats,
)
from signalforge.research.earnings_surprise.simulate import Book, Exclusion, Trade


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def _num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "—"
    return f"{value:.{digits}f}"


def _headline(trades: list[Trade], strategy: str | None = None) -> list[Trade]:
    rows = [trade for trade in trades if is_headline(trade)]
    if strategy is None:
        return rows
    return [trade for trade in rows if trade.strategy == strategy]


def _trade_frame(trades: list[Trade]) -> pd.DataFrame:
    records = [
        {
            "銘柄コード": trade.code,
            "銘柄名": trade.name,
            "決算発表日": trade.disc_date.isoformat(),
            "発表時刻": trade.disc_time,
            "エントリー日": trade.entry_date.isoformat(),
            "エントリー価格": trade.entry_px,
            "決済日": trade.exit_date.isoformat(),
            "決済価格": trade.exit_px,
            "リターン": trade.ret,
            "TOPIXリターン": trade.bench_ret,
            "超過リターン": trade.excess,
            "損切りの有無": "あり" if trade.stopped else "なし",
            "ギャップ損失": "あり" if trade.gap_loss else "なし",
            "戦略分類": trade.strategy,
            "エントリー方法": trade.method,
            "保有営業日": trade.hold,
            "損切り幅": trade.stop,
            "業種": trade.sector,
            "規模": trade.scale,
            "期間分割": trade.split,
            "スコア": trade.score,
            "信頼度": trade.confidence,
            "発表前20日": trade.pre_runup_20,
            "市場下落": trade.market_down,
            "売買代金": trade.va,
            "株数": trade.shares,
            "決済理由": trade.exit_reason,
        }
        for trade in trades
    ]
    return pd.DataFrame.from_records(records)


def _stats_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["区分", "件数", "勝率", "平均利益", "平均損失", "平均損益率", "プロフィットファクター", "平均超過"])
    out = []
    for row in rows:
        out.append(
            {
                "区分": row.get("bucket", row.get("label", "")),
                "件数": row["n"],
                "勝率": row["win_rate"],
                "平均利益": row["avg_win"],
                "平均損失": row["avg_loss"],
                "平均損益率": row["avg_ret"],
                "プロフィットファクター": row["pf"],
                "平均超過": row["avg_excess"],
                "損切り件数": row["stops"],
                "ギャップ件数": row["gaps"],
            }
        )
    return pd.DataFrame(out)


def _strategy_sheet(trades: list[Trade], books: list[Book], strategy: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = _headline(trades, strategy)
    rows = []
    for label in ("全体", "設計", "検証", "検証外"):
        subset = base if label == "全体" else [trade for trade in base if trade.split == label]
        row = stats(subset)
        row["bucket"] = label
        rows.append(row)
    other = _stats_frame(rows)
    book = find_book(books, strategy)
    cap = capital_stats(book)
    extra = pd.DataFrame(
        [
            {
                "項目": "資金制約あり最大DD",
                "値": cap["max_dd"],
            },
            {"項目": "最大同時保有", "値": cap["max_hold"]},
            {"項目": "平均資金拘束", "値": cap["avg_tied"]},
            {"項目": "最大資金拘束", "値": cap["max_tied"]},
            {"項目": "資金不足で見送り", "値": cap["rejected"]},
            {"項目": "口座", "値": ACCOUNT_JPY},
        ]
    )
    return other, extra


def _answers(trades: list[Trade], books: list[Book], exclusions: list[Exclusion]) -> list[str]:
    c0 = _headline(trades, "C0")
    c1 = _headline(trades, "C1")
    c2 = _headline(trades, "C2")
    c3 = _headline(trades, "C3")
    s0, s3 = stats(c0), stats(c3)
    lines: list[str] = []

    def few(rows: list[Trade]) -> bool:
        return len(rows) < 20

    lines.append(
        f"1. 勝率は C0 {_pct(s0['win_rate'])}（{s0['n']}件）、C3 {_pct(s3['win_rate'])}（{s3['n']}件）。"
        + ("件数不足のため優劣は保留。" if few(c0) or few(c3) else "この表の数字で比較する。")
    )
    lines.append(
        f"2. 平均損益率は C0 {_pct(s0['avg_ret'])}、C3 {_pct(s3['avg_ret'])}。"
        f" 平均超過は C0 {_pct(s0['avg_excess'])}、C3 {_pct(s3['avg_excess'])}。"
    )
    d0 = capital_stats(find_book(books, "C0"))["max_dd"]
    d3 = capital_stats(find_book(books, "C3"))["max_dd"]
    lines.append(
        f"3. 1,000万円口座の最大DDは C0 {_pct(d0)}、C3 {_pct(d3)}。"
        " 件数の差でDDが小さくなることがあるので、平均損益率と並べて見る。"
    )
    down0 = [trade for trade in c0 if trade.market_down is True]
    down3 = [trade for trade in c3 if trade.market_down is True]
    up0 = [trade for trade in c0 if trade.market_down is False]
    up3 = [trade for trade in c3 if trade.market_down is False]
    lines.append(
        f"4. 下落局面の平均超過は C0 {_pct(stats(down0)['avg_excess'])}（{len(down0)}件）、"
        f"C3 {_pct(stats(down3)['avg_excess'])}（{len(down3)}件）。"
        f" 上昇局面は C0 {_pct(stats(up0)['avg_excess'])}（{len(up0)}件）、"
        f"C3 {_pct(stats(up3)['avg_excess'])}（{len(up3)}件）。"
        + ("下落局面の件数が少なく、優位性の判断は保留。" if len(down3) < 10 else "")
    )
    lines.append(
        f"5. C0 {s0['n']}件・平均 {_pct(s0['avg_ret'])}。"
        f" セクター条件の C1 は {stats(c1)['n']}件・平均 {_pct(stats(c1)['avg_ret'])}。"
        f" 個別相対強度の C2 は {stats(c2)['n']}件・平均 {_pct(stats(c2)['avg_ret'])}。"
        " どちらが重要かは、件数を落とした分だけ平均が改善しているかで見る。"
    )
    ratio = None if not s0["n"] else s3["n"] / s0["n"]
    lines.append(
        f"6. C3 は C0 の {_pct(ratio)} の件数（{s3['n']} / {s0['n']}）。"
        " 市場が弱いという理由だけでは落としていない。減っているのはセクターと個別の両方がプラスという条件の分。"
    )
    method_c = [
        trade
        for trade in trades
        if trade.strategy == "C0" and trade.method == "C" and trade.hold == HEADLINE_HOLD and math.isclose(trade.stop, HEADLINE_STOP)
    ]
    unfilled_c = [row for row in exclusions if row.strategy == "C0" and row.method == "C" and row.reason == "高値未更新"]
    lines.append(
        "7. 翌営業日VWAP（方法B）は分足が取れないため未実施。"
        f" 寄り付きAは {len(c0)}件・平均 {_pct(s0['avg_ret'])}・ギャップ損失 {s0['gaps']}件。"
        f" 高値更新Cは {len(method_c)}件・平均 {_pct(stats(method_c)['avg_ret'])}・未更新で見送り {len(unfilled_c)}件。"
    )
    hot = [trade for trade in c0 if trade.pre_runup_20 is not None and trade.pre_runup_20 > 0.10]
    cold = [trade for trade in c0 if trade.pre_runup_20 is not None and trade.pre_runup_20 <= 0.10]
    lines.append(
        f"8. 発表前20日が10%超の C0 は {len(hot)}件・平均 {_pct(stats(hot)['avg_ret'])}。"
        f" 10%以下は {len(cold)}件・平均 {_pct(stats(cold)['avg_ret'])}。"
        " この10%は結果を見て動かしていない区切り。"
    )
    hold_bits = []
    for hold in HOLDS:
        subset = [
            trade
            for trade in trades
            if trade.strategy == "C0" and trade.method == "A" and trade.hold == hold and math.isclose(trade.stop, HEADLINE_STOP)
        ]
        hold_bits.append(f"{hold}日 {len(subset)}件・平均 {_pct(stats(subset)['avg_ret'])}")
    lines.append("9. 同じ寄り付きエントリーで保有日数だけ変えると、C0 は " + "、".join(hold_bits) + "。20日が最適とはまだ言えない。")
    stop_bits = []
    for stop in STOPS:
        subset = [
            trade
            for trade in trades
            if trade.strategy == "C0" and trade.method == "A" and trade.hold == HEADLINE_HOLD and math.isclose(trade.stop, stop)
        ]
        stop_bits.append(f"{stop * 100:.0f}% {len(subset)}件・平均 {_pct(stats(subset)['avg_ret'])}")
    lines.append("10. 損切り幅の感度（C0・寄り付き・20日）は " + "、".join(stop_bits) + "。-5%を採用済みの手法としては扱わない。")
    return lines


def _markdown(
    trades: list[Trade],
    books: list[Book],
    exclusions: list[Exclusion],
    meta: dict,
    counts: dict[str, int],
) -> str:
    lines = [
        f"# 決算サプライズ比較（{RULES_VERSION}）",
        "",
        "この結果は確立した投資手法ではない。配点と閾値は暫定で、結果を見て動かしていない。",
        "",
        "## 検証条件",
        "",
        f"- 取得期間: {meta.get('fetch_start', '—')} 〜 {meta.get('fetch_end', '—')}",
        f"- プラン上限: {meta.get('plan_start', '—')} 〜 {meta.get('plan_end', '—')}",
        f"- リクエストした年数: {meta.get('requested_years', 5)} 年。上記と違う場合、5年間の検証ではない。",
        f"- 株価: {meta.get('names', '—')} 銘柄（キャッシュ内）。モード: {meta.get('mode', '—')}",
        "- 市場: キャッシュ時点の東証プライム普通株",
        "- ベンチマーク: 1306（TOPIX連動ETF、コード 13060）の調整後株価。公式TOPIXは未取得。",
        "- C0: 会社の通期営業利益予想の上方修正、または前年同期比で営業利益が増え営業利益率も改善。市場コンセンサスではない。",
        "- C1: C0 かつ セクター20日リターン − ベンチマーク20日リターン > 0",
        "- C2: C0 かつ 個別−ベンチマーク20日 > 0 かつ 個別−セクター20日 > 0",
        "- C3: C2 かつ セクター相対強度20日 > 0。市場が弱いだけでは除外しない。",
        "- 相対強度の終値は、発表が公開される前の最後の引け。場中発表の当日終値は使わない。",
        "- エントリーA: 翌営業日寄り付き（9時前の発表だけ当日寄り）。B: 未実施。C: 前日高値を更新した価格。",
        "- 損切り -5%（寄り付きが下回れば寄り付き）。最大20営業日。手数料 0.105% + スリッページ 0.03% を往復。",
        "- 1銘柄100万円、100株単位。発表前日の売買代金 5億円未満は見送り。",
        f"- 口座制約の成績は初期資金 {ACCOUNT_JPY:,.0f} 円。シグナルの勝率は、資金不足で見送る前の約定。",
        f"- セクター指数: {meta.get('sector_note', 'キャッシュ内のプライム銘柄の等ウェイト')}",
        "",
        "## データ",
        "",
        f"- イベント {counts.get('events', 0)} 件、プライム候補 {counts.get('candidates', 0)} 件、C0 {counts.get('c0', 0)}、C1 {counts.get('c1', 0)}、C2 {counts.get('c2', 0)}、C3 {counts.get('c3', 0)}",
        f"- コンセンサス: {meta.get('consensus', '未取得')}",
        f"- 分足・VWAP: {meta.get('minute_bars', '未取得')}",
        f"- 値幅制限: {meta.get('limit_prices', 'UL/LL はほぼ空のため未使用')}",
        f"- 異常バー: {meta.get('bad_bars', 0)} / {meta.get('bars', 0)}",
        "",
        "## 10の問い",
        "",
    ]
    for line in _answers(trades, books, exclusions):
        lines.append(f"- {line}")
    lines.extend(["", "## 期間分割", ""])
    for strategy in ("C0", "C1", "C2", "C3"):
        bits = []
        for label in ("設計", "検証", "検証外"):
            subset = [trade for trade in _headline(trades, strategy) if trade.split == label]
            row = stats(subset)
            bits.append(f"{label} {row['n']}件・平均 {_pct(row['avg_ret'])}")
        lines.append(f"- {strategy}: " + "、".join(bits))
    lines.append("")
    lines.append("全体の平均がプラスでも、設計と検証がマイナスなら、そのプラスは最後の期間の少数の取引に寄っている。")
    lines.extend(
        [
            "",
            "## 見方",
            "",
            "設計・検証・検証外は、取引日の並びの先頭60%、次の20%、最後の20%である。条件の探索は設計期間でも行っていない。",
            "業績持続性（受注、継続収益、一過性利益）は短信サマリーに無く、スコアは満点にしない。信頼度「高」でもこの20点は欠測のまま。",
            "Excelの全取引履歴は寄り付き・20営業日・-5%だけ。保有日数と損切り幅の違いは trades.csv にある。",
            "",
        ]
    )
    return "\n".join(lines)


def _chart(books: list[Book], path: Path) -> None:
    try:
        import plotly.graph_objects as go
    except ImportError:
        return
    fig = go.Figure()
    for strategy in ("C0", "C1", "C2", "C3"):
        book = find_book(books, strategy)
        if book is None or not book.equity:
            continue
        fig.add_trace(go.Scatter(x=[day.isoformat() for day in book.days], y=book.equity, mode="lines", name=strategy))
    fig.update_layout(title="資金制約あり評価額（寄り付き・20日・-5%）", yaxis_title="円", template="plotly_white")
    fig.write_html(path, include_plotlyjs="cdn")


def write_outputs(
    out_dir: Path,
    trades: list[Trade],
    exclusions: list[Exclusion],
    books: list[Book],
    meta: dict,
    counts: dict[str, int],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    headline = _headline(trades)
    _trade_frame(trades).to_csv(out_dir / "trades.csv", index=False)
    pd.DataFrame(
        [
            {
                "銘柄コード": row.code,
                "銘柄名": row.name,
                "決算発表日": row.disc_date.isoformat(),
                "戦略分類": row.strategy,
                "エントリー方法": row.method,
                "理由": row.reason,
            }
            for row in exclusions
        ]
    ).to_csv(out_dir / "exclusions.csv", index=False)

    equity_rows = []
    for strategy in ("C0", "C1", "C2", "C3"):
        book = find_book(books, strategy)
        if book is None:
            continue
        peak = 0.0
        for day, equity, held in zip(book.days, book.equity, book.n_hold):
            peak = max(peak, equity)
            equity_rows.append(
                {
                    "戦略": strategy,
                    "日付": day.isoformat(),
                    "評価額": equity,
                    "ドローダウン": 0.0 if peak <= 0 else equity / peak - 1.0,
                    "同時保有": held,
                }
            )
    pd.DataFrame(equity_rows).to_csv(out_dir / "equity.csv", index=False)

    report = _markdown(trades, books, exclusions, meta, counts)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    _chart(books, out_dir / "equity.html")

    quality = pd.DataFrame([{"項目": key, "値": value} for key, value in meta.items()])
    with pd.ExcelWriter(out_dir / "earnings_surprise.xlsx") as writer:
        summary_rows = []
        for strategy in ("C0", "C1", "C2", "C3"):
            row = stats(_headline(trades, strategy))
            cap = capital_stats(find_book(books, strategy))
            summary_rows.append({"戦略": strategy, **row, "最大DD": cap["max_dd"], "最大同時保有": cap["max_hold"], "平均資金拘束": cap["avg_tied"], "最大資金拘束": cap["max_tied"], "資金不足": cap["rejected"]})
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="サマリー", index=False)
        _trade_frame(headline).to_excel(writer, sheet_name="全取引履歴", index=False)
        for strategy in ("C0", "C1", "C2", "C3"):
            table, extra = _strategy_sheet(trades, books, strategy)
            table.to_excel(writer, sheet_name=f"{strategy}成績", index=False, startrow=0)
            extra.to_excel(writer, sheet_name=f"{strategy}成績", index=False, startrow=len(table) + 2)
        _stats_frame([{**stats(items), "bucket": f"{strategy} {bucket}"} for strategy in ("C0", "C1", "C2", "C3") for bucket, items in _by(headline, strategy, lambda trade: str(trade.entry_date.year)).items()]).to_excel(writer, sheet_name="年別成績", index=False)
        _stats_frame([{**stats(items), "bucket": f"{strategy} {bucket}"} for strategy in ("C0", "C1", "C2", "C3") for bucket, items in _by(headline, strategy, lambda trade: trade.sector).items()]).to_excel(writer, sheet_name="業種別成績", index=False)
        _stats_frame([{**stats(items), "bucket": f"{strategy} {bucket}"} for strategy in ("C0", "C1", "C2", "C3") for bucket, items in _by(headline, strategy, regime_bucket).items()]).to_excel(writer, sheet_name="市場環境別成績", index=False)
        _month = [{**stats(items), "bucket": f"{strategy} {bucket}"} for strategy in ("C0", "C3") for bucket, items in _by(headline, strategy, month_key).items()]
        _stats_frame(_month).to_excel(writer, sheet_name="月別成績", index=False)
        _stats_frame([{**stats(items), "bucket": f"{strategy} {bucket}"} for strategy in ("C0", "C3") for bucket, items in _by(headline, strategy, liquidity_bucket).items()]).to_excel(writer, sheet_name="流動性別", index=False)
        _stats_frame([{**stats(items), "bucket": f"{strategy} {bucket}"} for strategy in ("C0", "C3") for bucket, items in _by(headline, strategy, lambda trade: trade.scale or "不明").items()]).to_excel(writer, sheet_name="規模別", index=False)
        _stats_frame([{**stats(items), "bucket": f"{strategy} {bucket}"} for strategy in ("C0", "C3") for bucket, items in _by(headline, strategy, runup_bucket).items()]).to_excel(writer, sheet_name="発表前上昇別", index=False)
        pd.DataFrame(
            [
                {
                    "銘柄コード": row.code,
                    "銘柄名": row.name,
                    "決算発表日": row.disc_date.isoformat(),
                    "戦略分類": row.strategy,
                    "エントリー方法": row.method,
                    "理由": row.reason,
                }
                for row in exclusions
            ]
            + [
                {
                    "銘柄コード": trade.code,
                    "銘柄名": trade.name,
                    "決算発表日": trade.disc_date.isoformat(),
                    "戦略分類": trade.strategy,
                    "エントリー方法": trade.method,
                    "理由": "資金不足",
                }
                for trade in trades
                for book in books
                if trade.id in book.rejected_ids and book.strategy == trade.strategy
            ]
        ).to_excel(writer, sheet_name="未約定・除外", index=False)
        quality.to_excel(writer, sheet_name="データ品質・欠損状況", index=False)
    return out_dir / "report.md"


def _by(trades: list[Trade], strategy: str, key) -> dict[str, list[Trade]]:
    out: dict[str, list[Trade]] = {}
    for trade in trades:
        if trade.strategy != strategy:
            continue
        name = str(key(trade))
        out.setdefault(name, []).append(trade)
    return out
