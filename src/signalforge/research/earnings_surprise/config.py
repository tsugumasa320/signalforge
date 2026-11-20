"""Pre-registered rules for the earnings-surprise study.

These values were fixed on 2026-11-11, before any backtest result from this
module was inspected. Do not retune them to improve a reported number.
"""

from __future__ import annotations

RULES_VERSION = "v0-2026-11-11"

# J-Quants free-plan window measured with this environment's key.
# A run must print the dates it actually loaded and must not claim five years.
REQUESTED_YEARS = 5

PRIME_MARKET = "0111"
COMMON_STOCK = "011"
BENCHMARK_CODE = "13060"  # NEXT FUNDS TOPIX (1306). Official TOPIX is not on this plan.

# One name, from the handover. Round lot of the TSE.
PER_NAME_JPY = 1_000_000.0
LOT = 100
# Fixed account used for the capital-constrained book. Not optimised.
ACCOUNT_JPY = 10_000_000.0

# config/costs/japan.yaml as of 2026-11-11. Applied on the way in and the way out.
COMMISSION = 0.00105
SLIPPAGE = 0.0003

# Prior-session yen turnover. Same 5億円 floor the project uses for liquid entries.
MIN_TURNOVER_JPY = 500_000_000.0
MIN_SECTOR_MEMBERS = 5

STOPS = (-0.03, -0.05, -0.08)
HEADLINE_STOP = -0.05
HOLDS = (5, 10, 20)
HEADLINE_HOLD = 20
ENTRY_METHODS = ("A", "C")  # B needs minute bars, which this plan does not serve.

# Analysis cut only. It does not change who is bought.
RUNUP_CUT = 0.10

# A forecast jump of this size is treated as a unit break, not a revision.
UNIT_BREAK = 1000.0

# Session split by count: first 60% design, next 20% validation, last 20% untouched.
DESIGN_FRACTION = 0.60
VALIDATE_FRACTION = 0.80
