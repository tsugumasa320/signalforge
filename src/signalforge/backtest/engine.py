from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from signalforge.backtest.metrics import BacktestResult, compute_metrics
from signalforge.backtest.costs import LegacyCostModel, TradeCostBreakdown, load_cost_model
from signalforge.data.calendar import is_earnings_blackout
from signalforge.interpret.journal import TradeJournal
from signalforge.profiles.base import StyleProfile
from signalforge.profiles.daytrade import DaytradeProfile
from signalforge.strategies.base import BaseStrategy

if TYPE_CHECKING:
    from signalforge.ml.filter import MetaLabelFilter


class BacktestEngine:
    def __init__(
        self,
        profile: StyleProfile,
        strategy: BaseStrategy,
        cfg: dict[str, Any],
        ml_filter: MetaLabelFilter | None = None,
        cost_model=None,
        commission_pct: float = 0.00005,
    ) -> None:
        self.profile = profile
        self.strategy = strategy
        self.cfg = cfg
        self.ml_filter = ml_filter
        if cost_model is None:
            defaults = cfg.get("_defaults", {})
            self.cost_model = LegacyCostModel(commission_pct=float(defaults.get("commission_pct", commission_pct)))
        else:
            self.cost_model = cost_model
        self.commission_pct = commission_pct
        self.journal = TradeJournal()
        exit_rules = cfg.get("rules", {}).get("exit", {})
        self.atr_tp = exit_rules.get("atr_tp_multiple", 3.0)
        self.atr_sl = exit_rules.get("atr_sl_multiple", 1.5)
        self.max_hold = profile.max_hold_bars
        self.blackout = cfg.get("_nvda", {}).get("earnings_blackout_days", 2)
        self._entry_signal_idx: int | None = None
        self._entry_is_oos = False
        self._entry_ml_expl: dict[str, Any] | None = None
        self._cash_at_entry = 0.0

    def run(self, df: pd.DataFrame, signals: pd.Series | None = None) -> BacktestResult:
        if isinstance(self.profile, DaytradeProfile):
            df = self.profile.apply_session_filter(df)

        if signals is None:
            signals = self.strategy.generate_signals(df)

        trade_rows = []
        equity = pd.Series(100_000.0, index=df.index)
        cash = 100_000.0
        position = 0
        position_shares = 0.0
        entry_price = 0.0
        entry_idx = 0
        side = "flat"
        trades_today = 0
        current_day = None
        ml_cfg = self.cfg.get("ml_filter", {})
        self._entry_cost_breakdown = TradeCostBreakdown()

        for i in range(len(df)):
            ts = df.index[i]
            day = ts.date() if hasattr(ts, "date") else pd.Timestamp(ts).date()
            if day != current_day:
                current_day = day
                trades_today = 0

            row = df.iloc[i]

            if position != 0:
                bars_held = i - entry_idx
                exit_price = None
                reason = ""

                if side == "long":
                    tp = entry_price + row["atr_14"] * self.atr_tp
                    sl = entry_price - row["atr_14"] * self.atr_sl
                    if row["high"] >= tp:
                        exit_price = tp
                        reason = "take_profit"
                    elif row["low"] <= sl:
                        exit_price = sl
                        reason = "stop_loss"
                else:
                    tp = entry_price - row["atr_14"] * self.atr_tp
                    sl = entry_price + row["atr_14"] * self.atr_sl
                    if row["low"] <= tp:
                        exit_price = tp
                        reason = "take_profit"
                    elif row["high"] >= sl:
                        exit_price = sl
                        reason = "stop_loss"

                if exit_price is None and self.profile.should_force_exit(df, i, bars_held):
                    exit_price = self.profile.exit_fill_price(df, i, side)
                    reason = "max_hold_or_session"

                if exit_price is not None:
                    raw_exit = exit_price
                    exit_price = self.cost_model.apply_exit_slippage(raw_exit, side)
                    shares = position_shares
                    breakdown = getattr(self, "_entry_cost_breakdown", TradeCostBreakdown())
                    self.cost_model.record_slippage(
                        shares, raw_exit, exit_price, breakdown, is_entry=False
                    )
                    if side == "long":
                        cash, net_pnl_pct, gross_pnl_pct, breakdown = self.cost_model.settle_long(
                            self._cash_at_entry, shares, entry_price, exit_price, breakdown
                        )
                    else:
                        cash, net_pnl_pct, gross_pnl_pct, breakdown = self.cost_model.settle_short(
                            self._cash_at_entry, shares, entry_price, exit_price, breakdown
                        )

                    signal_idx = self._entry_signal_idx if self._entry_signal_idx is not None else max(entry_idx - 1, 0)
                    audit_rec = self._find_audit(str(df.index[signal_idx]), side)
                    summary = self._build_summary(audit_rec, reason)

                    self.journal.add_trade(
                        timestamp=str(df.index[signal_idx]),
                        style=self.profile.name,
                        strategy=self.strategy.name,
                        action="BUY" if side == "long" else "SELL",
                        outcome="executed",
                        summary_ja=summary,
                        rules_audit={
                            "passed": audit_rec.passed_rules if audit_rec else [],
                            "failed": audit_rec.failed_rules if audit_rec else [],
                        },
                        ml_explanation=self._entry_ml_expl,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pnl_pct=net_pnl_pct,
                        hold_bars=bars_held,
                        is_oos=self._entry_is_oos,
                    )
                    trade_rows.append(
                        {
                            "entry_time": df.index[entry_idx],
                            "exit_time": ts,
                            "side": side,
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "pnl_pct": net_pnl_pct,
                            "gross_pnl_pct": gross_pnl_pct,
                            "hold_bars": bars_held,
                            "reason": reason,
                            "is_oos": self._entry_is_oos,
                            **breakdown.to_dict(),
                        }
                    )
                    position = 0
                    position_shares = 0.0
                    side = "flat"
                    self._entry_signal_idx = None
                    self._entry_ml_expl = None
                    self._entry_cost_breakdown = TradeCostBreakdown()

            if position == 0 and signals.iloc[i] != 0 and i + 1 < len(df):
                if is_earnings_blackout(ts, self.blackout):
                    continue
                if isinstance(self.profile, DaytradeProfile) and trades_today >= self.profile.max_trades_per_day:
                    continue

                sig_side = "long" if signals.iloc[i] > 0 else "short"
                audit_rec = self._find_audit(str(ts), sig_side)

                ml_ok = True
                ml_expl = None
                is_oos = False
                if self.ml_filter and self.ml_filter.enabled:
                    ml_ok, prob, ml_expl, is_oos = self.ml_filter.should_trade(df, i)
                    if not ml_ok:
                        if ml_cfg.get("interpretability", {}).get("log_rejected_signals", True):
                            self.journal.add_rejected(
                                timestamp=str(ts),
                                style=self.profile.name,
                                strategy=self.strategy.name,
                                outcome="rejected_by_ml",
                                summary_ja=self._rejection_summary(audit_rec, prob, is_oos),
                                rules_audit={
                                    "passed": audit_rec.passed_rules if audit_rec else [],
                                    "failed": audit_rec.failed_rules if audit_rec else [],
                                },
                                ml_explanation=ml_expl,
                                is_oos=is_oos,
                            )
                        continue

                entry_price = self.profile.entry_fill_price(df, i, sig_side)
                raw_entry = entry_price
                entry_price = self.cost_model.apply_entry_slippage(raw_entry, sig_side)
                self._cash_at_entry = cash
                if sig_side == "long":
                    shares, _, breakdown = self.cost_model.solve_entry(cash, entry_price)
                else:
                    shares, _, breakdown = self.cost_model.open_short(cash, entry_price)
                self.cost_model.record_slippage(shares, raw_entry, entry_price, breakdown, is_entry=True)
                if shares <= 0:
                    continue
                position = 1
                position_shares = shares
                side = sig_side
                entry_idx = i + 1
                self._entry_signal_idx = i
                self._entry_is_oos = is_oos
                self._entry_ml_expl = ml_expl
                self._entry_cost_breakdown = breakdown
                trades_today += 1

            equity.iloc[i] = cash

        trades_df = pd.DataFrame(trade_rows)
        metrics = compute_metrics(trades_df, equity)
        return BacktestResult(
            trades=trades_df,
            equity_curve=equity,
            metrics=metrics,
            journal_run_id=self.journal.run_id,
        )

    def _build_summary(self, audit_rec, reason: str) -> str:
        if audit_rec and audit_rec.all_passed:
            base = self.strategy.summary_ja(audit_rec)
        elif audit_rec:
            base = self.strategy.summary_ja(audit_rec)
        else:
            base = self.strategy.name
        return f"{base} → {reason}"

    def _rejection_summary(self, audit_rec, prob: float, is_oos: bool) -> str:
        scope = "OOS" if is_oos else "ウォームアップ"
        if audit_rec and audit_rec.all_passed:
            return f"{scope}: {self.strategy.name} 成立だが ML 棄却(prob={prob:.2f})"
        return f"{scope}: ML 棄却(prob={prob:.2f})"

    def _find_audit(self, ts: str, side: str):
        for rec in reversed(self.strategy.audit.records):
            if rec.timestamp == ts and rec.side == side:
                return rec
        for rec in reversed(self.strategy.audit.records):
            if rec.timestamp == ts:
                return rec
        return None
