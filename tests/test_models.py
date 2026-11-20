"""Unit tests for the domain model."""

from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal

from billdetective.models import (
    Direction,
    Transaction,
    is_void_status,
    normalize_direction,
    parse_amount,
    parse_datetime,
)


class ParseAmountTests(unittest.TestCase):
    def test_decorated_amount(self) -> None:
        self.assertEqual(parse_amount("¥1,234.50"), Decimal("1234.50"))

    def test_yuan_suffix(self) -> None:
        self.assertEqual(parse_amount("1,234.50元"), Decimal("1234.50"))

    def test_negative_becomes_positive(self) -> None:
        self.assertEqual(parse_amount("-58.00"), Decimal("58.00"))

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(parse_amount(""))
        self.assertIsNone(parse_amount("待确认"))
        self.assertIsNone(parse_amount(None))

    def test_float_input_preserves_value(self) -> None:
        # Floats are converted through str() so the Decimal reflects whatever the
        # float actually holds — no silent re-rounding of the caller's data.
        self.assertEqual(parse_amount(12.5), Decimal("12.5"))
        self.assertEqual(parse_amount(0.1 + 0.2), Decimal(str(0.1 + 0.2)))


class ParseDatetimeTests(unittest.TestCase):
    def test_common_formats(self) -> None:
        expected = datetime(2026, 3, 15, 12, 30, 45)
        for raw in ("2026-03-15 12:30:45", "2026/03/15 12:30:45"):
            self.assertEqual(parse_datetime(raw), expected)

    def test_minute_precision(self) -> None:
        self.assertEqual(parse_datetime("2026-03-15 12:30"), datetime(2026, 3, 15, 12, 30))

    def test_chinese_format(self) -> None:
        self.assertEqual(parse_datetime("2026年03月15日"), datetime(2026, 3, 15))

    def test_invalid(self) -> None:
        self.assertIsNone(parse_datetime("昨天"))
        self.assertIsNone(parse_datetime(""))


class DirectionTests(unittest.TestCase):
    def test_mapping(self) -> None:
        self.assertIs(normalize_direction("支出"), Direction.EXPENSE)
        self.assertIs(normalize_direction("收入"), Direction.INCOME)
        self.assertIs(normalize_direction("不计收支"), Direction.NEUTRAL)
        self.assertIs(normalize_direction("???"), Direction.UNKNOWN)


class EffectiveTransactionTests(unittest.TestCase):
    def _tx(self, direction: Direction, status: str, amount: str = "10") -> Transaction:
        return Transaction(
            occurred_at=datetime(2026, 6, 1, 12, 0),
            amount=Decimal(amount),
            direction=direction,
            status=status,
        )

    def test_normal_expense_counts(self) -> None:
        self.assertTrue(self._tx(Direction.EXPENSE, "交易成功").is_effective)

    def test_refund_does_not_count(self) -> None:
        # The whole reason this field exists: refunded orders must not inflate totals.
        self.assertFalse(self._tx(Direction.EXPENSE, "退款成功").is_effective)
        self.assertFalse(self._tx(Direction.EXPENSE, "交易关闭").is_effective)

    def test_neutral_does_not_count(self) -> None:
        self.assertFalse(self._tx(Direction.NEUTRAL, "交易成功").is_effective)

    def test_void_status_helper(self) -> None:
        self.assertTrue(is_void_status("已全额退款"))
        self.assertFalse(is_void_status("交易成功"))


if __name__ == "__main__":
    unittest.main()
