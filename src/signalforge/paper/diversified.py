"""Forward paper: one account, universe scan, greedy capital allocation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.config import data_dir, load_style_config
from signalforge.compare.prep_cache import load_or_prepare_ticker
from signalforge.compare.runner import run_cohort_backtests
from signalforge.portfolio.diversified import (
    attach_entry_rule_features,
    default_diversified_params,
    entry_rule_kwargs,
    fill_missing_sectors,
    filter_trades_after,
    trades_pool_from_backtest_rows,
)
from signalforge.lab.portfolio_sim import DEFAULT_ENTRY_RULES, simulate_diversified_portfolio
from signalforge.universe.filters import get_preset, resolve_cohort_tickers

ENTRY_RULES_VERSION = 2


def list_diversified_paper_books() -> list[DiversifiedPaperBook]:
    """All saved diversified forward accounts under data/paper/."""
    root = data_dir() / "paper"
    books: list[DiversifiedPaperBook] = []
    if not root.is_dir():
        return books
    for path in sorted(root.glob("diversified_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            book = DiversifiedPaperBook(**data)
        except (json.JSONDecodeError, TypeError):
            continue
        book.upgrade_rules()
        books.append(book)
    return books


def diversified_book_path(style: str, strategy: str) -> Path:
    safe = f"{style}_{strategy}".replace("/", "_")
    return data_dir() / "paper" / f"diversified_{safe}.json"


@dataclass
class DiversifiedPaperBook:
    style: str
    strategy: str
    cohort: str = "prime"
    ticker_limit: int = 0
    cost_model: str = "japan"
    initial_capital: float = 3_000_000.0
    max_positions: int = 5
    position_pct: float = 0.2
    entry_priority: str = "sector_liquidity"
    min_turnover_jpy: float = 0.0
    min_breadth_rank: float = 0.0
    regime_filter: str = "none"
    rules_version: int = 1
    currency: str = "JPY"
    started_at: str = ""
    entry_cutoff: str = ""
    last_run_at: str | None = None
    universe_size: int = 0
    last_sim: dict[str, Any] = field(default_factory=dict)
    tickers: list[str] = field(default_factory=list)
    workers: int = 8

    @classmethod
    def load(cls, style: str, strategy: str) -> DiversifiedPaperBook | None:
        path = diversified_book_path(style, strategy)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        book = cls(**data)
        book.upgrade_rules()
        return book

    def upgrade_rules(self) -> bool:
        """Move books created before ENTRY_RULES_VERSION onto DEFAULT_ENTRY_RULES (start date kept)."""
        if self.rules_version >= ENTRY_RULES_VERSION:
            return False
        self.apply_rules(DEFAULT_ENTRY_RULES)
        return True

    def apply_rules(self, rules: dict[str, Any]) -> None:
        self.entry_priority = str(rules["entry_priority"])
        self.min_turnover_jpy = float(rules["min_turnover_jpy"])
        self.min_breadth_rank = float(rules["min_breadth_rank"])
        self.regime_filter = str(rules["regime_filter"])
        self.rules_version = ENTRY_RULES_VERSION

    def entry_rules(self) -> dict[str, Any]:
        return {
            "entry_priority": self.entry_priority,
            "min_turnover_jpy": self.min_turnover_jpy,
            "min_breadth_rank": self.min_breadth_rank,
            "regime_filter": self.regime_filter,
        }

    def save(self) -> Path:
        path = diversified_book_path(self.style, self.strategy)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, default=str), encoding="utf-8")
        return path


def latest_bar_across_universe(style: str, tickers: list[str], *, refresh: bool) -> pd.Timestamp | None:
    latest: pd.Timestamp | None = None
    for sym in tickers:
        try:
            bundle = load_or_prepare_ticker(style, sym, refresh_data=refresh)
            df = bundle.get("df")
            if df is None or df.empty:
                continue
            ts = pd.Timestamp(df.index[-1])
            if latest is None or ts > latest:
                latest = ts
        except Exception:
            continue
    return latest


LIQUID_COHORT = "tse_liquid"
LIQUID_COHORT_MIN_MEDIAN_TURNOVER_JPY = 3e8
LIQUID_COHORT_LOOKBACK_BARS = 250


def resolve_universe_tickers(cohort: str, ticker_limit: int) -> list[str]:
    if cohort == LIQUID_COHORT:
        from signalforge.portfolio.entry_features import liquid_tickers

        tickers = liquid_tickers(
            LIQUID_COHORT_MIN_MEDIAN_TURNOVER_JPY, lookback_bars=LIQUID_COHORT_LOOKBACK_BARS
        )
        return tickers[:ticker_limit] if ticker_limit > 0 else tickers
    preset = get_preset(cohort)
    tickers = resolve_cohort_tickers({**(preset.get("filter") or {}), "exclude_etf": True})
    if ticker_limit > 0:
        tickers = tickers[:ticker_limit]
    return tickers


def init_diversified_paper(
    style: str,
    strategy: str,
    *,
    cohort: str = "prime",
    ticker_limit: int = 0,
    cost_model: str = "japan",
    initial_cash_jpy: float | None = None,
    max_positions: int = 5,
    position_pct: float = 0.2,
    workers: int = 8,
    entry_rules: dict[str, Any] | None = None,
    refresh: bool = True,
) -> DiversifiedPaperBook:
    load_style_config(style)
    tickers = resolve_universe_tickers(cohort, ticker_limit)
    if not tickers:
        raise RuntimeError("ユニバースに銘柄がありません。")
    params = default_diversified_params(
        initial_cash_jpy=initial_cash_jpy,
        max_positions=max_positions,
        position_pct=position_pct,
    )
    now = datetime.now(timezone.utc).isoformat()
    cutoff_ts = latest_bar_across_universe(style, tickers, refresh=refresh)
    if cutoff_ts is None:
        raise RuntimeError("最終足が取得できませんでした。fetch を実行してください。")
    book = DiversifiedPaperBook(
        style=style,
        strategy=strategy,
        cohort=cohort,
        ticker_limit=ticker_limit,
        cost_model=cost_model,
        initial_capital=float(params["initial_capital"]),
        max_positions=int(params["max_positions"]),
        position_pct=float(params["position_pct"]),
        currency="JPY",
        started_at=now,
        entry_cutoff=str(cutoff_ts),
        universe_size=len(tickers),
        tickers=tickers,
        workers=workers,
    )
    book.apply_rules({**DEFAULT_ENTRY_RULES, **(entry_rules or {})})
    run_diversified_paper(book, refresh=refresh, workers=workers)
    return book


def run_diversified_paper(
    book: DiversifiedPaperBook,
    *,
    refresh: bool = True,
    workers: int | None = None,
) -> dict[str, Any]:
    tickers = book.tickers or resolve_universe_tickers(book.cohort, book.ticker_limit)
    book.tickers = tickers
    w = workers if workers is not None else book.workers
    cohort_result = run_cohort_backtests(
        strategy_id=book.strategy,
        style=book.style,
        tickers=tickers,
        cost_model=book.cost_model,
        refresh=refresh,
        bulk_mode=True,
        max_workers=max(1, int(w)),
    )
    rows = cohort_result.get("tickers") or []
    rules = book.entry_rules()
    pool = attach_entry_rule_features(fill_missing_sectors(trades_pool_from_backtest_rows(rows)), rules)
    cutoff = pd.Timestamp(book.entry_cutoff)
    if cutoff.tzinfo is None and not pool.empty and pool["entry_time"].dt.tz is not None:
        cutoff = cutoff.tz_localize("UTC")
    pool = filter_trades_after(pool, cutoff)
    chart_end = pd.Timestamp.now(tz="UTC")
    if not pool.empty and "exit_time" in pool.columns:
        ex = pd.to_datetime(pool["exit_time"].max())
        if ex.tzinfo is None:
            ex = ex.tz_localize("UTC")
        else:
            ex = ex.tz_convert("UTC")
        chart_end = max(chart_end, ex)
    sim = simulate_diversified_portfolio(
        pool,
        initial_capital=book.initial_capital,
        max_positions=book.max_positions,
        position_pct=book.position_pct,
        chart_start=cutoff,
        chart_end=chart_end,
        **entry_rule_kwargs(rules),
    )
    book.last_sim = sim
    book.last_run_at = datetime.now(timezone.utc).isoformat()
    book.universe_size = len(tickers)
    book.save()
    return {
        "book": book,
        "n_trades_forward": len(pool),
        "simulation": sim,
        "n_tickers_ok": cohort_result.get("summary", {}).get("n_ok"),
    }
