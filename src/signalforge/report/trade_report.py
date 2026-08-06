from __future__ import annotations

from pathlib import Path

from signalforge.interpret.journal import TradeJournal


def journal_to_markdown(journal: TradeJournal) -> str:
    lines = [f"# Trade Journal — run `{journal.run_id}`", ""]
    lines.append(f"## Executed Trades ({len(journal.trades)})")
    lines.append("")
    for t in journal.trades:
        lines.append(f"### Trade #{t.trade_id} — {t.timestamp}")
        lines.append(f"- **Action**: {t.action} | **Outcome**: {t.outcome}")
        lines.append(f"- **Summary**: {t.summary_ja}")
        if t.rules_audit:
            passed = t.rules_audit.get("passed", [])
            failed = t.rules_audit.get("failed", [])
            if passed:
                lines.append(f"- **Rules passed**: {', '.join(passed)}")
            if failed:
                lines.append(f"- **Rules failed**: {', '.join(failed)}")
        if t.pnl_pct is not None:
            lines.append(f"- **PnL**: {t.pnl_pct:.2f}% | **Hold**: {t.hold_bars} bars")
        if t.ml_explanation:
            prob = t.ml_explanation.get("probability")
            lines.append(f"- **ML prob**: {prob:.2f}" if prob else "")
        lines.append("")

    if journal.rejected:
        lines.append(f"## Rejected Signals ({len(journal.rejected)})")
        lines.append("")
        for r in journal.rejected:
            lines.append(f"- `{r.timestamp}`: {r.summary_ja}")
        lines.append("")

    return "\n".join(lines)


def save_report(journal: TradeJournal, path: Path, fmt: str = "md") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        out = path / f"report_{journal.run_id}.md"
        out.write_text(journal_to_markdown(journal), encoding="utf-8")
    else:
        out = path / f"report_{journal.run_id}.json"
        journal.save(path)
        out = path / f"journal_{journal.run_id}.json"
    return out
