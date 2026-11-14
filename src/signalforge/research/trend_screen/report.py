"""ランキング、指標、個別メモ、日足チャートの出力。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from signalforge.research.trend_screen.cases import TEST_CASES
from signalforge.research.trend_screen.config import CHART_LABELS, DETAIL_N, UNCONFIRMED_ALWAYS, WEIGHTS_NOTE
from signalforge.research.trend_screen.forward import ForwardReport
from signalforge.research.trend_screen.score import ScoredName, primary_label, ranked


def _pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "未確認"
    return f"{value:+.1%}" if signed else f"{value:.1%}"


def _num(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "未確認"
    return f"{value:.{digits}f}"


def _yen(value: float | None) -> str:
    if value is None:
        return "未確認"
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:,.1f}億円"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.1f}百万円"
    return f"{value:,.0f}円"


def _price(value: float | None) -> str:
    if value is None:
        return "未確認"
    if abs(value - round(value)) < 0.05:
        return f"{value:,.0f}円"
    return f"{value:,.2f}円"


def _peg(row: ScoredName) -> str:
    val = row.valuation
    if val is None or val.status == "未確認" or val.peg is None and val.status != "算出不能":
        return "未確認"
    if val.status == "算出不能":
        return "算出不能"
    return f"{val.peg:.2f}（{val.status}）"


def _points(score: float | None, maximum: float | None = None) -> str:
    if score is None:
        return "未確認"
    if maximum is None:
        return f"{score:.1f}"
    return f"{score:.1f}/{maximum:.0f}"


def _table(rows: list[ScoredName]) -> list[dict[str, str]]:
    body = []
    for rank, row in enumerate(rows, start=1):
        chart = row.chart_score
        fund = row.fundamentals
        body.append(
            {
                "順位": str(rank),
                "コード": row.code.replace(".T", ""),
                "企業名": row.name,
                "総合点": _points(row.total, row.total_max),
                "チャート": _points(None if chart is None else chart.score, None if chart is None else chart.max_points),
                "業績": _points(
                    None if fund is None else fund.score,
                    None if fund is None else fund.max_points,
                ),
                "PEG": _peg(row),
                "判定": row.grade,
                "購入タイミング": "" if row.chart is None else row.chart.timing_label,
                "留意": " / ".join(row.flags) if row.flags else "",
            }
        )
    return body


def _metrics_row(row: ScoredName) -> dict[str, object]:
    chart = row.chart
    val = row.valuation
    fund = row.fundamentals
    return {
        "コード": row.code.replace(".T", ""),
        "企業名": row.name,
        "市場": row.market,
        "業種": row.sector,
        "総合点": row.total,
        "満点": row.total_max,
        "判定": row.grade,
        "候補": row.candidate_status,
        "チャート": None if row.chart_score is None else row.chart_score.score,
        "業績": None if fund is None else fund.score,
        "PEG": None if val is None else val.peg,
        "PEG区分": None if val is None else val.status,
        "PER": None if val is None else val.per,
        "PER区分": None if val is None else val.per_kind,
        "EPS成長率%": None if val is None else val.growth_pct,
        "成長率区分": None if val is None else val.growth_kind,
        "成長率期間": None if val is None else val.growth_span,
        "PEG式": None if val is None else val.formula,
        "基準日": None if chart is None else chart.as_of,
        "株価": None if chart is None else chart.price,
        "時価総額": row.market_cap,
        "売買代金20日": None if chart is None else chart.turnover_20d,
        "1年リターン": None if chart is None else chart.ret_1y,
        "3年リターン": None if chart is None else chart.ret_3y,
        "1年配当込み": None if chart is None else chart.ret_1y_total,
        "3年配当込み": None if chart is None else chart.ret_3y_total,
        "1年相対": None if chart is None else chart.excess_1y,
        "3年相対": None if chart is None else chart.excess_3y,
        "1年DD": None if chart is None else chart.mdd_1y,
        "3年DD": None if chart is None else chart.mdd_3y,
        "年率ボラ": None if chart is None else chart.vol_1y,
        "上昇月": None if chart is None else chart.up_month_ratio,
        "200日線上": None if chart is None else chart.pct_above_ma200,
        "200日線傾き": None if chart is None else chart.ma200_slope,
        "75日線傾き": None if chart is None else chart.ma75_slope,
        "52週高値から": None if chart is None else chart.dd_52w,
        "一次条件": "" if chart is None else primary_label(chart.primary),
        "タイミング": "" if chart is None else chart.timing,
        "留意": " / ".join(row.flags),
        "価格ソース": row.price_source,
        "財務ソース": row.fundamental_source,
        "エラー": row.error or "",
    }


def _detail(row: ScoredName) -> list[str]:
    chart = row.chart
    fund = row.fundamentals
    val = row.valuation
    lines = [
        f"## {row.code.replace('.T', '')} {row.name}",
        "",
        f"- 市場: {row.market}",
        f"- 業種: {row.sector}",
        f"- 時価総額: {_yen(row.market_cap)}",
        f"- 株価: {_price(None if chart is None else chart.price)}（基準日 {('未確認' if chart is None else chart.as_of)}）",
        f"- 20営業日平均売買代金: {_yen(None if chart is None else chart.turnover_20d)}（終値×出来高）",
        f"- 総合 { _points(row.total, row.total_max) } / 判定 {row.grade}",
        f"- 購入タイミング: {'' if chart is None else chart.timing_label}",
        "",
        "### チャート",
        "",
    ]
    if chart is None or row.chart_score is None:
        lines.append("日足指標は未確認。")
    else:
        lines.extend(
            [
                f"- 1年リターン {_pct(chart.ret_1y, signed=True)}（{chart.ret_1y_start or '未確認'}から、配当なし）",
                f"- 3年リターン {_pct(chart.ret_3y, signed=True)}（{chart.ret_3y_start or '未確認'}から、配当なし）",
                f"- 配当込み1年 {_pct(chart.ret_1y_total, signed=True)} / 3年 {_pct(chart.ret_3y_total, signed=True)}",
                f"- TOPIX相対 1年 {_pct(chart.excess_1y, signed=True)} / 3年 {_pct(chart.excess_3y, signed=True)}",
                f"- 最大ドローダウン 1年 {_pct(chart.mdd_1y)} / 3年 {_pct(chart.mdd_3y)}（終値）",
                f"- 200日線より上 {_pct(chart.pct_above_ma200)} / 200日線の60日変化 {_pct(chart.ma200_slope, signed=True)}",
                f"- 75日線の20日変化 {_pct(chart.ma75_slope, signed=True)}",
                f"- 52週高値から {_pct(chart.dd_52w)} / 年率ボラティリティ {_pct(chart.vol_1y)} / 上昇月 {_pct(chart.up_month_ratio)}",
                f"- 移動平均 5 {_price(chart.ma5)} / 25 {_price(chart.ma25)} / 75 {_price(chart.ma75)} / 200 {_price(chart.ma200)}",
                f"- 一次条件 {primary_label(chart.primary)}",
                "",
                "チャート配点:",
                "",
            ]
        )
        for key, label in CHART_LABELS.items():
            lines.append(f"- {label}: {_num(row.chart_score.components.get(key))}")
        lines.append("")
        lines.extend(f"- {note}" for note in chart.notes + row.chart_score.notes)
    lines.extend(["", "### 業績", ""])
    if fund is None or not fund.annuals:
        lines.append("通期財務は未確認。")
    else:
        lines.append("| 決算期 | 売上 | 営業利益 | EPS | 利益率 | ROE | 営業CF | 自己資本比率 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for annual in fund.annuals:
            lines.append(
                "| "
                + " | ".join(
                    [
                        annual.fiscal_end,
                        _yen(annual.sales),
                        _yen(annual.operating_income),
                        _num(annual.eps, 2),
                        _pct(annual.op_margin),
                        _pct(annual.roe),
                        _yen(annual.operating_cf),
                        _pct(annual.equity_ratio),
                    ]
                )
                + " |"
            )
        lines.append("")
        lines.append(f"業績点 {_points(fund.score, fund.max_points)}。出典: {fund.source}")
        lines.extend(f"- {note}" for note in fund.notes)
        if fund.penalties:
            lines.extend(f"- 減点: {item}" for item in fund.penalties)
    lines.extend(["", "### バリュエーション", ""])
    if val is None:
        lines.append("未確認。")
    else:
        lines.extend(
            [
                f"- 区分: {val.status}",
                f"- PER: {_num(val.per, 2)}（{val.per_kind}）",
                f"- EPS成長率: {_num(val.growth_pct, 2)}%（{val.growth_kind}、{val.growth_span}）",
                f"- PEG: {_peg(row)}",
                f"- 計算式: {val.formula}",
                f"- 点数: {_points(val.score, val.max_points)}",
                f"- 出典: {val.source}",
            ]
        )
        lines.extend(f"- {note}" for note in val.notes)
    lines.extend(["", "### 投資判断", "", "- 強み:"])
    if row.strengths:
        lines.extend(f"  - {item}" for item in row.strengths)
    else:
        lines.append("  - 数値上の強みは確認できない。")
    return lines


def _detail_block(row: ScoredName) -> str:
    lines = _detail(row)
    lines.append("- リスク:")
    if row.risks:
        lines.extend(f"  - {item}" for item in row.risks)
    else:
        lines.append("  - フラグは付いていない。")
    lines.extend(
        [
            f"- 株価が上昇している理由: {row.price_rise_note}",
            f"- 現在の購入タイミング: {'' if row.chart is None else row.chart.timing_label}",
            f"- 押し目の位置: {row.pullback}",
            f"- トレンド崩れ: {row.trend_break}",
            "- 未確認:",
        ]
    )
    lines.extend(f"  - {item}" for item in UNCONFIRMED_ALWAYS)
    lines.append("")
    return "\n".join(lines)


def _write_chart(path: Path, row: ScoredName, bars: pd.DataFrame) -> None:
    import plotly.graph_objects as go

    view = bars.tail(935)
    figure = go.Figure()
    if {"open", "high", "low", "close"}.issubset(view.columns) and view["high"].notna().any():
        figure.add_trace(
            go.Candlestick(
                x=view.index,
                open=view["open"],
                high=view["high"],
                low=view["low"],
                close=view["close"],
                name="日足",
            )
        )
    else:
        figure.add_trace(go.Scatter(x=view.index, y=view["close"], name="終値"))
    for window, label in ((5, "5日"), (25, "25日"), (75, "75日"), (200, "200日")):
        average = view["close"].rolling(window, min_periods=window).mean()
        figure.add_trace(go.Scatter(x=view.index, y=average, name=label, line={"width": 1.2}))
    figure.update_layout(
        title=f"{row.code.replace('.T', '')} {row.name} 日足（直近約4年）",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        yaxis_title="円",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(str(path), include_plotlyjs="cdn")


def _forward_md(report: ForwardReport | None) -> str:
    if report is None:
        return "前方リターン集計は未実施。\n"
    lines = [
        "## チャート条件だけの前方リターン（戦略A）",
        "",
        report.note,
        "",
        f"- シグナル日: {report.n_signal_dates}（{report.start or '未確認'} 〜 {report.end or '未確認'}）",
        f"- 対象銘柄数: {report.n_names}",
        "",
        "| 期間 | 件数 | 平均（コスト前） | 平均（コスト後） | 勝率 | 平均利益 | 平均損失 | TOPIX超過 | 最悪 | 平均銘柄数 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for stat in report.horizons:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{stat.horizon}営業日",
                    str(stat.n),
                    _pct(stat.mean_gross, signed=True),
                    _pct(stat.mean_net, signed=True),
                    _pct(stat.win_rate),
                    _pct(stat.avg_win, signed=True),
                    _pct(stat.avg_loss, signed=True),
                    _pct(stat.mean_excess, signed=True),
                    _pct(stat.worst, signed=True),
                    _num(stat.avg_names, 1),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(
    rows: list[ScoredName],
    *,
    out: Path,
    meta: dict,
    bars: dict[str, pd.DataFrame],
    forward: ForwardReport | None,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    order = ranked(rows)
    table = _table(order)
    frame = pd.DataFrame(table)
    frame.to_csv(out / "ranking.csv", index=False, encoding="utf-8-sig")
    metrics = pd.DataFrame([_metrics_row(row) for row in rows])
    metrics.to_csv(out / "metrics.csv", index=False, encoding="utf-8-sig")
    excluded = [row for row in rows if row.candidate_status == "原則除外"]
    unknown = [row for row in rows if row.candidate_status in {"総合点未確定", "取得失敗"}]
    excluded_frame = pd.DataFrame([_metrics_row(row) for row in excluded + unknown])
    excluded_frame.to_csv(out / "excluded.csv", index=False, encoding="utf-8-sig")
    try:
        with pd.ExcelWriter(out / "ranking.xlsx") as writer:
            frame.to_excel(writer, sheet_name="ランキング", index=False)
            metrics.to_excel(writer, sheet_name="指標", index=False)
            excluded_frame.to_excel(writer, sheet_name="除外と未確定", index=False)
    except Exception as exc:
        meta["excel_error"] = str(exc)

    detail_rows = list(order[:DETAIL_N])
    seen = {row.code for row in detail_rows}
    for code in TEST_CASES:
        match = next((row for row in rows if row.code == code), None)
        if match is not None and match.code not in seen:
            detail_rows.append(match)
            seen.add(match.code)
    chart_notes: list[str] = []
    for row in detail_rows:
        frame_bars = bars.get(row.code)
        if frame_bars is None or row.chart is None:
            chart_notes.append(f"{row.code}: チャートファイルなし")
            continue
        try:
            _write_chart(out / "charts" / f"{row.code.replace('.T', '')}.html", row, frame_bars)
        except Exception as exc:
            chart_notes.append(f"{row.code}: {exc}")
    meta["chart_notes"] = chart_notes
    (out / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 長期上昇トレンド スクリーニング",
        "",
        f"- 手法バージョン: {meta.get('method_version')}",
        f"- 実行: {meta.get('run_at')}",
        f"- 全体の基準日: {meta.get('as_of')}（銘柄ごとに最終バーが違う場合は個別に記載）",
        f"- 価格: {meta.get('price_source')}",
        f"- 相対: {meta.get('benchmark')}",
        f"- 上場一覧: {meta.get('listing_as_of')} / {meta.get('listing_source')}",
        f"- {meta.get('universe_note')}",
        f"- {WEIGHTS_NOTE}",
        "- 判定閾値は100点満点の絶対点。欠測は0点にせず、総合点は「得点/その銘柄の満点」で示す。",
        "- 一次条件を一つ欠いても選定対象に残す。200日線が下向きのときだけ新規候補から外す。",
        "- テストケースは事前に合格にしていない。",
        "",
        "## ランキング",
        "",
    ]
    if table:
        header = list(table[0])
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for item in table:
            lines.append("| " + " | ".join(item[key] for key in header) + " |")
    else:
        lines.append("選定対象で総合点が出た銘柄はない。")
    lines.extend(["", "## 除外・未確定", ""])
    if not excluded and not unknown:
        lines.append("該当なし。")
    for row in excluded + unknown:
        reason = row.error or " / ".join(row.flags) or row.candidate_status
        lines.append(f"- {row.code.replace('.T', '')} {row.name}: {row.candidate_status}。{reason}")
    lines.extend(["", "## テストケース", "", "2702と3563は妥当性確認用であり、同一式で採点した。", ""])
    lines.append("| コード | 総合点 | 3年リターン | 3年DD | PEG | タイミング |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for code in TEST_CASES:
        row = next((item for item in rows if item.code == code), None)
        if row is None or row.chart is None:
            lines.append(f"| {code.replace('.T', '')} | 未確認 | 未確認 | 未確認 | 未確認 | 未確認 |")
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    code.replace(".T", ""),
                    _points(row.total, row.total_max),
                    _pct(row.chart.ret_3y, signed=True),
                    _pct(row.chart.mdd_3y),
                    _peg(row),
                    row.chart.timing_label,
                ]
            )
            + " |"
        )
    lines.extend(["", "## 個別", ""])
    for row in detail_rows:
        lines.append(_detail_block(row))
    lines.append(_forward_md(forward))
    lines.extend(
        [
            "## まだやっていないこと",
            "",
            "- 東証全普通株の日足取得と全市場ランキング",
            "- 2〜3年の予想EPSに基づく予想PEG（今回の過去PEGとは別）",
            "- 当時公表されていた財務を使う戦略B・C・Dのバックテスト",
            "- 売買代金を使った約定シミュレーションとポートフォリオの最大ドローダウン",
            "",
        ]
    )
    (out / "ranking.md").write_text("\n".join(lines), encoding="utf-8")
