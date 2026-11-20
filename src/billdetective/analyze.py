"""Aggregation layer: turns normalised transactions into a report-ready model.

Everything the HTML report renders comes from :class:`Analysis`.  Keeping the
aggregation separate from rendering means the CLI, the web preview and the tests
all read the same numbers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Sequence

from .categorize import UNCATEGORIZED, categorize_all
from .models import Direction, Transaction
from .subscriptions import Subscription, detect_subscriptions

__all__ = ["Analysis", "analyze", "MonthBucket", "MerchantTotal"]

ZERO = Decimal("0.00")


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


@dataclass(slots=True)
class MonthBucket:
    key: str          # "2026-03"
    label: str        # "3月"
    expense: Decimal = ZERO
    income: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return _q(self.income - self.expense)


@dataclass(slots=True)
class MerchantTotal:
    name: str
    total: Decimal
    count: int


@dataclass(slots=True)
class Analysis:
    period_start: date | None = None
    period_end: date | None = None
    total_expense: Decimal = ZERO
    total_income: Decimal = ZERO
    transaction_count: int = 0
    effective_count: int = 0
    skipped_count: int = 0
    by_category: dict[str, Decimal] = field(default_factory=dict)
    by_month: list[MonthBucket] = field(default_factory=list)
    top_merchants: list[MerchantTotal] = field(default_factory=list)
    subscriptions: list[Subscription] = field(default_factory=list)
    largest_expenses: list[Transaction] = field(default_factory=list)
    uncategorized_amount: Decimal = ZERO
    insights: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    # -- derived -------------------------------------------------------
    @property
    def net(self) -> Decimal:
        return _q(self.total_income - self.total_expense)

    @property
    def hidden_subscriptions(self) -> list[Subscription]:
        return [s for s in self.subscriptions if s.is_hidden]

    @property
    def fixed_bills(self) -> list[Subscription]:
        return [s for s in self.subscriptions if not s.is_hidden]

    @property
    def hidden_annual_total(self) -> Decimal:
        return _q(sum((s.annual_cost for s in self.hidden_subscriptions), ZERO))

    @property
    def recurring_annual_total(self) -> Decimal:
        return _q(sum((s.annual_cost for s in self.subscriptions), ZERO))

    @property
    def months_covered(self) -> int:
        return max(len(self.by_month), 1)

    @property
    def monthly_average_expense(self) -> Decimal:
        return _q(self.total_expense / Decimal(self.months_covered))

    @property
    def daily_average_expense(self) -> Decimal:
        if not self.period_start or not self.period_end:
            return ZERO
        days = max((self.period_end - self.period_start).days + 1, 1)
        return _q(self.total_expense / Decimal(days))

    def category_share(self, category: str) -> float:
        if not self.total_expense:
            return 0.0
        return float(self.by_category.get(category, ZERO) / self.total_expense)


def _month_buckets(transactions: Sequence[Transaction]) -> list[MonthBucket]:
    buckets: dict[str, MonthBucket] = {}
    for transaction in transactions:
        key = transaction.occurred_at.strftime("%Y-%m")
        bucket = buckets.get(key)
        if bucket is None:
            bucket = MonthBucket(key=key, label=f"{transaction.occurred_at.month}月")
            buckets[key] = bucket
        if transaction.direction is Direction.EXPENSE:
            bucket.expense += transaction.amount
        elif transaction.direction is Direction.INCOME:
            bucket.income += transaction.amount
    ordered = [buckets[key] for key in sorted(buckets)]
    for bucket in ordered:
        bucket.expense = _q(bucket.expense)
        bucket.income = _q(bucket.income)
    return ordered


def _merchant_totals(transactions: Sequence[Transaction], limit: int = 10) -> list[MerchantTotal]:
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    counts: dict[str, int] = defaultdict(int)
    for transaction in transactions:
        name = transaction.merchant or "未标注商户"
        totals[name] += transaction.amount
        counts[name] += 1
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [MerchantTotal(name=name, total=_q(total), count=counts[name]) for name, total in ranked]


def _build_insights(analysis: Analysis) -> list[str]:
    """Generate the few sentences that carry the whole story."""
    insights: list[str] = []

    hidden = analysis.hidden_subscriptions
    if hidden:
        top = hidden[0]
        insights.append(
            f"检测到 {len(hidden)} 项隐形订阅，按年计算共需 ¥{analysis.hidden_annual_total:,.0f}，"
            f"其中「{top.merchant}」最贵，年化 ¥{top.annual_cost:,.0f}。"
        )
    else:
        insights.append("没有检测到明显的隐形订阅——这份账单比大多数人的干净。")

    if analysis.by_month:
        peak = max(analysis.by_month, key=lambda b: b.expense)
        insights.append(f"支出最高的月份是 {peak.key}，共 ¥{peak.expense:,.0f}。")

    if analysis.total_expense:
        top_category, top_amount = max(analysis.by_category.items(), key=lambda kv: kv[1])
        share = analysis.category_share(top_category)
        if share >= 0.25:
            insights.append(
                f"「{top_category}」占了总支出的 {share:.0%}，是最大的钱袋子。"
            )

    if analysis.largest_expenses:
        biggest = analysis.largest_expenses[0]
        insights.append(
            f"单笔最大支出是 {biggest.occurred_at:%Y-%m-%d} 的"
            f"「{biggest.merchant or '未知商户'}」，¥{biggest.amount:,.0f}。"
        )

    if analysis.uncategorized_amount > 0:
        share = float(analysis.uncategorized_amount / analysis.total_expense) if analysis.total_expense else 0
        if share >= 0.05:
            insights.append(
                f"有 ¥{analysis.uncategorized_amount:,.0f}（{share:.0%}）没能归类，"
                "可在报告末尾补充商户关键词来提升识别率。"
            )

    return insights


def _largest_distinct(expenses: Sequence[Transaction], limit: int = 5) -> list[Transaction]:
    """Top expenses, one per merchant.

    Without the dedupe, rent — the same merchant, once a month — fills the whole
    list and the section tells the user nothing they did not already know.
    """
    seen: set[str] = set()
    picked: list[Transaction] = []
    for transaction in sorted(expenses, key=lambda t: t.amount, reverse=True):
        key = transaction.merchant or "未标注商户"
        if key in seen:
            continue
        seen.add(key)
        picked.append(transaction)
        if len(picked) >= limit:
            break
    return picked


def analyze(
    transactions: Iterable[Transaction],
    *,
    skipped_count: int = 0,
    sources: Sequence[str] = (),
) -> Analysis:
    """Categorise, aggregate and detect subscriptions in one pass."""
    categorized = categorize_all(list(transactions))
    effective = [t for t in categorized if t.is_effective]

    analysis = Analysis(
        transaction_count=len(categorized),
        effective_count=len(effective),
        skipped_count=skipped_count,
        sources=list(sources),
    )
    if not effective:
        return analysis

    dates = [t.occurred_at.date() for t in effective]
    analysis.period_start = min(dates)
    analysis.period_end = max(dates)

    expenses = [t for t in effective if t.direction is Direction.EXPENSE]
    incomes = [t for t in effective if t.direction is Direction.INCOME]

    analysis.total_expense = _q(sum((t.amount for t in expenses), ZERO))
    analysis.total_income = _q(sum((t.amount for t in incomes), ZERO))

    category_totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for transaction in expenses:
        category_totals[transaction.category] += transaction.amount
    analysis.by_category = dict(
        sorted(
            ((name, _q(total)) for name, total in category_totals.items()),
            key=lambda kv: kv[1],
            reverse=True,
        )
    )
    analysis.uncategorized_amount = _q(category_totals.get(UNCATEGORIZED, ZERO))

    analysis.by_month = _month_buckets(effective)
    analysis.top_merchants = _merchant_totals(expenses)
    analysis.largest_expenses = _largest_distinct(expenses)
    analysis.subscriptions = detect_subscriptions(effective)
    analysis.insights = _build_insights(analysis)

    return analysis
