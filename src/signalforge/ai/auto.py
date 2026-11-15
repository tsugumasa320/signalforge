"""Rule-based AI responses for CI (no LLM API required)."""

from __future__ import annotations

from typing import Any


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _pct(x: Any) -> str:
    try:
        return f"{float(x):+.1%}"
    except (TypeError, ValueError):
        return "—"


def score_candidate(c: dict[str, Any]) -> dict[str, Any]:
    trend = 10.0
    if (c.get("ret_1y") or 0) > 0.5:
        trend += 4
    if (c.get("vs_ma25") or 0) > 0:
        trend += 3
    if (c.get("trend_r2") or 0) > 0.7:
        trend += 3
    trend = _clamp(trend, 0, 20)

    r20 = float(c.get("ret_20d") or 0)
    mom = 12.0
    if 0.02 <= r20 <= 0.12:
        mom += 6
    elif r20 > 0.35:
        mom -= 8
    elif r20 > 0.2:
        mom -= 3
    elif r20 < 0:
        mom -= 4
    mom = _clamp(mom, 0, 20)

    risk = 16.0
    vol = float(c.get("vol_1y") or 0.4)
    mdd = abs(float(c.get("mdd_1y") or 0))
    if vol > 0.8:
        risk -= 8
    elif vol > 0.5:
        risk -= 4
    if mdd > 0.4:
        risk -= 6
    elif mdd > 0.25:
        risk -= 3
    risk = _clamp(risk, 0, 20)

    turn = float(c.get("turnover_20d") or 0)
    if turn >= 1e10:
        liq = 18.0
    elif turn >= 5e9:
        liq = 14.0
    elif turn >= 2e9:
        liq = 10.0
    else:
        liq = 6.0

    days = c.get("earnings_next_days")
    event_data = c.get("event_data") or ("missing" if days is None else "ranking")
    if days is not None:
        if float(days) <= 7:
            event = 6.0
        elif float(days) <= 21:
            event = 10.0
        else:
            event = 17.0
    elif event_data == "missing":
        # Unknown calendar: neutral (do not invent a blank-window bonus).
        event = 12.0
    else:
        # Ranking/cache known but no upcoming date → treat as event-blank.
        event = 16.0

    surprise = c.get("surprise") if isinstance(c.get("surprise"), dict) else None
    if surprise and surprise.get("days_ago") is not None and int(surprise["days_ago"]) <= 45:
        if surprise.get("c0"):
            event += 2
        if surprise.get("rev_op") is True:
            event += 1
        yoy = surprise.get("op_yoy")
        if yoy is not None and float(yoy) <= -0.2:
            event -= 3
        elif yoy is not None and float(yoy) >= 0.2 and surprise.get("c0"):
            event += 1

    news_sent = c.get("news_sentiment")
    if news_sent == "positive":
        event += 1
    elif news_sent == "negative":
        event -= 2
    event = _clamp(event, 0, 20)

    total = int(round(trend + mom + risk + liq + event))
    decision = "WATCH"
    if r20 > 0.35 or vol > 0.9 or (days is not None and float(days) <= 7):
        decision = "SKIP"
    elif news_sent == "negative" and surprise and surprise.get("c0") is False:
        decision = "SKIP" if total < 75 else "WATCH"
    elif total >= 70:
        decision = "ADOPT"
    elif total < 60:
        decision = "SKIP"

    earn_next = c.get("earnings_next")
    content_bits = []
    if surprise and surprise.get("summary"):
        content_bits.append(str(surprise["summary"]))
    if news_sent and news_sent != "neutral":
        content_bits.append(f"news={news_sent}")
    titles = [str(n.get("title") or "") for n in (c.get("news") or [])[:2] if isinstance(n, dict)]
    if titles:
        content_bits.append(" / ".join(titles)[:120])

    return {
        "ticker": c.get("ticker"),
        "name": c.get("name"),
        "total": total,
        "decision": decision,
        "factors": {
            "trend": int(trend),
            "momentum": int(mom),
            "risk": int(risk),
            "liquidity": int(liq),
            "event": int(event),
        },
        "why": (
            f"1年{_pct(c.get('ret_1y'))} · 20日{_pct(r20)} · "
            f"vol={vol:.2f} · turnover={turn:.0f}"
            + ((" · " + " · ".join(content_bits)) if content_bits else "")
        ),
        "risk": (
            f"mdd_1y={c.get('mdd_1y')} · earnings_next={earn_next} · "
            f"earnings_next_days={days} · event_data={event_data} · "
            f"content_data={c.get('content_data')}"
        ),
        "surprise": surprise,
        "news": c.get("news"),
        "news_sentiment": news_sent,
        "content_data": c.get("content_data"),
    }


