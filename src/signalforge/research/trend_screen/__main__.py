"""長期上昇トレンドのスクリーニング。

例
--
uv run python -m signalforge.research.trend_screen run --cases
uv run python -m signalforge.research.trend_screen universe
"""

from __future__ import annotations

import argparse
import sys

from signalforge.research.trend_screen.screen import ScreenUsageError, run_cli, universe_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="長期上昇トレンド成長株のスクリーニング")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("universe", help="上場一覧の件数だけを見る。日足は取らない")
    run = sub.add_parser("run", help="指定銘柄だけ採点する。全市場は回さない")
    run.add_argument("--tickers", default="", help="カンマ区切り。例: 2702.T,3563.T")
    run.add_argument("--cases", action="store_true", help="テストケースと再評価リスト")
    run.add_argument("--refresh", action="store_true", help="日足と財務を取り直す")
    run.add_argument("--no-forward", action="store_true", help="戦略Aの前方リターン集計を省く")
    race = sub.add_parser("race", help="流動性上位の日足で選別案の成績を比べる")
    race.add_argument("--limit", type=int, default=300, help="流動性上位の銘柄数")
    race.add_argument("--no-funds", action="store_true", help="業績キャッシュを読まない")
    funds = sub.add_parser("fetch-funds", help="流動性上位の通期財務をキャッシュする")
    funds.add_argument("--limit", type=int, default=300)
    freq = sub.add_parser("frequency", help="一次条件の月末判定と毎日判定を比べる")
    freq.add_argument("--limit", type=int, default=300)
    conc = sub.add_parser("concentration", help="一次条件の全銘柄と上昇率上位への集中を比べる")
    conc.add_argument("--limit", type=int, default=300)
    sub.add_parser("rules", help="採用シストレの規則を表示")
    targets = sub.add_parser("targets", help="直近月末の目標ポートフォリオを出す")
    targets.add_argument("--limit", type=int, default=0, help="0なら採用ルールの300")
    bt = sub.add_parser("backtest", help="採用シストレの学習／確認を再計算")
    bt.add_argument("--limit", type=int, default=0)
    improve = sub.add_parser("improve", help="改善案を比べ、確認を通れば採用を更新")
    improve.add_argument("--limit", type=int, default=300)
    improve.add_argument("--no-promote", action="store_true", help="採用ファイルを更新しない")
    args = parser.parse_args(argv)
    if args.command == "universe":
        print(universe_text())
        return 0
    if args.command == "race":
        from signalforge.research.trend_screen.horse import run_cached_race

        run_cached_race(limit=args.limit, fetch_funds=not args.no_funds)
        return 0
    if args.command == "fetch-funds":
        from signalforge.research.trend_screen.horse import _load_funds
        from signalforge.research.trend_screen.universe_build import read_liquid_list, write_liquid_list

        write_liquid_list(args.limit)
        names = read_liquid_list(args.limit)
        found = _load_funds(names, fetch_missing=True)
        print(f"財務キャッシュ {len(found)}/{len(names)}")
        return 0
    if args.command == "frequency":
        from signalforge.research.trend_screen.frequency import run_cached_frequency

        run_cached_frequency(limit=args.limit)
        return 0
    if args.command == "concentration":
        from signalforge.research.trend_screen.concentration import run_cached_concentration

        run_cached_concentration(limit=args.limit)
        return 0
    if args.command == "rules":
        from signalforge.research.trend_screen.system import print_rules

        print_rules()
        return 0
    if args.command == "targets":
        from signalforge.research.trend_screen.ruleset import load_adopted
        from signalforge.research.trend_screen.system import compute_targets, print_targets

        limit = args.limit or load_adopted().universe_limit
        print_targets(compute_targets(limit=limit))
        return 0
    if args.command == "backtest":
        from signalforge.research.trend_screen.ruleset import load_adopted
        from signalforge.research.trend_screen.system import run_system_backtest

        limit = args.limit or load_adopted().universe_limit
        info = run_system_backtest(limit=limit)
        train, test = info["train"], info["test"]
        print(
            f"学習 CAGR {train.cagr:+.2%} excess {train.mean_excess:+.2%} DD {train.max_dd:+.2%} | "
            f"確認 CAGR {test.cagr:+.2%} excess {test.mean_excess:+.2%} DD {test.max_dd:+.2%}",
            flush=True,
        )
        print(f"出力: {info['out'] / 'backtest.md'}", flush=True)
        return 0
    if args.command == "improve":
        from signalforge.research.trend_screen.improve import run_cached_improve

        run_cached_improve(limit=args.limit, promote=not args.no_promote)
        return 0
    try:
        run_cli(
            tickers=args.tickers,
            use_cases=args.cases,
            refresh=args.refresh,
            with_forward=not args.no_forward,
        )
    except ScreenUsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
