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
- If backtests fail on missing OHLCV: `uv run signalforge fetch --ticker 7203.T --timeframe 1d` or `fetch --universe japan_liquid`

## PyArrow / macOS

- Pickle cache (not parquet) for OHLCV to avoid Streamlit thread SIGSEGV.
- `ARROW_DEFAULT_MEMORY_POOL=system` is set on dashboard start.

## Precomputed strategy results (default UX)

Users **browse** reports; they do not run full catalog backtests from the dashboard by default.

```bash
uv run signalforge results status
uv run signalforge results build          # or: hub build
uv run signalforge hub open
uv run signalforge dashboard start --force
```

Outputs: `data/reports/catalog_backtests.json`, `compare_matrix.json`, `lab_matrix.json`, `hub/index.html`.

Lab rules: `config/lab/izanami_palette.yaml`. Parity: `docs/izanami_parity.md`.

## TSE experiments (optional long campaign)

```bash
uv run signalforge experiments run --ignore-schedule --workers 8
uv run signalforge experiments status
uv run signalforge experiments compact    # slim JSON + .tickers.json sidecar
uv run signalforge experiments aggregate
scripts/resume-experiments.sh             # compact + aggregate + resume
scripts/start-experiments-supervisor.sh   # BT 停止を監視して自動再開
scripts/rerun-experiments-metrics.sh      # 期待値・最大DD 用に完了戦略を再BT（--refresh-metrics）
scripts/rerun-experiments-series.sh      # 期間スライス用系列データ追記（--refresh-series）
scripts/rerun-experiments-capital.sh      # 口座/上限変更後（--refresh-capital、INITIAL_CASH_JPY 等）
```

**蓋を閉じて BT 継続:** `./scripts/rerun-experiments-series-closed-lid.sh`（**バッテリー可**・要 `sudo` pmset、`caffeinate -dims -u -s`）。終わったら `./scripts/restore-battery-sleep.sh`。電源接続なら `./scripts/rerun-experiments-series.sh` でも可。落ちたら `./scripts/start-experiments-supervisor.sh`。

Details: `docs/experiments.md`. Dashboard: **📊 戦略結果 → TSE 実験** (segment heatmap when aggregates exist).

**近似→本データ:** `docs/alt_data.md` · **J-Quants:** `docs/jquants_setup.md`（`JQUANTS_API_KEY` → `alt-data jquants-test` → `fetch --jquants-credit`）。

## Paper trading (forward virtual)

Daily fetch + incremental virtual PnL (not historical backtest):

```bash
uv run signalforge paper init --style swing --strategy macd_cross
uv run signalforge paper run --style swing --strategy macd_cross   # run daily
uv run signalforge paper status
```

State: `data/paper/{style}_{strategy}.json` (committed by GitHub Actions; local `data/*.pkl` stays gitignored).

**1口座・分散（実運用近似）:** `paper diversified-init/run-all` · ログ付き一括: `./scripts/run-diversified-paper-prime.sh` → `data/logs/diversified-paper-prime.log`

GitHub Actions (`.github/workflows/daily-paper.yml`): scheduled Mon–Fri 22:00 UTC, runs `scripts/ci-daily-paper.sh`, commits paper JSON.

**フォワードの見方:** 更新は Actions 日次（JST 朝頃）→ **GitHub Pages**（`dashboard export` の hub）。`data/paper/diversified_*.json` を commit すると分散ペーパーも Pages に載る。Streamlit `127.0.0.1:8501` はローカル専用。