def generate_score_response(packet: dict[str, Any], *, max_adopt: int = 4) -> dict[str, Any]:
    scored = [score_candidate(c) for c in (packet.get("candidates") or [])]
    scored.sort(key=lambda s: float(s.get("total") or 0), reverse=True)
    adopted: list[str] = []
    for row in scored:
        if row["decision"] == "ADOPT":
            if len(adopted) >= max_adopt:
                row["decision"] = "WATCH"
            else:
                adopted.append(str(row["ticker"]))
    return {
        "as_of": packet.get("as_of"),
        "generator": "rules/v1",
        "scores": scored,
        "adopted": adopted,
        "skipped_reasons": [
            "20日リターンが概ね35%超、または vol_1y>0.9 は SKIP",
            "決算7日以内（earnings_next_days≤7）は SKIP",
            "決算カレンダー欠損は event を中立点（event_data=missing）",
            "直近サプライズ悪材料 + ネガティブ見出しは慎重に SKIP/WATCH",
            f"ADOPT は最大 {max_adopt} 銘柄",
        ],
    }


def _content_line(row: dict[str, Any]) -> str:
    bits: list[str] = []
    surprise = row.get("surprise") if isinstance(row.get("surprise"), dict) else None
    if surprise and surprise.get("summary"):
        bits.append(str(surprise["summary"]))
    news = row.get("news") or []
    if news and isinstance(news[0], dict) and news[0].get("title"):
        bits.append(f"ニュース: {news[0]['title'][:80]}")
    sent = row.get("news_sentiment")
    if sent and sent != "neutral":
        bits.append(f"見出し={sent}")
    return " · ".join(bits)


def generate_brief_response(packet: dict[str, Any], score_resp: dict[str, Any] | None = None) -> dict[str, Any]:
    from signalforge.ai.content import enrich_content_rows
    from signalforge.ai.events import enrich_event_rows

    ts = packet.get("trend_screen") or {}
    paper = packet.get("trend_paper") or {}
    as_of = ts.get("as_of") or packet.get("generated_at")
    as_of_s = str(as_of)[:10] if as_of else None
    targets = enrich_content_rows(
        enrich_event_rows(list(ts.get("targets") or []), as_of=as_of_s),
        as_of=as_of_s,
        fetch_news=False,
    )
    holdings = paper.get("holdings") or []
    adopted = set((score_resp or {}).get("adopted") or [])
    score_by_ticker = {
        str(s.get("ticker")): s for s in ((score_resp or {}).get("scores") or []) if s.get("ticker")
    }

    watch: list[dict[str, Any]] = []
    for t in targets:
        ticker = str(t.get("ticker") or "")
        r20 = float(t.get("ret_20d") or 0)
        scored = score_by_ticker.get(ticker) or {}
        # Prefer score-packet content (may include freshly fetched news).
        content_src = scored if scored.get("surprise") or scored.get("news") else t
        content = _content_line(content_src)
        if ticker in adopted:
            stance, conf = "WATCH", 70
            why = "採点 ADOPT。目標入りかつ過熱が相対的に軽い。"
            risk = "スクリーニング遅行・セクター感応。"
        elif r20 > 0.35:
            stance, conf = "AVOID", 72
            why = f"目標入りだが20日{_pct(r20)}で過熱。"
            risk = "追撃よりサイズ管理。"
        else:
            stance, conf = "WATCH", 62
            why = f"目標 {t.get('rank')} 位 · 1年{_pct(t.get('ret_1y'))} · 20日{_pct(r20)}"
            risk = "イベント日付はパケット次第。"
        if content:
            why = f"{why} · {content}"
        watch.append(
            {
                "ticker": ticker,
                "name": t.get("name"),
                "stance": stance,
                "confidence": conf,
                "why": why,
                "risk": risk,
                "surprise": content_src.get("surprise"),
                "news": content_src.get("news"),
                "content_data": content_src.get("content_data"),
            }
        )

    for h in holdings:
        ret = float(h.get("return") or 0)
        if ret <= -0.15:
            watch.append(
                {
                    "ticker": h.get("ticker"),
                    "name": h.get("name"),
                    "stance": "REDUCE",
                    "confidence": 68,
                    "why": f"紙上保有リターン {_pct(ret)}。当月の足を引っ張りやすい。",
                    "risk": "ルール上の出口確認。裁量損切りは別判断。",
                }
            )

    month_ex = paper.get("month_excess")
    market_take = (
        f"トレンド通過 {ts.get('n_pass')} / 目標 {ts.get('n_target')}。"
        f"紙上当月超過は {_pct(month_ex)}。"
        "ルールベース自動 Brief（LLMなし）。新規攻めより保有点検を優先。"
    )
    skip = [
        "過熱銘柄（20日リターンが極端）の追撃",
        "分散ペーパーが弱い局面でのサイズ拡大",
    ]
    if any((t.get("earnings_next") for t in targets)):
        skip.append("直近決算銘柄の新規")

    return {
        "as_of": as_of,
        "generator": "rules/v1",
        "market_take": market_take,
        "watch": watch[:8],
        "paper_notes": [
            f"trend_paper open={paper.get('open')} · month_excess={_pct(month_ex)}",
            f"diversified papers={len(packet.get('diversified_papers') or [])} 口座を参照",
            "内容: surprise=earnings_surprise/fins · news=data/alt/news（あれば why に併記）",
        ],
        "skip_today": skip,
        "actions_for_human": [
            "ADOPT 提案を `ai pending` で確認し、`ai approve` / `ai reject` でゲートする",
            "ADOPT / REDUCE 銘柄のチャート確認（Yahoo JP リンク）",
            "紙上ドロー銘柄の出口ルール確認",
            "サプライズ悪材料・ネガティブ見出しの銘柄は一次情報を確認",
            "追跡は adoption ログ＋hash 台帳（`ai ledger`）で自動",
        ],
        "committee_roles": [
            "analyst_score",
            "brief_summarizer",
            "bull_researcher",
            "bear_researcher",
            "risk_officer",
            "human_approver",
        ],
    }


