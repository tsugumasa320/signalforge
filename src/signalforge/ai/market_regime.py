"""Global market regime (地合い) from major index / ETF proxies.

Uses local OHLCV cache (yfinance). Not investment advice; no brokerage.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from signalforge.ai.packet import read_json, utc_now_iso, write_json
from signalforge.ai.paths import published_path
from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher

SCHEMA = "signalforge-market-regime/v1"
PUBLISHED_NAME = "market_regime.json"

# Prefer JP-listed ETFs for Nikkei/TOPIX (same cache as rest of SignalForge).
# US cash indices via Yahoo.
INDEX_SPECS: list[dict[str, str]] = [
    {"id": "nikkei", "ticker": "1321.T", "name": "日経平均（1321 ETF）", "region": "jp"},
    {"id": "topix", "ticker": "1306.T", "name": "TOPIX（1306 ETF）", "region": "jp"},
    {"id": "dow", "ticker": "^DJI", "name": "NYダウ", "region": "us"},
    {"id": "spx", "ticker": "^GSPC", "name": "S&P 500", "region": "us"},
    {"id": "nasdaq", "ticker": "^IXIC", "name": "NASDAQ総合", "region": "us"},
]


def market_regime_path():
    return published_path(PUBLISHED_NAME)


def load_market_regime() -> dict[str, Any] | None:
    raw = read_json(market_regime_path())
    return raw if isinstance(raw, dict) else None


def _close_series(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)
    col = "close" if "close" in df.columns else ("Close" if "Close" in df.columns else None)
    if col is None:
        return pd.Series(dtype=float)
    s = df[col].astype(float).dropna().sort_index()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index, utc=True)
    elif s.index.tz is None:
        s.index = s.index.tz_localize("UTC")
    else:
        s.index = s.index.tz_convert("UTC")
    return s


def _ret(s: pd.Series, n: int) -> float | None:
    if len(s) <= n:
        return None
    a, b = float(s.iloc[-1]), float(s.iloc[-(n + 1)])
    if b == 0:
        return None
    return a / b - 1.0


def _vs_ma(s: pd.Series, window: int) -> float | None:
    if len(s) < window:
        return None
    ma = float(s.iloc[-window:].mean())
    if ma == 0:
        return None
    return float(s.iloc[-1]) / ma - 1.0


def _stance(ret_20d: float | None, vs_ma200: float | None) -> str:
    """Local risk stance for one index."""
    if ret_20d is None and vs_ma200 is None:
        return "unknown"
    score = 0
    if ret_20d is not None:
        if ret_20d >= 0.02:
            score += 1
        elif ret_20d <= -0.02:
            score -= 1
    if vs_ma200 is not None:
        if vs_ma200 >= 0:
            score += 1
        else:
            score -= 1
    if score >= 2:
        return "risk_on"
    if score <= -2:
        return "risk_off"
    return "mixed"


def analyze_series(close: pd.Series) -> dict[str, Any]:
    as_of = None
    if not close.empty:
        as_of = str(pd.Timestamp(close.index[-1]).date())
    ret_1d = _ret(close, 1)
    ret_5d = _ret(close, 5)
    ret_20d = _ret(close, 20)
    vs25 = _vs_ma(close, 25)
    vs200 = _vs_ma(close, 200)
    stance = _stance(ret_20d, vs200)
    return {
        "as_of": as_of,
        "last": float(close.iloc[-1]) if len(close) else None,
        "ret_1d": ret_1d,
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "vs_ma25": vs25,
        "vs_ma200": vs200,
        "stance": stance,
        "n_bars": int(len(close)),
    }


def _load_close(ticker: str, *, refresh: bool) -> pd.Series:
    cache = ParquetCache()
    fetcher = MarketDataFetcher(data_source="yfinance")
    try:
        if refresh:
            df = cache.update(ticker, "1d", fetcher)
        else:
            df = cache.load_or_fetch(ticker, "1d", fetcher, refresh=False)
    except Exception as exc:  # noqa: BLE001 — keep other indices usable
        return pd.Series(dtype=float, name=str(exc))
    return _close_series(df)


def _region_label(stances: list[str]) -> str:
    known = [s for s in stances if s != "unknown"]
    if not known:
        return "unknown"
    on = sum(1 for s in known if s == "risk_on")
    off = sum(1 for s in known if s == "risk_off")
    if on == len(known):
        return "risk_on"
    if off == len(known):
        return "risk_off"
    if on > off:
        return "mixed_on"
    if off > on:
        return "mixed_off"
    return "mixed"


def _overall(jp: str, us: str) -> str:
    if jp == "unknown" and us == "unknown":
        return "unknown"
    if jp == "risk_on" and us == "risk_on":
        return "risk_on"
    if jp == "risk_off" and us == "risk_off":
        return "risk_off"
    if "off" in jp or "off" in us:
        if "on" in jp or "on" in us:
            return "mixed"
        return "risk_off" if jp == "risk_off" or us == "risk_off" else "mixed_off"
    if jp == "risk_on" or us == "risk_on":
        return "mixed_on" if jp != us else "risk_on"
    return "mixed"


def _takeaway(overall: str, indices: list[dict[str, Any]]) -> str:
    labels = {
        "risk_on": "地合い強め（リスクオン寄り）",
        "mixed_on": "地合いやや強め",
        "mixed": "地合いまちまち",
        "mixed_off": "地合いやや弱め",
        "risk_off": "地合い弱め（リスクオフ寄り）",
        "unknown": "地合い判定不能（データ不足）",
    }
    bits = [labels.get(overall, overall)]
    for row in indices:
        r20 = row.get("ret_20d")
        if r20 is None:
            continue
        bits.append(f"{row.get('name')}:20日{r20:+.1%}/{row.get('stance')}")
    return " · ".join(bits[:6])


def build_market_regime(*, refresh: bool = False) -> dict[str, Any]:
    indices: list[dict[str, Any]] = []
    for spec in INDEX_SPECS:
        close = _load_close(spec["ticker"], refresh=refresh)
        metrics = analyze_series(close)
        indices.append(
            {
                **spec,
                **metrics,
                "ok": metrics.get("n_bars", 0) >= 25,
            }
        )

    jp = _region_label([i["stance"] for i in indices if i.get("region") == "jp"])
    us = _region_label([i["stance"] for i in indices if i.get("region") == "us"])
    overall = _overall(jp, us)
    as_ofs = [i.get("as_of") for i in indices if i.get("as_of")]
    as_of = max(as_ofs) if as_ofs else None

    payload = {
        "schema": SCHEMA,
        "generated_at": utc_now_iso(),
        "as_of": as_of,
        "overall": overall,
        "jp": jp,
        "us": us,
        "takeaway": _takeaway(overall, indices),
        "indices": indices,
        "notes": [
            "JPは東証ETF（1321/1306）、米はYahoo現金指数。",
            "完全なマクロモデルではなく、短期リターンと200日線の簡易地合い。",
            "発注には接続しない。",
        ],
    }
    write_json(market_regime_path(), payload)
    return payload
