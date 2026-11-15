"""Global market regime (地合い) from major index / ETF / futures proxies.

Uses local OHLCV cache (yfinance). Not investment advice; no brokerage.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from signalforge.ai.packet import read_json, utc_now_iso, write_json
from signalforge.ai.paths import published_path
from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher

SCHEMA = "signalforge-market-regime/v2"
PUBLISHED_NAME = "market_regime.json"

# Spot: JP ETFs + US cash indices. Futures: CME / SGX-style Yahoo continuous.
INDEX_SPECS: list[dict[str, str]] = [
    {"id": "nikkei", "ticker": "1321.T", "name": "日経平均（1321 ETF）", "region": "jp", "asset": "spot"},
    {"id": "topix", "ticker": "1306.T", "name": "TOPIX（1306 ETF）", "region": "jp", "asset": "spot"},
    {"id": "dow", "ticker": "^DJI", "name": "NYダウ", "region": "us", "asset": "spot"},
    {"id": "spx", "ticker": "^GSPC", "name": "S&P 500", "region": "us", "asset": "spot"},
    {"id": "nasdaq", "ticker": "^IXIC", "name": "NASDAQ総合", "region": "us", "asset": "spot"},
    {"id": "niy_fut", "ticker": "NIY=F", "name": "日経225先物", "region": "jp", "asset": "future"},
    {"id": "ym_fut", "ticker": "YM=F", "name": "ダウ先物", "region": "us", "asset": "future"},
    {"id": "es_fut", "ticker": "ES=F", "name": "S&P500先物", "region": "us", "asset": "future"},
    {"id": "nq_fut", "ticker": "NQ=F", "name": "NASDAQ100先物", "region": "us", "asset": "future"},
]

STANCE_JA = {
    "risk_on": "強気（リスクオン）",
    "mixed_on": "やや強気",
    "mixed": "まちまち",
    "mixed_off": "やや弱気",
    "risk_off": "弱気（リスクオフ）",
    "unknown": "不明",
}

STANCE_HELP = {
    "risk_on": "直近20日がおおむね上昇し、価格が200日線の上 → 資金がリスク資産に向かいやすい局面の目安",
    "mixed_on": "強気寄りだが指数間でバラつきあり",
    "mixed": "上げ下げ・線上下が混在。方向感が薄い",
    "mixed_off": "弱気寄りだが指数間でバラつきあり",
    "risk_off": "直近20日がおおむね下落し、価格が200日線の下 → 守り・現金寄りになりやすい局面の目安",
    "unknown": "データ不足で判定できない",
}


def market_regime_path():
    return published_path(PUBLISHED_NAME)


def load_market_regime() -> dict[str, Any] | None:
    raw = read_json(market_regime_path())
    return raw if isinstance(raw, dict) else None


def stance_label_ja(stance: str | None) -> str:
    return STANCE_JA.get(str(stance or ""), str(stance or "—"))


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
    """Local risk stance for one series."""
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
        "stance_ja": stance_label_ja(stance),
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
    except Exception as exc:  # noqa: BLE001 — keep other series usable
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


def _blend(*labels: str) -> str:
    known = [x for x in labels if x and x != "unknown"]
    if not known:
        return "unknown"
    if all(x == "risk_on" for x in known):
        return "risk_on"
    if all(x == "risk_off" for x in known):
        return "risk_off"
    ons = sum(1 for x in known if "on" in x and "off" not in x)
    offs = sum(1 for x in known if "off" in x)
    if ons and offs:
        return "mixed"
    if offs:
        return "mixed_off" if offs < len(known) else "risk_off"
    if ons:
        return "mixed_on" if ons < len(known) else "risk_on"
    return "mixed"


def _takeaway(overall: str, indices: list[dict[str, Any]]) -> str:
    bits = [stance_label_ja(overall)]
    # Prefer futures first in the short summary (more leading), then spot
    ordered = sorted(indices, key=lambda r: 0 if r.get("asset") == "future" else 1)
    for row in ordered:
        r20 = row.get("ret_20d")
        if r20 is None:
            continue
        bits.append(f"{row.get('name')}:20日{r20:+.1%}/{row.get('stance_ja') or row.get('stance')}")
    return " · ".join(bits[:8])


def build_market_regime(*, refresh: bool = False) -> dict[str, Any]:
    indices: list[dict[str, Any]] = []
    for spec in INDEX_SPECS:
        close = _load_close(spec["ticker"], refresh=refresh)
        metrics = analyze_series(close)
        # Futures continuous contracts: shorter MA is fine for stance when <200 bars
        if spec.get("asset") == "future" and metrics.get("vs_ma200") is None and metrics.get("n_bars", 0) >= 25:
            # re-stance with available vs_ma25 if 200d missing
            metrics["stance"] = _stance(metrics.get("ret_20d"), metrics.get("vs_ma25"))
            metrics["stance_ja"] = stance_label_ja(metrics["stance"])
        indices.append(
            {
                **spec,
                **metrics,
                "ok": metrics.get("n_bars", 0) >= 25,
            }
        )

    spot = [i for i in indices if i.get("asset") == "spot"]
    futs = [i for i in indices if i.get("asset") == "future"]
    jp = _region_label([i["stance"] for i in indices if i.get("region") == "jp"])
    us = _region_label([i["stance"] for i in indices if i.get("region") == "us"])
    futures = _region_label([i["stance"] for i in futs])
    spot_lbl = _region_label([i["stance"] for i in spot])
    overall = _blend(spot_lbl, futures)

    as_ofs = [i.get("as_of") for i in indices if i.get("as_of")]
    as_of = max(as_ofs) if as_ofs else None

    payload = {
        "schema": SCHEMA,
        "generated_at": utc_now_iso(),
        "as_of": as_of,
        "overall": overall,
        "overall_ja": stance_label_ja(overall),
        "jp": jp,
        "jp_ja": stance_label_ja(jp),
        "us": us,
        "us_ja": stance_label_ja(us),
        "spot": spot_lbl,
        "futures": futures,
        "futures_ja": stance_label_ja(futures),
        "takeaway": _takeaway(overall, indices),
        "legend": STANCE_HELP,
        "legend_ja": STANCE_JA,
        "indices": indices,
        "notes": [
            "現金指数: JP=東証ETF（1321/1306）、米=Yahoo現金指数。",
            "先物: NIY=F（日経）、YM/ES/NQ=F（米株価指数先物・連続）。",
            "判定は直近20日リターン（±2%）と200日線上下の簡易ルール。売買シグナルではない。",
            "発注には接続しない。",
        ],
    }
    write_json(market_regime_path(), payload)
    return payload
