"""採用ルールでスクリーニング母集団をランキングし、公開用 JSON を書く。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.config import data_dir
from signalforge.research.trend_screen.config import (
    MA200_SLOPE_LAG,
    MA75_SLOPE_LAG,
    RET_1Y_STEPS,
    RET_3Y_STEPS,
)
from signalforge.research.trend_screen.duke_fundamentals import (
    FUND_GATE_KEYS,
    FUND_GATE_LABELS,
    evaluate_duke_fundamentals,
)
from signalforge.research.trend_screen.horse import _clean, _load_bars, _load_funds
from signalforge.research.trend_screen.improve import _stats_at
from signalforge.research.trend_screen.ruleset import SystemRules, load_adopted, rules_markdown
from signalforge.research.trend_screen.system import (
    _signal_coverage,
    latest_asof_day,
    latest_signal_day,
)
from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list

GATE_LABELS = {
    "primary": "一次条件（長期トレンド）",
    "no_bar": "シグナル日の日足なし",
    "above_ma200": "終値>200日線",
    "ma200_up": "200日線上向き",
    "ma75_up": "75日線上向き",
    "ret_1y_pos": "1年リターン>0",
    "ret_3y_pos": "3年リターン>0",
    "excess_1y": "1年でTOPIX超え",
    "turnover": "売買代金下限",
    "ret_20d": "直近20日下落なし",
    "above_ma25": "終値>25日線",
    "dd_52w": "52週高値からの下落上限",
    # DUKE。図23 第2ステージ + 新高値ブレイク
    "duke_above_sma150_200": "終値>SMA150&200",
    "duke_sma150_gt_200": "SMA150>SMA200",
    "duke_sma200_up": "SMA200上昇（約1カ月）",
    "duke_sma50_stack": "SMA50>SMA150&200",
    "duke_off_52w_low": "52週安値+25%以上",
    "duke_near_52w_high": "52週高値の25%以内",
    "duke_above_sma50": "終値≧SMA50−10%",
    "duke_rs_pos": "対市場RS（6週）プラス",
    "duke_volume_surge": "出来高比率≧1.5",
    "duke_fresh_break": "新高値ブレイク（当日）",
    **FUND_GATE_LABELS,
}

# サイト上でON/OFFできる条件（採用ルールの部品）
LAB_GATE_KEYS = (
    "above_ma200",
    "ma200_up",
    "ma75_up",
    "ret_1y_pos",
    "ret_3y_pos",
    "excess_1y",
    "turnover",
    "ret_20d",
    "above_ma25",
    "dd_52w",
    "duke_above_sma150_200",
    "duke_sma150_gt_200",
    "duke_sma200_up",
    "duke_sma50_stack",
    "duke_off_52w_low",
    "duke_near_52w_high",
    "duke_above_sma50",
    "duke_rs_pos",
    "duke_volume_surge",
    "duke_fresh_break",
    *FUND_GATE_KEYS,
)

TREND_LAB_GATE_KEYS = (
    "above_ma200",
    "ma200_up",
    "ma75_up",
    "ret_1y_pos",
    "ret_3y_pos",
    "excess_1y",
    "turnover",
    "ret_20d",
    "above_ma25",
    "dd_52w",
)

DUKE_LAB_GATE_KEYS = (
    "duke_above_sma150_200",
    "duke_sma150_gt_200",
    "duke_sma200_up",
    "duke_sma50_stack",
    "duke_off_52w_low",
    "duke_near_52w_high",
    "duke_above_sma50",
    "duke_rs_pos",
    "duke_volume_surge",
    "duke_fresh_break",
    *FUND_GATE_KEYS,
)


def published_ranking_path() -> Path:
    return data_dir() / "published" / "trend_screen_ranking.json"


def _listing_maps() -> tuple[dict[str, dict], dict[str, str]]:
    from signalforge.universe.tse_listing import listing_by_ticker

    try:
        listing = listing_by_ticker()
    except Exception:
        return {}, {}
    sectors = {str(sym): str(row.get("sector_tse") or "未確認") for sym, row in listing.items()}
    return listing, sectors


def _passes_extra(rules: SystemRules, stats: dict[str, float | None]) -> tuple[bool, list[str]]:
    fails: list[str] = []
    if rules.min_turnover is not None:
        turn = stats.get("turnover_20d")
        if turn is None or turn < rules.min_turnover:
            fails.append("turnover")
    if rules.min_ret_20d is not None:
        ret20 = stats.get("ret_20d")
        if ret20 is None or ret20 <= rules.min_ret_20d:
            fails.append("ret_20d")
    if rules.require_above_ma25:
        vs25 = stats.get("vs_ma25")
        if vs25 is None or vs25 <= 0:
            fails.append("above_ma25")
    if rules.max_dd_52w is not None:
        dd52 = stats.get("dd_52w")
        if dd52 is None or dd52 < rules.max_dd_52w:
            fails.append("dd_52w")
    return not fails, fails


def _empty_snap(*, had_bar: bool = False) -> dict[str, Any]:
    return {
        "had_bar": had_bar,
        "price": None,
        "ret_1y": None,
        "ret_3y": None,
        "excess_1y": None,
        "ret_20d": None,
        "ret_60d": None,
        "vs_ma25": None,
        "dd_52w": None,
        "mdd_1y": None,
        "up_month_ratio": None,
        "trend_r2": None,
        "steady_score": None,
        "vol_1y": None,
        "risk_adj_1y": None,
        "turnover_20d": None,
        "volume_ratio_20": None,
        "market_rs_30d": None,
        "pct_above_52w_low": None,
        "pct_of_52w_high": None,
        "duke_score": None,
        "fund_sales_yoy": None,
        "fund_op_yoy": None,
        "fund_op_margin": None,
        "target_price_fund": None,
        "upside_pct": None,
        "stop_price": None,
        "t1_price": None,
        "t2_price": None,
        "t3_price": None,
        "gates": {k: False for k in LAB_GATE_KEYS},
    }


def _duke_gate_snapshot(
    px: pd.Series,
    volume: pd.Series | None,
    bench: pd.Series,
    loc: int,
    price: float,
) -> dict[str, Any]:
    """DUKE。図23 + 新高値ブレイク用ゲート（終値系列で近似）。"""
    out: dict[str, Any] = {
        "volume_ratio_20": None,
        "market_rs_30d": None,
        "pct_above_52w_low": None,
        "pct_of_52w_high": None,
        "duke_score": None,
        "gates": {k: False for k in DUKE_LAB_GATE_KEYS},
    }
    if loc < 200:
        return out

    sma50 = px.rolling(50, min_periods=50).mean()
    sma150 = px.rolling(150, min_periods=150).mean()
    sma200 = px.rolling(200, min_periods=200).mean()
    s50 = float(sma50.iloc[loc]) if pd.notna(sma50.iloc[loc]) else None
    s150 = float(sma150.iloc[loc]) if pd.notna(sma150.iloc[loc]) else None
    s200 = float(sma200.iloc[loc]) if pd.notna(sma200.iloc[loc]) else None
    s200_prev = None
    if loc >= 21 and pd.notna(sma200.iloc[loc - 21]):
        s200_prev = float(sma200.iloc[loc - 21])

    lookback = 252
    window = px.iloc[max(0, loc - lookback + 1) : loc + 1]
    low_52 = float(window.min()) if len(window) else None
    high_52 = float(window.max()) if len(window) else None
    prior_high = float(px.iloc[max(0, loc - lookback) : loc].max()) if loc > 0 else None

    pct_off_low = None
    pct_of_high = None
    if low_52 and low_52 > 0:
        pct_off_low = price / low_52 - 1.0
    if high_52 and high_52 > 0:
        pct_of_high = price / high_52

    vol_ratio = None
    if volume is not None:
        vol = _clean(volume).reindex(px.index)
        if loc < len(vol) and pd.notna(vol.iloc[loc]):
            vma = vol.rolling(20, min_periods=10).mean()
            if pd.notna(vma.iloc[loc]) and float(vma.iloc[loc]) > 0:
                vol_ratio = float(vol.iloc[loc]) / float(vma.iloc[loc])

    market_rs = None
    if loc >= 30:
        bpx = _clean(bench).reindex(px.index)
        stock_sum = float(px.pct_change().iloc[loc - 29 : loc + 1].sum())
        if loc < len(bpx) and bpx.iloc[loc - 29 : loc + 1].notna().sum() >= 20:
            bench_sum = float(bpx.pct_change().iloc[loc - 29 : loc + 1].sum())
            market_rs = (stock_sum - bench_sum) * 100.0

    gates = {
        "duke_above_sma150_200": bool(s150 is not None and s200 is not None and price > s150 and price > s200),
        "duke_sma150_gt_200": bool(s150 is not None and s200 is not None and s150 > s200),
        "duke_sma200_up": bool(s200 is not None and s200_prev is not None and s200 > s200_prev),
        "duke_sma50_stack": bool(
            s50 is not None and s150 is not None and s200 is not None and s50 > s150 and s50 > s200
        ),
        "duke_off_52w_low": bool(pct_off_low is not None and pct_off_low >= 0.25),
        "duke_near_52w_high": bool(pct_of_high is not None and pct_of_high >= 0.75),
        "duke_above_sma50": bool(s50 is not None and price >= s50 * 0.90),
        "duke_rs_pos": bool(market_rs is not None and market_rs > 0),
        "duke_volume_surge": bool(vol_ratio is not None and vol_ratio >= 1.5),
        "duke_fresh_break": bool(prior_high is not None and price > prior_high),
    }

    # 並び用: 高値接近度 + RS + 出来高（いずれも正規化して合成）
    score_parts: list[float] = []
    if pct_of_high is not None:
        score_parts.append(max(0.0, min(1.0, (pct_of_high - 0.75) / 0.25)) * 40.0)
    if market_rs is not None:
        score_parts.append(max(0.0, min(40.0, market_rs * 2.0)))
    if vol_ratio is not None:
        score_parts.append(max(0.0, min(20.0, (vol_ratio - 1.0) * 10.0)))
    duke_score = round(sum(score_parts), 1) if score_parts else None

    out.update(
        {
            "volume_ratio_20": vol_ratio,
            "market_rs_30d": market_rs,
            "pct_above_52w_low": pct_off_low,
            "pct_of_52w_high": pct_of_high,
            "duke_score": duke_score,
            "gates": gates,
        }
    )
    return out


def _steady_metrics(window: pd.Series) -> dict[str, float | None]:
    """じわじわ上昇の参考指標。急騰後の失速銘柄を見分けやすくする。"""
    from signalforge.research.trend_screen.chart import max_drawdown

    out: dict[str, float | None] = {
        "mdd_1y": None,
        "up_month_ratio": None,
        "trend_r2": None,
        "steady_score": None,
    }
    if len(window) < 40:
        return out
    out["mdd_1y"] = max_drawdown(window)
    monthly = window.resample("ME").last().dropna()
    changes = monthly.pct_change().dropna()
    if len(changes) >= 6:
        out["up_month_ratio"] = float((changes > 0).mean())
    # log価格の時間回帰 R²（1に近いほど直線的な上昇/下落）
    import math

    y = window.apply(lambda v: math.log(float(v)) if float(v) > 0 else float("nan")).dropna()
    if len(y) >= 40:
        x = pd.Series(range(len(y)), index=y.index, dtype=float)
        x_mean = float(x.mean())
        y_mean = float(y.mean())
        var_x = float(((x - x_mean) ** 2).sum())
        if var_x > 0:
            cov = float(((x - x_mean) * (y - y_mean)).sum())
            slope = cov / var_x
            intercept = y_mean - slope * x_mean
            fitted = intercept + slope * x
            ss_res = float(((y - fitted) ** 2).sum())
            ss_tot = float(((y - y_mean) ** 2).sum())
            if ss_tot > 0:
                out["trend_r2"] = max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
                # 上昇トレンドでない直線は安定上昇とみなさない
                if slope <= 0:
                    out["trend_r2"] = float(out["trend_r2"]) * 0.25

    up_m = out["up_month_ratio"]
    r2 = out["trend_r2"]
    mdd = out["mdd_1y"]
    rets = window.pct_change().dropna()
    vol = float(rets.std(ddof=1) * (245**0.5)) if len(rets) >= 20 else None
    parts: list[float] = []
    weights: list[float] = []
    if up_m is not None:
        parts.append(up_m)
        weights.append(0.30)
    if r2 is not None:
        parts.append(r2)
        weights.append(0.25)
    if mdd is not None:
        # -40%超の経路DDで0点
        parts.append(max(0.0, 1.0 - min(1.0, abs(mdd) / 0.40)))
        weights.append(0.25)
    if vol is not None:
        # 年率15%までは減点なし、60%で0
        parts.append(max(0.0, 1.0 - min(1.0, max(0.0, vol - 0.15) / 0.45)))
        weights.append(0.20)
    if parts and sum(weights) > 0:
        score = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
        out["steady_score"] = round(100.0 * score, 1)
    return out


def _gate_snapshot(
    close: pd.Series,
    volume: pd.Series | None,
    bench: pd.Series,
    signal: pd.Timestamp,
) -> dict[str, Any]:
    """サイトで条件を付け替えられるよう、銘柄×シグナル日の生メトリクスと可否を返す。"""
    px = _clean(close)
    if signal not in px.index:
        return _empty_snap(had_bar=False)
    loc = px.index.get_loc(signal)
    if not isinstance(loc, int):
        return _empty_snap(had_bar=False)
    price = float(px.iloc[loc])
    ma75 = px.rolling(75, min_periods=75).mean()
    ma200 = px.rolling(200, min_periods=200).mean()
    m200 = float(ma200.iloc[loc]) if pd.notna(ma200.iloc[loc]) else None
    m75 = float(ma75.iloc[loc]) if pd.notna(ma75.iloc[loc]) else None
    m200_prev = None
    m75_prev = None
    if loc >= MA200_SLOPE_LAG and pd.notna(ma200.iloc[loc - MA200_SLOPE_LAG]):
        m200_prev = float(ma200.iloc[loc - MA200_SLOPE_LAG])
    if loc >= MA75_SLOPE_LAG and pd.notna(ma75.iloc[loc - MA75_SLOPE_LAG]):
        m75_prev = float(ma75.iloc[loc - MA75_SLOPE_LAG])

    ret_1y = None
    ret_3y = None
    ret_60d = None
    if loc >= RET_1Y_STEPS:
        start = float(px.iloc[loc - RET_1Y_STEPS])
        if start > 0:
            ret_1y = price / start - 1.0
    if loc >= RET_3Y_STEPS:
        start = float(px.iloc[loc - RET_3Y_STEPS])
        if start > 0:
            ret_3y = price / start - 1.0
    if loc >= 60:
        start = float(px.iloc[loc - 60])
        if start > 0:
            ret_60d = price / start - 1.0

    bpx = _clean(bench).reindex(px.index)
    excess_1y = None
    if loc >= RET_1Y_STEPS and pd.notna(bpx.iloc[loc]) and pd.notna(bpx.iloc[loc - RET_1Y_STEPS]):
        bs = float(bpx.iloc[loc - RET_1Y_STEPS])
        be = float(bpx.iloc[loc])
        if bs > 0 and ret_1y is not None:
            excess_1y = ret_1y - (be / bs - 1.0)

    stats = _stats_at(close, volume, signal)
    steady = _steady_metrics(px.iloc[max(0, loc - RET_1Y_STEPS) : loc + 1])
    duke = _duke_gate_snapshot(px, volume, bench, loc, price)
    gates = {
        "above_ma200": bool(m200 is not None and price > m200),
        "ma200_up": bool(m200 is not None and m200_prev is not None and m200 > m200_prev),
        "ma75_up": bool(m75 is not None and m75_prev is not None and m75 > m75_prev),
        "ret_1y_pos": bool(ret_1y is not None and ret_1y > 0),
        "ret_3y_pos": bool(ret_3y is not None and ret_3y > 0),
        "excess_1y": bool(excess_1y is not None and excess_1y > 0),
        "turnover": bool(stats.get("turnover_20d") is not None),
        "ret_20d": bool(stats.get("ret_20d") is not None and float(stats["ret_20d"]) > 0),
        "above_ma25": bool(stats.get("vs_ma25") is not None and float(stats["vs_ma25"]) > 0),
        "dd_52w": bool(stats.get("dd_52w") is not None),
        **duke["gates"],
    }
    return {
        "had_bar": True,
        "price": price,
        "ret_1y": ret_1y if ret_1y is not None else stats.get("ret_1y"),
        "ret_3y": ret_3y,
        "excess_1y": excess_1y,
        "ret_20d": stats.get("ret_20d"),
        "ret_60d": ret_60d,
        "vs_ma25": stats.get("vs_ma25"),
        "dd_52w": stats.get("dd_52w"),
        "mdd_1y": steady["mdd_1y"],
        "up_month_ratio": steady["up_month_ratio"],
        "trend_r2": steady["trend_r2"],
        "steady_score": steady["steady_score"],
        "vol_1y": stats.get("vol_1y"),
        "risk_adj_1y": stats.get("risk_adj_1y"),
        "turnover_20d": stats.get("turnover_20d"),
        "volume_ratio_20": duke.get("volume_ratio_20"),
        "market_rs_30d": duke.get("market_rs_30d"),
        "pct_above_52w_low": duke.get("pct_above_52w_low"),
        "pct_of_52w_high": duke.get("pct_of_52w_high"),
        "duke_score": duke.get("duke_score"),
        "gates": gates,
    }


def build_ranking(
    *,
    limit: int | None = None,
    refresh_universe: bool = True,
    as_of_mode: str = "latest",
) -> dict[str, Any]:
    """スクリーニング順位を作る。

    as_of_mode:
      - latest: 日足が揃う最新営業日（サイト表示・毎日更新向け）
      - month_end: 完了した月末（リバランス判定と同じ）
    """
    rules = load_adopted()
    limit = limit or rules.universe_limit
    if refresh_universe:
        write_liquid_list(limit)
    names = read_liquid_list(limit)
    closes, volumes, bench = _load_bars(names)
    bench = _clean(bench)
    rebalance_signal = latest_signal_day(bench)
    if as_of_mode == "month_end":
        signal = rebalance_signal
    else:
        signal = latest_asof_day(closes)
    n_on_signal, coverage_ok, warning = _signal_coverage(closes, signal)
    listing, sectors = _listing_maps()
    fund_map = _load_funds(sorted(closes), fetch_missing=False)

    from signalforge.research.trend_screen.corporate_events import (
        event_fields_for,
        load_yutai_map,
    )

    try:
        yutai_map = load_yutai_map()
    except Exception:
        yutai_map = {}
    as_of_s = signal.date().isoformat()

    rows: list[dict[str, Any]] = []
    for code, series in closes.items():
        snap = _gate_snapshot(series, volumes.get(code), bench, signal)
        stats = {
            "ret_1y": snap["ret_1y"],
            "vol_1y": snap["vol_1y"],
            "risk_adj_1y": snap["risk_adj_1y"],
            "turnover_20d": snap["turnover_20d"],
            "ret_20d": snap["ret_20d"],
            "vs_ma25": snap["vs_ma25"],
            "dd_52w": snap["dd_52w"],
        }
        gates = dict(snap["gates"])
        # 売買代金・52週DDは採用ルールの閾値込みで再評価（ラボ用の生値も残す）
        if rules.min_turnover is not None:
            turn = stats.get("turnover_20d")
            gates["turnover"] = bool(turn is not None and turn >= rules.min_turnover)
        else:
            # 流動性ゲートなしでも、ラボでONにできるよう値が取れれば True
            gates["turnover"] = stats.get("turnover_20d") is not None
        if rules.max_dd_52w is not None:
            dd52 = stats.get("dd_52w")
            gates["dd_52w"] = bool(dd52 is not None and dd52 >= rules.max_dd_52w)
        elif stats.get("dd_52w") is not None:
            gates["dd_52w"] = True

        box_height = None
        px_series = _clean(series)
        if snap.get("had_bar") and snap.get("price") is not None and signal in px_series.index:
            loc = px_series.index.get_loc(signal)
            if isinstance(loc, int) and loc >= 60:
                window = px_series.iloc[loc - 60 : loc]
                if len(window) >= 20:
                    box_height = float(window.max() - window.min())
        fund = evaluate_duke_fundamentals(
            fund_map.get(code),
            price=snap.get("price"),
            box_height=box_height,
        )
        gates.update(fund.gates)

        primary_keys = ("above_ma200", "ma200_up", "ma75_up", "ret_1y_pos", "ret_3y_pos", "excess_1y")
        mask_ok = bool(snap["had_bar"] and all(gates[k] for k in primary_keys))
        extra_ok, extra_fails = _passes_extra(rules, stats)
        passed = bool(mask_ok and extra_ok and stats.get("ret_1y") is not None)
        fails = [k for k in primary_keys if not gates.get(k)] + extra_fails
        if not snap["had_bar"]:
            fails = ["no_bar"]
        sym = code.replace(".T", "")
        meta = listing.get(code) or listing.get(sym) or {}
        rows.append(
            {
                "ticker": code,
                "code": sym,
                "name": str(meta.get("name") or ""),
                "sector": sectors.get(code) or sectors.get(sym) or str(meta.get("sector_tse") or ""),
                "market": str(meta.get("market") or meta.get("segment") or ""),
                "passed": passed,
                "fails": fails,
                "fail_labels": [GATE_LABELS.get(f, f) for f in fails],
                "price": snap["price"],
                "ret_1y": stats.get("ret_1y"),
                "ret_3y": snap.get("ret_3y"),
                "excess_1y": snap.get("excess_1y"),
                "ret_20d": stats.get("ret_20d"),
                "ret_60d": snap.get("ret_60d"),
                "dd_52w": stats.get("dd_52w"),
                "mdd_1y": snap.get("mdd_1y"),
                "up_month_ratio": snap.get("up_month_ratio"),
                "trend_r2": snap.get("trend_r2"),
                "steady_score": snap.get("steady_score"),
                "vs_ma25": stats.get("vs_ma25"),
                "vol_1y": stats.get("vol_1y"),
                "risk_adj_1y": stats.get("risk_adj_1y"),
                "turnover_20d": stats.get("turnover_20d"),
                "volume_ratio_20": snap.get("volume_ratio_20"),
                "market_rs_30d": snap.get("market_rs_30d"),
                "pct_above_52w_low": snap.get("pct_above_52w_low"),
                "pct_of_52w_high": snap.get("pct_of_52w_high"),
                "duke_score": snap.get("duke_score"),
                "box_height": box_height,
                **fund.to_row_fields(),
                "gates": gates,
                "midplan_kpi_hint": None,
                "midplan_human_todos": None,
            }
        )

    from signalforge.research.trend_screen.midplan_card import sector_hints

    # 配当は既存キャッシュのみ使う（ランキング中の yfinance 一括取得は重い／弾かれやすい）
    for row in rows:
        row.update(event_fields_for(row["ticker"], as_of=as_of_s, yutai_map=yutai_map))
        hints = sector_hints(str(row.get("sector") or ""))
        row["midplan_kpi_hint"] = hints["kpi"]
        row["midplan_revenue_mix_hint"] = hints["revenue_mix"]
        row["midplan_market_hint"] = hints["market"]

    passers = [r for r in rows if r["passed"]]
    passers.sort(key=lambda r: (-(r["ret_1y"] or -1e9), r["code"]))
    for i, row in enumerate(passers, start=1):
        row["rank"] = i
        row["target"] = i <= int(rules.top_n)

    others = [r for r in rows if not r["passed"]]
    others.sort(
        key=lambda r: (
            0 if r["fails"] == ["primary"] else 1,
            len(r["fails"]),
            -(r["ret_1y"] if r["ret_1y"] is not None else -1e9),
            r["code"],
        )
    )
    for row in others:
        row["rank"] = None
        row["target"] = False

    targets = [
        {
            "rank": r["rank"],
            "ticker": r["ticker"],
            "code": r["code"],
            "name": r["name"],
            "weight": 1.0 / min(rules.top_n, len(passers)) if passers else 0.0,
            "ret_1y": r["ret_1y"],
            "ret_20d": r["ret_20d"],
            "price": r["price"],
            "yahoo_jp_url": r.get("yahoo_jp_url"),
            "earnings_last": r.get("earnings_last"),
            "earnings_next": r.get("earnings_next"),
            "dividend_yield": r.get("dividend_yield"),
            "ex_dividend_date": r.get("ex_dividend_date"),
            "yutai": r.get("yutai"),
            "yutai_months": r.get("yutai_months"),
            "yutai_type": r.get("yutai_type"),
            "yutai_url": r.get("yutai_url"),
        }
        for r in passers[: rules.top_n]
    ]

    trend_gates = {
        "above_ma200": True,
        "ma200_up": True,
        "ma75_up": True,
        "ret_1y_pos": True,
        "ret_3y_pos": True,
        "excess_1y": True,
        "turnover": rules.min_turnover is not None,
        "ret_20d": rules.min_ret_20d is not None,
        "above_ma25": bool(rules.require_above_ma25),
        "dd_52w": rules.max_dd_52w is not None,
        **{k: False for k in DUKE_LAB_GATE_KEYS},
    }
    # スクリーニング用: 図23第2ステージ＋ファンダ（売上/営利/利益率）。出来高/当日ブレイク/目標上振れは任意
    duke_gates = {
        **{k: False for k in TREND_LAB_GATE_KEYS},
        **{k: True for k in DUKE_LAB_GATE_KEYS},
        "duke_volume_surge": False,
        "duke_fresh_break": False,
        "fund_upside_pos": False,
        "turnover": False,
        "ret_20d": False,
        "above_ma25": False,
        "dd_52w": False,
    }
    # トレンド採用プリセットではファンダ条件はOFF
    for k in FUND_GATE_KEYS:
        trend_gates[k] = False
    lab_defaults = {
        "gates": dict(trend_gates),
        "active_preset": "trend",
        "presets": {
            "trend": {
                "label": "長期トレンド（採用）",
                "gates": trend_gates,
                "rank_by": rules.rank_by or "ret_1y",
                "top_n": int(rules.top_n),
                "min_steady_score": 0.0,
                "min_up_month_ratio": 0.0,
                "max_mdd_1y": -1.0,
                "min_trend_r2": 0.0,
            },
            "duke": {
                "label": "DUKE新高値ブレイク",
                "gates": duke_gates,
                "rank_by": "duke_score",
                "top_n": 10,
                "min_steady_score": 0.0,
                "min_up_month_ratio": 0.0,
                "max_mdd_1y": -1.0,
                "min_trend_r2": 0.0,
            },
        },
        "min_turnover": float(rules.min_turnover or 0.0),
        "min_ret_20d": float(rules.min_ret_20d if rules.min_ret_20d is not None else 0.0),
        "max_dd_52w": float(rules.max_dd_52w) if rules.max_dd_52w is not None else -1.0,
        # 安定上昇の参考フィルタ（初期は緩め＝オフ相当）
        "min_steady_score": 0.0,
        "min_up_month_ratio": 0.0,
        "max_mdd_1y": -1.0,
        "min_trend_r2": 0.0,
        "top_n": int(rules.top_n),
        "rank_by": rules.rank_by or "ret_1y",
    }
    payload: dict[str, Any] = {
        "system_id": rules.id,
        "version": rules.version,
        "name": rules.name,
        "as_of_mode": as_of_mode if as_of_mode in {"latest", "month_end"} else "latest",
        "as_of": signal.date().isoformat(),
        # 互換: 旧キー。サイトでは as_of を基準日として使う
        "signal_date": signal.date().isoformat(),
        "rebalance_signal_date": rebalance_signal.date().isoformat(),
        "benchmark": rules.benchmark,
        "universe_limit": limit,
        "n_universe": len(closes),
        "n_on_signal": n_on_signal,
        "n_pass": len(passers),
        "n_target": len(targets),
        "n_fund_ready": sum(1 for r in rows if (r.get("gates") or {}).get("fund_data")),
        "coverage_ok": coverage_ok,
        "warning": warning,
        "note": (
            "基準日は最新営業日の終値。採用シストレのリバランス判定は月末"
            f"（次回シグナル候補: {rebalance_signal.date().isoformat()}）。"
            if as_of_mode != "month_end"
            else "基準日は完了した月末シグナル。"
        ),
        "top_n": rules.top_n,
        "rank_by": rules.rank_by,
        "min_turnover": rules.min_turnover,
        "min_ret_20d": rules.min_ret_20d,
        "require_above_ma25": rules.require_above_ma25,
        "max_dd_52w": rules.max_dd_52w,
        "lab_defaults": lab_defaults,
        "gate_labels": {k: GATE_LABELS[k] for k in LAB_GATE_KEYS},
        "rules_markdown": rules_markdown(rules),
        "targets": targets,
        "ranking": passers,
        "rejected": others,
        # サイトの条件ラボ用（全銘柄・ゲート付き）
        "universe": rows,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    return payload


def save_ranking(payload: dict[str, Any], path: Path | None = None) -> Path:
    path = path or published_ranking_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_ranking(path: Path | None = None) -> dict[str, Any] | None:
    path = path or published_ranking_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def build_and_publish(*, limit: int | None = None) -> tuple[dict[str, Any], Path]:
    payload = build_ranking(limit=limit)
    path = save_ranking(payload)
    return payload, path
