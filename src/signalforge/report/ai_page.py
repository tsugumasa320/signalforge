"""Static GitHub Pages export for AI trade trial responses."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from signalforge.ai.publish import PUBLISHED_NAMES, load_response_for_pages, published_response_path
from signalforge.report.static_html import wrap_page


def _badge(text: str | None) -> str:
    s = (text or "—").upper()
    cls = "badge"
    if s in {"ADOPT", "BUY", "WATCH", "LONG_CANDIDATE"}:
        cls += " positive"
    elif s in {"AVOID", "SKIP", "REDUCE"}:
        cls += " negative"
    return f'<span class="{cls}">{escape(str(text or "—"))}</span>'


def _ul(items: list[Any] | None) -> str:
    if not items:
        return '<p class="muted">—</p>'
    lis = "".join(f"<li>{escape(str(x))}</li>" for x in items)
    return f'<ul class="compact">{lis}</ul>'


def _table(headers: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = ""
    for row in rows:
        body += "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="muted">データなし</td></tr>'
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def render_brief_section(resp: dict[str, Any] | None) -> str:
    if not resp:
        return '<section id="brief"><h2>Brief</h2><p class="muted">未公開。`ai save-response brief` 後に commit してください。</p></section>'
    rows = []
    for w in resp.get("watch") or []:
        rows.append(
            [
                _badge(w.get("stance")),
                escape(str(w.get("ticker") or "")),
                escape(str(w.get("name") or "")),
                escape(str(w.get("confidence") or "")),
                escape(str(w.get("why") or "")),
                escape(str(w.get("risk") or "")),
            ]
        )
    return f"""
    <section id="brief">
      <h2>Brief — 日次ブリーフィング</h2>
      <p class="muted">基準日 {escape(str(resp.get('as_of') or '—'))}</p>
      <p>{escape(str(resp.get('market_take') or '—'))}</p>
      {_table(["stance", "ticker", "name", "conf", "why", "risk"], rows)}
      <h3>ペーパーメモ</h3>
      {_ul(resp.get("paper_notes"))}
      <h3>今日やらないこと</h3>
      {_ul(resp.get("skip_today"))}
      <h3>人がやること</h3>
      {_ul(resp.get("actions_for_human"))}
    </section>
    """


def render_score_section(resp: dict[str, Any] | None) -> str:
    if not resp:
        return '<section id="score"><h2>Score</h2><p class="muted">未公開。`ai save-response score` 後に commit してください。</p></section>'
    adopted = resp.get("adopted") or []
    adopted_html = (
        f'<p class="positive"><strong>ADOPT:</strong> {escape(", ".join(str(t) for t in adopted))}</p>'
        if adopted
        else '<p class="muted">ADOPT なし</p>'
    )
    rows = []
    for s in resp.get("scores") or []:
        f = s.get("factors") or {}
        rows.append(
            [
                _badge(s.get("decision")),
                escape(str(s.get("ticker") or "")),
                escape(str(s.get("name") or "")),
                escape(str(s.get("total") or "")),
                escape(str(f.get("trend", ""))),
                escape(str(f.get("momentum", ""))),
                escape(str(f.get("risk", ""))),
                escape(str(f.get("liquidity", ""))),
                escape(str(f.get("event", ""))),
            ]
        )
    return f"""
    <section id="score">
      <h2>Score — 候補採点</h2>
      <p class="muted">基準日 {escape(str(resp.get('as_of') or '—'))}</p>
      {adopted_html}
      {_table(["decision", "ticker", "name", "total", "trend", "mom", "risk", "liq", "event"], rows)}
      <h3>SKIP方針</h3>
      {_ul(resp.get("skipped_reasons"))}
    </section>
    """


def render_debate_section(resp: dict[str, Any] | None) -> str:
    if not resp:
        return '<section id="debate"><h2>Debate</h2><p class="muted">未公開。`ai save-response debate` 後に commit してください。</p></section>'
    cards = []
    for d in resp.get("debates") or []:
        cards.append(
            f"""
            <div class="card">
              <h2>{_badge(d.get('decision'))} {escape(str(d.get('ticker') or ''))}
                {escape(str(d.get('name') or ''))}
                <span class="muted">({escape(str(d.get('confidence') or ''))})</span>
              </h2>
              <p><strong>Bull</strong> {escape(str(d.get('bull') or '—'))}</p>
              <p><strong>Bear</strong> {escape(str(d.get('bear') or '—'))}</p>
              <p><strong>Risk</strong> {escape(str(d.get('risk_officer') or '—'))}</p>
              <p class="muted"><strong>Invalidation</strong> {escape(str(d.get('invalidation') or '—'))}</p>
              <p class="muted"><strong>Fail</strong> {escape(str(d.get('why_this_could_fail') or '—'))}</p>
            </div>
            """
        )
    return f"""
    <section id="debate">
      <h2>Debate — ブル／ベア議論</h2>
      <p class="muted">基準日 {escape(str(resp.get('as_of') or '—'))}</p>
      <p>{escape(str(resp.get('committee_summary') or '—'))}</p>
      {''.join(cards)}
    </section>
    """


def render_ai_body(
    brief: dict[str, Any] | None,
    score: dict[str, Any] | None,
    debate: dict[str, Any] | None,
) -> str:
    as_ofs = [r.get("as_of") for r in (brief, score, debate) if r and r.get("as_of")]
    as_of = as_ofs[0] if as_ofs else "—"
    return f"""
    <div class="info-box">
      GitHub Pages 用の AIトライアル結果です。発注には接続しません。
      更新: <code>uv run signalforge ai save-response …</code> →
      <code>data/published/ai_*.json</code> を commit → 日次 Actions / <code>dashboard export</code>。
      基準日の目安: <strong>{escape(str(as_of))}</strong>
    </div>
    {render_brief_section(brief)}
    {render_score_section(score)}
    {render_debate_section(debate)}
    """


def export_ai_page(output_dir: Path) -> Path:
    brief = load_response_for_pages("brief")
    score = load_response_for_pages("score")
    debate = load_response_for_pages("debate")
    body = render_ai_body(brief, score, debate)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title="AIトライアル",
        subtitle="Brief · Score · Debate（参考意見・非自動売買）",
        body=body,
        generated=generated,
        nav_active="ai",
        depth=1,
    )
    out = output_dir / "ai"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(html, encoding="utf-8")
    for kind, name in PUBLISHED_NAMES.items():
        src = published_response_path(kind)
        if src.exists():
            (out / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return path
