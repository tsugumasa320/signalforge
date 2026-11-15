"""Streamlit panel for AI trade trial packets and responses."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from signalforge.ai.paths import ai_dir
from signalforge.ai.publish import load_response_for_pages, published_response_path


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
                "name": w.get("name"),
                "confidence": w.get("confidence"),
                "why": w.get("why"),
                "risk": w.get("risk"),
            }
            for w in watch
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
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
        st.success("ADOPT: " + ", ".join(str(t) for t in adopted))
    scores = resp.get("scores") or []
    if scores:
        rows = []
        for s in scores:
            factors = s.get("factors") or {}
            rows.append(
                {
                    "decision": f"{_stance_emoji(s.get('decision'))} {s.get('decision')}",
                    "ticker": s.get("ticker"),
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
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
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

    tab_b, tab_s, tab_d = st.tabs(["Brief", "Score", "Debate"])
    with tab_b:
        _render_brief(brief_resp, _file_mtime(base / "brief_latest.json"))
    with tab_s:
        _render_score(score_resp, _file_mtime(base / "scores_latest.json"))
    with tab_d:
        _render_debate(debate_resp, _file_mtime(base / "debate_latest.json"))
