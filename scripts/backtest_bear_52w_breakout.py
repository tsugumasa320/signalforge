#!/usr/bin/env python3
"""Test a fixed 52-week-high relative-strength strategy during a bear regime."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

from compare_long_stocks import load_local, signals as base_signals
from signalforge.research.broad_pit import Spec, simulate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/bear_regime_20261122/52w_breakout_rs.json"
START = "2016-01-04"
END = "2026-08-28"
INITIAL = 3_000_000.0
FEE = 0.00105
SLIP = 0.0003


def main() -> None:
    m, audit = load_local(membership_guard=True)
    _, atr, box, _ = base_signals(m, market_filter=False)

    close = m["C"]
    high = m["H"]
    index = close["13210"]
    market_ma200 = index.rolling(200).mean()
    below_market = index.lt(market_ma200).fillna(False)

    own_ma200 = close.rolling(200).mean()
    own_ma50 = close.rolling(50).mean()
    prior_252_high = high.shift(1).rolling(252).max()
    relative_60d = close.pct_change(60, fill_method=None).sub(
        index.pct_change(60, fill_method=None), axis=0
    )

    # All features are observable at the signal close; orders fill next open.
    strong_stock = (close > own_ma200) & (own_ma200 > own_ma200.shift(21))
    eligible = m["active"] & m["Va"].ge(500_000_000)
    entry = (
        (close > prior_252_high)
        & strong_stock
        & relative_60d.gt(0)
        & eligible
        & below_market.to_numpy()[:, None]
    ).fillna(False).to_numpy()

    # A close under the stock's 50-day average is a next-open exit.
    exit_stock = close.lt(own_ma50).fillna(False).to_numpy()
    exit_market = (~below_market).to_numpy()[:, None]
    exit_signal = exit_stock | exit_market
    score = relative_60d.fillna(-1e30).to_numpy()

    start_i = int(close.index.searchsorted(pd.Timestamp(START)))
    end_i = int(close.index.searchsorted(pd.Timestamp(END), side="right") - 1)
    entry[:start_i] = False
    entry[end_i + 1 :] = False

    spec = Spec("bear_52w_high_rs", "bear_52w_high_rs", 120, 2.0, None)
    results = []
    for cost_multiple in (1, 2, 3):
        sig = {"enter": entry.copy(), "exit": exit_signal.copy(), "score": score.copy()}
        r = simulate(
            m,
            sig,
            spec,
            atr,
            box,
            start_i,
            fee=FEE * cost_multiple,
            slip=SLIP * cost_multiple,
            fractional_research=True,
        )
        daily = pd.DataFrame(r["daily"])
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily[daily["date"].between(START, END)]
        equity = daily["equity"].to_numpy()
        peak = np.maximum.accumulate(equity)
        exit_reasons = Counter(
            order.get("reason", "unknown")
            for order in r["orders"]
            if order["side"] == "sell"
        )
        row = {
            "cost_multiple": cost_multiple,
            "return_pct": float((equity[-1] / INITIAL - 1) * 100),
            "cagr_pct": float(
                ((equity[-1] / INITIAL) ** (365.25 / (pd.Timestamp(END) - pd.Timestamp(START)).days) - 1)
                * 100
            ),
            "max_dd_pct": float((equity / peak - 1).min() * 100),
            "final_equity_jpy": float(equity[-1]),
            "buys": int(r["buys"]),
            "closed_trades": int(r["closed_trades"]),
            "mean_invested_pct": float(
                ((daily["equity"] - daily["cash"]) / daily["equity"]).mean() * 100
            ),
            "exit_reasons": dict(exit_reasons),
            "unresolved_positions": len(r["unresolved_positions"]),
            "corporate_action_flags": len(r["corporate_action_exposures"]),
        }
        results.append(row)
        print(
            f"cost={cost_multiple}x return={row['return_pct']:.2f}% "
            f"CAGR={row['cagr_pct']:.2f}% maxDD={row['max_dd_pct']:.2f}% "
            f"buys={row['buys']} closed={row['closed_trades']} "
            f"invested={row['mean_invested_pct']:.2f}% "
            f"exits={dict(exit_reasons)}",
            flush=True,
        )

    source_paths = [
        Path(__file__),
        ROOT / "scripts/compare_long_stocks.py",
        ROOT / "src/signalforge/research/broad_pit.py",
    ]
    output = {
        "period": {"start": START, "end": END},
        "universe_count": audit["stock_count"],
        "market_below_200_sessions": int(below_market.loc[START:END].sum()),
        "market_below_200_periods": int(
            (below_market.loc[START:END]
             & ~below_market.loc[START:END].shift(1, fill_value=False)).sum()
        ),
        "capital_jpy": INITIAL,
        "rules": {
            "entry": "1321 closes below its 200-day SMA; stock closes above its prior 252-session high, above its own 200-day SMA with that SMA higher than 21 sessions earlier, and its 60-session return exceeds 1321's. Turnover proxy >= JPY 500m.",
            "ranking": "60-session excess return versus 1321, descending.",
            "portfolio": "Max 5 stocks, 20% per stock, max 2 per sector.",
            "stop": "2ATR below entry using prior-session ATR; intraday low trigger, gap exits may be worse.",
            "other_exits": "Sell next open after stock close falls below its 50-day SMA, 1321 closes above its 200-day SMA, or 120 sessions elapse.",
            "execution": "Entry signals at close and next-open execution; 0.105% fee and 0.03% slippage per side at 1x; adjusted prices and fractional research shares.",
        },
        "limitations": [
            "Exploratory historical comparison; no independent untouched out-of-sample period.",
            "Current-survivor universe and adjusted prices; historical membership, delistings, corporate actions, and actual board lots are incomplete.",
            "Turnover is a price-times-volume proxy, not historical exchange-recorded yen turnover.",
            "Open positions at the period end are marked to market, not forcibly liquidated.",
        ],
        "results": results,
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths
        },
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
