"""Static GitHub Pages export for AI trade trial responses."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from signalforge.ai.adoption import adoption_eval_path, adoption_log_path
from signalforge.ai.packet import read_json
from signalforge.ai.publish import PUBLISHED_NAMES, load_response_for_pages, published_response_path
from signalforge.report.static_html import wrap_page


def _pct_cell(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return escape(f"{float(v):+.1%}")
    except (TypeError, ValueError):
        return "—"


def render_adoption_section() -> str:
    log = read_json(adoption_log_path()) if adoption_log_path().exists() else None
    ev = read_json(adoption_eval_path()) if adoption_eval_path().exists() else None
    if not isinstance(log, dict) and not isinstance(ev, dict):
        return (
            '<section id="adoption"><h2>Adoption 成績</h2>'
            '<p class="muted">まだ採択ログがありません。日次の <code>ai daily</code> で溜まります。</p></section>'
        )
    entries = (log or {}).get("entries") or [] if isinstance(log, dict) else []
    summary = (ev or {}).get("summary") or {} if isinstance(ev, dict) else {}
    metrics = f"""
      <div class="metrics">
        <div class="metric"><label>採択行数</label><value>{escape(str(summary.get('n_adopted_rows') or len(entries)))}</value></div>
        <div class="metric"><label>5日 評価数</label><value>{escape(str(summary.get('n_eval_5d') or 0))}</value></div>
        <div class="metric"><label>5日 平均</label><value>{_pct_cell(summary.get('mean_ret_5d'))}</value></div>
        <div class="metric"><label>5日 的中</label><value>{_pct_cell(summary.get('hit_rate_5d'))}</value></div>
        <div class="metric"><label>20日 平均</label><value>{_pct_cell(summary.get('mean_ret_20d'))}</value></div>
        <div class="metric"><label>20日 的中</label><value>{_pct_cell(summary.get('hit_rate_20d'))}</value></div>
      </div>
    """
    recent = []
    for e in reversed(entries[-8:]):
        adopted = ", ".join(
            str(a.get("ticker") or "") for a in (e.get("adopted") or []) if a.get("ticker")
        ) or "—"
        recent.append(
            [
                escape(str(e.get("as_of") or "")),
                escape(str(e.get("source") or "")),
                escape(adopted),
                escape(str(e.get("skipped_count") or 0)),
            ]
        )
    eval_rows = []
    for r in ((ev or {}).get("rows") or [])[-30:] if isinstance(ev, dict) else []:
        eval_rows.append(
            [
                escape(str(r.get("as_of") or "")),
                escape(str(r.get("ticker") or "")),
                escape(str(r.get("name") or "")),
                _pct_cell(r.get("ret_5d")),
                escape(str(r.get("status_5d") or "")),
                _pct_cell(r.get("ret_20d")),
                escape(str(r.get("status_20d") or "")),
            ]
        )
    return f"""
    <section id="adoption">
      <h2>Adoption — 採択ログとフォワード成績</h2>
      <p class="muted">ADOPT 銘柄を記録し、キャッシュ日足で 5営業日 / 20営業日リターンを集計。不足データは pending。</p>
      {metrics}
      <h3>最近の採択</h3>
      {_table(["as_of", "source", "adopted", "skipped"], recent)}
      <h3>銘柄別フォワード</h3>
      {_table(["as_of", "ticker", "name", "ret_5d", "5d", "ret_20d", "20d"], eval_rows)}
    </section>
    """


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
    gen = (score or {}).get("generator") or (brief or {}).get("generator") or "—"
    return f"""
    <div class="info-box">
      GitHub Pages 用の AIトライアル結果です。発注には接続しません。
      日次 Actions が <code>ai daily</code>（ルールベース generator=<strong>{escape(str(gen))}</strong>）で更新します。
      基準日の目安: <strong>{escape(str(as_of))}</strong>
    </div>
    {render_brief_section(brief)}
    {render_score_section(score)}
    {render_debate_section(debate)}
    {render_adoption_section()}
    """


def export_ai_page(output_dir: Path) -> Path:
    brief = load_response_for_pages("brief")
    score = load_response_for_pages("score")
    debate = load_response_for_pages("debate")
    body = render_ai_body(brief, score, debate)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title="AIトライアル",
        subtitle="Brief · Score · Debate · Adoption（参考意見・非自動売買）",
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
    for src in (adoption_log_path(), adoption_eval_path()):
        if src.exists():
            (out / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return path
