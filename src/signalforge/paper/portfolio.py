from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signalforge.config import data_dir


def paper_dir() -> Path:
    d = data_dir() / "paper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def portfolio_path(style: str, strategy: str) -> Path:
    safe = f"{style}_{strategy}".replace("/", "_")
    return paper_dir() / f"{safe}.json"


@dataclass
class PaperPortfolio:
    style: str
    strategy: str
    cost_model: str = "alpaca"
    initial_cash: float = 100_000.0
    cash: float = 100_000.0
    started_at: str = ""
    last_processed_bar: str | None = None
    last_run_at: str | None = None
    position: dict[str, Any] | None = None
    closed_trades: list[dict[str, Any]] = field(default_factory=list)
    equity_snapshots: list[dict[str, Any]] = field(default_factory=list)
    daily_log: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, style: str, strategy: str) -> PaperPortfolio | None:
        path = portfolio_path(style, strategy)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    @classmethod
    def create(
        cls,
        style: str,
        strategy: str,
        *,
        cost_model: str = "alpaca",
        initial_cash: float = 100_000.0,
        last_bar_ts: str,
    ) -> PaperPortfolio:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            style=style,
            strategy=strategy,
            cost_model=cost_model,
            initial_cash=initial_cash,
            cash=initial_cash,
            started_at=now,
            last_processed_bar=last_bar_ts,
            last_run_at=now,
        )

    def save(self) -> Path:
        path = portfolio_path(self.style, self.strategy)
        path.write_text(json.dumps(asdict(self), indent=2, default=str), encoding="utf-8")
        return path

    def to_engine_state(self) -> dict[str, Any] | None:
        if not self.position:
            return None
        pos = dict(self.position)
        pos["position"] = 1
        return pos

    def apply_engine_state(self, state: dict[str, Any] | None, cash: float) -> None:
        self.cash = cash
        if not state or int(state.get("position", 0)) == 0:
            self.position = None
            return
        self.position = {
            "position_shares": state.get("position_shares", 0.0),
            "entry_price": state.get("entry_price", 0.0),
            "entry_idx": state.get("entry_idx", 0),
            "side": state.get("side", "flat"),
            "entry_signal_idx": state.get("entry_signal_idx"),
            "entry_is_oos": state.get("entry_is_oos", False),
            "entry_ml_expl": state.get("entry_ml_expl"),
            "cash_at_entry": state.get("cash_at_entry", cash),
            "entry_cost_breakdown": state.get("entry_cost_breakdown", {}),
        }

    def mark_to_market_equity(self, last_close: float) -> float:
        if not self.position:
            return self.cash
        shares = float(self.position.get("position_shares", 0))
        entry = float(self.position.get("entry_price", 0))
        side = self.position.get("side", "long")
        if side == "long":
            return self.cash + shares * last_close
        cash_at_entry = float(self.position.get("cash_at_entry", self.cash))
        return self.cash + cash_at_entry + (entry - last_close) * shares
