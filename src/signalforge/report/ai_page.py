"""Static GitHub Pages export for AI trade trial responses."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from urllib.parse import quote

from signalforge.ai.adoption import adoption_eval_path, adoption_log_path
from signalforge.ai.approval import PUBLISHED_NAME as APPROVALS_PUBLISHED, load_approvals
from signalforge.ai.discover import PUBLISHED_NAME as DISCOVER_PUBLISHED, load_discover_response
from signalforge.ai.ledger import PUBLISHED_NAME as LEDGER_PUBLISHED, load_ledger, verify_ledger
from signalforge.ai.market_regime import (
    PUBLISHED_NAME as MARKET_PUBLISHED,
    STANCE_HELP,
    STANCE_JA,
    load_market_regime,
)
from signalforge.ai.packet import read_json
from signalforge.ai.publish import PUBLISHED_NAMES, load_response_for_pages, published_response_path
from signalforge.ai.paths import published_path
from signalforge.report.static_html import wrap_page
from signalforge.report.yahoo_jp import yahoo_jp_anchor, yahoo_jp_url


def _index_link(ticker: str | None, name: str | None = None) -> str:
    t = str(ticker or "").strip()
    if not t:
        return "—"
    label = escape(str(name or t))
    # JP ETFs via shared helper; US cash indices via Yahoo JP quote with encoding
    if t.endswith(".T"):
        return yahoo_jp_anchor(t, label=str(name or t))
    url = f"https://finance.yahoo.co.jp/quote/{quote(t, safe='')}"
    return f'<a href="{escape(url)}" target="_blank" rel="noopener">{label}</a>'

# Back-compat for dashboard_ai / tests importing private helpers.
YAHOO_JP_QUOTE = "https://finance.yahoo.co.jp/quote/{ticker}"
_yahoo_jp_url = yahoo_jp_url


def _ticker_link(ticker: str | None) -> str:
    return yahoo_jp_anchor(ticker)


def _ticker_list_links(tickers: list[Any] | None) -> str:
    items = [str(t).strip() for t in (tickers or []) if str(t).strip()]
    if not items:
        return "—"
    return ", ".join(_ticker_link(t) for t in items)


def _pct_cell(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return escape(f"{float(v):+.1%}")
    except (TypeError, ValueError):
        return "—"


def render_market_section() -> str:
    regime = load_market_regime()
    if not isinstance(regime, dict):
        return (
            '<section id="market"><h2>地合い（Market）</h2>'
            '<p class="muted">未生成。日次の <code>ai daily</code> または <code>ai market</code> で更新。</p></section>'
        )
    rows = []
    for i in regime.get("indices") or []:
        rows.append(
            [
                _index_link(i.get("ticker"), i.get("name")),
                escape(str(i.get("asset") or "")),
                escape(str(i.get("region") or "")),
                _pct_cell(i.get("ret_1d")),
                _pct_cell(i.get("ret_5d")),
                _pct_cell(i.get("ret_20d")),
                _pct_cell(i.get("vs_ma200") if i.get("vs_ma200") is not None else i.get("vs_ma25")),
                _stance_tip(str(i.get("stance") or ""), show_ja=True),
            ]
        )
    legend = regime.get("legend") or STANCE_HELP
    legend_bits = "".join(
        f'<li><span class="tip"><code>{escape(k)}</code>'
        f'<button type="button" class="tip-mark" aria-label="{escape(k)}の説明">?</button>'
        f'<span class="tip-bubble" role="tooltip">{escape(str(v))}</span></span>'
        f" — {escape(STANCE_JA.get(k, k))}</li>"
        for k, v in legend.items()
        if k in {"risk_on", "mixed_on", "mixed", "mixed_off", "risk_off"}
    )
    summary = " · ".join(
        [
            _stance_summary_tip("overall", regime.get("overall")),
            _stance_summary_tip("JP", regime.get("jp")),
            _stance_summary_tip("US", regime.get("us")),
            _stance_summary_tip("先物", regime.get("futures")),
        ]
    )
    return f"""
    <section id="market">
      <h2>地合い — 現金指数 + 先物</h2>
      <p class="muted">基準日 {escape(str(regime.get('as_of') or '—'))} ·
        ラベルにマウスを乗せると解説が出ます（? でも可）。</p>
      <p>{summary}</p>
      <p>{escape(str(regime.get('takeaway') or ''))}</p>
      <p class="muted">凡例（ホバーで詳細）</p>
      <ul class="compact">{legend_bits}</ul>
      {_table(["index", "asset", "region", "1d", "5d", "20d", "vsMA", "stance"], rows)}
    </section>
    """


def render_approvals_section() -> str:
    store = load_approvals()
    items = list(store.get("items") or [])
    if not items:
        return (
            '<section id="approvals"><h2>Approval ゲート</h2>'
            '<p class="muted">ADOPT 提案は <code>ai daily</code> 後に pending になります。'
            '<code>ai approve</code> / <code>ai reject</code> で人がゲート（発注なし）。</p></section>'
        )
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    for i in items:
        st = str(i.get("status") or "")
        if st in counts:
            counts[st] += 1
    rows = []
    for i in reversed(items[-20:]):
        rows.append(
            [
                escape(str(i.get("as_of") or "")),
                _ticker_link(i.get("ticker")),
                escape(str(i.get("name") or "")),
                escape(str(i.get("total") or "")),
                _badge(str(i.get("status") or "")),
                escape(str(i.get("note") or "")),
            ]
        )
    return f"""
    <section id="approvals">
      <h2>Approval — 人のゲート</h2>
      <p class="muted">システムは提案のみ。承認は CLI（<code>ai pending</code>）。発注には接続しません。</p>
      <div class="metrics">
        <div class="metric"><label>pending</label><value>{counts['pending']}</value></div>
        <div class="metric"><label>approved</label><value>{counts['approved']}</value></div>
        <div class="metric"><label>rejected</label><value>{counts['rejected']}</value></div>
      </div>
      {_table(["as_of", "ticker", "name", "total", "status", "note"], rows)}
    </section>
    """


def render_ledger_section() -> str:
    ledger = load_ledger()
    events = list(ledger.get("events") or [])
    check = verify_ledger(ledger)
    tip = str(check.get("tip") or "")[:16]
    if not events:
        return (
            '<section id="ledger"><h2>Ledger 監査</h2>'
            '<p class="muted">hash 連鎖の決定台帳はまだ空です。</p></section>'
        )
    rows = []
    for ev in events[-16:]:
        payload = ev.get("payload") or {}
        if payload.get("adopted"):
            detail = _ticker_list_links(payload.get("adopted"))
        elif payload.get("ticker"):
            detail = _ticker_link(payload.get("ticker"))
        else:
            detail = escape(str(payload.get("source") or payload.get("note") or ""))
        rows.append(
            [
                escape(str(ev.get("seq") or "")),
                escape(str(ev.get("kind") or "")),
                escape(str(ev.get("as_of") or "")),
                detail,
                escape(str(ev.get("hash") or "")[:12] + "…"),
            ]
        )
    ok = "OK" if check.get("ok") else "BROKEN"
    return f"""
    <section id="ledger">
      <h2>Ledger — hash 連鎖監査</h2>
      <p class="muted">改ざん検知用の決定台帳。検証: <strong>{escape(ok)}</strong>
        · tip <code>{escape(tip)}…</code> · events {len(events)}</p>
      {_table(["#", "kind", "as_of", "detail", "hash"], rows)}
    </section>
    """


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
    approved = (ev or {}).get("summary_approved") or {} if isinstance(ev, dict) else {}
    metrics = f"""
      <h3>Paper intent（approved のみ）</h3>
      <div class="metrics">
        <div class="metric"><label>承認行数</label><value>{escape(str(approved.get('n_paper_intents') or approved.get('n_adopted_rows') or 0))}</value></div>
        <div class="metric"><label>5日 評価数</label><value>{escape(str(approved.get('n_eval_5d') or 0))}</value></div>
        <div class="metric"><label>5日 平均</label><value>{_pct_cell(approved.get('mean_ret_5d'))}</value></div>
        <div class="metric"><label>5日 的中</label><value>{_pct_cell(approved.get('hit_rate_5d'))}</value></div>
        <div class="metric"><label>20日 平均</label><value>{_pct_cell(approved.get('mean_ret_20d'))}</value></div>
        <div class="metric"><label>20日 的中</label><value>{_pct_cell(approved.get('hit_rate_20d'))}</value></div>
      </div>
      <h3>提案全体（システム性能）</h3>
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
        adopted = _ticker_list_links(
            [a.get("ticker") for a in (e.get("adopted") or []) if a.get("ticker")]
        )
        recent.append(
            [
                escape(str(e.get("as_of") or "")),
                escape(str(e.get("source") or "")),
                adopted,
                escape(str(e.get("skipped_count") or 0)),
            ]
        )
    eval_rows = []
    for r in ((ev or {}).get("rows") or [])[-30:] if isinstance(ev, dict) else []:
        eval_rows.append(
            [
                escape(str(r.get("as_of") or "")),
                _ticker_link(r.get("ticker")),
                escape(str(r.get("name") or "")),
                _badge(str(r.get("gate") or "")),
                "Y" if r.get("paper_intent") else "",
                _pct_cell(r.get("ret_5d")),
                escape(str(r.get("status_5d") or "")),
                _pct_cell(r.get("ret_20d")),
                escape(str(r.get("status_20d") or "")),
            ]
        )
    return f"""
    <section id="adoption">
      <h2>Adoption — 採択ログとフォワード成績</h2>
      <p class="muted">提案全体と、<strong>approved のみの paper intent</strong> を分けて集計。
        キャッシュ日足で 5/20 営業日リターン。不足は pending。発注なし。</p>
      {metrics}
      <h3>最近の採択</h3>
      {_table(["as_of", "source", "adopted", "skipped"], recent)}
      <h3>銘柄別フォワード</h3>
      {_table(["as_of", "ticker", "name", "gate", "paper", "ret_5d", "5d", "ret_20d", "20d"], eval_rows)}
    </section>
    """


