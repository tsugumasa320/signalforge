#!/bin/bash
# CI / cron: fetch OHLCV once, advance diversified paper books from cache, export unified dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== SignalForge daily (multi-strategy) ==="

uv sync --extra dev --frozen 2>/dev/null || uv sync --extra dev

if [[ "${PUBLISH_ONLY:-}" == "1" ]]; then
  echo "--- publish only (paper books already computed) ---"
else
  echo "--- update paper-book universe (1d, append new bars) ---"
  uv run signalforge fetch --paper-books --timeframe 1d --update --with-correlations --workers 8

  echo "--- diversified paper (TSE forward, cached data) ---"
  uv run signalforge paper diversified-run-all --no-refresh --workers 8 || true

  echo "--- trend-screen liquid universe OHLCV update ---"
  uv run python - <<'PY'
from concurrent.futures import ThreadPoolExecutor, as_completed
from signalforge.data.cache import ParquetCache
from signalforge.data.fetcher import MarketDataFetcher
from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list

write_liquid_list(300)
tickers = read_liquid_list(300)
if "1306.T" not in tickers:
    tickers = [*tickers, "1306.T"]
cache = ParquetCache()
fetcher = MarketDataFetcher(data_source="yfinance")
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
print(f"trend-screen bars updated ok={ok} fail={fail}", flush=True)
PY

  echo "--- trend-screen full ranking (published JSON) ---"
  uv run signalforge trend-screen ranking --top 10

  echo "--- trend-screen forward paper ---"
  uv run signalforge trend-screen forward
fi

echo "--- export unified dashboard ---"
uv run signalforge dashboard export --output _site
