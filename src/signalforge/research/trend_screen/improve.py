"""採用シストレを土台に、改善案を学習期間だけで選ぶ。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from signalforge.research.trend_screen.config import LIQUIDITY_YEN, RET_1Y_STEPS, ROUND_TRIP_COST
from signalforge.research.trend_screen.frequency import _window_freq, build_masks, monthly_signals, ready_date
from signalforge.research.trend_screen.horse import (
    TEST_START,
    TRAIN_END,
    MonthRow,
    VariantResult,
    _clean,
    _pct,
    _price,
    is_confirmed,
)
from signalforge.research.trend_screen.ruleset import DEFAULT_SYSTEM_ID


@dataclass(frozen=True)
class ImproveSpec:
    id: str
    title: str
    summary: str
    top_n: int
    rank_by: str  # ret_1y | risk_adj_1y
    weight: str  # equal | inv_vol
    sector_max: int | None
    min_turnover: float | None
    min_ret_20d: float | None = None
    require_above_ma25: bool = False
    max_dd_52w: float | None = None


def catalog() -> tuple[ImproveSpec, ...]:
    """成績を見る前に固定した案。ベースは一次条件＋月末判定。"""
    base = "一次条件＋月末判定は共通。"
    liquid = float(LIQUIDITY_YEN)
    return (
        ImproveSpec(
            "base_top5_equal",
            "現行・上位5等金額",
            base + " 1年リターン上位5を等金額。",
            5,
            "ret_1y",
            "equal",
            None,
            None,
        ),
        ImproveSpec(
            "top5_liquid",
            "上位5・売買代金下限",
            base + f" 20日売買代金が{LIQUIDITY_YEN:,.0f}円以上だけを候補にし、1年リターン上位5。",
            5,
            "ret_1y",
            "equal",
            None,
            liquid,
        ),
        ImproveSpec(
            "top5_liquid_ret20",
            "上位5・直近20日下落なし",
            base + f" 売買代金≥{LIQUIDITY_YEN:,.0f}円、過去20営業日リターン>0、1年リターン上位5。",
            5,
            "ret_1y",
            "equal",
            None,
            liquid,
            min_ret_20d=0.0,
        ),
        ImproveSpec(
            "top5_liquid_ma25",
            "上位5・25日線より上",
            base + f" 売買代金≥{LIQUIDITY_YEN:,.0f}円、終値>25日線、1年リターン上位5。",
            5,
            "ret_1y",
            "equal",
            None,
            liquid,
            require_above_ma25=True,
        ),
        ImproveSpec(
            "top5_liquid_dd15",
            "上位5・52週高値から15%以内",
            base + f" 売買代金≥{LIQUIDITY_YEN:,.0f}円、52週高値からの下落が15%以内、1年リターン上位5。",
            5,
            "ret_1y",
            "equal",
            None,
            liquid,
            max_dd_52w=-0.15,
        ),
        ImproveSpec(
            "top5_liquid_fresh",
            "上位5・直近モメンタム",
            base
            + f" 売買代金≥{LIQUIDITY_YEN:,.0f}円、20日リターン>0かつ終値>25日線、1年リターン上位5。",
            5,
            "ret_1y",
            "equal",
            None,
            liquid,
            min_ret_20d=0.0,
            require_above_ma25=True,
        ),
        ImproveSpec(
            "top5_liquid_big",
            "上位5・売買代金5億以上",
            base + " 20日売買代金が5億円以上だけを候補にし、1年リターン上位5。",
            5,
            "ret_1y",
            "equal",
            None,
            500_000_000.0,
        ),
        ImproveSpec(
            "top5_sector2",
            "上位5・業種上限2",
            base + " 1年リターン順に取り、同一33業種は最大2。目標5銘柄。",
            5,
            "ret_1y",
            "equal",
            2,
            None,
        ),
        ImproveSpec(
            "top5_inv_vol",
            "上位5・ボラ逆数",
            base + " 1年リターン上位5を、1年ボラの逆数で配分。",
            5,
            "ret_1y",
            "inv_vol",
            None,
            None,
        ),
        ImproveSpec(
            "top5_risk_adj",
            "リスク調整リターン上位5",
            base + " 1年リターン÷1年ボラの上位5を等金額。",
            5,
            "risk_adj_1y",
            "equal",
            None,
            None,
        ),
    )


def _stats_at(close: pd.Series, volume: pd.Series | None, day: pd.Timestamp) -> dict[str, float | None]:
    empty = {
        "ret_1y": None,
        "vol_1y": None,
        "risk_adj_1y": None,
        "turnover_20d": None,
        "ret_20d": None,
        "vs_ma25": None,
        "dd_52w": None,
    }
    px = _clean(close)
    if day not in px.index:
        return empty
    loc = px.index.get_loc(day)
    if not isinstance(loc, int):
        return empty
    price = float(px.iloc[loc])
    ret_1y = None
    vol_1y = None
    dd_52w = None
    if loc >= RET_1Y_STEPS:
        start = float(px.iloc[loc - RET_1Y_STEPS])
        if start > 0:
            ret_1y = price / start - 1.0
        rets = px.iloc[loc - RET_1Y_STEPS : loc + 1].pct_change().dropna()
        if len(rets) >= 20:
            vol_1y = float(rets.std(ddof=1) * (245 ** 0.5))
        hi = float(px.iloc[loc - RET_1Y_STEPS : loc + 1].max())
        if hi > 0:
            dd_52w = price / hi - 1.0
    risk = None
    if ret_1y is not None and vol_1y is not None and vol_1y > 1e-6:
        risk = ret_1y / vol_1y
    ret_20d = None
    if loc >= 20:
        start20 = float(px.iloc[loc - 20])
        if start20 > 0:
            ret_20d = price / start20 - 1.0
    vs_ma25 = None
    if loc >= 24:
        ma25 = float(px.iloc[loc - 24 : loc + 1].mean())
        if ma25 > 0:
            vs_ma25 = price / ma25 - 1.0
    turnover = None
    if volume is not None:
        vol = _clean(volume).reindex(px.index)
        traded = (px * vol).dropna()
        if day in traded.index:
            tloc = traded.index.get_loc(day)
            if isinstance(tloc, int) and tloc >= 19:
                turnover = float(traded.iloc[tloc - 19 : tloc + 1].mean())
    return {
        "ret_1y": ret_1y,
        "vol_1y": vol_1y,
        "risk_adj_1y": risk,
        "turnover_20d": turnover,
        "ret_20d": ret_20d,
        "vs_ma25": vs_ma25,
        "dd_52w": dd_52w,
    }


def _sector_map() -> dict[str, str]:
    from signalforge.universe.tse_listing import listing_by_ticker

    try:
        listing = listing_by_ticker()
    except Exception:
        return {}
    return {str(sym): str(row.get("sector_tse") or "未確認") for sym, row in listing.items()}


def _rank_key(spec: ImproveSpec, stats: dict[str, float | None]) -> float | None:
    if spec.rank_by == "ret_1y":
        return stats["ret_1y"]
    if spec.rank_by == "risk_adj_1y":
        return stats["risk_adj_1y"]
    return None


def select_names(
    spec: ImproveSpec,
    day: pd.Timestamp,
    masks: dict[str, pd.Series],
    closes: dict[str, pd.Series],
    volumes: dict[str, pd.Series],
    sectors: dict[str, str],
) -> list[str]:
    scored: list[tuple[float, str, dict[str, float | None]]] = []
    for code, mask in masks.items():
        if day not in mask.index or not bool(mask.loc[day]):
            continue
        stats = _stats_at(closes[code], volumes.get(code), day)
        if spec.min_turnover is not None:
            turn = stats["turnover_20d"]
            if turn is None or turn < spec.min_turnover:
                continue
        if spec.min_ret_20d is not None:
            ret20 = stats["ret_20d"]
            if ret20 is None or ret20 <= spec.min_ret_20d:
                continue
        if spec.require_above_ma25:
            vs25 = stats["vs_ma25"]
            if vs25 is None or vs25 <= 0:
                continue
        if spec.max_dd_52w is not None:
            dd52 = stats["dd_52w"]
            if dd52 is None or dd52 < spec.max_dd_52w:
                continue
        score = _rank_key(spec, stats)
        if score is None:
            continue
        if spec.weight == "inv_vol" and (stats["vol_1y"] is None or stats["vol_1y"] <= 0):
            continue
        scored.append((score, code, stats))
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[str] = []
    sector_count: dict[str, int] = {}
    for _score, code, _stats in scored:
        if len(chosen) >= spec.top_n:
            break
        if spec.sector_max is not None:
            sector = sectors.get(code) or "未確認"
            if sector_count.get(sector, 0) >= spec.sector_max:
                continue
            sector_count[sector] = sector_count.get(sector, 0) + 1
        chosen.append(code)
    return chosen


def _weights(
    spec: ImproveSpec,
    codes: list[str],
    day: pd.Timestamp,
    closes: dict[str, pd.Series],
    volumes: dict[str, pd.Series],
) -> dict[str, float]:
    if not codes:
        return {}
    if spec.weight == "equal":
        w = 1.0 / len(codes)
        return {code: w for code in codes}
    inv: dict[str, float] = {}
    for code in codes:
        stats = _stats_at(closes[code], volumes.get(code), day)
        vol = stats["vol_1y"]
        if vol is None or vol <= 0:
            continue
        inv[code] = 1.0 / vol
    total = sum(inv.values())
    if total <= 0:
        w = 1.0 / len(codes)
        return {code: w for code in codes}
    return {code: inv.get(code, 0.0) / total for code in codes}


def _simulate(
    spec: ImproveSpec,
    masks: dict[str, pd.Series],
    closes: dict[str, pd.Series],
    volumes: dict[str, pd.Series],
    bench: pd.Series,
    ready: pd.Timestamp,
    sectors: dict[str, str],
) -> VariantResult:
    prepared = {code: _clean(series) for code, series in closes.items()}
    rows: list[MonthRow] = []
    held: dict[str, float] = {}
    for signal, entry, exit_ in monthly_signals(bench, ready):
        chosen = select_names(spec, signal, masks, closes, volumes, sectors)
        weights = _weights(spec, chosen, signal, closes, volumes)
        tradable: list[str] = []
        gross = 0.0
        for code, weight in weights.items():
            series = prepared.get(code)
            if series is None or weight <= 0:
                continue
            start_px = _price(series, entry)
            end_px = _price(series, exit_)
            if start_px is None or end_px is None:
                continue
            tradable.append(code)
            gross += weight * (end_px / start_px - 1.0)
        # 約定できなかった分は現金（リターン0）のまま。ウェイトは再正規化しない。
        live_weights = {code: weights[code] for code in tradable}
        names = set(held) | set(live_weights)
        one_way = sum(abs(live_weights.get(code, 0.0) - held.get(code, 0.0)) for code in names) / 2.0
        cost = one_way * ROUND_TRIP_COST
        bench_entry = _price(bench, entry)
        bench_exit = _price(bench, exit_)
        if bench_entry is None or bench_exit is None:
            continue
        bench_ret = bench_exit / bench_entry - 1.0
        net = gross - cost
        rows.append(
            MonthRow(
                variant=spec.id,
                signal=signal.date().isoformat(),
                n=len(tradable),
                gross=gross,
                cost=cost,
                net=net,
                bench=bench_ret,
                excess=net - bench_ret,
                codes=",".join(tradable),
            )
        )
        held = live_weights
    train = [row for row in rows if pd.Timestamp(row.signal) <= TRAIN_END]
    test = [row for row in rows if pd.Timestamp(row.signal) >= TEST_START]
    return VariantResult(
        spec.id,
        spec.title,
        spec.summary,
        _window_freq(train, periods_per_year=12.0),
        _window_freq(test, periods_per_year=12.0),
        rows,
    )


def choose_winner(results: list[VariantResult]) -> VariantResult | None:
    eligible = [
        item
        for item in results
        if item.train.n_invested >= 12 and item.train.cagr is not None and item.train.max_dd is not None
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item.train.cagr, item.train.max_dd), reverse=True)
    return eligible[0]


def run_improve_race(
    closes: dict[str, pd.Series],
    volumes: dict[str, pd.Series],
    benchmark: pd.Series,
) -> tuple[list[VariantResult], str | None, bool, str, str]:
    bench = _clean(benchmark)
    print(f"building masks for {len(closes)} names", flush=True)
    masks = build_masks(closes, bench)
    ready = ready_date(masks)
    if ready is None:
        return [], None, False, "一次条件を満たす日が無い。", "未確認"
    sectors = _sector_map()
    results = []
    for spec in catalog():
        print(f"simulate {spec.id}", flush=True)
        results.append(_simulate(spec, masks, closes, volumes, bench, ready, sectors))
    winner = choose_winner(results)
    confirmed = is_confirmed(winner)
    if winner is None:
        verdict = "学習期間で投資月が足りる案が無く、ベストは選べない。"
    elif confirmed:
        verdict = f"採用は「{winner.title}」。学習CAGR最大かつ確認でも1306超過がプラス。"
    else:
        verdict = f"学習最大は「{winner.title}」。確認の超過がプラスでないので見送り。"
    return results, None if winner is None else winner.id, confirmed, verdict, ready.date().isoformat()


def write_report(
    *,
    out: Path,
    results: list[VariantResult],
    winner_id: str | None,
    confirmed: bool,
    verdict: str,
    names: list[str],
    as_of: str,
    ready_from: str,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([asdict(m) for r in results for m in r.months]).to_csv(
        out / "improve_months.csv", index=False, encoding="utf-8-sig"
    )
    summary = [
        {
            "id": r.id,
            "title": r.title,
            "train_cagr": r.train.cagr,
            "train_excess": r.train.mean_excess,
            "train_dd": r.train.max_dd,
            "train_names": r.train.avg_names,
            "train_invested": r.train.n_invested,
            "test_cagr": r.test.cagr,
            "test_excess": r.test.mean_excess,
            "test_dd": r.test.max_dd,
            "test_names": r.test.avg_names,
            "test_invested": r.test.n_invested,
        }
        for r in results
    ]
    pd.DataFrame(summary).to_csv(out / "improve_summary.csv", index=False, encoding="utf-8-sig")
    note = (
        f"土台は採用版 {DEFAULT_SYSTEM_ID}。"
        "変えたのは銘柄数・配分・業種上限・流動性・ランキング・直近下落フィルタ。"
        "最良は学習期間の口座CAGR。確認は2023年以降の1306超過がプラスかだけ。"
    )
    lines = [
        "# シストレ改善案の比較",
        "",
        f"- 基準日: {as_of}",
        f"- 開始: {ready_from}",
        f"- 銘柄数: {len(names)}",
        f"- {note}",
        "",
        f"**{verdict}**",
        "",
        "| 案 | 学習CAGR | 学習超過 | 学習DD | 平均銘柄 | 確認CAGR | 確認超過 | 確認DD |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        mark = ""
        if r.id == winner_id:
            mark = " 採用" if confirmed else " 学習最大"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{r.title}{mark}",
                    _pct(r.train.cagr),
                    _pct(r.train.mean_excess),
                    _pct(r.train.max_dd),
                    "未確認" if r.train.avg_names is None else f"{r.train.avg_names:.1f}",
                    _pct(r.test.cagr),
                    _pct(r.test.mean_excess),
                    _pct(r.test.max_dd),
                ]
            )
            + " |"
        )
    lines.extend(["", "## 定義", ""])
    for r in results:
        lines.append(f"- {r.title}: {r.summary}")
    lines.append("")
    (out / "improve.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "improve.json").write_text(
        json.dumps(
            {
                "as_of": as_of,
                "ready_from": ready_from,
                "winner_id": winner_id,
                "confirmed": confirmed,
                "verdict": verdict,
                "note": note,
                "results": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def data_dir_adopted() -> Path:
    from signalforge.research.trend_screen.ruleset import adopted_path

    path = adopted_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def promote_winner(winner_id: str) -> None:
    """確認を通った案だけ adopted.json を更新する。"""
    from signalforge.research.trend_screen.ruleset import DEFAULT_SYSTEM_ID

    spec = next(item for item in catalog() if item.id == winner_id)
    out = data_dir_adopted()
    payload = {
        "system_id": f"trend_{spec.id}",
        "version": "1.2",
        "name": f"長期上昇トレンド・{spec.title}",
        "based_on": DEFAULT_SYSTEM_ID,
        "improve_id": spec.id,
        "top_n": spec.top_n,
        "rank_by": spec.rank_by,
        "weight": spec.weight,
        "sector_max": spec.sector_max,
        "min_turnover": spec.min_turnover,
        "min_ret_20d": spec.min_ret_20d,
        "require_above_ma25": spec.require_above_ma25,
        "max_dd_52w": spec.max_dd_52w,
        "signal_on": "month_end",
        "promoted_from": "improve_race",
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_cached_improve(*, limit: int = 300, promote: bool = True) -> Path:
    from signalforge.config import data_dir
    from signalforge.research.trend_screen.horse import _load_bars
    from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list

    write_liquid_list(limit)
    closes, volumes, bench = _load_bars(read_liquid_list(limit))
    results, winner_id, confirmed, verdict, ready = run_improve_race(closes, volumes, bench)
    as_of = _clean(bench).index[-1].date().isoformat()
    out = data_dir() / "reports" / "trend_screen" / "improve" / as_of
    write_report(
        out=out,
        results=results,
        winner_id=winner_id,
        confirmed=confirmed,
        verdict=verdict,
        names=sorted(closes),
        as_of=as_of,
        ready_from=ready,
    )
    print(verdict, flush=True)
    for r in results:
        flag = " *" if r.id == winner_id else ""
        print(
            f"{r.title}{flag} train {r.train.cagr:+.2%} DD {r.train.max_dd:+.2%} | "
            f"test {r.test.cagr:+.2%} excess {r.test.mean_excess:+.2%}",
            flush=True,
        )
    if promote and confirmed and winner_id:
        promote_winner(winner_id)
        print(f"採用を更新: {data_dir_adopted()}", flush=True)
    print(f"出力: {out / 'improve.md'}", flush=True)
    return out
