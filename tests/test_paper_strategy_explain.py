"""Diversified paper pages explain the strategy that the code actually runs."""

from __future__ import annotations

import inspect
import re

from signalforge.config import load_implementation_map
from signalforge.data.entry_filters import uses_reversion_entry
from signalforge.indicators.engine import IndicatorEngine, adx, atr, bollinger, cci, ichimoku, rsi
from signalforge.paper.diversified_specs import DIVERSIFIED_PAPER_SIMULATIONS
from signalforge.report.paper_strategy_explain import explain_diversified_strategy


def _joined(strategy_id: str) -> str:
    parts = explain_diversified_strategy(strategy_id)
    return parts["buy"] + parts["exit"] + parts["account"]


def test_every_diversified_book_has_buy_exit_and_account_rules():
    impl = load_implementation_map().get("strategies") or {}
    assert len(DIVERSIFIED_PAPER_SIMULATIONS) == 7
    for spec in DIVERSIFIED_PAPER_SIMULATIONS:
        text = explain_diversified_strategy(spec.strategy, style=spec.style)
        assert text["buy"] and text["exit"] and text["account"]
        assert "テンプレート " not in text["buy"]
        assert "implementation_map に買い条件がありません" not in text["buy"]
        blob = text["buy"] + text["exit"] + text["account"]
        assert "時間足" not in blob
        assert "1時間" not in blob
        assert "hourly" not in blob.lower()
        assert "先着" not in blob
        assert "5銘柄" in text["account"]
        assert "現金の20%" in text["account"]
        assert "5億円" in text["account"]
        assert "250エントリー日" in text["account"]
        assert "80%以上" in text["account"]
        assert "上位20%" in text["account"]
        assert "60日未満" in text["account"]
        assert "指数の暴落を見る条件ではありません" in text["account"]
        assert "日経連動ETFの200日線や急落では買いを止めません" in text["account"]
        if (impl.get(spec.strategy) or {}).get("exit"):
            assert "この戦略だけの上書き" in text["exit"]
        else:
            assert "決済の上書きはありません" in text["exit"]
        if uses_reversion_entry(spec.strategy):
            assert "シグナルを消します" in text["buy"]
            assert "シグナルを消しません" not in text["buy"]
        else:
            assert "シグナルを消しません" in text["buy"]


def test_indicator_words_follow_engine_defaults():
    compute = inspect.getsource(IndicatorEngine.compute)
    assert f"rsi(c, {inspect.signature(rsi).parameters['period'].default})" in compute
    assert "bollinger(c)" in compute
    assert f"atr(h, l, c, {inspect.signature(atr).parameters['period'].default})" in compute
    assert f"adx(h, l, c, {inspect.signature(adx).parameters['period'].default})" in compute
    assert f"cci(h, l, c, {inspect.signature(cci).parameters['period'].default})" in compute
    assert "ichimoku(h, l, c)" in compute
    rolls = [int(n) for n in re.findall(r"rolling\((\d+)\)", inspect.getsource(ichimoku))]
    ichi = explain_diversified_strategy("ichimoku_tk_cross")["buy"]
    assert f"{rolls[0]}日" in ichi
    assert f"{rolls[2]}日" in ichi

    bb_period = inspect.signature(bollinger).parameters["period"].default
    bb_std = inspect.signature(bollinger).parameters["std"].default
    bb = explain_diversified_strategy("bb_lower_rsi_oversold")["buy"]
    assert f"{int(bb_period)}日移動平均" in bb
    assert f"{int(bb_std) if float(bb_std) == int(bb_std) else bb_std}標準偏差" in bb


