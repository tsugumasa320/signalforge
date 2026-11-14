"""yfinanceの年次財務表を通期の並びにそろえる。"""

from __future__ import annotations

import math

import pandas as pd

from signalforge.research.trend_screen.fundamentals import AnnualPoint

_SALES = ("Total Revenue", "Operating Revenue")
_OP = ("Operating Income", "Operating Income Loss", "Total Operating Income As Reported")
_EPS = ("Diluted EPS", "Basic EPS")
_NI = ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests")
_EQ = ("Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest")
_ASSETS = ("Total Assets",)
_OCF = ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities")


def _num(value: object) -> float | None:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _orient(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    labels = {str(item).strip().lower() for item in data.index}
    if "total revenue" in labels or "operating income" in labels or "diluted eps" in labels:
        return data
    columns = {str(item).strip().lower() for item in data.columns}
    if "total revenue" in columns or "operating income" in columns or "diluted eps" in columns:
        return data.T
    return data


def _series(frame: pd.DataFrame, names: tuple[str, ...]) -> pd.Series | None:
    if frame.empty:
        return None
    lookup = {str(item).strip().lower(): item for item in frame.index}
    for name in names:
        key = lookup.get(name.lower())
        if key is not None:
            return frame.loc[key]
    return None


def _dates(series: pd.Series | None) -> dict[str, float | None]:
    if series is None:
        return {}
    found: dict[str, float | None] = {}
    for column, value in series.items():
        try:
            stamp = pd.Timestamp(column)
        except (TypeError, ValueError):
            continue
        if pd.isna(stamp):
            continue
        found[stamp.date().isoformat()] = _num(value)
    return found


def annuals_from_frames(
    income: pd.DataFrame | None,
    balance: pd.DataFrame | None,
    cash: pd.DataFrame | None,
) -> list[AnnualPoint]:
    income_o = _orient(income)
    balance_o = _orient(balance)
    cash_o = _orient(cash)
    sales = _dates(_series(income_o, _SALES))
    op = _dates(_series(income_o, _OP))
    eps = _dates(_series(income_o, _EPS))
    ni = _dates(_series(income_o, _NI))
    equity = _dates(_series(balance_o, _EQ))
    assets = _dates(_series(balance_o, _ASSETS))
    ocf = _dates(_series(cash_o, _OCF))
    days = sorted(set(sales) | set(op) | set(eps) | set(ni) | set(equity) | set(assets) | set(ocf))
    return [
        AnnualPoint(
            fiscal_end=day,
            sales=sales.get(day),
            operating_income=op.get(day),
            eps=eps.get(day),
            net_income=ni.get(day),
            operating_cf=ocf.get(day),
            equity=equity.get(day),
            assets=assets.get(day),
        )
        for day in days
    ]
