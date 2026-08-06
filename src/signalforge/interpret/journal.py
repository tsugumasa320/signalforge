from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from signalforge.backtest.metrics import compute_metrics


@dataclass
class TradeRecord:
    trade_id: int
    run_id: str
    timestamp: str
    style: str
    strategy: str
    action: str
    outcome: str
    summary_ja: str
    rules_audit: dict[str, list[str]] = field(default_factory=dict)
    ml_explanation: dict[str, Any] | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    pnl_pct: float | None = None
    hold_bars: int | None = None
    is_oos: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "style": self.style,
            "strategy": self.strategy,
            "action": self.action,
            "outcome": self.outcome,
            "summary_ja": self.summary_ja,
            "rules_audit": self.rules_audit,
            "ml_explanation": self.ml_explanation,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl_pct": self.pnl_pct,
            "hold_bars": self.hold_bars,
            "is_oos": self.is_oos,
        }


@dataclass
class RejectedSignal:
    signal_id: int
    run_id: str
    timestamp: str
    style: str
    strategy: str
    outcome: str
    summary_ja: str
    rules_audit: dict[str, list[str]] = field(default_factory=dict)
    ml_explanation: dict[str, Any] | None = None
    is_oos: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "style": self.style,
            "strategy": self.strategy,
            "outcome": self.outcome,
            "summary_ja": self.summary_ja,
            "rules_audit": self.rules_audit,
            "ml_explanation": self.ml_explanation,
            "is_oos": self.is_oos,
        }


class TradeJournal:
    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id or str(uuid.uuid4())[:8]
        self.trades: list[TradeRecord] = []
        self.rejected: list[RejectedSignal] = []
        self._trade_counter = 0
        self._signal_counter = 0

    def add_trade(self, **kwargs: Any) -> TradeRecord:
        self._trade_counter += 1
        rec = TradeRecord(trade_id=self._trade_counter, run_id=self.run_id, **kwargs)
        self.trades.append(rec)
        return rec

    def add_rejected(self, **kwargs: Any) -> RejectedSignal:
        self._signal_counter += 1
        rec = RejectedSignal(signal_id=self._signal_counter, run_id=self.run_id, **kwargs)
        self.rejected.append(rec)
        return rec

    def get_trade(self, trade_id: int) -> TradeRecord | None:
        for t in self.trades:
            if t.trade_id == trade_id:
                return t
        return None

    def oos_trades_df(self) -> pd.DataFrame:
        rows = []
        for t in self.trades:
            if t.is_oos and t.pnl_pct is not None:
                rows.append(
                    {
                        "entry_time": pd.Timestamp(t.timestamp),
                        "pnl_pct": t.pnl_pct,
                        "hold_bars": t.hold_bars or 0,
                        "side": "long" if t.action == "BUY" else "short",
                    }
                )
        return pd.DataFrame(rows)

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        with open(path / f"journal_{self.run_id}.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "run_id": self.run_id,
                    "trades": [t.to_dict() for t in self.trades],
                    "rejected": [r.to_dict() for r in self.rejected],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    @classmethod
    def load(cls, path: Path, run_id: str) -> TradeJournal:
        with open(path / f"journal_{run_id}.json", encoding="utf-8") as f:
            data = json.load(f)
        j = cls(run_id=data["run_id"])
        for t in data.get("trades", []):
            j.trades.append(TradeRecord(**t))
            j._trade_counter = max(j._trade_counter, t["trade_id"])
        for r in data.get("rejected", []):
            j.rejected.append(RejectedSignal(**r))
        return j


def compute_oos_metrics(journal: TradeJournal, equity: pd.Series) -> dict[str, Any]:
    oos_df = journal.oos_trades_df()
    if oos_df.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe": 0.0,
            "max_drawdown_pct": 0.0,
            "total_return_pct": 0.0,
            "avg_pnl_pct": 0.0,
        }
    return compute_metrics(oos_df, equity)
