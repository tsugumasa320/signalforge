"""GitHub Pages 用：長期トレンド・スクリーニング全銘柄ランキング。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from signalforge.report.static_html import wrap_page
from signalforge.research.trend_screen.forward_paper import published_forward_path
from signalforge.research.trend_screen.ranking import build_and_publish, load_ranking


def _pct(value: float | None, *, digits: int = 1) -> str:
    if value is None:
        return "—"
    cls = "positive" if value > 0 else "negative" if value < 0 else ""
    text = f"{value * 100:.{digits}f}%"
    return f'<span class="{cls}">{text}</span>' if cls else text


# 画面用語の短い解説（? ホバー用）
TERM_TIPS: dict[str, str] = {
    "as_of": "日足データがそろっている、いちばん新しい営業日。サイトの表示はこの日基準です。",
    "month_signal": "採用ルールが売買を決める日。完了した月末の終値で判定し、翌営業日終値で入れ替えます。",
    "universe": "スクリーニングの母集団。いまは売買代金が多い東証銘柄の上位およそ300です。",
    "bars_on_asof": "基準日に終値データがある銘柄数。欠けが多いと判定が不安定になります。",
    "passed": "いまの採用条件をすべて満たした銘柄数。",
    "targets": "通過銘柄を並べたうえで、実際に持つ想定の上位N銘柄。",
    "lab": "採用ルールを変えずに、条件のON/OFFや閾値をこの場で試す画面です。結果は保存されません。",
    "preset_toggle": "長期トレンド（採用ルール）と DUKE。新高値ブレイク（図23第2ステージ）をワンクリックで切り替えます。",
    "duke_score": "高値接近度・対市場RS・出来高を合成したDUKE向け参考点（高いほどブレイク候補寄り）。",
    "duke_above_sma150_200": "終値が150日・200日移動平均より上（第2ステージ①）。",
    "duke_sma150_gt_200": "150日線が200日線より上（第2ステージ②）。",
    "duke_sma200_up": "200日線が約1カ月上昇（第2ステージ③）。",
    "duke_sma50_stack": "50日線が150日・200日線より上（第2ステージ④）。",
    "duke_off_52w_low": "終値が52週安値から25%以上上（第2ステージ⑤）。",
    "duke_near_52w_high": "終値が52週高値の25%以内（第2ステージ⑥）。",
    "duke_above_sma50": "終値が50日線のほぼ上（−10%まで許容・第2ステージ⑦）。",
    "duke_rs_pos": "直近約6週で市場平均より強い（第2ステージ⑧）。",
    "duke_volume_surge": "出来高が20日平均の1.5倍以上。",
    "duke_fresh_break": "当日終値が過去約1年の高値を更新した初動日。",
    "fund_data": "通期の売上・利益キャッシュがある。",
    "fund_sales_up": "直近通期の売上が前年比プラス。",
    "fund_op_up": "直近通期の営業利益が前年比プラス。",
    "fund_margin_ok": "営業利益率が前年比で2ポイント超悪化していない。",
    "fund_upside_pos": "ファンダ目標株価（予想EPS×想定PER）が現値より上。",
    "target_fund": "粗いファンダ目標。予想EPS（成長外挿）×成長帯ごとの想定PER。中計ストーリーは含まない。",
    "stop_t1": "損切り目安は現値−10%。T1は＋20%（建値引き上げ）。T2は直近60日ボックス値幅を足した計測目標。T3は＋100%の参考。",
    "above_ma200": "終値が200日移動平均より上。中長期の上昇トレンド側にいる目安です。",
    "ma200_up": "200日線自体が上向き（60営業日前より高い）。トレンドが続いているかの目安です。",
    "ma75_up": "75日線が上向き（20営業日前より高い）。中期の勢いの目安です。",
    "ret_1y_pos": "約1年前の終値より今の方が高い（1年リターンがプラス）。",
    "ret_3y_pos": "約3年前の終値より今の方が高い（3年リターンがプラス）。",
    "excess_1y": "直近1年の値上がりが、TOPIX連動ETF（1306）より大きい。",
    "turnover": "直近20営業日の「終値×出来高」平均が一定以上。薄すぎる銘柄を避ける条件です。",
    "ret_20d": "直近20営業日で株価がプラス。急落直後の買いを抑える条件です。",
    "above_ma25": "終値が25日移動平均より上。短期でも下げ止まり寄りかの目安です。",
    "dd_52w": "直近52週の高値から、いま何％下がっているか。浅いほど高値圏に近いです。",
    "min_turnover": "直近20日の平均売買代金の下限。単位は億円です。",
    "min_ret20": "直近20営業日のリターン下限（％）。0なら「下がっていない」だけを要求します。",
    "max_dd52": "52週高値からの下落率の下限。例: -15 なら、高値から15％以内だけ残します。",
    "steady": "じわ上げ度の参考点（0–100）。上昇月の多さ・直線性・途中の沈み・ボラを合成します。",
    "up_month": "直近およそ1年で、月次リターンがプラスだった月の割合。",
    "path_dd": "直近1年の途中で、ピークから最大どれだけ沈んだか（経路の最大ドローダウン）。",
    "trend_r2": "値動きが直線的な上昇に近いか（0–1）。急騰あとの失速は低くなりやすいです。",
    "top_n": "通過銘柄のうち、保有候補として残す件数。",
    "rank_by": "通過銘柄を並べ替える基準。採用ルールは基本的に1年リターンです。",
    "col_steady": "安定度スコア。高いほど「急騰より、じわじわ上がってきた」寄りです。",
    "col_upm": "上昇した月の割合。高いほど毎月プラスが多かったことを示します。",
    "col_mdd": "1年の経路最大DD。0に近いほど途中の下落が浅いです。",
    "col_1y": "約1年前からいままでの株価リターン。",
    "col_60d": "直近約60営業日（およそ3か月）のリターン。",
    "col_20d": "直近20営業日のリターン。",
    "col_earn_last": "取得済みカレンダー上の、いちばん新しい決算発表日。",
    "col_earn_next": "取得済みカレンダー上の、これから来る決算発表日。",
    "col_div_y": "直近の配当利回り（年率の目安）。データが無い銘柄は — です。",
    "col_exdiv": "権利落ち日の目安。配当を受け取るには、通常その前に保有が必要です。",
    "col_yutai": "株主優待の有無・種類（参考）。種類は有報からの推定でずれることがあります。リンクは優待しらべの会社ページです。",
    "col_yutai_m": "優待の権利確定月（参考）。優待しらべと優待めぐりを突合した月です。複数は「・」つなぎ。IRと違う場合はIRを優先。",
    "cagr": "年率換算のリターン。複利で伸ばしたときのペース感です。",
    "bench_cagr": "比較対象（TOPIX連動ETF 1306）の年率リターン。",
    "total_ret": "期間全体の累積リターン（手数料控除後）。",
    "max_dd": "ピークから谷までの最大下落率。痛みの深さの目安です。",
    "live_ret": "いまの含み損益まで含めた口座全体のリターン。",
    "fwd_net": "その月の戦略リターン（入れ替えコスト控除後）。",
    "fwd_bench": "同じ期間のベンチマーク（1306）リターン。",
    "fwd_excess": "戦略リターン − ベンチマーク。プラスなら市場平均より良い月です。",
    "forward": "採用ルールを2023年以降に仮想運用した結果。未来のデータは使っていません。",
}


def _tip(label: str, tip_key: str, *, plain: bool = False) -> str:
    """ラベル＋?。ホバー／フォーカスで解説を出す。"""
    text = TERM_TIPS.get(tip_key, "")
    if not text:
        return escape(label) if plain else label
    return (
        f'<span class="tip">{escape(label) if plain else label}'
        f'<button type="button" class="tip-mark" aria-label="{escape(label)}の説明">?</button>'
        f'<span class="tip-bubble" role="tooltip">{escape(text)}</span></span>'
    )


def _load_forward() -> dict[str, Any] | None:
    path = published_forward_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _forward_section(fwd: dict[str, Any] | None) -> str:
    if not fwd:
        return """
    <section id="forward">
      <h2>フォワード（確認期間）</h2>
      <p class="muted">未生成。 <code>uv run signalforge trend-screen forward</code></p>
    </section>
    """
    s = fwd.get("summary") or {}
    live = fwd.get("live") or {}
    open_book = fwd.get("open") or {}
    from signalforge.report.yahoo_jp import yahoo_jp_anchor

    holds = "".join(
        f"<li><strong>{yahoo_jp_anchor(str(h.get('code') or h.get('ticker') or ''))}</strong> "
        f"{escape(str(h.get('name') or ''))} · {_pct(h.get('return'))}</li>"
        for h in (open_book.get("holdings") or [])
    )
    recent = list(fwd.get("months") or [])[-12:]
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(m.get('signal') or ''))}</td>"
        f"<td>{m.get('n') or 0}</td>"
        f"<td>{_pct(m.get('net'))}</td>"
        f"<td>{_pct(m.get('bench'))}</td>"
        f"<td>{_pct(m.get('excess'))}</td>"
        f"<td class='muted'>{escape(str(m.get('codes') or ''))}</td>"
        f"<td>{'オープン' if m.get('open') else ''}</td>"
        "</tr>"
        for m in recent
    )
    return f"""
    <section id="forward">
      <h2>{_tip("フォワード", "forward")}（{escape(str(fwd.get('start') or ''))} → {escape(str(fwd.get('as_of') or ''))}）</h2>
      <p class="muted">{escape(str(fwd.get('note') or ''))}</p>
      <div class="metrics">
        <div class="metric"><label>{_tip("確定CAGR", "cagr")}</label><value>{_pct(s.get('cagr'))}</value></div>
        <div class="metric"><label>{_tip("ベンチCAGR", "bench_cagr")}</label><value>{_pct(s.get('bench_cagr'))}</value></div>
        <div class="metric"><label>{_tip("累積リターン", "total_ret")}</label><value>{_pct(s.get('total_return'))}</value></div>
        <div class="metric"><label>{_tip("最大DD", "max_dd")}</label><value>{_pct(s.get('max_dd'))}</value></div>
        <div class="metric"><label>{_tip("時価込み", "live_ret")}</label><value>{_pct(live.get('total_return'))}</value></div>
      </div>
      <h3>直近ポジション</h3>
      <p class="muted">シグナル {escape(str(open_book.get('signal_date') or ''))} ·
      評価 {escape(str(open_book.get('as_of') or ''))} ·
      月次 {_pct(open_book.get('month_net'))}
      {"（オープン）" if open_book.get("open") else ""}</p>
      <ul class="compact">{holds or '<li class="muted">なし</li>'}</ul>
      <h3>直近12か月</h3>
      <table>
        <thead><tr>
          <th>{_tip("シグナル", "month_signal")}</th><th>銘柄数</th>
          <th>{_tip("ネット", "fwd_net")}</th>
          <th>{_tip("ベンチ", "fwd_bench")}</th>
          <th>{_tip("超過", "fwd_excess")}</th>
          <th>銘柄</th><th></th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """


def _rules_html(markdown: str) -> str:
    lines = []
    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        if not line or line.startswith("# "):
            continue
        if line.startswith("## "):
            lines.append(f"<h3>{escape(line[3:])}</h3>")
        elif line.startswith("- "):
            lines.append(f"<li>{escape(line[2:])}</li>")
        else:
            lines.append(f"<p class='muted'>{escape(line)}</p>")
    out: list[str] = []
    in_ul = False
    for item in lines:
        if item.startswith("<li>"):
            if not in_ul:
                out.append("<ul class='compact'>")
                in_ul = True
            out.append(item)
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(item)
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def _lab_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """ページ埋め込み用に必要なキーだけ残す（HTMLサイズ抑制）。"""
    universe = []
    for row in payload.get("universe") or list(payload.get("ranking") or []) + list(payload.get("rejected") or []):
        universe.append(
            {
                "code": row.get("code"),
                "name": row.get("name"),
                "sector": row.get("sector"),
                "price": row.get("price"),
                "ret_1y": row.get("ret_1y"),
                "ret_3y": row.get("ret_3y"),
                "excess_1y": row.get("excess_1y"),
                "ret_20d": row.get("ret_20d"),
                "ret_60d": row.get("ret_60d"),
                "dd_52w": row.get("dd_52w"),
                "mdd_1y": row.get("mdd_1y"),
                "up_month_ratio": row.get("up_month_ratio"),
                "trend_r2": row.get("trend_r2"),
                "steady_score": row.get("steady_score"),
                "vs_ma25": row.get("vs_ma25"),
                "vol_1y": row.get("vol_1y"),
                "risk_adj_1y": row.get("risk_adj_1y"),
                "turnover_20d": row.get("turnover_20d"),
                "volume_ratio_20": row.get("volume_ratio_20"),
                "market_rs_30d": row.get("market_rs_30d"),
                "pct_above_52w_low": row.get("pct_above_52w_low"),
                "pct_of_52w_high": row.get("pct_of_52w_high"),
                "duke_score": row.get("duke_score"),
                "fund_sales_yoy": row.get("fund_sales_yoy"),
                "fund_op_yoy": row.get("fund_op_yoy"),
                "fund_op_margin": row.get("fund_op_margin"),
                "trailing_per": row.get("trailing_per"),
                "fwd_eps": row.get("fwd_eps"),
                "assumed_per": row.get("assumed_per"),
                "target_price_fund": row.get("target_price_fund"),
                "upside_pct": row.get("upside_pct"),
                "stop_price": row.get("stop_price"),
                "t1_price": row.get("t1_price"),
                "t2_price": row.get("t2_price"),
                "t3_price": row.get("t3_price"),
                "box_height": row.get("box_height"),
                "midplan_kpi_hint": row.get("midplan_kpi_hint"),
                "gates": row.get("gates") or {},
                "yahoo_jp_url": row.get("yahoo_jp_url"),
                "earnings_last": row.get("earnings_last"),
                "earnings_next": row.get("earnings_next"),
                "earnings_next_days": row.get("earnings_next_days"),
                "dividend_yield": row.get("dividend_yield"),
                "ex_dividend_date": row.get("ex_dividend_date"),
                "last_dividend": row.get("last_dividend"),
                "last_dividend_date": row.get("last_dividend_date"),
                "yutai": row.get("yutai"),
                "yutai_months": row.get("yutai_months"),
                "yutai_record": row.get("yutai_record"),
                "yutai_min_shares": row.get("yutai_min_shares"),
                "yutai_type": row.get("yutai_type"),
                "yutai_annual_est": row.get("yutai_annual_est"),
                "yutai_url": row.get("yutai_url"),
            }
        )
    return {
        "as_of": payload.get("as_of") or payload.get("signal_date"),
        "signal_date": payload.get("signal_date"),
        "rebalance_signal_date": payload.get("rebalance_signal_date"),
        "name": payload.get("name"),
        "version": payload.get("version"),
        "lab_defaults": payload.get("lab_defaults") or {},
        "gate_labels": payload.get("gate_labels") or {},
        "universe": universe,
    }


def _lab_section(payload: dict[str, Any]) -> str:
    lab = _lab_payload(payload)
    defaults = lab.get("lab_defaults") or {}
    gate_labels = lab.get("gate_labels") or {}
    trend_gate_order = [
        "above_ma200",
        "ma200_up",
        "ma75_up",
        "ret_1y_pos",
        "ret_3y_pos",
        "excess_1y",
        "turnover",
        "ret_20d",
        "above_ma25",
        "dd_52w",
    ]
    duke_gate_order = [
        "duke_above_sma150_200",
        "duke_sma150_gt_200",
        "duke_sma200_up",
        "duke_sma50_stack",
        "duke_off_52w_low",
        "duke_near_52w_high",
        "duke_above_sma50",
        "duke_rs_pos",
        "duke_volume_surge",
        "duke_fresh_break",
    ]
    fund_gate_order = [
        "fund_data",
        "fund_sales_up",
        "fund_op_up",
        "fund_margin_ok",
        "fund_upside_pos",
    ]
    gate_defaults = defaults.get("gates") or {}
    gate_tip_keys = {k: k for k in trend_gate_order + duke_gate_order + fund_gate_order}

    def _gate_checks(keys: list[str]) -> str:
        bits = []
        for key in keys:
            label = gate_labels.get(key, key)
            checked = " checked" if gate_defaults.get(key, False) else ""
            tip_html = _tip(str(label), gate_tip_keys.get(key, key), plain=True)
            bits.append(
                f'<label class="gate"><input type="checkbox" data-gate="{escape(key)}"{checked}/> '
                f"{tip_html}</label>"
            )
        return "".join(bits)

    trend_checks = _gate_checks(trend_gate_order)
    duke_checks = _gate_checks(duke_gate_order)
    fund_checks = _gate_checks(fund_gate_order)
    min_turn = float(defaults.get("min_turnover") or 0) / 1e8
    min_ret20 = float(defaults.get("min_ret_20d") or 0) * 100
    max_dd = float(defaults.get("max_dd_52w") if defaults.get("max_dd_52w") is not None else -1) * 100
    min_steady = float(defaults.get("min_steady_score") or 0)
    min_up_m = float(defaults.get("min_up_month_ratio") or 0) * 100
    max_mdd = float(defaults.get("max_mdd_1y") if defaults.get("max_mdd_1y") is not None else -1) * 100
    min_r2 = float(defaults.get("min_trend_r2") or 0)
    top_n = int(defaults.get("top_n") or 5)
    rank_by = str(defaults.get("rank_by") or "ret_1y")
    data_json = json.dumps(lab, ensure_ascii=False)
    # </script> がデータに含まれないようエスケープ
    data_json = data_json.replace("<", "\\u003c")

    return f"""
    <style>
      .lab-controls {{ display:grid; gap:0.75rem; }}
      .gate-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:0.35rem 0.75rem; }}
      .gate {{ display:flex; align-items:center; gap:0.4rem; font-size:0.85rem; color:var(--text); }}
      .param-row {{ display:flex; flex-wrap:wrap; gap:0.75rem 1.25rem; align-items:end; }}
      .param {{ display:flex; flex-direction:column; gap:0.25rem; font-size:0.8rem; color:var(--muted); }}
      .param input, .param select {{ background:#0b1220; color:var(--text); border:1px solid #334155; border-radius:6px; padding:0.35rem 0.5rem; min-width:7rem; }}
      .lab-actions {{ display:flex; flex-wrap:wrap; gap:0.5rem; align-items:center; }}
      .lab-actions button {{ background:var(--accent); color:#fff; border:0; border-radius:6px; padding:0.45rem 0.9rem; cursor:pointer; font-size:0.85rem; }}
      .lab-actions button.secondary {{ background:#334155; }}
      .preset-toggle {{ display:inline-flex; border:1px solid #334155; border-radius:8px; overflow:hidden; }}
      .preset-toggle button {{ background:#0b1220; color:var(--muted); border:0; border-radius:0; padding:0.55rem 1rem; cursor:pointer; font-size:0.9rem; }}
      .preset-toggle button.active {{ background:var(--accent); color:#fff; }}
      #lab-summary {{ font-size:0.9rem; color:var(--muted); }}
      #lab-table td, #lab-table th {{ white-space:nowrap; }}
      #lab-table td.name {{ white-space:normal; max-width:14rem; }}
      .gate-group h3 {{ margin:0.5rem 0 0.35rem; font-size:0.95rem; }}
    </style>
    <section id="lab">
      <h2>{_tip("条件ラボ", "lab")}（この場で試す）</h2>
      <p class="muted">採用ルールを初期値に、条件のON/OFFと閾値を変えて通過銘柄を並べ替えます。結果はブラウザ内のみで、採用ルール自体は変わりません。母集団は流動性上位約300（採用ルール）。? にマウスを置くと用語の説明が出ます。</p>
      <div class="lab-actions" style="margin-bottom:0.75rem">
        <span class="muted">{_tip("スクリーニング切替", "preset_toggle")}</span>
        <div class="preset-toggle" role="group" aria-label="スクリーニング切替">
          <button type="button" id="lab-preset-trend" class="active">長期トレンド</button>
          <button type="button" id="lab-preset-duke">DUKE新高値ブレイク</button>
        </div>
        <span id="lab-preset-note" class="muted"></span>
      </div>
      <div class="info-box">
        <strong>安定度スコア（0–100）</strong>は「じわじわ上がってきたか」の参考値です。
        上昇月の割合・値動きの直線性（trend R²）・1年の経路最大DD・ボラを合成。
        急騰あとの失速銘柄は低く出やすいです。買ってすぐ含み損が不安なときは、
        安定度や上昇月割合で絞り、並びを安定度にすると見やすいです。
      </div>
      <div class="info-box">
        <strong>DUKE新高値ブレイク</strong>は図23の第2ステージ（SMA50/150/200・52週・対市場RS）と
        ファンダ（売上・営利YoY、利益率）を必須にし、並びは {_tip("DUKEスコア", "duke_score")} です。
        {_tip("ファンダ目標株価", "target_fund")} と {_tip("損切り/T1–T3", "stop_t1")} も表示します。
        「出来高急増」「当日ブレイク」「目標＞現値」は初期OFFです。
      </div>
      <div class="info-box">
        <strong>決算・配当・優待</strong>は参考表示です（通過条件には使いません）。
        決算日は取得済みカレンダー、配当は Yahoo Finance、優待は
        <a href="https://yutai-shirabe.com/download/index.html" target="_blank" rel="noopener">優待しらべ</a>
        （EDINET 有報の自動抽出）を主に、権利月・必要株数は
        <a href="https://yutai-meguri.com/" target="_blank" rel="noopener">優待めぐり</a>
        と突合しています。種類の分類や権利月は推定・欠落があり得るので、売買前に各社IRで確認してください。
        銘柄コード横の Yahoo は日本版ファイナンスへのリンクです。
      </div>
      <div class="lab-controls">
        <div class="gate-group">
          <h3>長期トレンド条件</h3>
          <div class="gate-grid">{trend_checks}</div>
        </div>
        <div class="gate-group">
          <h3>DUKE / 第2ステージ条件</h3>
          <div class="gate-grid">{duke_checks}</div>
        </div>
        <div class="gate-group">
          <h3>ファンダ条件（通期）</h3>
          <div class="gate-grid">{fund_checks}</div>
        </div>
        <div class="param-row">
          <label class="param">{_tip("売買代金下限（億円）", "min_turnover")}
            <input id="lab-min-turn" type="number" step="0.1" min="0" value="{min_turn:g}"/>
          </label>
          <label class="param">{_tip("20日リターン下限（%）", "min_ret20")}
            <input id="lab-min-ret20" type="number" step="0.5" value="{min_ret20:g}"/>
          </label>
          <label class="param">{_tip("52週DD下限（%、例 -15）", "max_dd52")}
            <input id="lab-max-dd" type="number" step="1" value="{max_dd:g}"/>
          </label>
          <label class="param">{_tip("安定度スコア下限", "steady")}
            <input id="lab-min-steady" type="number" step="1" min="0" max="100" value="{min_steady:g}"/>
          </label>
          <label class="param">{_tip("上昇月割合下限（%）", "up_month")}
            <input id="lab-min-upm" type="number" step="1" min="0" max="100" value="{min_up_m:g}"/>
          </label>
          <label class="param">{_tip("1年経路DD下限（%、例 -25）", "path_dd")}
            <input id="lab-max-mdd" type="number" step="1" value="{max_mdd:g}"/>
          </label>
          <label class="param">{_tip("trend R² 下限（0–1）", "trend_r2")}
            <input id="lab-min-r2" type="number" step="0.05" min="0" max="1" value="{min_r2:g}"/>
          </label>
          <label class="param">{_tip("上位N", "top_n")}
            <input id="lab-topn" type="number" step="1" min="1" max="50" value="{top_n}"/>
          </label>
          <label class="param">{_tip("並び替え", "rank_by")}
            <select id="lab-rankby">
              <option value="ret_1y" {"selected" if rank_by == "ret_1y" else ""}>1年リターン</option>
              <option value="duke_score" {"selected" if rank_by == "duke_score" else ""}>DUKEスコア</option>
              <option value="upside_pct">ファンダ上振れ%</option>
              <option value="target_price_fund">ファンダ目標株価</option>
              <option value="market_rs_30d">対市場RS（6週）</option>
              <option value="pct_of_52w_high">52週高値接近度</option>
              <option value="volume_ratio_20">出来高比率</option>
              <option value="steady_score" {"selected" if rank_by == "steady_score" else ""}>安定度スコア</option>
              <option value="ret_20d" {"selected" if rank_by == "ret_20d" else ""}>20日リターン</option>
              <option value="ret_60d" {"selected" if rank_by == "ret_60d" else ""}>60日リターン</option>
              <option value="risk_adj_1y" {"selected" if rank_by == "risk_adj_1y" else ""}>リスク調整1年</option>
              <option value="up_month_ratio" {"selected" if rank_by == "up_month_ratio" else ""}>上昇月割合</option>
              <option value="excess_1y" {"selected" if rank_by == "excess_1y" else ""}>TOPIX超過1年</option>
            </select>
          </label>
        </div>
        <div class="lab-actions">
          <button type="button" id="lab-apply">この条件でランキング</button>
          <button type="button" class="secondary" id="lab-reset">採用ルールに戻す</button>
          <button type="button" class="secondary" id="lab-steady">安定寄りプリセット</button>
          <span id="lab-summary"></span>
        </div>
      </div>
      <div class="metrics" id="lab-metrics" style="margin-top:1rem"></div>
      <h3>保有候補（上位N）</h3>
      <ul class="compact" id="lab-targets"></ul>
      <h3>通過ランキング</h3>
      <div style="overflow-x:auto">
        <table id="lab-table">
          <thead>
            <tr>
              <th>#</th><th>コード</th><th>会社名</th><th>業種</th>
              <th>{_tip("DUKE", "duke_score")}</th>
              <th>{_tip("目標", "target_fund")}</th>
              <th>上振れ</th>
              <th>{_tip("損切", "stop_t1")}</th>
              <th>T1</th>
              <th>T2箱</th>
              <th>売上YoY</th>
              <th>営利YoY</th>
              <th>KPIヒント</th>
              <th>RS6週</th>
              <th>出来高比</th>
              <th>高値比</th>
              <th>{_tip("安定度", "col_steady")}</th>
              <th>{_tip("上昇月", "col_upm")}</th>
              <th>{_tip("経路DD", "col_mdd")}</th>
              <th>{_tip("1年", "col_1y")}</th>
              <th>{_tip("60日", "col_60d")}</th>
              <th>{_tip("20日", "col_20d")}</th>
              <th>終値</th>
              <th>{_tip("直近決算", "col_earn_last")}</th>
              <th>{_tip("次回決算", "col_earn_next")}</th>
              <th>{_tip("配当利回", "col_div_y")}</th>
              <th>{_tip("権利落", "col_exdiv")}</th>
              <th>{_tip("優待", "col_yutai")}</th>
              <th>{_tip("権利月", "col_yutai_m")}</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </section>
    <script id="trend-lab-data" type="application/json">{data_json}</script>
    <script>
    (function() {{
      const raw = document.getElementById('trend-lab-data');
      if (!raw) return;
      const DATA = JSON.parse(raw.textContent);
      const defaults = DATA.lab_defaults || {{}};
      const universe = DATA.universe || [];
      const presets = defaults.presets || {{}};
      let activePreset = defaults.active_preset || 'trend';

      function pct(v, digits=1) {{
        if (v === null || v === undefined || Number.isNaN(v)) return '—';
        const x = Number(v) * 100;
        const s = (x >= 0 ? '+' : '') + x.toFixed(digits) + '%';
        const cls = x > 0 ? 'positive' : (x < 0 ? 'negative' : '');
        return cls ? '<span class="'+cls+'">'+s+'</span>' : s;
      }}
      function yen(v) {{
        if (v === null || v === undefined || Number.isNaN(v)) return '—';
        return Math.round(Number(v)).toLocaleString('ja-JP');
      }}
      function gateOn(key) {{
        const el = document.querySelector('input[data-gate="'+key+'"]');
        return !!(el && el.checked);
      }}
      function readParams() {{
        return {{
          minTurn: Number(document.getElementById('lab-min-turn').value || 0) * 1e8,
          minRet20: Number(document.getElementById('lab-min-ret20').value || 0) / 100,
          maxDd: Number(document.getElementById('lab-max-dd').value || -100) / 100,
          minSteady: Number(document.getElementById('lab-min-steady').value || 0),
          minUpM: Number(document.getElementById('lab-min-upm').value || 0) / 100,
          maxMdd: Number(document.getElementById('lab-max-mdd').value || -100) / 100,
          minR2: Number(document.getElementById('lab-min-r2').value || 0),
          topN: Math.max(1, Math.min(50, Number(document.getElementById('lab-topn').value || 5))),
          rankBy: document.getElementById('lab-rankby').value || 'ret_1y',
        }};
      }}
      function passes(row, p) {{
        const g = row.gates || {{}};
        const required = [
          'above_ma200','ma200_up','ma75_up','ret_1y_pos','ret_3y_pos','excess_1y',
          'turnover','ret_20d','above_ma25','dd_52w',
          'duke_above_sma150_200','duke_sma150_gt_200','duke_sma200_up','duke_sma50_stack',
          'duke_off_52w_low','duke_near_52w_high','duke_above_sma50','duke_rs_pos',
          'duke_volume_surge','duke_fresh_break',
          'fund_data','fund_sales_up','fund_op_up','fund_margin_ok','fund_upside_pos'
        ];
        for (const key of required) {{
          if (!gateOn(key)) continue;
          if (key === 'turnover') {{
            if (row.turnover_20d == null || row.turnover_20d < p.minTurn) return false;
            continue;
          }}
          if (key === 'ret_20d') {{
            if (row.ret_20d == null || row.ret_20d <= p.minRet20) return false;
            continue;
          }}
          if (key === 'above_ma25') {{
            if (row.vs_ma25 == null || row.vs_ma25 <= 0) return false;
            continue;
          }}
          if (key === 'dd_52w') {{
            if (row.dd_52w == null || row.dd_52w < p.maxDd) return false;
            continue;
          }}
          if (!g[key]) return false;
        }}
        if (p.minSteady > 0 && (row.steady_score == null || row.steady_score < p.minSteady)) return false;
        if (p.minUpM > 0 && (row.up_month_ratio == null || row.up_month_ratio < p.minUpM)) return false;
        if (p.maxMdd > -0.999 && (row.mdd_1y == null || row.mdd_1y < p.maxMdd)) return false;
        if (p.minR2 > 0 && (row.trend_r2 == null || row.trend_r2 < p.minR2)) return false;
        if (activePreset === 'duke') return row.price != null;
        return row.ret_1y != null;
      }}
      function score(row, rankBy) {{
        const v = row[rankBy];
        return (v === null || v === undefined || Number.isNaN(v)) ? -1e99 : Number(v);
      }}
      function num(v, digits=1) {{
        if (v === null || v === undefined || Number.isNaN(v)) return '—';
        return Number(v).toFixed(digits);
      }}
      function txt(v) {{
        if (v === null || v === undefined || v === '') return '—';
        return String(v);
      }}
      function yahooLink(r) {{
        const u = r.yahoo_jp_url;
        if (!u) return txt(r.code);
        return `<a href="${{u}}" target="_blank" rel="noopener">${{r.code || ''}}</a>`;
      }}
      function yutaiCell(r) {{
        if (!r.yutai) return '—';
        const raw = (r.yutai_type || '').trim();
        const unknown = !raw || raw === '記載なし' || raw === '読み取れず' || raw === '不明';
        const label = unknown ? 'あり' : raw;
        if (r.yutai_url) {{
          return `<a href="${{r.yutai_url}}" target="_blank" rel="noopener">${{label}}</a>`;
        }}
        return label;
      }}
      function nextEarn(r) {{
        if (!r.earnings_next) return '—';
        const d = r.earnings_next_days;
        const tip = (d === null || d === undefined) ? '' : `（あと${{d}}日）`;
        return txt(r.earnings_next) + tip;
      }}
      function setPresetButtons() {{
        const t = document.getElementById('lab-preset-trend');
        const d = document.getElementById('lab-preset-duke');
        if (t) t.classList.toggle('active', activePreset === 'trend');
        if (d) d.classList.toggle('active', activePreset === 'duke');
        const note = document.getElementById('lab-preset-note');
        if (note) {{
          note.textContent = activePreset === 'duke'
            ? '図23第2ステージ＋出来高で絞り込み中'
            : '採用の長期トレンド条件で絞り込み中';
        }}
      }}
      function applyPreset(name) {{
        const preset = presets[name];
        if (!preset) return;
        activePreset = name;
        const g = preset.gates || {{}};
        document.querySelectorAll('input[data-gate]').forEach(el => {{
          const key = el.getAttribute('data-gate');
          el.checked = !!g[key];
        }});
        document.getElementById('lab-topn').value = preset.top_n || defaults.top_n || 5;
        document.getElementById('lab-rankby').value = preset.rank_by || 'ret_1y';
        document.getElementById('lab-min-steady').value = preset.min_steady_score || 0;
        document.getElementById('lab-min-upm').value = ((preset.min_up_month_ratio || 0) * 100);
        document.getElementById('lab-max-mdd').value = ((preset.max_mdd_1y != null ? preset.max_mdd_1y : -1) * 100);
        document.getElementById('lab-min-r2').value = preset.min_trend_r2 || 0;
        setPresetButtons();
        render();
      }}
      function render() {{
        const p = readParams();
        const pass = universe.filter(r => passes(r, p));
        pass.sort((a,b) => score(b, p.rankBy) - score(a, p.rankBy) || String(a.code).localeCompare(String(b.code)));
        const targets = pass.slice(0, p.topN);
        document.getElementById('lab-summary').textContent =
          '通過 ' + pass.length + ' / ' + universe.length + ' · 上位 ' + targets.length;
        document.getElementById('lab-metrics').innerHTML = `
          <div class="metric"><label>通過</label><value>${{pass.length}}</value></div>
          <div class="metric"><label>上位N</label><value>${{targets.length}}</value></div>
          <div class="metric"><label>ユニバース</label><value>${{universe.length}}</value></div>
          <div class="metric"><label>モード</label><value>${{activePreset === 'duke' ? 'DUKE' : 'トレンド'}}</value></div>
        `;
        document.getElementById('lab-targets').innerHTML = targets.length
          ? targets.map((r,i) => `<li>${{yahooLink(r)}} ${{r.name || ''}} · 目標 ${{yen(r.target_price_fund)}} · 上振れ ${{pct(r.upside_pct)}} · DUKE ${{num(r.duke_score,1)}} · 1年 ${{pct(r.ret_1y)}}</li>`).join('')
          : '<li class="muted">条件に合う銘柄なし</li>';
        const tb = document.querySelector('#lab-table tbody');
        tb.innerHTML = pass.map((r,i) => {{
          const badge = i < p.topN ? ' <span class="badge">保有</span>' : '';
          return `<tr>
            <td>${{i+1}}${{badge}}</td>
            <td>${{yahooLink(r)}}</td>
            <td class="name">${{r.name || ''}}</td>
            <td class="muted">${{r.sector || ''}}</td>
            <td>${{num(r.duke_score,1)}}</td>
            <td>${{yen(r.target_price_fund)}}</td>
            <td>${{pct(r.upside_pct)}}</td>
            <td>${{yen(r.stop_price)}}</td>
            <td>${{yen(r.t1_price)}}</td>
            <td>${{yen(r.t2_price)}}</td>
            <td>${{pct(r.fund_sales_yoy)}}</td>
            <td>${{pct(r.fund_op_yoy)}}</td>
            <td class="name muted">${{txt(r.midplan_kpi_hint)}}</td>
            <td>${{num(r.market_rs_30d,1)}}</td>
            <td>${{num(r.volume_ratio_20,2)}}</td>
            <td>${{pct(r.pct_of_52w_high ? (r.pct_of_52w_high - 1) : null)}}</td>
            <td>${{num(r.steady_score,1)}}</td>
            <td>${{pct(r.up_month_ratio,0)}}</td>
            <td>${{pct(r.mdd_1y)}}</td>
            <td>${{pct(r.ret_1y)}}</td>
            <td>${{pct(r.ret_60d)}}</td>
            <td>${{pct(r.ret_20d)}}</td>
            <td>${{yen(r.price)}}</td>
            <td>${{txt(r.earnings_last)}}</td>
            <td>${{nextEarn(r)}}</td>
            <td>${{pct(r.dividend_yield,2)}}</td>
            <td>${{txt(r.ex_dividend_date)}}</td>
            <td>${{yutaiCell(r)}}</td>
            <td>${{txt(r.yutai_months)}}</td>
          </tr>`;
        }}).join('');
      }}
      function reset() {{
        applyPreset('trend');
        document.getElementById('lab-min-turn').value = ((defaults.min_turnover || 0) / 1e8);
        document.getElementById('lab-min-ret20').value = ((defaults.min_ret_20d || 0) * 100);
        document.getElementById('lab-max-dd').value = ((defaults.max_dd_52w != null ? defaults.max_dd_52w : -1) * 100);
      }}
      function steadyPreset() {{
        applyPreset('trend');
        document.getElementById('lab-min-steady').value = 55;
        document.getElementById('lab-min-upm').value = 55;
        document.getElementById('lab-max-mdd').value = -25;
        document.getElementById('lab-min-r2').value = 0.35;
        document.getElementById('lab-min-ret20').value = 0;
        document.getElementById('lab-rankby').value = 'steady_score';
        render();
      }}
      document.getElementById('lab-apply').addEventListener('click', render);
      document.getElementById('lab-reset').addEventListener('click', reset);
      document.getElementById('lab-steady').addEventListener('click', steadyPreset);
      document.getElementById('lab-preset-trend').addEventListener('click', () => applyPreset('trend'));
      document.getElementById('lab-preset-duke').addEventListener('click', () => applyPreset('duke'));
      document.querySelectorAll('.lab-controls input, .lab-controls select').forEach(el => {{
        el.addEventListener('change', render);
      }});
      document.querySelectorAll('.tip-mark').forEach(el => {{
        el.addEventListener('click', (e) => {{ e.preventDefault(); e.stopPropagation(); }});
      }});
      setPresetButtons();
      render();
    }})();
    </script>
    """


def render_trend_screen_body(payload: dict[str, Any], *, forward: dict[str, Any] | None = None) -> str:
    warning = ""
    if payload.get("warning"):
        warning = f"<div class='info-box'><strong>警告</strong> {escape(str(payload['warning']))}</div>"
    targets = payload.get("targets") or []
    target_bits_parts: list[str] = []
    for t in targets:
        code = str(t.get("code") or "")
        yurl = t.get("yahoo_jp_url") or (
            f"https://finance.yahoo.co.jp/quote/{code}.T" if code else ""
        )
        code_html = (
            f'<a href="{escape(str(yurl))}" target="_blank" rel="noopener">'
            f"<strong>{escape(code)}</strong></a>"
            if yurl
            else f"<strong>{escape(code)}</strong>"
        )
        extra = []
        if t.get("earnings_next"):
            extra.append(f"次回決算 {escape(str(t['earnings_next']))}")
        if t.get("dividend_yield") is not None:
            extra.append(f"配当 {_pct(t.get('dividend_yield'), digits=2)}")
        if t.get("yutai"):
            extra.append(f"優待 {escape(str(t.get('yutai_months') or 'あり'))}")
        extra_s = (" · " + " · ".join(extra)) if extra else ""
        target_bits_parts.append(
            f"<li>{code_html} {escape(str(t.get('name') or ''))} · 1年 {_pct(t.get('ret_1y'))}{extra_s}</li>"
        )
    target_bits = "".join(target_bits_parts)
    as_of = payload.get("as_of") or payload.get("signal_date") or ""
    rebalance = payload.get("rebalance_signal_date") or ""
    note = payload.get("note") or ""
    return f"""
    {warning}
    <div class="info-box">
      <strong>基準日</strong>は最新の終値が揃った営業日です（毎日更新）。
      採用シストレの売買タイミングは別で、完了した<strong>月末シグナル</strong>
      （いま {escape(str(rebalance))}）で判定します。
      {escape(str(note)) if note else ""}
    </div>
    <div class="metrics">
      <div class="metric"><label>{_tip("基準日（最新）", "as_of")}</label><value>{escape(str(as_of))}</value></div>
      <div class="metric"><label>{_tip("月末シグナル", "month_signal")}</label><value>{escape(str(rebalance))}</value></div>
      <div class="metric"><label>{_tip("ユニバース", "universe")}</label><value>{payload.get('n_universe', 0)}</value></div>
      <div class="metric"><label>{_tip("基準日バー", "bars_on_asof")}</label><value>{payload.get('n_on_signal', 0)}</value></div>
      <div class="metric positive"><label>{_tip("採用通過", "passed")}</label><value>{payload.get('n_pass', 0)}</value></div>
      <div class="metric"><label>{_tip("保有目標", "targets")}</label><value>{payload.get('n_target', 0)}</value></div>
    </div>

    <section>
      <h2>採用ルールの保有目標（上位 {escape(str(payload.get('top_n') or 5))}）</h2>
      <p class="muted">{escape(str(payload.get('name') or ''))} · 版 {escape(str(payload.get('version') or ''))} · 基準日 {escape(str(as_of))}</p>
      <ul class="compact">{target_bits or '<li class="muted">なし</li>'}</ul>
    </section>

    {_lab_section(payload)}

    <section id="forward"><h2>フォワードテスト</h2><p>日々の判断・注文を保存する新しい口座で観測します。</p><a href="../index.html#forward">フォワードテストの成績を見る →</a></section>

    <section id="rules">
      <h2>採用規則</h2>
      {_rules_html(str(payload.get('rules_markdown') or ''))}
    </section>
    """


def export_trend_screen_page(
    output_dir: Path,
    *,
    rebuild: bool = True,
    limit: int | None = None,
) -> Path:
    """Publish ranking JSON (optional rebuild) and write screen/trend.html."""
    if rebuild:
        payload, _ = build_and_publish(limit=limit)
    else:
        payload = load_ranking()
        if payload is None:
            payload, _ = build_and_publish(limit=limit)

    body = render_trend_screen_body(payload)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = wrap_page(
        title="長期上昇トレンド・スクリーニング",
        subtitle=(
            f"基準日 {payload.get('as_of') or payload.get('signal_date', '')} · "
            f"通過 {payload.get('n_pass', 0)} / ユニバース {payload.get('n_universe', 0)}"
        ),
        body=body,
        generated=generated,
        nav_active="screen",
        depth=1,
    )
    out = output_dir / "screen"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "trend.html"
    path.write_text(html, encoding="utf-8")
    screen_dir = output_dir / "screen"
    from signalforge.research.trend_screen.ranking import published_ranking_path

    (screen_dir / published_forward_path().name).unlink(missing_ok=True)
    for src in (published_ranking_path(),):
        if src.exists():
            (screen_dir / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return path
