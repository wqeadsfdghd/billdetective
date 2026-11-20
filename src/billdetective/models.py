"""Core domain model for BillDetective.

The whole pipeline speaks one internal language: :class:`Transaction`.
Every parser normalises into it, every analysis reads from it.  Amounts are
always stored as *positive* :class:`~decimal.Decimal` values; direction is a
separate axis.  Mixing sign and direction is the single most common source of
double-counting bugs in expense tooling, so it is forbidden here by design.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

__all__ = [
    "Direction",
    "Transaction",
    "ParseResult",
    "parse_amount",
    "parse_datetime",
    "normalize_direction",
    "is_effective",
]


class Direction(str, Enum):
    """Which way the money moved."""

    EXPENSE = "expense"
    INCOME = "income"
    #: Transfers between the user's own accounts, top-ups, repayments, etc.
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


#: Statuses that must never count towards spending, even when the row says 支出.
#: A refunded or closed order is not money the user actually lost.
VOID_STATUS_MARKERS = (
    "退款成功",
    "已退款",
    "全额退款",
    "交易关闭",
    "已关闭",
    "支付失败",
    "已撤销",
    "已失效",
    "交易失败",
)

#: Statuses that mean "the order completed normally".
SETTLED_STATUS_MARKERS = ("交易成功", "已收钱", "支付成功", "已完成", "成功")

_AMOUNT_CLEAN = re.compile(r"[¥￥$,\s\"']")
_CN_YUAN_SPLIT = re.compile(r"[元圆]")


def parse_amount(raw: str | int | float | Decimal | None) -> Decimal | None:
    """Parse ``"¥1,234.50"`` style amounts into a positive Decimal.

    Returns ``None`` when the value cannot be understood, so callers can decide
    whether to skip the row rather than silently treating it as zero.
    """
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return abs(raw)
    if isinstance(raw, (int, float)):
        return Decimal(str(abs(raw)))

    text = str(raw).strip()
    if not text:
        return None

    # Some exports append a currency word: "1234.50元".
    text = _CN_YUAN_SPLIT.sub("", text)
    text = _AMOUNT_CLEAN.sub("", text)
    if not text:
        return None
    if text.startswith("-"):
        text = text[1:]

    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


_DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y年%m月%d日 %H:%M:%S",
    "%Y年%m月%d日",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y%m%d",
)


def parse_datetime(raw: str | datetime | None) -> datetime | None:
    """Parse the date formats seen in Alipay / WeChat / bank exports."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw

    text = str(raw).strip().strip("\"'")
    if not text:
        return None

    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    # Last resort: ISO-ish strings such as "2026-03-15T12:30:45+08:00".
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def normalize_direction(raw: str | None) -> Direction:
    """Map the 收/支 column onto a :class:`Direction`."""
    if raw is None:
        return Direction.UNKNOWN
    text = str(raw).strip()
    if not text:
        return Direction.UNKNOWN
    if text in {"支出", "支", "-", "付款", "out", "expense"}:
        return Direction.EXPENSE
    if text in {"收入", "收", "+", "收款", "in", "income"}:
        return Direction.INCOME
    if "不计" in text or text in {"其他", "中性", "/"}:
        return Direction.NEUTRAL
    return Direction.UNKNOWN


def _status_key(status: str) -> str:
    return re.sub(r"\s+", "", status)


def is_void_status(status: str) -> bool:
    """True when the row represents money that never really left the account."""
    key = _status_key(status)
    if not key:
        return False
    return any(marker in key for marker in VOID_STATUS_MARKERS)


@dataclass(slots=True, frozen=True)
class Transaction:
    """One normalised row from any supported statement."""

    occurred_at: datetime
    amount: Decimal
    direction: Direction
    counterparty: str = ""
    description: str = ""
    category_raw: str = ""
    method: str = ""
    status: str = ""
    source: str = ""
    source_file: str = ""
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    #: Filled in by :mod:`billdetective.categorize`.
    category: str = ""
    tags: tuple[str, ...] = ()

    @property
    def is_effective(self) -> bool:
        """Whether this row should count towards real cash flow."""
        if self.direction is Direction.NEUTRAL:
            return False
        if is_void_status(self.status):
            return False
        return self.amount > 0

    @property
    def signed_amount(self) -> Decimal:
        """Expenses negative, income positive — for chart axes only."""
        if self.direction is Direction.EXPENSE:
            return -self.amount
        return self.amount

    @property
    def merchant(self) -> str:
        """Best-effort merchant identity for grouping subscriptions."""
        return (self.counterparty or self.description or "").strip()

    def with_category(self, category: str, tags: tuple[str, ...] = ()) -> "Transaction":
        return replace(self, category=category, tags=tags)

    def with_direction(self, direction: "Direction") -> "Transaction":
        """Reclassify direction — used to demote internal transfers to neutral."""
        return replace(self, direction=direction)


@dataclass(slots=True)
class ParseResult:
    """Everything a parser learned, including what it had to skip."""

    transactions: list[Transaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_format: str = "unknown"
    rows_total: int = 0
    rows_skipped: int = 0

    def extend(self, other: "ParseResult") -> None:
        self.transactions.extend(other.transactions)
        self.warnings.extend(other.warnings)
        self.rows_total += other.rows_total
        self.rows_skipped += other.rows_skipped

    @property
    def effective_count(self) -> int:
        return sum(1 for t in self.transactions if t.is_effective)
