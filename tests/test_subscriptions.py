"""Subscription detection — the precision-critical part of the project.

Each test here encodes a failure mode observed in real bill data.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

from billdetective.models import Direction, Transaction
from billdetective.subscriptions import detect_subscriptions


def tx(
    day: date,
    amount: str,
    merchant: str,
    category: str = "订阅服务",
    description: str = "",
    direction: Direction = Direction.EXPENSE,
) -> Transaction:
    return Transaction(
        occurred_at=datetime.combine(day, datetime.min.time()),
        amount=Decimal(amount),
        direction=direction,
        counterparty=merchant,
        description=description,
        category=category,
    )


def monthly(merchant: str, amount: str, start: date, count: int, **kwargs) -> list[Transaction]:
    """Charges every ~30 days, mirroring how real monthly plans bill."""
    return [tx(start + timedelta(days=30 * i), amount, merchant, **kwargs) for i in range(count)]


class DetectionTests(unittest.TestCase):
    def test_monthly_plan_is_detected(self) -> None:
        charges = monthly("爱奇艺", "25.00", date(2026, 1, 15), 6, description="黄金VIP连续包月")
        found = detect_subscriptions(charges)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].cycle, "monthly")
        self.assertEqual(found[0].occurrences, 6)

    def test_annual_cost_uses_calendar_months(self) -> None:
        # 25 * 12 = 300, never 25 * 365/30 = 304.17.
        charges = monthly("爱奇艺", "25.00", date(2026, 1, 15), 6)
        self.assertEqual(detect_subscriptions(charges)[0].annual_cost, Decimal("300.00"))

    def test_quarterly_plan_is_detected(self) -> None:
        charges = [
            tx(date(2026, 1, 5) + timedelta(days=91 * i), "68.00", "某云存储", description="季度订阅")
            for i in range(3)
        ]
        found = detect_subscriptions(charges)
        self.assertEqual(found[0].cycle, "quarterly")
        self.assertEqual(found[0].annual_cost, Decimal("272.00"))

    def test_two_charges_are_not_enough(self) -> None:
        # Two points always fit some cycle by chance; requiring three is what
        # keeps the false-positive rate down.
        charges = monthly("某订阅", "30.00", date(2026, 1, 1), 2)
        self.assertEqual(detect_subscriptions(charges), [])

    def test_frequent_cafe_visits_are_not_a_subscription(self) -> None:
        # 30 random visits to one noodle shop — the classic false positive.
        charges = [
            tx(date(2026, 1, 1) + timedelta(days=i * 5 + (i % 3)), "32.00", "兰州拉面", category="餐饮美食")
            for i in range(30)
        ]
        self.assertEqual(detect_subscriptions(charges), [])

    def test_habit_category_with_membership_hint_is_allowed(self) -> None:
        # "瑞幸咖啡会员" is genuinely a plan, despite the food category.
        charges = monthly("瑞幸咖啡", "19.00", date(2026, 1, 1), 4, category="餐饮美食", description="咖啡会员")
        self.assertEqual(len(detect_subscriptions(charges)), 1)

    def test_credit_repayment_excluded(self) -> None:
        charges = monthly("招商银行信用卡", "1520.00", date(2026, 1, 25), 5, category="转账理财")
        self.assertEqual(detect_subscriptions(charges), [])

    def test_unstable_amount_is_rejected(self) -> None:
        amounts = ["20.00", "45.00", "18.00", "90.00", "22.00"]
        charges = [
            tx(date(2026, 1, 1) + timedelta(days=30 * i), amount, "某商户", category="日用购物")
            for i, amount in enumerate(amounts)
        ]
        self.assertEqual(detect_subscriptions(charges), [])

    def test_one_missed_month_is_tolerated(self) -> None:
        # Gap of 60 days should still read as monthly, not a broken cycle.
        days = [0, 30, 60, 120, 150]
        charges = [tx(date(2026, 1, 1) + timedelta(days=d), "15.00", "网易云音乐") for d in days]
        found = detect_subscriptions(charges)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].cycle, "monthly")

    def test_income_ignored(self) -> None:
        charges = monthly("某公司", "15000.00", date(2026, 1, 10), 5, direction=Direction.INCOME)
        self.assertEqual(detect_subscriptions(charges), [])

    def test_hidden_flag_for_digital_plan(self) -> None:
        charges = monthly("腾讯视频", "30.00", date(2026, 1, 8), 5, description="腾讯视频VIP连续包月")
        self.assertTrue(detect_subscriptions(charges)[0].is_hidden)

    def test_gym_is_recurring_but_not_hidden(self) -> None:
        charges = monthly("乐刻健身", "199.00", date(2026, 1, 1), 5, category="休闲娱乐", description="月卡续费")
        found = detect_subscriptions(charges)
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].is_hidden)


if __name__ == "__main__":
    unittest.main()
