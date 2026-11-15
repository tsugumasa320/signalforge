"""Yahoo!ファイナンス日本版 quote links for report / Pages / Streamlit."""

from __future__ import annotations

from html import escape

from signalforge.research.trend_screen.corporate_events import yahoo_jp_url as _yahoo_jp_url_raw

YAHOO_JP_QUOTE = "https://finance.yahoo.co.jp/quote/{ticker}"


def yahoo_jp_url(ticker: str | None) -> str | None:
    t = str(ticker or "").strip()
    if not t or t == "—":
        return None
    return _yahoo_jp_url_raw(t)


def yahoo_jp_anchor(ticker: str | None, *, label: str | None = None) -> str:
    """HTML `<a>` for a ticker, or escaped text / em dash when missing."""
    t = str(ticker or "").strip()
    if not t:
        return "—"
    url = yahoo_jp_url(t)
    text = escape(label if label is not None else t)
    if not url:
        return text
    return f'<a href="{escape(url)}" target="_blank" rel="noopener">{text}</a>'


def normalize_tse_code(ticker: str | None) -> str:
    """Return bare TSE code (e.g. 7203) for Kabutan / TradingView."""
    code = str(ticker or "").strip()
    if code.upper().endswith(".T"):
        code = code[:-2]
    return code
