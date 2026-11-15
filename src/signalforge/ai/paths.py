from __future__ import annotations

from pathlib import Path

from signalforge.config import ROOT, data_dir


def ai_dir() -> Path:
    path = data_dir() / "ai"
    path.mkdir(parents=True, exist_ok=True)
    return path


def prompts_dir() -> Path:
    return ROOT / "prompts"


def load_prompt(name: str) -> str:
    path = prompts_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip() + "\n"


def published_path(name: str) -> Path:
    return data_dir() / "published" / name


def paper_dir() -> Path:
    return data_dir() / "paper"
