"""Command line interface.

Deliberately dependency-free: ``python -m billdetective`` works on a clean
Python install with nothing to pip install first.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .analyze import analyze
from .parsers import ParseError, load_statements
from .report import render_html, render_text

__all__ = ["main"]


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"无法序列化 {type(value)!r}")


def _to_json(analysis: Any) -> str:
    payload = {
        "period": {
            "start": analysis.period_start,
            "end": analysis.period_end,
        },
        "total_expense": analysis.total_expense,
        "total_income": analysis.total_income,
        "net": analysis.net,
        "transaction_count": analysis.transaction_count,
        "effective_count": analysis.effective_count,
        "skipped_count": analysis.skipped_count,
        "by_category": analysis.by_category,
        "by_month": [
            {"month": b.key, "expense": b.expense, "income": b.income} for b in analysis.by_month
        ],
        "subscriptions": [
            {
                "merchant": s.merchant,
                "amount": s.amount,
                "cycle": s.cycle,
                "occurrences": s.occurrences,
                "first_seen": s.first_seen,
                "last_seen": s.last_seen,
                "annual_cost": s.annual_cost,
                "confidence": s.confidence,
                "category": s.category,
                "is_hidden": s.is_hidden,
            }
            for s in analysis.subscriptions
        ],
        "hidden_annual_total": analysis.hidden_annual_total,
        "insights": analysis.insights,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="billdetective",
        description="账单侦探：在你自己的电脑上，找出偷偷流走的钱。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  billdetective 支付宝账单.csv\n"
            "  billdetective 支付宝.csv 微信.csv --out 报告.html\n"
            "  billdetective 账单.csv --format text\n"
            "  billdetective 账单.csv --format json > data.json\n"
        ),
    )
    parser.add_argument("files", nargs="+", help="支付宝 / 微信 / 通用 CSV 账单")
    parser.add_argument(
        "-o", "--out",
        default="账单体检报告.html",
        help="HTML 报告输出路径（默认：账单体检报告.html）",
    )
    parser.add_argument(
        "-f", "--format",
        choices=("html", "text", "json"),
        default="html",
        help="输出格式（默认 html）",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="生成后自动用浏览器打开报告",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=8,
        help="榜单展示条数（默认 8）",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"billdetective {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.files]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for path in missing:
            print(f"✗ 找不到文件：{path}", file=sys.stderr)
        return 2

    try:
        parsed = load_statements(paths)
    except ParseError as error:
        print(f"✗ {error}", file=sys.stderr)
        print("  提示：请使用支付宝/微信导出的 CSV 账单，不要用 PDF 或截图。", file=sys.stderr)
        return 1

    if not parsed.transactions:
        print("✗ 没有解析到任何交易记录。", file=sys.stderr)
        return 1

    analysis = analyze(
        parsed.transactions,
        skipped_count=parsed.rows_skipped,
        sources=[p.name for p in paths],
    )

    if args.format == "json":
        print(_to_json(analysis))
        return 0

    if args.format == "text":
        print(render_text(analysis))
        for warning in parsed.warnings:
            print(f"  · {warning}", file=sys.stderr)
        return 0

    html = render_html(analysis)
    out_path = Path(args.out)
    out_path.write_text(html, encoding="utf-8")
    print(render_text(analysis))
    print()
    print(f"✓ 报告已生成：{out_path.resolve()}")
    print("  单文件离线 HTML，可直接双击打开或发给别人。")

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
