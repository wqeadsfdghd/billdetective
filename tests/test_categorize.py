"""Categorisation and internal-transfer tests."""

from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal

from billdetective.categorize import categorize
from billdetective.models import Direction, Transaction


def make(
    counterparty: str,
    description: str = "",
    category_raw: str = "",
    direction: Direction = Direction.EXPENSE,
) -> Transaction:
    return Transaction(
        occurred_at=datetime(2026, 6, 1, 12, 0),
        amount=Decimal("20.00"),
        direction=direction,
        counterparty=counterparty,
        description=description,
        category_raw=category_raw,
    )


class CategorizeTests(unittest.TestCase):
    def test_food_keywords(self) -> None:
        self.assertEqual(categorize(make("美团外卖")).category, "餐饮美食")
        self.assertEqual(categorize(make("瑞幸咖啡")).category, "餐饮美食")

    def test_transport_keywords(self) -> None:
        self.assertEqual(categorize(make("上海地铁")).category, "交通出行")
        self.assertEqual(categorize(make("滴滴出行", "快车")).category, "交通出行")

    def test_subscription_keywords(self) -> None:
        self.assertEqual(categorize(make("爱奇艺", "黄金VIP会员连续包月")).category, "订阅服务")
        self.assertEqual(categorize(make("Apple", "iCloud+ 50GB 订阅")).category, "订阅服务")

    def test_platform_label_is_trusted(self) -> None:
        self.assertEqual(categorize(make("某公司", "", "交通出行")).category, "交通出行")

    def test_income_always_income(self) -> None:
        tx = make("某公司", "工资", direction=Direction.INCOME)
        self.assertEqual(categorize(tx).category, "收入")

    def test_unknown_lands_in_other(self) -> None:
        self.assertEqual(categorize(make("某某科技")).category, "其他")


class InternalTransferTests(unittest.TestCase):
    def test_credit_card_repayment_is_neutral(self) -> None:
        # Would otherwise double-count everything bought with that card.
        tx = make("招商银行信用卡", "信用卡还款", "转账")
        result = categorize(tx)
        self.assertIs(result.direction, Direction.NEUTRAL)
        self.assertFalse(result.is_effective)

    def test_topup_to_yuebao_is_neutral(self) -> None:
        tx = make("余额宝", "转入余额宝", "投资理财")
        self.assertIs(categorize(tx).direction, Direction.NEUTRAL)

    def test_gym_renewal_is_not_hidden_subscription(self) -> None:
        # "月卡续费" is a deliberate purchase, not an unnoticed auto-renewal.
        result = categorize(make("乐刻健身", "月卡续费", "休闲娱乐"))
        self.assertEqual(result.category, "休闲娱乐")


if __name__ == "__main__":
    unittest.main()