def test_bb_lower_rsi_matches_code_not_the_catalog_nickname():
    text = explain_diversified_strategy("bb_lower_rsi_oversold")
    assert "RSI(14)が30以下" in text["buy"]
    assert "毎日シグナルが出ます" in text["buy"]
    assert "翌セッションの寄り付き" in text["buy"]
    assert "前後1日" in text["buy"]
    assert "カタログ名" not in text["buy"]
    assert "この戦略だけの上書き" in text["exit"]
    assert "ATR(14)の2倍を足した" in text["exit"]
    assert "ATR(14)の3倍を引いた" in text["exit"]
    assert "10本経過" in text["exit"]
    assert "最大15本）ではありません" in text["exit"]
    assert "シャンデリア" not in _joined("bb_lower_rsi_oversold")
    assert "5日" not in text["buy"]


def test_name_mismatches_are_stated_only_where_the_code_differs():
    mean = explain_diversified_strategy("mean_reversion_short_term")
    assert "RSI(14)が前の足で35未満、当足で35以上" in mean["buy"]
    assert "過去5日のリターンを計算していません" in mean["buy"]
    assert "ATR(14)の2倍を足した" in mean["exit"]
    assert "10本経過" in mean["exit"]

    cci = explain_diversified_strategy("cci_zero_cross")
    assert "CCI(20)が前の足では0未満、当足では0以上" in cci["buy"]
    assert "±100のブレイクは条件にありません" in cci["buy"]
    assert "決済の上書きはありません" in cci["exit"]
    assert "15本経過" in cci["exit"]
    assert "ATR(14)の1.5倍を引いた" in cci["exit"]

    dip = explain_diversified_strategy("rsi_dip_200ma")
    assert "終値がEMA200より上" in dip["buy"]
    assert "35未満のあいだは買わず" in dip["buy"]
    assert "決済の上書きはありません" in dip["exit"]

    ichi = explain_diversified_strategy("ichimoku_tk_cross")
    assert "雲の上かどうかは見ていません" in ichi["buy"]
    assert "カタログ名" not in ichi["buy"]
    assert "カタログ名" not in ichi["exit"]
    assert "シグナルを消しません" in ichi["buy"]

    trail = explain_diversified_strategy("trailing_atr_chandelier")
    assert "ADX(14)が18以上" in trail["buy"]
    assert "EMA20" in trail["buy"]
    assert "毎日シグナルが出ます" in trail["buy"]
    assert "シャンデリア（直近高値からATRを引く追跡損切り）は使っていません" in trail["exit"]
    assert "決済の上書きはありません" in trail["exit"]
    assert "ATR(14)の3倍を足した" in trail["exit"]
    assert "シグナルを消しません" in trail["buy"]

    bnf = explain_diversified_strategy("bnf_regime_trend_vs_fade")
    assert "ADX(14)が22以上" in bnf["buy"]
    assert "EMA25" in bnf["buy"]
    assert "逆張りに切り替える処理はありません" in bnf["buy"]
    assert "シグナルを消しません" in bnf["buy"]
    assert "シャンデリア" not in bnf["exit"]


def test_diversified_paper_page_shows_rules_near_the_top(tmp_path):
    from signalforge.paper.diversified import DiversifiedPaperBook
    from signalforge.report.static_dashboard import export_diversified_paper_page

    book = DiversifiedPaperBook(
        style="swing",
        strategy="bb_lower_rsi_oversold",
        entry_priority="sector_turnover",
        min_turnover_jpy=5e8,
        min_breadth_rank=0.8,
        regime_filter="none",
        rules_version=2,
        cohort="tse_liquid",
        universe_size=10,
        entry_cutoff="2026-10-16",
        initial_capital=3_000_000,
    )
    path = export_diversified_paper_page(tmp_path, book)
    assert path is not None
    html = path.read_text(encoding="utf-8")
    assert 'class="strategy-rules"' in html
    assert "<strong>いつ買うか。</strong>" in html
    assert "<strong>いつ手じまうか。</strong>" in html
    assert "<strong>口座の共通条件。</strong>" in html
    assert html.index("この戦略のルール") < html.index("評価額")
    assert "RSI(14)が30以下" in html
    assert "売買代金の大きい順" in html
    assert "先着" not in html
    assert "時間足" not in html
