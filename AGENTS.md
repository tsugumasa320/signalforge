# SignalForge — Agent Instructions

## Project location

- **Use this path only:** `/Users/tsugumasayutani/Documents/GitHub/signalforge`
- Do **not** use the iCloud copy under `~/Library/Mobile Documents/...` (files may be evicted / empty).

## Dashboard (Streamlit web app)

The dashboard is a **local** Streamlit server, not a hosted site.

### Default: background daemon (recommended)

Starts detached from the terminal. **Closing the terminal does not stop the server.**

```bash
cd /Users/tsugumasayutani/Documents/GitHub/signalforge
uv run signalforge dashboard          # same as `dashboard start`
uv run signalforge dashboard start    # explicit start
uv run signalforge dashboard status   # check URL / PID
uv run signalforge dashboard stop     # stop background server
```

- URL: usually `http://127.0.0.1:8501` (see `dashboard status` if port differs)
- PID / log: `data/.dashboard/dashboard.pid`, `data/logs/dashboard.log`
- macOS shortcut: double-click `scripts/start-dashboard.command`

### Foreground (debug only)

Stops when the terminal closes:

```bash
uv run signalforge dashboard run
```

### Agent rules

1. Before telling the user to open the browser, run `uv run signalforge dashboard status` or `start`.
2. If the user reports “cannot connect”, check `status` first — the server is often **not running**.
3. Use `dashboard start`, not `dashboard run`, unless debugging.
4. Do not `pkill` streamlit unless restarting; prefer `dashboard stop`.
5. After code changes to `dashboard.py` / report modules, run `dashboard stop` then `dashboard start --force`.

## Environment

```bash
uv sync --extra dev
uv run signalforge doctor
uv run pytest
```

## Data cache

- Runtime data lives under `data/` (gitignored).
- If backtests fail on missing OHLCV: `uv run signalforge fetch --ticker NVDA --timeframe 1d`

## PyArrow / macOS

- Pickle cache (not parquet) for OHLCV to avoid Streamlit thread SIGSEGV.
- `ARROW_DEFAULT_MEMORY_POOL=system` is set on dashboard start.

## Paper trading (forward virtual)

Daily fetch + incremental virtual PnL (not historical backtest):

```bash
uv run signalforge paper init --style swing --strategy macd_cross
uv run signalforge paper run --style swing --strategy macd_cross   # run daily
uv run signalforge paper status
```

State: `data/paper/{style}_{strategy}.json` (committed by GitHub Actions; local `data/*.pkl` stays gitignored).

GitHub Actions (`.github/workflows/daily-paper.yml`): scheduled Mon–Fri 22:00 UTC, runs `scripts/ci-daily-paper.sh`, commits paper JSON.
