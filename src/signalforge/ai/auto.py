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

    total = int(round(trend + mom + risk + liq + event))
    decision = "WATCH"
    if r20 > 0.35 or vol > 0.9 or (days is not None and float(days) <= 7):
        decision = "SKIP"
    elif total >= 70:
        decision = "ADOPT"
    elif total < 60:
        decision = "SKIP"

    earn_next = c.get("earnings_next")
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
        ),
        "risk": (
            f"mdd_1y={c.get('mdd_1y')} · earnings_next={earn_next} · "
            f"earnings_next_days={days} · event_data={event_data}"
        ),
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
            f"ADOPT は最大 {max_adopt} 銘柄",
        ],
    }


def generate_brief_response(packet: dict[str, Any], score_resp: dict[str, Any] | None = None) -> dict[str, Any]:
    ts = packet.get("trend_screen") or {}
    paper = packet.get("trend_paper") or {}
    as_of = ts.get("as_of") or packet.get("generated_at")
    targets = ts.get("targets") or []
    holdings = paper.get("holdings") or []
    adopted = set((score_resp or {}).get("adopted") or [])

    watch: list[dict[str, Any]] = []
    for t in targets:
        ticker = str(t.get("ticker") or "")
        r20 = float(t.get("ret_20d") or 0)
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
        watch.append(
            {
                "ticker": ticker,
                "name": t.get("name"),
                "stance": stance,
                "confidence": conf,
                "why": why,
                "risk": risk,
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
        ],
        "skip_today": skip,
        "actions_for_human": [
            "ADOPT / REDUCE 銘柄のチャート確認",
            "紙上ドロー銘柄の出口ルール確認",
            "採用したら ai adoption ログで追跡（日次で自動）",
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
        debates.append(
            {
                "ticker": ticker,
                "name": name,
                "bull": f"スクリーニング通過・1年{_pct(m.get('ret_1y'))}・20日{_pct(r20)}。",
                "bear": f"vol_1y={vol:.2f} · mdd_1y={m.get('mdd_1y')} · earnings_next_days={days}。",
                "risk_officer": "参考意見のみ。発注・サイズ指定はしない。",
                "decision": decision,
                "confidence": conf,
                "invalidation": "vs_ma25 が負転、または20日リターンが急反落。",
                "why_this_could_fail": "スクリーニング遅行やイベントギャップ。",
            }
        )
    return {
        "as_of": packet.get("as_of"),
        "generator": "rules/v1",
        "debates": debates,
        "committee_summary": (
            "ルールベース議論。BUY は過熱・直近決算を避けた候補のみ。"
            "人が最終判断し、発注には接続しない。"
        ),
    }
