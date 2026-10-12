"""Split legacy monolithic checkpoint JSON into meta + tickers sidecar."""

from __future__ import annotations

import json
from pathlib import Path

from signalforge.experiments.runner import _checkpoint_path, _checkpoint_tickers_path, experiments_dir


def migrate_oversized_checkpoints(*, min_bytes: int = 256_000) -> list[str]:
    migrated: list[str] = []
    d = experiments_dir() / "strategies"
    if not d.is_dir():
        return migrated
    for path in sorted(d.glob("*.checkpoint.json")):
        if path.stat().st_size < min_bytes:
            continue
        sid = path.name.replace(".checkpoint.json", "")
        side = _checkpoint_tickers_path(sid)
        if side.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(doc, dict):
            continue
        tickers = doc.pop("tickers", None)
        if not tickers:
            continue
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        side.write_text(json.dumps(tickers, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        migrated.append(sid)
    return migrated
