"""Minimal J-Quants API V2 client (x-api-key)."""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://api.jquants.com/v2"


class JQuantsError(RuntimeError):
    pass


def api_key() -> str:
    key = (os.getenv("JQUANTS_API_KEY") or "").strip()
    if not key:
        raise JQuantsError(
            "環境変数 JQUANTS_API_KEY が未設定です。"
            " https://jpx-jquants.com/ で無料プラン登録 → ダッシュボード「API Key」を発行し、"
            " export JQUANTS_API_KEY='...' または .env に記載してください。"
        )
    return key


def listing_code_to_jquants(code: str) -> str:
    """TSE listing code (4 digits) → J-Quants issue code (often 5 digits)."""
    c = str(code).strip()
    if len(c) == 4 and c.isdigit():
        return f"{c}0"
    return c


def ticker_to_jquants_code(ticker: str) -> str:
    base = ticker.replace(".T", "").strip()
    return listing_code_to_jquants(base)


def get_paginated(path: str, params: dict[str, Any], *, max_pages: int = 500) -> list[dict[str, Any]]:
    """GET with pagination_key until exhausted."""
    key = api_key()
    out: list[dict[str, Any]] = []
    pagination_key: str | None = None
    for _ in range(max_pages):
        q = dict(params)
        if pagination_key:
            q["pagination_key"] = pagination_key
        url = f"{BASE_URL}{path}?{urlencode({k: v for k, v in q.items() if v is not None})}"
        req = Request(url, headers={"x-api-key": key})
        for attempt in range(6):
            try:
                with urlopen(req, timeout=120) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                break
            except HTTPError as e:
                if e.code == 429 and attempt < 5:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                detail = e.read().decode("utf-8", errors="replace")[:500]
                raise JQuantsError(f"J-Quants HTTP {e.code}: {detail}") from e
        rows = body.get("data") or []
        if isinstance(rows, list):
            out.extend(r for r in rows if isinstance(r, dict))
        pagination_key = body.get("pagination_key") or body.get("paginationKey")
        if not pagination_key:
            break
    return out


def test_connection(*, sample_code: str = "72030") -> dict[str, Any]:
    """Verify API key (Free plan: master + earnings-calendar; margin may be paid-only)."""
    master = get_paginated("/equities/master", {"code": sample_code}, max_pages=1)
    cal = get_paginated("/equities/earnings-calendar", {"code": sample_code}, max_pages=1)
    margin_ok = False
    margin_note = ""
    try:
        m = get_paginated(
            "/markets/margin-interest",
            {"code": sample_code, "from": "20240101", "to": "20240131"},
            max_pages=1,
        )
        margin_ok = len(m) >= 0
    except JQuantsError as e:
        margin_note = str(e)
    return {
        "ok": True,
        "code": sample_code,
        "master_rows": len(master),
        "earnings_calendar_rows": len(cal),
        "margin_interest_available": margin_ok,
        "margin_note": margin_note[:200] if margin_note else "",
    }
