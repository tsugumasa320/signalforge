from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

CostPreset = Literal["legacy", "alpaca", "alpaca_conservative"]


def _round_up_cent(amount: float) -> float:
    if amount <= 0:
        return 0.0
    return math.ceil(amount * 100) / 100


@dataclass
class TradeCostBreakdown:
    buy_fees_usd: float = 0.0
    sell_fees_usd: float = 0.0
    slippage_entry_usd: float = 0.0
    slippage_exit_usd: float = 0.0
    sec_fee_usd: float = 0.0
    taf_fee_usd: float = 0.0
    cat_fee_usd: float = 0.0
    commission_usd: float = 0.0

    @property
    def total_fees_usd(self) -> float:
        return self.buy_fees_usd + self.sell_fees_usd

    @property
    def total_slippage_usd(self) -> float:
        return self.slippage_entry_usd + self.slippage_exit_usd

    @property
    def total_cost_usd(self) -> float:
        return self.total_fees_usd + self.total_slippage_usd

    def to_dict(self) -> dict[str, float]:
        return {
            "buy_fees_usd": self.buy_fees_usd,
            "sell_fees_usd": self.sell_fees_usd,
            "sec_fee_usd": self.sec_fee_usd,
            "taf_fee_usd": self.taf_fee_usd,
            "cat_fee_usd": self.cat_fee_usd,
            "commission_usd": self.commission_usd,
            "slippage_entry_usd": self.slippage_entry_usd,
            "slippage_exit_usd": self.slippage_exit_usd,
            "total_fees_usd": self.total_fees_usd,
            "total_slippage_usd": self.total_slippage_usd,
            "total_cost_usd": self.total_cost_usd,
        }


@dataclass
class LegacyCostModel:
    """Original simplified pct-based commission."""

    commission_pct: float = 0.00005
    name: str = "legacy"

    def solve_entry(self, cash_usd: float, price: float) -> tuple[float, float, TradeCostBreakdown]:
        shares = cash_usd / price if price > 0 else 0.0
        fee = cash_usd * self.commission_pct
        breakdown = TradeCostBreakdown(
            buy_fees_usd=fee,
            commission_usd=fee,
        )
        shares = (cash_usd - fee) / price if price > 0 else 0.0
        return shares, fee, breakdown

    def exit_proceeds(self, shares: float, price: float, breakdown: TradeCostBreakdown) -> tuple[float, TradeCostBreakdown]:
        notional = shares * price
        fee = notional * self.commission_pct
        breakdown.sell_fees_usd = fee
        breakdown.commission_usd += fee
        return notional - fee, breakdown

    def apply_entry_slippage(self, price: float, side: str, extra_bps: float = 0.0) -> float:
        return price

    def apply_exit_slippage(self, price: float, side: str, extra_bps: float = 0.0) -> float:
        return price

    def record_slippage(
        self, shares: float, raw_price: float, slipped_price: float, breakdown: TradeCostBreakdown, *, is_entry: bool
    ) -> None:
        return

    def open_short(self, cash_usd: float, price: float) -> tuple[float, float, TradeCostBreakdown]:
        shares = cash_usd / price if price > 0 else 0.0
        fee = cash_usd * self.commission_pct
        breakdown = TradeCostBreakdown(sell_fees_usd=fee, commission_usd=fee)
        return shares, fee, breakdown

    def settle_long(
        self,
        cash_at_entry: float,
        shares: float,
        entry_price: float,
        exit_price: float,
        breakdown: TradeCostBreakdown,
    ) -> tuple[float, float, float, TradeCostBreakdown]:
        proceeds, breakdown = self.exit_proceeds(shares, exit_price, breakdown)
        net_pct = (proceeds - cash_at_entry) / cash_at_entry * 100 if cash_at_entry else 0.0
        gross_pct = (exit_price / entry_price - 1) * 100 if entry_price else 0.0
        return proceeds, net_pct, gross_pct, breakdown

    def settle_short(
        self,
        cash_at_entry: float,
        shares: float,
        entry_price: float,
        exit_price: float,
        breakdown: TradeCostBreakdown,
    ) -> tuple[float, float, float, TradeCostBreakdown]:
        notional = shares * exit_price
        fee = notional * self.commission_pct
        breakdown.buy_fees_usd += fee
        breakdown.commission_usd += fee
        net_dollar = shares * (entry_price - exit_price) - breakdown.sell_fees_usd - fee
        cash_after = cash_at_entry + net_dollar
        net_pct = net_dollar / cash_at_entry * 100 if cash_at_entry else 0.0
        gross_pct = (entry_price / exit_price - 1) * 100 if exit_price else 0.0
        return cash_after, net_pct, gross_pct, breakdown


