"""日足と通期財務の取得。バックテスト用の調整済みキャッシュとは別置き。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from signalforge.config import data_dir
from signalforge.research.trend_screen.config import PRICE_START
from signalforge.research.trend_screen.fundamentals import AnnualPoint
from signalforge.research.trend_screen.statements import annuals_from_frames
from signalforge.research.trend_screen.universe import is_common_code

BAR_COLUMNS = ("open", "high", "low", "close", "volume", "adj_close")
PRICE_SOURCE = "yfinance日足。closeは分割調整後の株価、adj_closeは配当込みに近い調整終値。スコアはclose。"
FUND_SOURCE = "yfinanceの年次損益・貸借・キャッシュフロー。通貨単位の再検証はしていない。"


def _root() -> Path:
    path = data_dir() / "trend_screen"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bar_path(ticker: str) -> Path:
    return _root() / "bars" / f"{ticker.replace('/', '_')}.pkl"


def _fin_path(ticker: str) -> Path:
    return _root() / "fins" / f"{ticker.replace('/', '_')}.json"


def _flatten(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        if "Close" in out.columns.get_level_values(0):
            out.columns = out.columns.get_level_values(0)
        elif "Close" in out.columns.get_level_values(1):
            out.columns = out.columns.get_level_values(1)
        else:
            out.columns = out.columns.get_level_values(0)
    return out


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    data = _flatten(frame)
    rename = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    }
    data = data.rename(columns=rename)
    if "close" not in data.columns:
        raise ValueError("日足にCloseがありません。")
    index = pd.to_datetime(data.index)
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    data.index = pd.DatetimeIndex(index).normalize()
    data = data[~data.index.duplicated(keep="last")].sort_index()
    for column in BAR_COLUMNS:
        if column not in data.columns:
            data[column] = pd.NA
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["close"])
    if data["adj_close"].isna().all():
        data = data.drop(columns=["adj_close"])
    keep = [column for column in BAR_COLUMNS if column in data.columns]
    return data[keep]


def load_bars(ticker: str, *, refresh: bool = False) -> pd.DataFrame:
    path = _bar_path(ticker)
    if path.exists() and not refresh:
        cached = pd.read_pickle(path)
        cached.index = pd.to_datetime(cached.index)
        return cached
    frame = yf.download(
        ticker,
        start=PRICE_START,
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    if frame is None or frame.empty:
        raise ValueError(f"{ticker} の日足が空です。")
    bars = _normalize_bars(frame)
    if bars.empty:
        raise ValueError(f"{ticker} の終値が空です。")
    path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_pickle(path)
    return bars


def _point_from_json(row: dict) -> AnnualPoint:
    return AnnualPoint(
        fiscal_end=str(row.get("fiscal_end") or ""),
        sales=row.get("sales"),
        operating_income=row.get("operating_income"),
        eps=row.get("eps"),
        net_income=row.get("net_income"),
        operating_cf=row.get("operating_cf"),
        equity=row.get("equity"),
        assets=row.get("assets"),
    )


def load_annuals(ticker: str, *, refresh: bool = False) -> tuple[list[AnnualPoint], str]:
    path = _fin_path(ticker)
    if path.exists() and not refresh:
        payload = json.loads(path.read_text(encoding="utf-8"))
        annuals = [_point_from_json(row) for row in payload.get("annuals") or []]
        return annuals, str(payload.get("source") or FUND_SOURCE)
    ticker_obj = yf.Ticker(ticker)
    try:
        income = ticker_obj.income_stmt
        balance = ticker_obj.balance_sheet
        cash = ticker_obj.cashflow
    except Exception as exc:
        raise ValueError(f"{ticker} の財務取得に失敗: {exc}") from exc
    annuals = annuals_from_frames(income, balance, cash)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": FUND_SOURCE,
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "annuals": [row.__dict__ for row in annuals],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return annuals, FUND_SOURCE


def load_market_cap(ticker: str) -> float | None:
    try:
        info = yf.Ticker(ticker).fast_info
        value = getattr(info, "market_cap", None)
        if value is None and isinstance(info, dict):
            value = info.get("market_cap")
        if value is None:
            return None
        number = float(value)
    except Exception:
        return None
    if number <= 0:
        return None
    return number


def load_benchmark(*, refresh: bool = False) -> tuple[pd.Series | None, str]:
    candidates = (
        ("^TOPX", "Yahoo ^TOPX。TOPIX指数そのものかは系列名以上の検証をしていない。"),
        ("1306.T", "TOPIX連動ETF 1306（NEXT FUNDS TOPIX）。指数そのものではない。"),
        ("1475.T", "iシェアーズ・コア TOPIX ETF。指数そのものではない。"),
    )
    errors: list[str] = []
    for symbol, label in candidates:
        try:
            bars = load_bars(symbol if symbol.startswith("^") else symbol, refresh=refresh)
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            continue
        close = bars["close"].dropna()
        if len(close) < 800:
            errors.append(f"{symbol}: 日足が{len(close)}本")
            continue
        return close, f"{label} 基準日 {pd.Timestamp(close.index[-1]).date().isoformat()}。"
    return None, "TOPIX相対は未確認。" + " ".join(errors)


def listing_snapshot() -> dict:
    from collections import Counter

    from signalforge.universe.tse_listing import load_tse_listing

    doc = load_tse_listing(refresh=False)
    rows = list(doc.get("tickers") or [])
    common = [row for row in rows if is_common_code(str(row.get("ticker") or ""))]
    return {
        "fetched_at": str(doc.get("fetched_at") or "未確認"),
        "source_url": str(doc.get("source_url") or "未確認"),
        "domestic_rows": len(rows),
        "common_rows": len(common),
        "by_segment": dict(Counter(str(row.get("segment") or "未確認") for row in common)),
        "table": {str(row["ticker"]): row for row in common if row.get("ticker")},
    }
