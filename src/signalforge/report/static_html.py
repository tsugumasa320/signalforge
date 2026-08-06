"""Shared HTML/CSS helpers for static GitHub Pages exports."""

from __future__ import annotations

from html import escape

BASE_CSS = """
:root {
  --bg: #0f172a;
  --card: #1e293b;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --accent: #3b82f6;
  --green: #22c55e;
  --red: #ef4444;
  --yellow: #eab308;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
}
nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  padding: 0.75rem 2rem;
  background: #0b1220;
  border-bottom: 1px solid #334155;
  font-size: 0.875rem;
}
nav a { color: var(--accent); text-decoration: none; }
nav a:hover { text-decoration: underline; }
nav .active { color: var(--text); font-weight: 600; }
header {
  padding: 1.5rem 2rem;
  border-bottom: 1px solid #334155;
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
}
header h1 { margin: 0 0 0.25rem; font-size: 1.5rem; }
header p { margin: 0; color: var(--muted); font-size: 0.9rem; }
main { max-width: 1200px; margin: 0 auto; padding: 1.5rem; }
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}
.metric {
  background: var(--card);
  border-radius: 8px;
  padding: 1rem;
  border: 1px solid #334155;
}
.metric label { display: block; font-size: 0.75rem; color: var(--muted); text-transform: uppercase; }
.metric value { display: block; font-size: 1.35rem; font-weight: 600; margin-top: 0.25rem; }
.metric.positive value { color: var(--green); }
.metric.negative value { color: var(--red); }
section, .card {
  background: var(--card);
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
  border: 1px solid #334155;
}
section h2, .card h2 { margin: 0 0 0.75rem; font-size: 1rem; color: var(--muted); }
section h3 { margin: 1rem 0 0.5rem; font-size: 0.95rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid #334155; }
th { color: var(--muted); font-weight: 500; }
tr:hover td { background: rgba(255,255,255,0.02); }
.muted { color: var(--muted); }
.positive { color: var(--green); }
.negative { color: var(--red); }
.badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  background: #334155;
}
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } }
ul.compact { margin: 0.25rem 0; padding-left: 1.25rem; }
footer {
  text-align: center;
  padding: 2rem;
  color: var(--muted);
  font-size: 0.8rem;
}
a { color: var(--accent); }
.info-box {
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.35);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
}
"""


def _prefix_for(path_depth: int) -> str:
    return "../" * path_depth if path_depth else ""


def render_nav(active: str, depth: int = 0) -> str:
    p = _prefix_for(depth)
    links = [
        ("hub", "🏠 ホーム", f"{p}index.html"),
        ("paper", "📈 Paper 成績", f"{p}index.html#paper"),
        ("backtest", "⚖️ バックテスト比較", f"{p}index.html#backtest"),
        ("guides", "📚 戦略解説", f"{p}index.html#guides"),
    ]
    parts = ["<nav>"]
    for key, label, href in links:
        cls = ' class="active"' if key == active else ""
        parts.append(f'<a href="{href}"{cls}>{escape(label)}</a>')
    parts.append("</nav>")
    return "\n".join(parts)


def wrap_page(
    *,
    title: str,
    subtitle: str,
    body: str,
    generated: str,
    nav_active: str = "hub",
    depth: int = 0,
) -> str:
    nav = render_nav(nav_active, depth)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{escape(title)}</title>
  <style>{BASE_CSS}</style>
</head>
<body>
{nav}
<header>
  <h1>{escape(title)}</h1>
  <p>{subtitle}</p>
</header>
<main>
{body}
</main>
<footer>
  Generated {escape(generated)} ·
  <a href="https://github.com/tsugumasa320/signalforge">SignalForge</a>
</footer>
</body>
</html>
"""


def fig_to_html_block(fig, *, include_plotlyjs: bool | str = False, div_id: str = "chart") -> str:
    return fig.to_html(
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        config={"displayModeBar": False},
        div_id=div_id,
    )