@dataclass
class AlpacaCostModel:
    """
    Alpaca equities cost model from published fee schedule.

    - $0 commission (self-directed API cash account)
    - SEC + FINRA TAF on sells
    - FINRA CAT on buys and sells (rounded up to $0.01)
    """

    sec_rate: float = 0.0000206
    taf_per_share: float = 0.000195
    taf_max_usd: float = 9.79
    cat_per_share: float = 0.000003
    commission_per_share: float = 0.0
    commission_per_trade: float = 0.0
    round_up: bool = True
    entry_slippage_bps: float = 0.0
    exit_slippage_bps: float = 0.0
    name: str = "alpaca"

    @classmethod
    def from_config(cls, cfg: dict[str, Any], style: str, *, conservative: bool = False) -> AlpacaCostModel:
        reg = cfg.get("regulatory", {})
        slip_root = cfg.get("conservative" if conservative else "slippage", {})
        slip = slip_root.get(style, {})
        return cls(
            sec_rate=float(reg.get("sec_rate_per_dollar", 0.0000206)),
            taf_per_share=float(reg.get("finra_taf_per_share", 0.000195)),
            taf_max_usd=float(reg.get("finra_taf_max_usd", 9.79)),
            cat_per_share=float(reg.get("cat_per_share", 0.000003)),
            commission_per_share=float(cfg.get("commission_per_share", 0.0)),
            commission_per_trade=float(cfg.get("commission_per_trade", 0.0)),
            round_up=bool(reg.get("round_up_to_cent", True)),
            entry_slippage_bps=float(slip.get("entry_bps", 5.0)),
            exit_slippage_bps=float(slip.get("exit_bps", 5.0)),
            name="alpaca_conservative" if conservative else "alpaca",
        )

    def _round(self, amount: float) -> float:
        return _round_up_cent(amount) if self.round_up else amount

    def buy_fees(self, shares: float) -> float:
        if shares <= 0:
            return 0.0
        cat = shares * self.cat_per_share
        commission = self.commission_per_trade + shares * self.commission_per_share
        return self._round(cat + commission)

    def sell_fees(self, shares: float, price: float) -> tuple[float, float, float, float]:
        if shares <= 0 or price <= 0:
            return 0.0, 0.0, 0.0, 0.0
        notional = shares * price
        sec = notional * self.sec_rate
        taf = min(shares * self.taf_per_share, self.taf_max_usd)
        cat = shares * self.cat_per_share
        commission = self.commission_per_trade + shares * self.commission_per_share
        sec_r = self._round(sec)
        taf_r = self._round(taf)
        cat_r = self._round(cat)
        comm_r = self._round(commission)
        return sec_r, taf_r, cat_r, comm_r

    def solve_entry(self, cash_usd: float, price: float) -> tuple[float, float, TradeCostBreakdown]:
        if price <= 0 or cash_usd <= 0:
            return 0.0, 0.0, TradeCostBreakdown()
        shares = cash_usd / price
        for _ in range(8):
            fees = self.buy_fees(shares)
            shares = max((cash_usd - fees) / price, 0.0)
        fees = self.buy_fees(shares)
        breakdown = TradeCostBreakdown(buy_fees_usd=fees, cat_fee_usd=fees)
        return shares, fees, breakdown

    def exit_proceeds(
        self, shares: float, price: float, breakdown: TradeCostBreakdown
    ) -> tuple[float, TradeCostBreakdown]:
        sec, taf, cat, comm = self.sell_fees(shares, price)
        sell_fees = sec + taf + cat + comm
        breakdown.sell_fees_usd = sell_fees
        breakdown.sec_fee_usd = sec
        breakdown.taf_fee_usd = taf
        breakdown.cat_fee_usd = breakdown.cat_fee_usd + cat
        breakdown.commission_usd += comm
        proceeds = shares * price - sell_fees
        return proceeds, breakdown

    def apply_entry_slippage(self, price: float, side: str, extra_bps: float = 0.0) -> float:
        bps = self.entry_slippage_bps + extra_bps
        if bps <= 0:
            return price
        slip = bps / 10_000
        return price * (1 + slip) if side == "long" else price * (1 - slip)

    def apply_exit_slippage(self, price: float, side: str, extra_bps: float = 0.0) -> float:
        bps = self.exit_slippage_bps + extra_bps
        if bps <= 0:
            return price
        slip = bps / 10_000
        # Exiting long = sell (receive lower); exiting short = buy cover (pay higher)
        return price * (1 - slip) if side == "long" else price * (1 + slip)

    def record_slippage(
        self, shares: float, raw_price: float, slipped_price: float, breakdown: TradeCostBreakdown, *, is_entry: bool
    ) -> None:
        diff = abs(slipped_price - raw_price) * shares
        if is_entry:
            breakdown.slippage_entry_usd = diff
        else:
            breakdown.slippage_exit_usd = diff

    def open_short(self, cash_usd: float, price: float) -> tuple[float, float, TradeCostBreakdown]:
        if price <= 0 or cash_usd <= 0:
            return 0.0, 0.0, TradeCostBreakdown()
        shares = cash_usd / price
        sec, taf, cat, comm = self.sell_fees(shares, price)
        sell_fees = sec + taf + cat + comm
        breakdown = TradeCostBreakdown(
            sell_fees_usd=sell_fees,
            sec_fee_usd=sec,
            taf_fee_usd=taf,
            cat_fee_usd=cat,
            commission_usd=comm,
        )
        return shares, sell_fees, breakdown

    def settle_long(
        self,
        cash_at_entry: float,
        shares: float,
        entry_price: float,
        exit_price: float,
        breakdown: TradeCostBreakdown,
    ) -> tuple[float, float, float, TradeCostBreakdown]:
        proceeds, breakdown = self.exit_proceeds(shares, exit_price, breakdown)
        net_pct = (proceeds - cash_at_entry) / cash_at_entry * 100 if cash_at_entry else 0.0
        gross_pct = (exit_price / entry_price - 1) * 100 if entry_price else 0.0
        return proceeds, net_pct, gross_pct, breakdown

    def settle_short(
        self,
        cash_at_entry: float,
        shares: float,
        entry_price: float,
        exit_price: float,
        breakdown: TradeCostBreakdown,
    ) -> tuple[float, float, float, TradeCostBreakdown]:
        cover_fee = self.buy_fees(shares)
        cover_cost = shares * exit_price + cover_fee
        entry_credit = shares * entry_price - breakdown.sell_fees_usd
        net_dollar = entry_credit - cover_cost
        breakdown.buy_fees_usd += cover_fee
        breakdown.cat_fee_usd += cover_fee
        cash_after = cash_at_entry + net_dollar
        net_pct = net_dollar / cash_at_entry * 100 if cash_at_entry else 0.0
        gross_pct = (entry_price / exit_price - 1) * 100 if exit_price else 0.0
        return cash_after, net_pct, gross_pct, breakdown


def load_cost_model(
    preset: CostPreset,
    style: str,
    cfg_defaults: dict[str, Any] | None = None,
) -> LegacyCostModel | AlpacaCostModel:
    from signalforge.config import load_cost_config

    if preset == "legacy":
        defaults = cfg_defaults or {}
        return LegacyCostModel(commission_pct=float(defaults.get("commission_pct", 0.00005)))

    alpaca_cfg = load_cost_config("alpaca")
    conservative = preset == "alpaca_conservative"
    return AlpacaCostModel.from_config(alpaca_cfg, style, conservative=conservative)