def _badge(text: str | None) -> str:
    s = (text or "—").upper()
    cls = "badge"
    if s in {"ADOPT", "BUY", "WATCH", "LONG_CANDIDATE", "APPROVED", "RISK_ON", "MIXED_ON"}:
        cls += " positive"
    elif s in {"AVOID", "SKIP", "REDUCE", "REJECTED", "RISK_OFF", "MIXED_OFF"}:
        cls += " negative"
    return f'<span class="{cls}">{escape(str(text or "—"))}</span>'


def _stance_tip(stance: str | None, *, show_ja: bool = True) -> str:
    """Badge + hover tip for market regime labels (risk_on / mixed / …)."""
    key = str(stance or "").strip().lower()
    help_text = STANCE_HELP.get(key) or "地合いラベル（簡易ルール）。売買シグナルではない。"
    ja = STANCE_JA.get(key, "")
    badge = _badge(key or "—")
    label = f"{badge} {escape(ja)}" if show_ja and ja else badge
    return (
        f'<span class="tip">{label}'
        f'<button type="button" class="tip-mark" aria-label="{escape(key or "stance")}の説明">?</button>'
        f'<span class="tip-bubble" role="tooltip">{escape(help_text)}</span></span>'
    )


def _stance_summary_tip(label: str, stance: str | None) -> str:
    """Summary chip (overall / JP / US / futures) with hover explanation."""
    key = str(stance or "").strip().lower()
    help_text = STANCE_HELP.get(key) or "地合いラベル（簡易ルール）。売買シグナルではない。"
    ja = STANCE_JA.get(key, key or "—")
    return (
        f'<span class="tip"><strong>{escape(label)}</strong> {escape(ja)}'
        f' <code>{escape(key or "—")}</code>'
        f'<button type="button" class="tip-mark" aria-label="{escape(label)}の説明">?</button>'
        f'<span class="tip-bubble" role="tooltip">{escape(help_text)}</span></span>'
    )


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
                _ticker_link(w.get("ticker")),
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
        f'<p class="positive"><strong>ADOPT:</strong> {_ticker_list_links(adopted)}</p>'
        if adopted
        else '<p class="muted">ADOPT なし</p>'
    )
    rows = []
    for s in resp.get("scores") or []:
        f = s.get("factors") or {}
        rows.append(
            [
                _badge(s.get("decision")),
                _ticker_link(s.get("ticker")),
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
              <h2>{_badge(d.get('decision'))} {_ticker_link(d.get('ticker'))}
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


def render_discover_section(resp: dict[str, Any] | None) -> str:
    if not resp:
        return (
            '<section id="discover"><h2>Discover — 独自発掘</h2>'
            '<p class="muted">未生成。 <code>uv run signalforge ai discover</code></p></section>'
        )
    cmp_ = resp.get("compare") or {}
    pool = resp.get("pool") or {}
    rows = []
    for s in (resp.get("scores") or [])[:40]:
        if s.get("decision") not in {"ADOPT", "WATCH"}:
            continue
        f = s.get("factors") or {}
        tag = "screen" if s.get("screen_passed") else "discover"
        rows.append(
            [
                _badge(s.get("decision")),
                escape(tag),
                _ticker_link(s.get("ticker")),
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
    <section id="discover">
      <h2>Discover — トレンド通過なしの独自発掘</h2>
      <p class="muted">
        基準日 {escape(str(resp.get('as_of') or '—'))} · generator {escape(str(resp.get('generator') or '—'))} ·
        母集団 {escape(str(pool.get('after_liquidity') or '—'))}/{escape(str(pool.get('universe_size') or '—'))}
        （売買代金 ≥ {escape(str(pool.get('min_turnover') or '—'))}）
      </p>
      <p><strong>ADOPT:</strong> {_ticker_list_links(cmp_.get("adopted"))}</p>
      <p class="positive"><strong>discover_only（スクリーニング非通過）:</strong>
        {_ticker_list_links(cmp_.get("discover_only"))}</p>
      <p><strong>overlap（スクリーニング通過と一致）:</strong>
        {_ticker_list_links(cmp_.get("overlap_with_screen"))}</p>
      {_table(["decision", "tag", "ticker", "name", "total", "trend", "mom", "risk", "liq", "event"], rows)}
    </section>
    """


def render_ai_body(
    brief: dict[str, Any] | None,
    score: dict[str, Any] | None,
    debate: dict[str, Any] | None,
    discover: dict[str, Any] | None = None,
) -> str:
    as_ofs = [r.get("as_of") for r in (brief, score, debate, discover) if r and r.get("as_of")]
    as_of = as_ofs[0] if as_ofs else "—"
    gen = (score or {}).get("generator") or (brief or {}).get("generator") or "—"
    return f"""
    <div class="info-box">
      GitHub Pages 用の AIトライアル結果です。発注には接続しません。
      日次 Actions が <code>ai daily</code>（ルールベース generator=<strong>{escape(str(gen))}</strong>）で更新します。
      <code>ai discover</code> はトレンド通過を外した発掘比較です。
      ADOPT は承認ゲート（<code>ai approve</code>）経由。基準日の目安: <strong>{escape(str(as_of))}</strong>
    </div>
    {render_market_section()}
    {render_brief_section(brief)}
    {render_score_section(score)}
    {render_discover_section(discover)}
    {render_debate_section(debate)}
    {render_approvals_section()}
    {render_ledger_section()}
    {render_adoption_section()}
    """


def export_ai_page(output_dir: Path) -> Path:
    brief = load_response_for_pages("brief")
    score = load_response_for_pages("score")
    debate = load_response_for_pages("debate")
    discover = load_discover_response()
    body = render_ai_body(brief, score, debate, discover)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title="AIトライアル",
        subtitle="地合い · Brief · Score · Debate · Approval · Ledger · Adoption（参考意見・非自動売買）",
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
    for src in (
        adoption_log_path(),
        adoption_eval_path(),
        published_path(DISCOVER_PUBLISHED),
        published_path(APPROVALS_PUBLISHED),
        published_path(LEDGER_PUBLISHED),
        published_path(MARKET_PUBLISHED),
    ):
        if src.exists():
            (out / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return path
