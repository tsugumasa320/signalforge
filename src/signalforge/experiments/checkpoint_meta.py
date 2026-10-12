"""Fast checkpoint progress reads (avoid parsing MB-scale JSON)."""

from __future__ import annotations

import json
import re
from pathlib import Path

_META_DONE = re.compile(r'"n_tickers_done"\s*:\s*(\d+)')
_META_TARGET = re.compile(r'"n_tickers_target"\s*:\s*(\d+)')


def read_checkpoint_progress(path: Path) -> dict[str, int]:
    """Return n_tickers_done / n_tickers_target without loading ticker rows."""
    if not path.exists():
        return {"n_tickers_done": 0, "n_tickers_target": 0}
    size = path.stat().st_size
    if size <= 256_000:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                return {
                    "n_tickers_done": int(doc.get("n_tickers_done") or 0),
                    "n_tickers_target": int(doc.get("n_tickers_target") or 0),
                }
        except json.JSONDecodeError:
            pass
    text = path.read_text(encoding="utf-8", errors="replace")
    done_m = _META_DONE.search(text)
    tgt_m = _META_TARGET.search(text)
    return {
        "n_tickers_done": int(done_m.group(1)) if done_m else 0,
        "n_tickers_target": int(tgt_m.group(1)) if tgt_m else 0,
    }
