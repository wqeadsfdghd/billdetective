"""Hand-rolled inline SVG charts.

No charting library and no matplotlib: the report must stay a single portable
file that renders identically offline, on any machine, with no fonts to install.
Every function returns an SVG fragment string.
"""

from __future__ import annotations

from decimal import Decimal
from html import escape
from typing import Sequence

__all__ = ["bar_chart", "donut_chart", "hbar_chart", "PALETTE"]

#: Category palette — teal first (the brand colour), then warm accents.
PALETTE: tuple[str, ...] = (
    "#0E7C66",
    "#F2994A",
    "#3E7CB1",
    "#B4553F",
    "#6B8E5A",
    "#8E6BA8",
    "#C9A227",
    "#4F8A8B",
    "#A65E7A",
    "#7A8B99",
    "#5C6B73",
    "#D08C60",
)

FONT = "'PingFang SC','Hiragino Sans GB','Microsoft YaHei',system-ui,sans-serif"


def _money(value: Decimal | float) -> str:
    amount = float(value)
    if abs(amount) >= 10000:
        return f"{amount / 10000:.1f}万"
    if abs(amount) >= 1000:
        return f"{amount:,.0f}"
    return f"{amount:.0f}"


def bar_chart(
    labels: Sequence[str],
    values: Sequence[Decimal | float],
    *,
    width: int = 760,
    height: int = 260,
    color: str = "#0E7C66",
) -> str:
    """Vertical bars with a soft baseline and value labels."""
    if not labels:
        return ""
    pad_l, pad_r, pad_t, pad_b = 12, 12, 26, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    peak = max((float(v) for v in values), default=0.0) or 1.0

    slot = plot_w / len(labels)
    gap = min(slot * 0.28, 14)
    bar_w = max(slot - gap, 6)

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="月度支出趋势" xmlns="http://www.w3.org/2000/svg">',
        f'<defs><linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.95"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0.55"/>'
        f"</linearGradient></defs>",
    ]

    # Horizontal grid lines, drawn behind the bars.
    for frac in (0.25, 0.5, 0.75, 1.0):
        y = pad_t + plot_h * (1 - frac)
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="#E3E9E6" stroke-width="1" stroke-dasharray="3 4"/>'
        )

    baseline = pad_t + plot_h
    for index, (label, value) in enumerate(zip(labels, values)):
        value_f = float(value)
        bar_h = max((value_f / peak) * plot_h, 1.0)
        x = pad_l + index * slot + (slot - bar_w) / 2
        y = baseline - bar_h
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'rx="4" fill="url(#barGrad)"/>'
        )
        if len(labels) <= 14:
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{y - 7:.1f}" text-anchor="middle" '
                f'font-family="{FONT}" font-size="10" fill="#5C6B73">{_money(value)}</text>'
            )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{baseline + 18:.1f}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="11" fill="#7A8B99">{escape(label)}</text>'
        )

    parts.append(
        f'<line x1="{pad_l}" y1="{baseline}" x2="{width - pad_r}" y2="{baseline}" '
        f'stroke="#C9D6D1" stroke-width="1.5"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def donut_chart(
    items: Sequence[tuple[str, Decimal | float]],
    *,
    size: int = 220,
    thickness: int = 26,
    legend: bool = True,
) -> str:
    """Ring chart using dash-array segments — exact arcs without path maths."""
    total = sum(float(v) for _, v in items) or 1.0
    radius = (size - thickness) / 2 - 2
    circumference = 2 * 3.141592653589793 * radius
    center = size / 2

    parts: list[str] = [
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
        f'role="img" aria-label="支出分类占比" xmlns="http://www.w3.org/2000/svg">',
        f'<circle cx="{center}" cy="{center}" r="{radius}" fill="none" '
        f'stroke="#EDF2F0" stroke-width="{thickness}"/>',
    ]

    offset = 0.0
    for index, (_, value) in enumerate(items):
        portion = float(value) / total
        if portion <= 0:
            continue
        length = portion * circumference
        color = PALETTE[index % len(PALETTE)]
        parts.append(
            f'<circle cx="{center}" cy="{center}" r="{radius}" fill="none" '
            f'stroke="{color}" stroke-width="{thickness}" '
            f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {center} {center})" stroke-linecap="butt"/>'
        )
        offset += length

    parts.append(
        f'<text x="{center}" y="{center - 4}" text-anchor="middle" font-family="{FONT}" '
        f'font-size="12" fill="#7A8B99">总支出</text>'
        f'<text x="{center}" y="{center + 20}" text-anchor="middle" font-family="{FONT}" '
        f'font-size="19" font-weight="600" fill="#1F2A27">¥{_money(total)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def hbar_chart(
    items: Sequence[tuple[str, Decimal | float]],
    *,
    width: int = 760,
    row_height: int = 34,
    color_by_index: bool = True,
) -> str:
    """Horizontal bars — the most readable form for named categories."""
    if not items:
        return ""
    label_w = 92
    value_w = 86
    height = row_height * len(items) + 8
    bar_area = width - label_w - value_w
    peak = max((float(v) for _, v in items), default=0.0) or 1.0

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="分类金额" xmlns="http://www.w3.org/2000/svg">'
    ]
    for index, (label, value) in enumerate(items):
        y = index * row_height + 6
        bar_w = max((float(value) / peak) * bar_area, 2)
        color = PALETTE[index % len(PALETTE)] if color_by_index else "#0E7C66"
        parts.append(
            f'<text x="0" y="{y + 15}" font-family="{FONT}" font-size="12" '
            f'fill="#3A4744">{escape(str(label))}</text>'
            f'<rect x="{label_w}" y="{y + 3}" width="{bar_area}" height="16" rx="8" fill="#EDF2F0"/>'
            f'<rect x="{label_w}" y="{y + 3}" width="{bar_w:.1f}" height="16" rx="8" fill="{color}"/>'
            f'<text x="{width}" y="{y + 15}" text-anchor="end" font-family="{FONT}" '
            f'font-size="12" font-weight="500" fill="#1F2A27">¥{float(value):,.0f}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
