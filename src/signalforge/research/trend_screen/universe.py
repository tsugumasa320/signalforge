"""東証の普通株ユニバース。日足の有無とは別。"""

from __future__ import annotations

import re

_COMMON = re.compile(r"(\d{4}|\d{3}[A-HJ-NP-Z])")


def is_common_code(code: str) -> bool:
    """4桁、または3桁+英字の普通株コード。5桁の優先株などは含めない。"""
    base = code.upper().replace(".T", "").strip()
    return _COMMON.fullmatch(base) is not None


def normalize_ticker(raw: str) -> str:
    text = raw.strip().upper()
    if text.startswith("^"):
        return text
    base = text[:-2] if text.endswith(".T") else text
    if not is_common_code(base):
        raise ValueError(f"普通株コードとして解釈できません: {raw}")
    return f"{base}.T"


def domestic_common_rows(rows: list[dict]) -> list[dict]:
    kept = []
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if row.get("segment") not in {"prime", "standard", "growth"}:
            continue
        if not is_common_code(ticker):
            continue
        kept.append(row)
    return kept
