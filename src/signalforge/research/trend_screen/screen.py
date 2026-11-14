"""指定銘柄の採点。全市場の一括実行はここには無い。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

import pandas as pd

from signalforge.research.trend_screen.cases import DISPLAY_NAMES, case_tickers
from signalforge.research.trend_screen.chart import evaluate_chart
from signalforge.research.trend_screen.config import METHOD_VERSION, PRICE_START, WEIGHTS_NOTE
from signalforge.research.trend_screen.forward import ForwardReport, chart_forward
from signalforge.research.trend_screen.fundamentals import AnnualPoint, score_fundamentals
from signalforge.research.trend_screen.load import (
    FUND_SOURCE,
    PRICE_SOURCE,
    listing_snapshot,
    load_annuals,
    load_bars,
    load_benchmark,
    load_market_cap,
)
from signalforge.research.trend_screen.report import write_outputs
from signalforge.research.trend_screen.score import ScoredName, assemble, ranked
from signalforge.research.trend_screen.universe import normalize_ticker
from signalforge.research.trend_screen.valuation import score_valuation
from signalforge.config import data_dir


class ScreenUsageError(ValueError):
    pass


def evaluate_name(
    *,
    code: str,
    name: str,
    market: str,
    sector: str,
    market_cap: float | None,
    bars: pd.DataFrame,
    annuals: list[AnnualPoint],
    benchmark: pd.Series | None,
    price_source: str,
    fundamental_source: str,
    in_listing: bool | None,
) -> ScoredName:
    close = bars["close"]
    volume = bars["volume"] if "volume" in bars.columns else None
    adj = bars["adj_close"] if "adj_close" in bars.columns and bars["adj_close"].notna().any() else None
    metrics = evaluate_chart(close, volume, adj, benchmark)
    fund = score_fundamentals(annuals, sector, source=fundamental_source)
    valuation = score_valuation(price=metrics.price, annuals=fund.annuals, source=fundamental_source)
    return assemble(
        code=code,
        name=name,
        market=market,
        sector=sector,
        market_cap=market_cap,
        metrics=metrics,
        fund=fund,
        val=valuation,
        price_source=price_source,
        in_listing=in_listing,
    )


def _identity(code: str, listing: dict[str, dict], listing_loaded: bool) -> tuple[str, str, str, bool | None]:
    row = listing.get(code)
    if row:
        return (
            str(row.get("name") or DISPLAY_NAMES.get(code) or code),
            str(row.get("market") or "未確認"),
            str(row.get("sector_tse") or "未確認"),
            True,
        )
    fallback = DISPLAY_NAMES.get(code, code)
    if not listing_loaded:
        return fallback, "未確認", "未確認", None
    return fallback, "未確認", "未確認", False


def _mark_stale(rows: list[ScoredName]) -> str:
    dates = [row.chart.as_of for row in rows if row.chart and row.chart.as_of]
    if not dates:
        return datetime.now().date().isoformat()
    latest = max(dates)
    latest_day = datetime.fromisoformat(latest).date()
    for row in rows:
        if row.chart is None or not row.chart.as_of:
            continue
        age = (latest_day - datetime.fromisoformat(row.chart.as_of).date()).days
        if age > 7:
            row.flags.append(f"日足が全体の基準日より{age}日古い")
    return latest


def _parse_tickers(text: str, use_cases: bool) -> list[str]:
    if not text.strip() and not use_cases:
        raise ScreenUsageError(
            "全市場の一括スクリーニングは未実装です。--cases か --tickers を指定してください。"
        )
    chosen = case_tickers() if use_cases else []
    if text.strip():
        chosen.extend(normalize_ticker(part) for part in text.split(",") if part.strip())
    unique: list[str] = []
    for code in chosen:
        if code not in unique:
            unique.append(code)
    return unique


def universe_text() -> str:
    try:
        snap = listing_snapshot()
    except Exception as exc:
        return f"上場一覧は未確認（{exc}）。日足の全市場取得はしていない。"
    segments = "、".join(f"{key} {value}" for key, value in sorted(snap["by_segment"].items()))
    return (
        f"JPX上場一覧の内国株は{snap['domestic_rows']}行。"
        f"このうち4桁または英字入りの普通株コードは{snap['common_rows']}銘柄（{segments}）。"
        "ETF・ETN・REITはこの内国株区分に入らない。5桁コードは優先株などの可能性があるため普通株数から除いた。"
        "この銘柄数は一覧の件数であり、日足を取得してスクリーニングした件数ではない。"
    )


def run_screen(
    tickers: list[str],
    *,
    refresh: bool = False,
    with_forward: bool = True,
) -> tuple[list[ScoredName], dict, dict[str, pd.DataFrame], ForwardReport | None]:
    try:
        snap = listing_snapshot()
        listing = snap["table"]
        listing_loaded = True
        listing_as_of = snap["fetched_at"]
        listing_source = snap["source_url"]
    except Exception as exc:
        listing = {}
        listing_loaded = False
        listing_as_of = "未確認"
        listing_source = f"未確認 ({exc})"
    benchmark, benchmark_source = load_benchmark(refresh=refresh)
    rows: list[ScoredName] = []
    bars_map: dict[str, pd.DataFrame] = {}
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    for code in tickers:
        name, market, sector, in_listing = _identity(code, listing, listing_loaded)
        print(f"screen {code} {name}", flush=True)
        try:
            bars = load_bars(code, refresh=refresh)
            annuals, fundamental_source = load_annuals(code, refresh=refresh)
            market_cap = load_market_cap(code)
            row = evaluate_name(
                code=code,
                name=name,
                market=market,
                sector=sector,
                market_cap=market_cap,
                bars=bars,
                annuals=annuals,
                benchmark=benchmark,
                price_source=PRICE_SOURCE,
                fundamental_source=fundamental_source,
                in_listing=in_listing,
            )
            bars_map[code] = bars
            closes[code] = bars["close"]
            if "volume" in bars.columns:
                volumes[code] = bars["volume"]
        except Exception as exc:
            row = ScoredName(
                code=code,
                name=name,
                market=market,
                sector=sector,
                error=str(exc),
                candidate_status="取得失敗",
                grade="取得失敗",
                flags=[str(exc)],
                fundamental_source=FUND_SOURCE,
                price_source=PRICE_SOURCE,
            )
        rows.append(row)
    as_of = _mark_stale(rows)
    forward = chart_forward(closes, volumes, benchmark) if with_forward and closes else None
    meta = {
        "method_version": METHOD_VERSION,
        "weights_note": WEIGHTS_NOTE,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "price_start": PRICE_START,
        "price_source": PRICE_SOURCE,
        "benchmark": benchmark_source,
        "listing_as_of": listing_as_of,
        "listing_source": listing_source,
        "universe_note": universe_text(),
        "requested": [code.replace(".T", "") for code in tickers],
        "full_market_screened": False,
        "n_scored": len(rows),
        "n_ranked": len(ranked(rows)),
        "forward": None
        if forward is None
        else {
            "strategy": forward.strategy,
            "start": forward.start,
            "end": forward.end,
            "n_names": forward.n_names,
            "n_signal_dates": forward.n_signal_dates,
            "note": forward.note,
            "horizons": [asdict(item) for item in forward.horizons],
        },
    }
    return rows, meta, bars_map, forward


def run_cli(*, tickers: str, use_cases: bool, refresh: bool, with_forward: bool) -> Path:
    chosen = _parse_tickers(tickers, use_cases)
    rows, meta, bars_map, forward = run_screen(chosen, refresh=refresh, with_forward=with_forward)
    out = data_dir() / "reports" / "trend_screen" / str(meta["as_of"])
    write_outputs(rows, out=out, meta=meta, bars=bars_map, forward=forward)
    print(meta["universe_note"], flush=True)
    print(f"相対: {meta['benchmark']}", flush=True)
    print(f"全市場スクリーニング: していない（{meta['n_scored']}銘柄を採点、選定対象 {meta['n_ranked']}）", flush=True)
    order = ranked(rows)
    if not order:
        print("選定対象で総合点が出た銘柄はない。", flush=True)
    for rank, row in enumerate(order, start=1):
        peg = "未確認" if row.valuation is None or row.valuation.peg is None else f"{row.valuation.peg:.2f}"
        if row.valuation is not None and row.valuation.status == "算出不能":
            peg = "算出不能"
        print(
            f"{rank:>2} {row.code.replace('.T', ''):<6} {row.total:.1f}/{row.total_max:.0f} "
            f"chart {None if row.chart_score is None else row.chart_score.score} "
            f"fund {None if row.fundamentals is None else row.fundamentals.score} "
            f"PEG {peg} {row.grade} {row.name}",
            flush=True,
        )
    print(f"出力: {out / 'ranking.md'}", flush=True)
    return out
