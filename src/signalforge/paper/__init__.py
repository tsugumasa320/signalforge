"""Forward paper trading — daily data refresh + virtual performance tracking."""

from signalforge.paper.portfolio import PaperPortfolio
from signalforge.paper.runner import run_paper_daily

__all__ = ["PaperPortfolio", "run_paper_daily"]
