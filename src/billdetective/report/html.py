"""Self-contained HTML report renderer.

The output is a single ``.html`` file with no external stylesheet, script, font
or image.  It opens by double-clicking, works offline, and can be emailed to
someone who has never installed anything — which also means the user's bill data
never has to leave their machine to be shareable.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape

from ..analyze import Analysis
from ..subscriptions import Subscription
from .svg import bar_chart, donut_chart, hbar_chart

__all__ = ["render_html", "render_text"]

_CSS = """
:root{
  --ink:#1F2A27; --muted:#7A8B99; --line:#E3E9E6; --bg:#F7F9F8;
  --brand:#0E7C66; --brand-soft:#E8F3EF; --warn:#B4553F; --warn-soft:#FBEDE8;
  --card:#FFFFFF;
}
*{box-sizing:border-box}
body{
  margin:0; padding:32px 20px 64px; background:var(--bg); color:var(--ink);
  font-family:'PingFang SC','Hiragino Sans GB','Microsoft YaHei',system-ui,-apple-system,sans-serif;
  line-height:1.6; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:980px; margin:0 auto}
header.head{display:flex; justify-content:space-between; align-items:flex-start; gap:16px; flex-wrap:wrap; margin-bottom:26px}
h1{font-size:27px; margin:0 0 6px; letter-spacing:-.4px}
.sub{color:var(--muted); font-size:13.5px; margin:0}
.badge{
  display:inline-flex; align-items:center; gap:6px; background:var(--brand-soft);
  color:#0A5F4E; font-size:12.5px; font-weight:600; padding:7px 13px; border-radius:999px;
  border:1px solid #CFE5DE; white-space:nowrap;
}
.kpis{display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:26px}
.kpi{background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px 18px 16px}
.kpi .label{font-size:12.5px; color:var(--muted); margin-bottom:8px}
.kpi .value{font-size:25px; font-weight:650; letter-spacing:-.5px; font-variant-numeric:tabular-nums}
.kpi .note{font-size:11.5px; color:var(--muted); margin-top:6px}
.kpi.alert{background:var(--warn-soft); border-color:#F0D2C8}
.kpi.alert .value{color:var(--warn)}
section{background:var(--card); border:1px solid var(--line); border-radius:16px; padding:22px 24px; margin-bottom:18px}
section h2{font-size:16.5px; margin:0 0 4px; letter-spacing:-.2px}
section .hint{font-size:12.5px; color:var(--muted); margin:0 0 18px}
.insights{list-style:none; padding:0; margin:0}
.insights li{
  padding:12px 0 12px 26px; border-bottom:1px dashed var(--line); position:relative; font-size:14.5px;
}
.insights li:last-child{border-bottom:0; padding-bottom:0}
.insights li::before{
  content:''; position:absolute; left:4px; top:20px; width:7px; height:7px;
  border-radius:50%; background:var(--brand);
}
.subs{display:grid; grid-template-columns:1fr 1fr; gap:12px}
.sub-card{border:1px solid var(--line); border-radius:12px; padding:15px 16px; background:#FCFDFC}
.sub-card.hidden{border-left:3px solid var(--warn); background:#FFFBFA}
.sub-top{display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin-bottom:6px}
.sub-name{font-weight:600; font-size:14.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.sub-amt{font-variant-numeric:tabular-nums; font-weight:600; font-size:15px; white-space:nowrap}
.sub-meta{font-size:12.5px; color:var(--muted); display:flex; gap:10px; flex-wrap:wrap}
.sub-annual{margin-top:9px; font-size:12.5px; color:#0A5F4E; font-weight:600}
.pill{font-size:11px; padding:1px 7px; border-radius:999px; background:var(--brand-soft); color:#0A5F4E; font-weight:600}
.pill.mid{background:#FFF4E5; color:#8A5A1E}
.pill.hidden{background:var(--warn-soft); color:var(--warn)}
.two-col{display:grid; grid-template-columns:240px 1fr; gap:26px; align-items:center}
table{width:100%; border-collapse:collapse; font-size:13.5px}
th{text-align:left; font-weight:600; color:var(--muted); font-size:12px; padding:8px 10px; border-bottom:1px solid var(--line)}
td{padding:10px; border-bottom:1px solid #F0F4F2}
td.num,th.num{text-align:right; font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
.empty{color:var(--muted); font-size:13.5px; padding:14px 0}
footer{color:var(--muted); font-size:12px; text-align:center; margin-top:30px; line-height:1.9}
footer code{background:#EDF2F0; padding:1px 6px; border-radius:5px; font-size:11.5px}
@media (max-width:760px){
  .kpis{grid-template-columns:repeat(2,1fr)}
  .subs{grid-template-columns:1fr}
  .two-col{grid-template-columns:1fr}
  body{padding:20px 14px 48px}
}
@media print{
  body{background:#fff; padding:0}
  section,.kpi{break-inside:avoid}
}
"""


def _money(value: Decimal | float) -> str:
    return f"¥{float(value):,.2f}".replace(".00", "")


def _confidence_pill(confidence: str) -> str:
    if confidence == "high":
        return '<span class="pill">把握高</span>'
    return '<span class="pill mid">把握中</span>'


def _sub_card(sub: Subscription) -> str:
    classes = "sub-card hidden" if sub.is_hidden else "sub-card"
    tag = '<span class="pill hidden">隐形订阅</span>' if sub.is_hidden else ""
    return f"""
    <div class="{classes}">
      <div class="sub-top">
        <span class="sub-name">{escape(sub.merchant)}</span>
        <span class="sub-amt">{_money(sub.amount)}</span>
      </div>
      <div class="sub-meta">
        <span>{sub.cycle_label}扣款</span>
        <span>已扣 {sub.occurrences} 次</span>
        <span>{sub.first_seen:%Y-%m} 起</span>
        {_confidence_pill(sub.confidence)}
        {tag}
      </div>
      <div class="sub-annual">年化 {_money(sub.annual_cost)} · 下次约 {sub.next_expected:%m-%d}</div>
    </div>
    """


def render_html(
    analysis: Analysis,
    *,
    title: str = "账单侦探 · 消费体检报告",
    generated_at: datetime | None = None,
) -> str:
    """Render the complete report as a single HTML document."""
    generated_at = generated_at or datetime.now()
    period = "—"
    if analysis.period_start and analysis.period_end:
        period = f"{analysis.period_start:%Y-%m-%d} 至 {analysis.period_end:%Y-%m-%d}"

    hidden = analysis.hidden_subscriptions
    fixed = analysis.fixed_bills

    kpi_hidden = (
        f'<div class="kpi alert"><div class="label">隐形订阅年化</div>'
        f'<div class="value">{_money(analysis.hidden_annual_total)}</div>'
        f'<div class="note">{len(hidden)} 项自动续费</div></div>'
    ) if hidden else (
        '<div class="kpi"><div class="label">隐形订阅年化</div>'
        '<div class="value">¥0</div><div class="note">未发现自动续费</div></div>'
    )

    kpis = f"""
    <div class="kpis">
      <div class="kpi">
        <div class="label">总支出</div>
        <div class="value">{_money(analysis.total_expense)}</div>
        <div class="note">月均 {_money(analysis.monthly_average_expense)}</div>
      </div>
      <div class="kpi">
        <div class="label">总收入</div>
        <div class="value">{_money(analysis.total_income)}</div>
        <div class="note">净结余 {_money(analysis.net)}</div>
      </div>
      {kpi_hidden}
      <div class="kpi">
        <div class="label">有效交易</div>
        <div class="value">{analysis.effective_count:,}</div>
        <div class="note">已排除退款/关闭 {analysis.skipped_count + (analysis.transaction_count - analysis.effective_count)} 笔</div>
      </div>
    </div>
    """

    insights_html = "".join(f"<li>{escape(text)}</li>" for text in analysis.insights) or '<li>数据不足，无法生成洞察。</li>'

    if hidden or fixed:
        sub_sections = []
        if hidden:
            sub_sections.append(
                f'<h2 style="font-size:14.5px;margin:0 0 12px;color:var(--warn)">'
                f"隐形订阅 · {len(hidden)} 项 · 年化 {_money(analysis.hidden_annual_total)}</h2>"
                + '<div class="subs">' + "".join(_sub_card(s) for s in hidden) + "</div>"
            )
        if fixed:
            sub_sections.append(
                f'<h2 style="font-size:14.5px;margin:{"22px" if hidden else "0"} 0 12px;color:var(--muted)">'
                f"周期性固定账单 · {len(fixed)} 项</h2>"
                + '<div class="subs">' + "".join(_sub_card(s) for s in fixed) + "</div>"
            )
        subs_html = "".join(sub_sections)
    else:
        subs_html = '<div class="empty">没有检测到周期性扣款。要么你每笔都亲手付，要么账单周期还不够长。</div>'

    months = [b.label for b in analysis.by_month]
    month_values = [b.expense for b in analysis.by_month]
    trend_svg = bar_chart(months, month_values) if months else ""
    trend_block = (
        f'<section><h2>月度支出趋势</h2><p class="hint">按自然月汇总的支出金额</p>{trend_svg}</section>'
        if trend_svg else ""
    )

    category_items = list(analysis.by_category.items())[:8]
    if category_items:
        donut = donut_chart(category_items)
        bars = hbar_chart(category_items)
        category_block = f"""
        <section>
          <h2>支出构成</h2>
          <p class="hint">占比前 8 的消费分类</p>
          <div class="two-col">{donut}<div>{bars}</div></div>
        </section>
        """
    else:
        category_block = ""

    if analysis.top_merchants:
        rows = "".join(
            f"<tr><td>{index + 1}</td><td>{escape(m.name)}</td>"
            f'<td class="num">{m.count}</td><td class="num">{_money(m.total)}</td></tr>'
            for index, m in enumerate(analysis.top_merchants[:8])
        )
        merchant_block = f"""
        <section>
          <h2>花钱最多的商户</h2>
          <p class="hint">按累计支出排序</p>
          <table>
            <thead><tr><th>#</th><th>商户</th><th class="num">笔数</th><th class="num">金额</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>
        """
    else:
        merchant_block = ""

    if analysis.largest_expenses:
        rows = "".join(
            f'<tr><td>{t.occurred_at:%Y-%m-%d}</td><td>{escape(t.merchant or "未标注")}</td>'
            f'<td>{escape(t.category)}</td><td class="num">{_money(t.amount)}</td></tr>'
            for t in analysis.largest_expenses
        )
        largest_block = f"""
        <section>
          <h2>单笔最大支出</h2>
          <p class="hint">Top 5，金额从高到低</p>
          <table>
            <thead><tr><th>日期</th><th>商户</th><th>分类</th><th class="num">金额</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>
        """
    else:
        largest_block = ""

    source_note = "、".join(escape(s) for s in analysis.sources) or "本地文件"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="head">
    <div>
      <h1>{escape(title)}</h1>
      <p class="sub">账单周期 {period} · 来源 {source_note}</p>
    </div>
    <span class="badge">全程本地处理 · 数据未离开本机</span>
  </header>

  {kpis}

  <section>
    <h2>先说结论</h2>
    <p class="hint">由账单自动归纳，不含推测</p>
    <ul class="insights">{insights_html}</ul>
  </section>

  <section>
    <h2>订阅与固定扣款</h2>
    <p class="hint">基于扣款间隔与金额稳定性推断，把握中等的项建议自行核对</p>
    {subs_html}
  </section>

  {trend_block}
  {category_block}
  {merchant_block}
  {largest_block}

  <footer>
    由 <code>billdetective</code> 生成于 {generated_at:%Y-%m-%d %H:%M} · 单文件离线报告，无任何外部请求<br>
    报告包含敏感财务信息，分享前请自行评估
  </footer>
</div>
</body>
</html>
"""


def render_text(analysis: Analysis) -> str:
    """Compact terminal summary, for people who live in the shell."""
    lines: list[str] = []
    period = "—"
    if analysis.period_start and analysis.period_end:
        period = f"{analysis.period_start:%Y-%m-%d} ~ {analysis.period_end:%Y-%m-%d}"

    lines.append("账单侦探 · 消费体检")
    lines.append(f"周期      {period}")
    lines.append(f"总支出    {_money(analysis.total_expense)}")
    lines.append(f"总收入    {_money(analysis.total_income)}")
    lines.append(f"净结余    {_money(analysis.net)}")
    lines.append(f"有效交易  {analysis.effective_count} 笔（已排除退款/关闭）")
    lines.append("")

    if analysis.subscriptions:
        lines.append("订阅与固定扣款")
        for sub in analysis.subscriptions:
            flag = "隐形" if sub.is_hidden else "固定"
            lines.append(
                f"  [{flag}] {sub.merchant:<18.18} {_money(sub.amount):>10} × {sub.cycle_label:<3}"
                f" 年化 {_money(sub.annual_cost):>10}"
            )
        lines.append(f"  隐形订阅年化合计 {_money(analysis.hidden_annual_total)}")
        lines.append("")

    if analysis.by_category:
        lines.append("支出构成")
        for name, amount in list(analysis.by_category.items())[:6]:
            share = analysis.category_share(name)
            bar = "█" * max(int(share * 24), 0)
            lines.append(f"  {name:<6} {_money(amount):>12}  {share:>5.1%} {bar}")
        lines.append("")

    if analysis.insights:
        lines.append("结论")
        for text in analysis.insights:
            lines.append(f"  · {text}")

    return "\n".join(lines)
