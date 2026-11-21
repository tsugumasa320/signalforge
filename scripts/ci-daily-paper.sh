#!/bin/bash
# CI / cron: append forward observations, update screening, export dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== SignalForge daily (multi-strategy) ==="

uv sync --extra dev --frozen 2>/dev/null || uv sync --extra dev

if [[ "${PUBLISH_ONLY:-}" == "1" ]]; then
  echo "--- publish only (paper books already computed) ---"
else
  echo "--- append-only forward tests ---"
  uv run python scripts/run_forward_tests.py

  echo "--- trend-screen liquid universe OHLCV update ---"
  uv run python - <<'PY'
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher
from signalforge.research.trend_screen.ruleset import load_adopted
from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list

rules = load_adopted()
limit = int(rules.universe_limit or 300)
if limit <= 0:
    limit = 300
write_liquid_list(limit)
tickers = read_liquid_list(limit)
if "1306.T" not in tickers:
    tickers = [*tickers, "1306.T"]
cache = ParquetCache()
fetcher = MarketDataFetcher(data_source="yfinance")


def _last_bar_date(sym: str):
    df = cache.load(sym, "1d")
    if df is None or df.empty:
        return None
    ts = pd.Timestamp(df.index.max())
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC")
    return ts.date()


def _expected_jp_session_date():
    """CI は東証引け後想定。土日祝は直近の平日を期待する（祝日カレンダーは持たない）。"""
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    day = now.date()
    # 16:00 JST 前は「前日セッション」まで揃っていれば十分
    if now.hour < 16:
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


ok = fail = 0
with ThreadPoolExecutor(max_workers=8) as pool:
    futs = {pool.submit(cache.update, sym, "1d", fetcher): sym for sym in tickers}
    for fut in as_completed(futs):
        try:
            fut.result()
            ok += 1
        except Exception as exc:
            fail += 1
            print(f"✗ {futs[fut]}: {exc}", flush=True)
print(f"trend-screen bars updated ok={ok} fail={fail} universe={len(tickers)}", flush=True)

expected = _expected_jp_session_date()
lagging = []
for sym in tickers:
    last = _last_bar_date(sym)
    if last is None or last < expected:
        lagging.append(sym)
print(
    f"trend-screen bar tip expected>={expected} lagging={len(lagging)}/{len(tickers)}",
    flush=True,
)
if lagging:
    # Yahoo が遅い／キャッシュ先端が古いときに1日遅れの基準日になるのを防ぐ
    ok2 = fail2 = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {
            pool.submit(cache.load_or_fetch, sym, "1d", fetcher, True): sym
            for sym in lagging
        }
        for fut in as_completed(futs):
            try:
                fut.result()
                ok2 += 1
            except Exception as exc:
                fail2 += 1
                print(f"✗ refresh {futs[fut]}: {exc}", flush=True)
    still = sum(
        1
        for sym in tickers
        if (d := _last_bar_date(sym)) is None or d < expected
    )
    print(
        f"trend-screen refresh ok={ok2} fail={fail2} still_lagging={still}",
        flush=True,
    )
tips = sorted({str(_last_bar_date(sym)) for sym in tickers if _last_bar_date(sym)})
print(f"trend-screen bar tip dates: {tips[-5:]}", flush=True)
PY

  # CI has no local data/trend_screen/fins cache. DUKE's default preset requires
  # annual fundamentals, so populate them before calculating its gates.
  echo "--- trend-screen annual fundamentals (DUKE) ---"
  uv run signalforge trend-screen fetch-funds

  echo "--- trend-screen full ranking (published JSON) ---"
  uv run signalforge trend-screen ranking --top 10

fi

echo "--- AI trial daily (rules brief/score/debate + adoption eval) ---"
uv run signalforge ai daily || true

echo "--- AI discover (universe without trend-screen pass gate) ---"
uv run signalforge ai discover || true

echo "--- export unified dashboard ---"
uv run signalforge dashboard export --output _site
