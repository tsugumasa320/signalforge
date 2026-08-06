"""One-time native library warmup (macOS PyArrow thread-safety)."""

from __future__ import annotations

_warmed = False


def warmup_native_libs() -> None:
    """Import PyArrow on the main thread before Streamlit worker threads start."""
    global _warmed
    if _warmed:
        return
    try:
        import pyarrow  # noqa: F401
        import pyarrow.dataset  # noqa: F401
    except ImportError:
        pass
    _warmed = True
