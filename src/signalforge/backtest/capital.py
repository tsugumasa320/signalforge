"""Capital / position sizing policy for backtests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapitalPolicy:
    """How much cash may be deployed per entry (single-position engine)."""

    initial_cash: float = 100_000.0
    # 1エントリーで使えるのは口座評価額（ここでは現金）の最大割合
    max_position_pct: float = 1.0
    # 常に残す現金バッファ（口座現金に対する割合）
    min_cash_reserve_pct: float = 0.0
    currency: str = "USD"

    def entry_budget(self, cash: float, *, equity: float | None = None) -> float:
        """Cash available for the next entry after reserve and cap."""
        base = equity if equity is not None else cash
        reserve = max(0.0, cash * self.min_cash_reserve_pct)
        after_reserve = max(0.0, cash - reserve)
        cap = max(0.0, base * self.max_position_pct)
        return min(after_reserve, cap)

    def to_metrics_fragment(self) -> dict[str, Any]:
        return {
            "capital_initial": self.initial_cash,
            "capital_max_position_pct": self.max_position_pct,
            "capital_min_cash_reserve_pct": self.min_cash_reserve_pct,
            "capital_currency": self.currency,
        }

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> CapitalPolicy:
        defaults = cfg.get("_defaults") or {}
        bt = cfg.get("backtest") or {}
        market = cfg.get("_market") or {}
        hint = market.get("backtest_capital_hint") or {}
        cap = {**(defaults.get("capital") or {}), **hint, **(bt.get("capital") or {})}

        initial: float | None = None
        for key in ("initial_cash", "initial_cash_jpy", "initial_cash_usd"):
            if cap.get(key) is not None:
                initial = float(cap[key])
                break
        if initial is None:
            preset = str(market.get("cost_preset") or "")
            if preset == "japan" or market.get("currency") == "JPY":
                initial = float(cap.get("initial_cash_jpy") or defaults.get("capital", {}).get("initial_cash_jpy") or 3_000_000.0)
            else:
                initial = 100_000.0

        currency = str(cap.get("currency") or market.get("currency") or "USD")
        max_pct = float(cap.get("max_position_pct", 1.0))
        max_pct = min(1.0, max(0.01, max_pct))
        reserve = float(cap.get("min_cash_reserve_pct", 0.0))
        reserve = min(0.5, max(0.0, reserve))

        return cls(
            initial_cash=initial,
            max_position_pct=max_pct,
            min_cash_reserve_pct=reserve,
            currency=currency,
        )


def backtest_capital_record(policy: CapitalPolicy) -> dict[str, Any]:
    """Stable dict stored on experiment manifests / strategy headers."""
    rec: dict[str, Any] = {
        "max_position_pct": round(policy.max_position_pct, 6),
        "min_cash_reserve_pct": round(policy.min_cash_reserve_pct, 6),
        "currency": policy.currency,
    }
    if policy.currency == "JPY":
        rec["initial_cash_jpy"] = int(round(policy.initial_cash))
    else:
        rec["initial_cash"] = float(policy.initial_cash)
    return rec


def capital_records_match(stored: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if not stored or not current:
        return False
    keys = ("initial_cash_jpy", "initial_cash", "max_position_pct", "min_cash_reserve_pct", "currency")
    for key in keys:
        if key not in current and key not in stored:
            continue
        a, b = stored.get(key), current.get(key)
        if a is None and b is None:
            continue
        if a is None or b is None:
            return False
        if key in ("initial_cash_jpy",):
            if int(round(float(a))) != int(round(float(b))):
                return False
        elif key == "currency":
            if str(a) != str(b):
                return False
        elif abs(float(a) - float(b)) > 1e-9:
            return False
    return True


def _capital_overrides_from_env() -> dict[str, Any]:
    out: dict[str, Any] = {}
    mapping = (
        ("SIGNALFORGE_BT_INITIAL_CASH_JPY", "initial_cash_jpy"),
        ("INITIAL_CASH_JPY", "initial_cash_jpy"),
        ("SIGNALFORGE_BT_MAX_POSITION_PCT", "max_position_pct"),
        ("MAX_POSITION_PCT", "max_position_pct"),
        ("SIGNALFORGE_BT_MIN_CASH_RESERVE_PCT", "min_cash_reserve_pct"),
        ("MIN_CASH_RESERVE_PCT", "min_cash_reserve_pct"),
    )
    for env_key, cap_key in mapping:
        raw = os.getenv(env_key)
        if raw is None or raw == "":
            continue
        out[cap_key] = float(raw) if cap_key != "initial_cash_jpy" else int(float(raw))
    return out


def resolve_experiment_capital(
    *,
    plan_capital: dict[str, Any] | None = None,
    initial_cash_jpy: float | None = None,
    max_position_pct: float | None = None,
    min_cash_reserve_pct: float | None = None,
    style: str = "swing",
) -> CapitalPolicy:
    """Effective capital for TSE cohort backtests (config chain + plan + env + CLI)."""
    from signalforge.config import load_style_config

    cfg = load_style_config(style)
    bt = dict(cfg.get("backtest") or {})
    cap = dict(bt.get("capital") or {})
    for layer in (plan_capital or {}, _capital_overrides_from_env()):
        cap = {**cap, **{k: v for k, v in layer.items() if v is not None}}
    if initial_cash_jpy is not None:
        cap["initial_cash_jpy"] = int(initial_cash_jpy)
    if max_position_pct is not None:
        cap["max_position_pct"] = float(max_position_pct)
    if min_cash_reserve_pct is not None:
        cap["min_cash_reserve_pct"] = float(min_cash_reserve_pct)
    bt["capital"] = cap
    cfg["backtest"] = bt
    return CapitalPolicy.from_config(cfg)


def pipeline_cfg_override_from_capital(policy: CapitalPolicy) -> dict[str, Any]:
    cap: dict[str, Any] = {
        "max_position_pct": policy.max_position_pct,
        "min_cash_reserve_pct": policy.min_cash_reserve_pct,
        "currency": policy.currency,
    }
    if policy.currency == "JPY":
        cap["initial_cash_jpy"] = policy.initial_cash
    else:
        cap["initial_cash_usd"] = policy.initial_cash
    return {"backtest": {"capital": cap}}
