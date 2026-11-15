"""Streamlit panel for AI trade trial packets and responses."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from signalforge.ai.paths import ai_dir
from signalforge.ai.publish import load_response_for_pages, published_response_path
from signalforge.report.ai_page import _yahoo_jp_url


def _md_ticker(ticker: str | None) -> str:
    t = str(ticker or "").strip()
    if not t:
        return "—"
    url = _yahoo_jp_url(t)
    return f"[{t}]({url})" if url else t


def _file_mtime(path: Path) -> str:
    if not path.exists():
        return "未生成"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def _stance_emoji(stance: str | None) -> str:
    s = (stance or "").upper()
    if s in {"ADOPT", "BUY", "LONG_CANDIDATE", "WATCH"}:
        return "🟢"
    if s in {"HOLD"}:
        return "🟡"
    if s in {"REDUCE", "AVOID", "SKIP"}:
        return "🔴"
    return "⚪"


def _missing_box(cmd: str) -> None:
    st.info(
        f"まだ結果がありません。先に `{cmd}` を実行し、"
        "AIの返答を `signalforge ai save-response …` で保存してください。"
    )


def _render_brief(resp: dict[str, Any] | None, packet_mtime: str) -> None:
    st.subheader("日次ブリーフィング")
    st.caption(f"パケット更新: {packet_mtime}")
    if not resp:
        _missing_box("uv run signalforge ai brief")
        return
    st.markdown(f"**基準日:** {resp.get('as_of') or '—'}")
    st.write(resp.get("market_take") or "—")
    watch = resp.get("watch") or []
    if watch:
        rows = [
            {
                "stance": f"{_stance_emoji(w.get('stance'))} {w.get('stance')}",
                "ticker": w.get("ticker"),
                "yahoo": _yahoo_jp_url(w.get("ticker")),
                "name": w.get("name"),
                "confidence": w.get("confidence"),
                "why": w.get("why"),
                "risk": w.get("risk"),
            }
            for w in watch
        ]
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "yahoo": st.column_config.LinkColumn("Yahoo JP", display_text="開く"),
            },
        )
    notes = resp.get("paper_notes") or []
    if notes:
        st.markdown("**ペーパーメモ**")
        for n in notes:
            st.write(f"- {n}")
    skip = resp.get("skip_today") or []
    if skip:
        st.markdown("**今日やらないこと**")
        for n in skip:
            st.write(f"- {n}")
    actions = resp.get("actions_for_human") or []
    if actions:
        st.markdown("**人がやること**")
        for n in actions:
            st.write(f"- {n}")


def _render_score(resp: dict[str, Any] | None, packet_mtime: str) -> None:
    st.subheader("候補採点")
    st.caption(f"パケット更新: {packet_mtime}")
    if not resp:
        _missing_box("uv run signalforge ai score")
        return
    st.markdown(f"**基準日:** {resp.get('as_of') or '—'}")
    adopted = resp.get("adopted") or []
    if adopted:
        st.markdown("ADOPT: " + ", ".join(_md_ticker(t) for t in adopted))
    scores = resp.get("scores") or []
    if scores:
        rows = []
        for s in scores:
            factors = s.get("factors") or {}
            rows.append(
                {
                    "decision": f"{_stance_emoji(s.get('decision'))} {s.get('decision')}",
                    "ticker": s.get("ticker"),
                    "yahoo": _yahoo_jp_url(s.get("ticker")),
                    "name": s.get("name"),
                    "total": s.get("total"),
                    "trend": factors.get("trend"),
                    "momentum": factors.get("momentum"),
                    "risk": factors.get("risk"),
                    "liquidity": factors.get("liquidity"),
                    "event": factors.get("event"),
                    "why": s.get("why"),
                }
            )
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "yahoo": st.column_config.LinkColumn("Yahoo JP", display_text="開く"),
            },
        )
    reasons = resp.get("skipped_reasons") or []
    if reasons:
        st.markdown("**SKIP理由の方針**")
        for r in reasons:
            st.write(f"- {r}")


def _render_debate(resp: dict[str, Any] | None, packet_mtime: str) -> None:
    st.subheader("ブル／ベア議論")
    st.caption(f"パケット更新: {packet_mtime}")
    if not resp:
        _missing_box("uv run signalforge ai debate")
        return
    st.markdown(f"**基準日:** {resp.get('as_of') or '—'}")
    summary = resp.get("committee_summary")
    if summary:
        st.write(summary)
    for d in resp.get("debates") or []:
        title = (
            f"{_stance_emoji(d.get('decision'))} {d.get('ticker')} "
            f"{d.get('name') or ''} · {d.get('decision')} ({d.get('confidence')})"
        )
        with st.expander(title, expanded=False):
            st.markdown(f"**銘柄:** {_md_ticker(d.get('ticker'))}")
            st.markdown(f"**Bull:** {d.get('bull') or '—'}")
            st.markdown(f"**Bear:** {d.get('bear') or '—'}")
            st.markdown(f"**Risk:** {d.get('risk_officer') or '—'}")
            st.markdown(f"**Invalidation:** {d.get('invalidation') or '—'}")
            st.markdown(f"**Fail case:** {d.get('why_this_could_fail') or '—'}")


def render_ai_panel() -> None:
    """Show latest AI trial responses (same sources as GitHub Pages)."""
    base = ai_dir()
    brief_resp = load_response_for_pages("brief")
    score_resp = load_response_for_pages("score")
    debate_resp = load_response_for_pages("debate")

    c1, c2, c3 = st.columns(3)
    c1.metric("Brief 返答", _file_mtime(published_response_path("brief")))
    c2.metric("Score 返答", _file_mtime(published_response_path("score")))
    c3.metric("Debate 返答", _file_mtime(published_response_path("debate")))
    st.caption(
        "発注には接続しません。GitHub Pages と同じ `data/published/ai_*.json` を優先表示。"
        " 手順: `docs/ai_trade.md` · 公開URL: …/signalforge/ai/"
    )

    tab_b, tab_s, tab_d, tab_g, tab_a = st.tabs(
        ["Brief", "Score", "Debate", "Gate", "Adoption"]
    )
    with tab_b:
        _render_brief(brief_resp, _file_mtime(base / "brief_latest.json"))
    with tab_s:
        _render_score(score_resp, _file_mtime(base / "scores_latest.json"))
    with tab_d:
        _render_debate(debate_resp, _file_mtime(base / "debate_latest.json"))
    with tab_g:
        from signalforge.ai.approval import approval_summary, list_pending, load_approvals
        from signalforge.ai.ledger import load_ledger, verify_ledger

        summary = approval_summary()
        c1, c2, c3 = st.columns(3)
        c1.metric("pending", summary.get("pending") or 0)
        c2.metric("approved", summary.get("approved") or 0)
        c3.metric("rejected", summary.get("rejected") or 0)
        st.caption("`uv run signalforge ai pending` → `ai approve TICKER` / `ai reject TICKER`")
        pending = list_pending()
        if pending:
            for p in pending:
                st.markdown(
                    f"- `{p.get('as_of')}` · {_md_ticker(p.get('ticker'))} · "
                    f"{p.get('name') or ''} · total={p.get('total')}"
                )
        else:
            st.info("承認待ちはありません。")
        items = load_approvals().get("items") or []
        if items:
            st.dataframe(pd.DataFrame(items[-20:]), width="stretch", hide_index=True)
        ledger = load_ledger()
        check = verify_ledger(ledger)
        st.markdown(
            f"**Ledger** verify={'OK' if check.get('ok') else 'BROKEN'} · "
            f"events={check.get('n_events')}"
        )
        events = ledger.get("events") or []
        if events:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "seq": e.get("seq"),
                            "kind": e.get("kind"),
                            "as_of": e.get("as_of"),
                            "hash": str(e.get("hash") or "")[:12],
                        }
                        for e in events[-12:]
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
    with tab_a:
        from signalforge.ai.adoption import adoption_eval_path, adoption_log_path, load_adoption_log
        from signalforge.ai.packet import read_json

        log = load_adoption_log()
        ev = read_json(adoption_eval_path()) if adoption_eval_path().exists() else None
        st.caption(f"log: {_file_mtime(adoption_log_path())} · eval: {_file_mtime(adoption_eval_path())}")
        entries = log.get("entries") or []
        if not entries:
            st.info("採択ログがありません。`uv run signalforge ai daily` を実行してください。")
        else:
            st.write(f"エントリ数: {len(entries)}")
            for e in entries[-10:]:
                tickers_md = ", ".join(
                    _md_ticker(a.get("ticker")) for a in (e.get("adopted") or []) if a.get("ticker")
                )
                st.markdown(
                    f"- `{e.get('as_of')}` · {e.get('source') or '—'} · "
                    f"ADOPT: {tickers_md or '—'} · skip {e.get('skipped_count')}"
                )
        if isinstance(ev, dict):
            approved = ev.get("summary_approved") or {}
            st.subheader("Paper intent（approved）")
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("intents", approved.get("n_paper_intents") or approved.get("n_adopted_rows") or 0)
            mean5a = approved.get("mean_ret_5d")
            a2.metric("5日平均", "—" if mean5a is None else f"{float(mean5a):+.1%}")
            mean20a = approved.get("mean_ret_20d")
            a3.metric("20日平均", "—" if mean20a is None else f"{float(mean20a):+.1%}")
            hit5a = approved.get("hit_rate_5d")
            a4.metric("5日的中", "—" if hit5a is None else f"{float(hit5a):.0%}")

            summary = ev.get("summary") or {}
            st.subheader("提案全体")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("5日 n", summary.get("n_eval_5d") or 0)
            mean5 = summary.get("mean_ret_5d")
            c2.metric("5日平均", "—" if mean5 is None else f"{float(mean5):+.1%}")
            mean20 = summary.get("mean_ret_20d")
            c3.metric("20日平均", "—" if mean20 is None else f"{float(mean20):+.1%}")
            hit5 = summary.get("hit_rate_5d")
            c4.metric("5日的中", "—" if hit5 is None else f"{float(hit5):.0%}")
            rows = ev.get("rows") or []
            if rows:
                link_rows = []
                for r in rows:
                    link_rows.append({**r, "yahoo": _yahoo_jp_url(r.get("ticker"))})
                st.dataframe(
                    pd.DataFrame(link_rows),
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "yahoo": st.column_config.LinkColumn("Yahoo JP", display_text="開く"),
                    },
                )