def generate_debate_response(packet: dict[str, Any]) -> dict[str, Any]:
    debates = []
    for n in packet.get("names") or []:
        m = n.get("metrics") or {}
        ticker = str(n.get("ticker") or "")
        name = m.get("name") or ticker
        r20 = float(m.get("ret_20d") or 0)
        vol = float(m.get("vol_1y") or 0)
        days = m.get("earnings_next_days")
        if r20 > 0.35 or vol > 0.9:
            decision, conf = "AVOID", 70
        elif days is not None and float(days) <= 7:
            decision, conf = "HOLD", 55
        elif r20 < 0.15 and (m.get("ret_1y") or 0) > 0.3:
            decision, conf = "BUY", 64
        else:
            decision, conf = "HOLD", 58
        content = _content_line(m)
        bull = f"スクリーニング通過・1年{_pct(m.get('ret_1y'))}・20日{_pct(r20)}。"
        bear = f"vol_1y={vol:.2f} · mdd_1y={m.get('mdd_1y')} · earnings_next_days={days}。"
        if content:
            bull = f"{bull} 内容: {content}"
            if m.get("news_sentiment") == "negative" or (
                isinstance(m.get("surprise"), dict) and (m["surprise"].get("op_yoy") or 0) < -0.2
            ):
                bear = f"{bear} 内容リスク: {content}"
        debates.append(
            {
                "ticker": ticker,
                "name": name,
                "bull": bull,
                "bear": bear,
                "risk_officer": (
                    "参考意見のみ。発注・サイズ指定はしない。"
                    "人間が ai approve するまで paper intent にしない。"
                ),
                "roles": {
                    "bull_researcher": "bull",
                    "bear_researcher": "bear",
                    "risk_officer": "risk_officer",
                    "human_approver": "pending_gate",
                },
                "decision": decision,
                "confidence": conf,
                "invalidation": "vs_ma25 が負転、または20日リターンが急反落。",
                "why_this_could_fail": "スクリーニング遅行やイベントギャップ・決算内容の織り込み遅れ。",
                "surprise": m.get("surprise"),
                "news": m.get("news"),
            }
        )
    return {
        "as_of": packet.get("as_of"),
        "generator": "rules/v1",
        "debates": debates,
        "committee_roles": [
            "bull_researcher",
            "bear_researcher",
            "risk_officer",
            "human_approver",
        ],
        "committee_summary": (
            "ルールベース議論（TradingAgents 型の役割分け）。"
            "BUY は過熱・直近決算を避けた候補のみ。"
            "人が ai approve / reject で最終ゲートし、発注には接続しない。"
        ),
    }
