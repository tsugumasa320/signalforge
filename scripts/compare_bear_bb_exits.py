#!/usr/bin/env python3
"""Compare a small, predeclared set of exits for the bear-regime BB+RSI entry."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

from compare_long_stocks import load_local
from explore_bear_regime import build_stock_signals
from signalforge.research.broad_pit import Spec, simulate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/bear_regime_20261122/bb_exit_sensitivity.json"
START = "2016-01-04"
END = "2026-08-28"
INITIAL = 3_000_000.0
FEE = 0.00105
SLIP = 0.0003


def main() -> None:
    m, audit = load_local(membership_guard=True)
    stock_signals, atr, box = build_stock_signals(m)
    close = m["C"]
    index = close["13210"]
    below = index.lt(index.rolling(200).mean()).fillna(False)
    start_i = int(close.index.searchsorted(pd.Timestamp(START)))
    end_i = int(close.index.searchsorted(pd.Timestamp(END), side="right") - 1)
    bear = below.to_numpy(copy=True)
    bear[:start_i] = False
    bear[end_i + 1 :] = False
    exit_market = np.repeat((~below.to_numpy())[:, None], close.shape[1], axis=1)

    entry = stock_signals["bb_rsi_120"]["enter"].copy()
    entry &= bear[:, None]

    middle = close.rolling(20).mean()
    middle_exit = (close >= middle) & (close.shift() < middle.shift())

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    rsi_exit = (rsi >= 50) & (rsi.shift() < 50)

    candidates = [
        ("no_fixed_target", 2.0, None, None,
         "固定利食いなし。指数200日線回復・120営業日・2ATR損切りで退出。"),
        ("middle_band", 2.0, None, middle_exit,
         "終値が20日移動平均を下から上へ回復したら翌営業日始値で退出。"),
        ("rsi_cross_50", 2.0, None, rsi_exit,
         "RSI14が50を下から上へ回復したら翌営業日始値で退出。"),
        ("take_profit_1atr", 2.0, 1.0, None,
         "買値+1ATRに日中高値が到達したら利食い。"),
        ("take_profit_2atr", 2.0, 2.0, None,
         "買値+2ATRに日中高値が到達したら利食い。"),
    ]

    results = []
    for name, stop_atr, take_atr, signal_exit, rule in candidates:
        sell_signal = exit_market.copy()
        if signal_exit is not None:
            sell_signal |= signal_exit.to_numpy()
        sig = {
            "enter": entry.copy(),
            "exit": sell_signal,
            "score": m["Va"].fillna(0).to_numpy(),
        }
        spec = Spec(name, "bb_rsi_120", 120, stop_atr, take_atr)
        cost_multiples = (1, 2, 3) if name in ("no_fixed_target", "rsi_cross_50") else (1,)
        for cost_multiple in cost_multiples:
            r = simulate(
                m, sig, spec, atr, box, start_i,
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
                for order in r["orders"] if order["side"] == "sell"
            )
            results.append({
                "name": name,
                "cost_multiple": cost_multiple,
                "rule": rule,
                "return_pct": float((equity[-1] / INITIAL - 1) * 100),
                "cagr_pct": float(((equity[-1] / INITIAL) ** (365.25 / (pd.Timestamp(END) - pd.Timestamp(START)).days) - 1) * 100),
                "max_dd_pct": float((equity / peak - 1).min() * 100),
                "final_equity_jpy": float(equity[-1]),
                "closed_trades": int(r["closed_trades"]),
                "exit_reasons": dict(exit_reasons),
                "unresolved_positions": len(r["unresolved_positions"]),
                "corporate_action_flags": len(r["corporate_action_exposures"]),
            })
            print(
                f"{name} cost={cost_multiple}x: "
                f"return={results[-1]['return_pct']:.2f}% "
                f"CAGR={results[-1]['cagr_pct']:.2f}% "
                f"maxDD={results[-1]['max_dd_pct']:.2f}% "
                f"trades={r['closed_trades']} exits={dict(exit_reasons)}",
                flush=True,
            )

    sources = [
        Path(__file__),
        ROOT / "scripts/explore_bear_regime.py",
        ROOT / "scripts/compare_long_stocks.py",
        ROOT / "src/signalforge/research/broad_pit.py",
    ]
    output = {
        "period": {"start": START, "end": END},
        "universe_count": audit["stock_count"],
        "regime_sessions": int(bear[start_i : end_i + 1].sum()),
        "regime_periods": int((below.loc[START:END] & ~below.loc[START:END].shift(1, fill_value=False)).sum()),
        "capital_jpy": INITIAL,
        "common_rules": {
            "entry": "Nikkei 225 ETF 1321 below SMA200; stock close at/below prior-known 20-day Bollinger lower band (-2 sigma), RSI14 <= 30, turnover proxy >= JPY 500m.",
            "selection": "Top turnover proxy; max 5 names, 20% each, max 2 per sector.",
            "stop": "2ATR below entry using prior-session ATR; intraday low trigger, gap exits may be worse.",
            "timeout": "120 trading sessions, sell at next open.",
            "market_exit": "When 1321 closes back above SMA200, sell next open.",
            "execution": "Next-open entries, 0.105% fee and 0.03% slippage per side; adjusted prices and fractional research shares.",
        },
        "limitations": [
            "Exploratory in-sample comparison; all rules were chosen after viewing this historical period.",
            "Current survivor universe and adjusted prices; historical membership, delistings, corporate actions, and board lots are incomplete.",
            "No independent untouched out-of-sample period; do not treat the best row as an adopted or deployable strategy.",
        ],
        "results": results,
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
