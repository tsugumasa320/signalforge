"""GitHub Pages 用：長期トレンド・スクリーニング全銘柄ランキング。"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from signalforge.report.static_html import wrap_page
from signalforge.research.trend_screen.ranking import build_and_publish, load_ranking


def _pct(value: float | None, *, digits: int = 1) -> str:
    if value is None:
        return "—"
    cls = "positive" if value > 0 else "negative" if value < 0 else ""
    text = f"{value * 100:.{digits}f}%"
    return f'<span class="{cls}">{text}</span>' if cls else text


def _yen(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}"


def _oku(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value / 1e8:.1f}"


def _rules_html(markdown: str) -> str:
    lines = []
    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            lines.append(f"<h3>{escape(line[3:])}</h3>")
        elif line.startswith("- "):
            lines.append(f"<li>{escape(line[2:])}</li>")
        else:
            lines.append(f"<p class='muted'>{escape(line)}</p>")
    # wrap consecutive li
    out: list[str] = []
    in_ul = False
    for item in lines:
        if item.startswith("<li>"):
            if not in_ul:
                out.append("<ul class='compact'>")
                in_ul = True
            out.append(item)
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(item)
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def _ranking_table(rows: list[dict[str, Any]], *, show_target: bool = True) -> str:
    header = (
        "<tr><th>#</th><th>コード</th><th>会社名</th><th>業種</th>"
        "<th>1年</th><th>20日</th><th>52週DD</th><th>終値</th><th>売買代金(億)</th>"
        f"{'<th></th>' if show_target else ''}</tr>"
    )
    body_parts: list[str] = []
    for row in rows:
        rank = row.get("rank")
        badge = ""
        if show_target and row.get("target"):
            badge = '<span class="badge">保有</span>'
        body_parts.append(
            "<tr>"
            f"<td>{rank if rank is not None else '—'}</td>"
            f"<td>{escape(str(row.get('code') or ''))}</td>"
            f"<td>{escape(str(row.get('name') or ''))}</td>"
            f"<td class='muted'>{escape(str(row.get('sector') or ''))}</td>"
            f"<td>{_pct(row.get('ret_1y'))}</td>"
            f"<td>{_pct(row.get('ret_20d'))}</td>"
            f"<td>{_pct(row.get('dd_52w'))}</td>"
            f"<td>{_yen(row.get('price'))}</td>"
            f"<td>{_oku(row.get('turnover_20d'))}</td>"
            f"{f'<td>{badge}</td>' if show_target else ''}"
            "</tr>"
        )
    return f"<table><thead>{header}</thead><tbody>{''.join(body_parts)}</tbody></table>"


def _rejected_table(rows: list[dict[str, Any]], *, limit: int = 80) -> str:
    header = (
        "<tr><th>コード</th><th>会社名</th><th>1年</th><th>20日</th><th>落ちた条件</th></tr>"
    )
    body_parts: list[str] = []
    for row in rows[:limit]:
        labels = " / ".join(str(x) for x in (row.get("fail_labels") or row.get("fails") or []))
        body_parts.append(
            "<tr>"
            f"<td>{escape(str(row.get('code') or ''))}</td>"
            f"<td>{escape(str(row.get('name') or ''))}</td>"
            f"<td>{_pct(row.get('ret_1y'))}</td>"
            f"<td>{_pct(row.get('ret_20d'))}</td>"
            f"<td class='muted'>{escape(labels)}</td>"
            "</tr>"
        )
    more = ""
    if len(rows) > limit:
        more = f"<p class='muted'>他 {len(rows) - limit} 銘柄（JSON に全件）</p>"
    return f"<table><thead>{header}</thead><tbody>{''.join(body_parts)}</tbody></table>{more}"


def render_trend_screen_body(payload: dict[str, Any]) -> str:
    warning = ""
    if payload.get("warning"):
        warning = f"<div class='info-box'><strong>警告</strong> {escape(str(payload['warning']))}</div>"
    targets = payload.get("targets") or []
    target_bits = "".join(
        f"<li><strong>{escape(str(t.get('code')))}</strong> "
        f"{escape(str(t.get('name') or ''))} · 1年 {_pct(t.get('ret_1y'))}</li>"
        for t in targets
    )
    return f"""
    {warning}
    <div class="metrics">
      <div class="metric"><label>シグナル日</label><value>{escape(str(payload.get('signal_date') or ''))}</value></div>
      <div class="metric"><label>ユニバース</label><value>{payload.get('n_universe', 0)}</value></div>
      <div class="metric"><label>シグナル日バー</label><value>{payload.get('n_on_signal', 0)}</value></div>
      <div class="metric positive"><label>通過</label><value>{payload.get('n_pass', 0)}</value></div>
      <div class="metric"><label>保有目標</label><value>{payload.get('n_target', 0)}</value></div>
    </div>

    <section>
      <h2>今月の保有目標（上位 {escape(str(payload.get('top_n') or 5))}）</h2>
      <ul class="compact">{target_bits or '<li class="muted">なし</li>'}</ul>
    </section>

    <section id="ranking">
      <h2>通過銘柄ランキング（全 {payload.get('n_pass', 0)} 銘柄）</h2>
      <p class="muted">採用ルール: {escape(str(payload.get('name') or ''))} · 版 {escape(str(payload.get('version') or ''))} · 並びは過去1年リターン</p>
      {_ranking_table(list(payload.get('ranking') or []))}
    </section>

    <section id="rejected">
      <h2>未通過（参考）</h2>
      <p class="muted">一次条件・売買代金・直近20日などのいずれかで除外。1年リターンが高い順寄り。</p>
      {_rejected_table(list(payload.get('rejected') or []))}
    </section>

    <section id="rules">
      <h2>規則</h2>
      {_rules_html(str(payload.get('rules_markdown') or ''))}
    </section>
    """


def export_trend_screen_page(
    output_dir: Path,
    *,
    rebuild: bool = True,
    limit: int | None = None,
) -> Path:
    """Publish ranking JSON (optional rebuild) and write screen/trend.html."""
    if rebuild:
        payload, _ = build_and_publish(limit=limit)
    else:
        payload = load_ranking()
        if payload is None:
            payload, _ = build_and_publish(limit=limit)

    body = render_trend_screen_body(payload)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title="長期上昇トレンド・スクリーニング",
        subtitle=(
            f"シグナル {payload.get('signal_date', '')} · "
            f"通過 {payload.get('n_pass', 0)} / ユニバース {payload.get('n_universe', 0)}"
        ),
        body=body,
        generated=generated,
        nav_active="screen",
        depth=1,
    )
    out = output_dir / "screen"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "trend.html"
    path.write_text(html, encoding="utf-8")
    # also copy JSON next to page for download/debug
    raw = output_dir / "screen" / "trend_screen_ranking.json"
    from signalforge.research.trend_screen.ranking import published_ranking_path

    src = published_ranking_path()
    if src.exists():
        raw.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return path
