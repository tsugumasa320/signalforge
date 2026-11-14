"""日足からのチャート指標。週足にはリサンプルしない。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from signalforge.research.trend_screen.config import (
    LIQUIDITY_YEN,
    MA200_SLOPE_LAG,
    MA75_SLOPE_LAG,
    MA_SHORT_SLOPE_LAG,
    RET_1Y_STEPS,
    RET_3Y_STEPS,
)

TIMING_LABELS = {
    "ma200_down": "200日線が下向き。原則として候補から除外",
    "below_ma200": "200日線を下回っている。新規購入は原則見送り",
    "ppp": "PPP成立。上昇モメンタムあり",
    "pullback_ma25": "25日線付近。押し目候補",
    "pullback_ma75": "75日線まで調整。長期トレンドの維持を確認",
    "above_ma200": "200日線より上。PPPでも押し目でもない",
    "insufficient": "移動平均が未確定",
}


def _num(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _prepare(series: pd.Series) -> pd.Series:
    out = series.copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index))
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return pd.to_numeric(out, errors="coerce").dropna()


def _is_daily(index: pd.DatetimeIndex) -> bool:
    if len(index) < 5:
        return False
    gaps = pd.Series(index).diff().dt.days.dropna()
    if gaps.empty:
        return False
    return float(gaps.median()) <= 5


def _slope(series: pd.Series, lag: int) -> float | None:
    if len(series) <= lag:
        return None
    now = _num(series.iloc[-1])
    prev = _num(series.iloc[-1 - lag])
    if now is None or prev is None or prev == 0:
        return None
    return now / prev - 1.0


def _window_return(series: pd.Series, steps: int) -> tuple[float | None, str | None]:
    if len(series) <= steps:
        return None, None
    window = series.iloc[-(steps + 1) :]
    start = _num(window.iloc[0])
    end = _num(window.iloc[-1])
    if start is None or end is None or start <= 0:
        return None, None
    return end / start - 1.0, pd.Timestamp(window.index[0]).date().isoformat()


def max_drawdown(prices: pd.Series) -> float | None:
    px = pd.to_numeric(prices, errors="coerce").dropna()
    if len(px) < 2 or (px <= 0).any():
        return None
    return float((px / px.cummax() - 1.0).min())


@dataclass
class ChartMetrics:
    reliable_daily: bool = False
    as_of: str | None = None
    bars: int = 0
    price: float | None = None
    ma5: float | None = None
    ma25: float | None = None
    ma75: float | None = None
    ma200: float | None = None
    ma5_slope: float | None = None
    ma25_slope: float | None = None
    ma75_slope: float | None = None
    ma200_slope: float | None = None
    ret_1y: float | None = None
    ret_3y: float | None = None
    ret_1y_total: float | None = None
    ret_3y_total: float | None = None
    ret_1y_start: str | None = None
    ret_3y_start: str | None = None
    excess_1y: float | None = None
    excess_3y: float | None = None
    bench_1y: float | None = None
    bench_3y: float | None = None
    mdd_1y: float | None = None
    mdd_3y: float | None = None
    pct_above_ma200: float | None = None
    dd_52w: float | None = None
    vol_1y: float | None = None
    up_month_ratio: float | None = None
    turnover_20d: float | None = None
    timing: str = "insufficient"
    primary: dict[str, bool | None] = field(default_factory=dict)
    prefer: dict[str, bool | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def timing_label(self) -> str:
        return TIMING_LABELS.get(self.timing, self.timing)


def _gt(left: float | None, right: float | None) -> bool | None:
    if left is None or right is None:
        return None
    return left > right


def _positive(value: float | None) -> bool | None:
    if value is None:
        return None
    return value > 0


def _timing(
    price: float | None,
    ma5: float | None,
    ma25: float | None,
    ma75: float | None,
    ma200: float | None,
    s5: float | None,
    s25: float | None,
    s75: float | None,
    s200: float | None,
) -> str:
    if price is None or ma200 is None or s200 is None:
        return "insufficient"
    if s200 <= 0:
        return "ma200_down"
    if price <= ma200:
        return "below_ma200"
    ppp = (
        ma5 is not None
        and ma25 is not None
        and ma75 is not None
        and s5 is not None
        and s25 is not None
        and s75 is not None
        and ma5 > ma25 > ma75
        and s5 > 0
        and s25 > 0
        and s75 > 0
    )
    if ppp:
        return "ppp"
    if ma25 is not None and ma75 is not None and abs(price / ma25 - 1.0) <= 0.02 and price >= ma75:
        return "pullback_ma25"
    if ma75 is not None and ma25 is not None and price < ma25 and -0.01 <= price / ma75 - 1.0 <= 0.03:
        return "pullback_ma75"
    return "above_ma200"


def _excess(close: pd.Series, benchmark: pd.Series | None, steps: int) -> tuple[float | None, float | None]:
    if benchmark is None:
        return None, None
    bench = _prepare(benchmark)
    joined = pd.concat({"s": close, "b": bench}, axis=1, join="inner").dropna()
    stock_ret, _ = _window_return(joined["s"], steps)
    bench_ret, _ = _window_return(joined["b"], steps)
    if stock_ret is None or bench_ret is None:
        return None, bench_ret
    return stock_ret - bench_ret, bench_ret


def evaluate_chart(
    close: pd.Series,
    volume: pd.Series | None = None,
    adj_close: pd.Series | None = None,
    benchmark: pd.Series | None = None,
) -> ChartMetrics:
    """終値ベースの指標。最大ドローダウンは日中安値を含まない。"""
    px = _prepare(close)
    metrics = ChartMetrics(bars=int(len(px)))
    metrics.notes.append("最大ドローダウンは終値ベース。日中安値は使っていない。")
    metrics.notes.append("200日線より上の割合は、200日線が計算できる日だけを分母にする。")
    if px.empty:
        metrics.notes.append("日足が空。")
        return metrics
    metrics.as_of = pd.Timestamp(px.index[-1]).date().isoformat()
    metrics.price = _num(px.iloc[-1])
    if not _is_daily(px.index):
        metrics.notes.append("バー間隔の中央値が5日を超える。週足などの可能性があり、日足の移動平均としては計算しない。")
        return metrics
    metrics.reliable_daily = True

    ma5 = px.rolling(5, min_periods=5).mean()
    ma25 = px.rolling(25, min_periods=25).mean()
    ma75 = px.rolling(75, min_periods=75).mean()
    ma200 = px.rolling(200, min_periods=200).mean()
    metrics.ma5 = _num(ma5.iloc[-1])
    metrics.ma25 = _num(ma25.iloc[-1])
    metrics.ma75 = _num(ma75.iloc[-1])
    metrics.ma200 = _num(ma200.iloc[-1])
    metrics.ma5_slope = _slope(ma5, MA_SHORT_SLOPE_LAG)
    metrics.ma25_slope = _slope(ma25, MA_SHORT_SLOPE_LAG)
    metrics.ma75_slope = _slope(ma75, MA75_SLOPE_LAG)
    metrics.ma200_slope = _slope(ma200, MA200_SLOPE_LAG)

    metrics.ret_1y, metrics.ret_1y_start = _window_return(px, RET_1Y_STEPS)
    metrics.ret_3y, metrics.ret_3y_start = _window_return(px, RET_3Y_STEPS)
    if adj_close is not None:
        adj = _prepare(adj_close)
        metrics.ret_1y_total, _ = _window_return(adj, RET_1Y_STEPS)
        metrics.ret_3y_total, _ = _window_return(adj, RET_3Y_STEPS)
    else:
        metrics.notes.append("配当込みリターンは未確認。スコアに使うのは配当を含まない株価リターン。")

    metrics.excess_1y, metrics.bench_1y = _excess(px, benchmark, RET_1Y_STEPS)
    metrics.excess_3y, metrics.bench_3y = _excess(px, benchmark, RET_3Y_STEPS)
    if metrics.excess_1y is None:
        metrics.notes.append("TOPIX相対リターンは未確認。")

    if len(px) > RET_1Y_STEPS:
        metrics.mdd_1y = max_drawdown(px.iloc[-(RET_1Y_STEPS + 1) :])
    if len(px) > RET_3Y_STEPS:
        window = px.iloc[-(RET_3Y_STEPS + 1) :]
        metrics.mdd_3y = max_drawdown(window)
        ma_w = ma200.reindex(window.index)
        valid = ma_w.notna()
        if int(valid.sum()) >= 100:
            metrics.pct_above_ma200 = float((window[valid] > ma_w[valid]).mean())
        monthly = window.resample("ME").last().dropna()
        changes = monthly.pct_change().dropna()
        if len(changes) >= 12:
            metrics.up_month_ratio = float((changes > 0).mean())

    if len(px) >= RET_1Y_STEPS:
        high = _num(px.iloc[-RET_1Y_STEPS:].max())
        if high is not None and high > 0 and metrics.price is not None:
            metrics.dd_52w = metrics.price / high - 1.0
        rets = px.iloc[-(RET_1Y_STEPS + 1) :].pct_change().dropna()
        if len(rets) >= 20:
            metrics.vol_1y = float(rets.std(ddof=1) * (245 ** 0.5))

    if volume is not None:
        vol = _prepare(volume).reindex(px.index)
        traded = (px * vol).dropna()
        if len(traded) >= 20:
            metrics.turnover_20d = float(traded.iloc[-20:].mean())
            metrics.notes.append("売買代金は終値×出来高の近似。取引所の売買代金そのものではない。")

    metrics.timing = _timing(
        metrics.price,
        metrics.ma5,
        metrics.ma25,
        metrics.ma75,
        metrics.ma200,
        metrics.ma5_slope,
        metrics.ma25_slope,
        metrics.ma75_slope,
        metrics.ma200_slope,
    )
    metrics.primary = {
        "price_above_ma200": _gt(metrics.price, metrics.ma200),
        "ma200_rising_60": _positive(metrics.ma200_slope),
        "ma75_rising": _positive(metrics.ma75_slope),
        "ret_1y_positive": _positive(metrics.ret_1y),
        "ret_3y_positive": _positive(metrics.ret_3y),
        "topix_excess_1y": _positive(metrics.excess_1y),
    }
    metrics.prefer = {
        "mdd_3y_within_35": None if metrics.mdd_3y is None else metrics.mdd_3y >= -0.35,
        "mdd_1y_within_25": None if metrics.mdd_1y is None else metrics.mdd_1y >= -0.25,
        "above_ma200_70": None if metrics.pct_above_ma200 is None else metrics.pct_above_ma200 >= 0.70,
        "within_20_of_52w": None if metrics.dd_52w is None else metrics.dd_52w >= -0.20,
        "liquid": None if metrics.turnover_20d is None else metrics.turnover_20d >= LIQUIDITY_YEN,
    }
    return metrics
