"""Recurring-payment (subscription) detection.

The naive approach — "same merchant, roughly 30 days apart" — produces a flood
of false positives: the noodle shop you visit weekly, the monthly credit-card
repayment, the quarterly insurance premium.  A tool that cries wolf is a tool
nobody trusts.

This module therefore applies four independent filters:

1. **Cycle fitting.**  Candidate cycles (monthly / quarterly / yearly) are fitted
   against *every* gap, allowing a gap to span 1–3 cycles so a missed month does
   not break detection.  A group must fit one cycle cleanly.
2. **Amount stability.**  Subscription prices barely move; discretionary
   spending does.  Coefficient of variation must stay low.
3. **Category gating.**  Transfers, repayments and gifts are structurally
   periodic but are not subscriptions, so they are excluded outright.
4. **Weekly cycles are refused.**  Weekly cadence is dominated by habit
   spending and cannot be separated from it with statement data alone.

What survives is reported together with a confidence level, and the report
splits "hidden subscriptions" from "known fixed bills" so the headline number
stays honest.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

from .models import Direction, Transaction

__all__ = [
    "Subscription",
    "detect_subscriptions",
    "CYCLE_DAYS",
    "EXCLUDED_CATEGORIES",
]

#: Cycles we are willing to claim.
CYCLE_DAYS: dict[str, int] = {
    "monthly": 30,
    "quarterly": 91,
    "yearly": 365,
}

CYCLE_LABELS: dict[str, str] = {
    "monthly": "每月",
    "quarterly": "每季",
    "yearly": "每年",
}

#: Charges per year, by cycle.  Calendar-exact: a monthly plan bills 12 times,
#: not 365/30 = 12.17 times.  Using the day ratio quietly inflates every
#: annual figure by ~1.4%, which is the kind of error an expense tool cannot
#: afford once users start comparing it against their bank statements.
CYCLE_PER_YEAR: dict[str, int] = {
    "monthly": 12,
    "quarterly": 4,
    "yearly": 1,
}

#: Structurally periodic, but not subscriptions.
EXCLUDED_CATEGORIES: frozenset[str] = frozenset({"转账理财", "人情往来", "收入"})

#: High-frequency habit spending.  A merchant here is only considered a
#: subscription when its name carries an explicit membership hint — otherwise
#: "lunch at the same noodle shop every 30 days" would be reported as a plan.
HABIT_CATEGORIES: frozenset[str] = frozenset(
    {"餐饮美食", "交通出行", "日用购物", "服饰美妆"}
)

#: Minimum charges required before a cycle is claimed, per detected cycle.
MIN_OCCURRENCES_BY_CYCLE: dict[str, int] = {
    "monthly": 3,
    "quarterly": 2,
    "yearly": 2,
}

#: Beyond this many charges the merchant is certainly habit spending, not a plan.
MAX_OCCURRENCES = 24

#: Relative tolerance for a single inter-charge gap.  Tighter than it looks:
#: month gaps wobble by 1–3 days, but 0.35 admits too much random noise.
GAP_TOLERANCE = 0.25
#: Coefficient-of-variation ceiling for the amount sequence.
MAX_CV = 0.15
#: A gap may cover at most this many cycles (one missed charge is tolerated).
MAX_GAP_MULTIPLE = 3

#: Merchant/keyword hints that mean "this is a subscription, not a bill".
SUBSCRIPTION_HINTS = (
    "会员", "订阅", "vip", "svip", "包月", "包年", "续费", "自动续费",
    "subscription", "premium", "plus", "pro", "icloud", "netflix", "spotify",
    "爱奇艺", "腾讯视频", "优酷", "芒果", "网易云", "qq音乐", "百度网盘",
    "chatgpt", "claude", "openai", "notion", "figma", "github", "cursor",
)

#: Stricter than :data:`SUBSCRIPTION_HINTS`: a gym membership the user knowingly
#: renews is a subscription but not a *hidden* one.  Only text that implies an
#: auto-renewing digital plan counts towards the "quiet money leak" headline.
HIDDEN_HINTS = (
    "会员", "订阅", "vip", "svip", "包月", "包年", "自动续费",
    "连续包月", "连续包季", "连续包年", "subscription", "premium",
)


@dataclass(slots=True, frozen=True)
class Subscription:
    """A detected recurring charge."""

    merchant: str
    amount: Decimal
    cycle: str
    occurrences: int
    first_seen: date
    last_seen: date
    annual_cost: Decimal
    confidence: str
    category: str
    is_hidden: bool
    charges: tuple[date, ...] = ()
    monthly_equivalent: Decimal = Decimal("0")

    @property
    def cycle_label(self) -> str:
        return CYCLE_LABELS.get(self.cycle, self.cycle)

    @property
    def next_expected(self) -> date:
        return self.last_seen + timedelta(days=CYCLE_DAYS[self.cycle])


def _cv(values: Sequence[float]) -> float:
    """Coefficient of variation; 0 when the sequence is perfectly stable."""
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    if mean == 0:
        return 1.0
    return statistics.pstdev(values) / mean


def _fit_cycle(gaps: Sequence[int]) -> tuple[str, float] | None:
    """Find the cycle that explains every gap, or ``None``.

    Returns ``(cycle_name, worst_relative_error)``.
    """
    best: tuple[str, float] | None = None
    for cycle, days in CYCLE_DAYS.items():
        if cycle == "yearly" and len(gaps) < 1:
            continue
        worst = 0.0
        matched = 0
        for gap in gaps:
            if gap <= 0:
                continue
            multiple = round(gap / days)
            if multiple < 1:
                multiple = 1
            if multiple > MAX_GAP_MULTIPLE:
                continue
            expected = multiple * days
            error = abs(gap - expected) / expected
            if error <= GAP_TOLERANCE:
                matched += 1
                worst = max(worst, error)
        if gaps and matched == len(gaps):
            # Prefer the smallest cycle when several fit equally well.
            if best is None or worst < best[1]:
                best = (cycle, worst)
    return best


def _confidence(occurrences: int, cv: float, worst_error: float) -> str:
    if occurrences >= 3 and cv <= 0.05 and worst_error <= 0.15:
        return "high"
    if cv <= 0.10 and worst_error <= 0.25:
        return "medium"
    return "low"


def _build(
    merchant: str,
    group: Sequence[Transaction],
    cycle: str,
    category: str,
) -> Subscription | None:
    ordered = sorted(group, key=lambda t: t.occurred_at)
    amounts = [float(t.amount) for t in ordered]
    cv = _cv(amounts)
    if cv > MAX_CV:
        return None

    representative = Decimal(str(round(statistics.median(amounts), 2)))
    annual = (representative * CYCLE_PER_YEAR[cycle]).quantize(Decimal("0.01"))
    monthly = (annual / Decimal(12)).quantize(Decimal("0.01"))

    hints = f"{merchant} {ordered[0].category_raw} {ordered[0].description}".lower()
    is_hidden = category == "订阅服务" or any(h in hints for h in HIDDEN_HINTS)

    dates = tuple(t.occurred_at.date() for t in ordered)
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    fit = _fit_cycle(gaps)

    return Subscription(
        merchant=merchant,
        amount=representative,
        cycle=cycle,
        occurrences=len(ordered),
        first_seen=dates[0],
        last_seen=dates[-1],
        annual_cost=annual,
        confidence=_confidence(len(ordered), cv, fit[1] if fit else 1.0),
        category=category,
        is_hidden=is_hidden,
        charges=dates,
        monthly_equivalent=monthly,
    )


def _daily_collapse(group: Sequence[Transaction]) -> list[Transaction]:
    """Keep at most one charge per merchant per day.

    A subscription bills once per period; duplicate same-day rows are usually
    the same charge appearing twice in an export.
    """
    by_day: dict[date, Transaction] = {}
    for transaction in sorted(group, key=lambda t: t.occurred_at):
        day = transaction.occurred_at.date()
        current = by_day.get(day)
        if current is None or transaction.amount > current.amount:
            by_day[day] = transaction
    return [by_day[day] for day in sorted(by_day)]


def _amount_buckets(group: Sequence[Transaction]) -> list[list[Transaction]]:
    """Split a merchant's history by rounded amount.

    One merchant can sell several plans at once (iCloud 50GB *and* 2TB).  If the
    whole group fails, per-amount buckets often still fit.
    """
    buckets: dict[int, list[Transaction]] = {}
    for transaction in group:
        buckets.setdefault(int(round(float(transaction.amount))), []).append(transaction)
    return [bucket for bucket in buckets.values() if len(bucket) >= 2]


def _hinted(merchant: str, sample: Transaction) -> bool:
    """Whether the merchant text explicitly signals a subscription product."""
    text = f"{merchant} {sample.category_raw} {sample.description}".lower()
    return any(hint in text for hint in SUBSCRIPTION_HINTS)


def _evaluate(group: Sequence[Transaction], merchant: str) -> list[Subscription]:
    """Try to explain one merchant's history as one or more subscriptions."""
    collapsed = _daily_collapse(group)
    if len(collapsed) < 2:
        return []

    dates = [t.occurred_at.date() for t in collapsed]
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    if not gaps:
        return []

    fit = _fit_cycle(gaps)
    if fit and len(collapsed) >= MIN_OCCURRENCES_BY_CYCLE.get(fit[0], 3):
        subscription = _build(merchant, collapsed, fit[0], collapsed[0].category)
        if subscription and subscription.confidence != "low":
            return [subscription]

    # Fall back to per-amount buckets, but only for merchants that plausibly sell
    # several plans at once.  Two charges alone are far too easy to fit by chance.
    amounts = [float(t.amount) for t in collapsed]
    if _cv(amounts) <= MAX_CV:
        return []

    found: list[Subscription] = []
    for bucket in _amount_buckets(collapsed):
        if len(bucket) < 3:
            continue
        bucket_dates = [t.occurred_at.date() for t in bucket]
        bucket_gaps = [
            (bucket_dates[i + 1] - bucket_dates[i]).days for i in range(len(bucket_dates) - 1)
        ]
        bucket_fit = _fit_cycle(bucket_gaps)
        if not bucket_fit:
            continue
        if len(bucket) < MIN_OCCURRENCES_BY_CYCLE.get(bucket_fit[0], 3):
            continue
        subscription = _build(merchant, bucket, bucket_fit[0], bucket[0].category)
        if subscription and subscription.confidence != "low":
            found.append(subscription)
    return found


def detect_subscriptions(transactions: Iterable[Transaction]) -> list[Subscription]:
    """Detect recurring charges, most expensive first."""
    groups: dict[str, list[Transaction]] = {}
    display: dict[str, str] = {}

    for transaction in transactions:
        if not transaction.is_effective:
            continue
        if transaction.direction is not Direction.EXPENSE:
            continue
        if transaction.category in EXCLUDED_CATEGORIES:
            continue
        merchant = transaction.merchant
        if not merchant:
            continue
        key = merchant.strip().lower()
        groups.setdefault(key, []).append(transaction)
        display.setdefault(key, merchant.strip())

    results: list[Subscription] = []
    for key, group in groups.items():
        if len(group) < 2 or len(group) > MAX_OCCURRENCES:
            continue
        merchant = display[key]
        category = group[0].category
        # Habit spending needs an explicit membership hint to qualify.
        if category in HABIT_CATEGORIES and not _hinted(merchant, group[0]):
            continue
        results.extend(_evaluate(group, merchant))

    results.sort(key=lambda s: (s.annual_cost, s.occurrences), reverse=True)
    return results
