"""Aggregation and report rendering tests."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from billdetective.analyze import analyze
from billdetective.models import Direction, Transaction
from billdetective.report import render_html, render_text


def tx(
    day: date,
    amount: str,
    merchant: str,
    category_raw: str = "",
    direction: Direction = Direction.EXPENSE,
    status: str = "交易成功",
) -> Transaction:
    return Transaction(
        occurred_at=datetime.combine(day, datetime.min.time()),
        amount=Decimal(amount),
        direction=direction,
        counterparty=merchant,
        category_raw=category_raw,
        status=status,
    )


class AnalyzeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transactions = [
            tx(date(2026, 6, 1), "100.00", "某超市", "日用百货"),
            tx(date(2026, 6, 5), "50.00", "某餐厅", "餐饮美食"),
            tx(date(2026, 7, 2), "200.00", "某超市", "日用百货"),
            tx(date(2026, 7, 10), "5000.00", "某公司", direction=Direction.INCOME),
            tx(date(2026, 7, 12), "999.00", "某电商", "日用百货", status="退款成功"),
        ]
        self.analysis = analyze(self.transactions)

    def test_totals_exclude_refunds(self) -> None:
        self.assertEqual(self.analysis.total_expense, Decimal("350.00"))
        self.assertEqual(self.analysis.total_income, Decimal("5000.00"))

    def test_net(self) -> None:
        self.assertEqual(self.analysis.net, Decimal("4650.00"))

    def test_period(self) -> None:
        self.assertEqual(self.analysis.period_start, date(2026, 6, 1))
        # The refunded row on 07-12 is not effective, so it must not stretch the
        # reporting window past the last real transaction.
        self.assertEqual(self.analysis.period_end, date(2026, 7, 10))

    def test_monthly_buckets(self) -> None:
        self.assertEqual([b.key for b in self.analysis.by_month], ["2026-06", "2026-07"])
        self.assertEqual(self.analysis.by_month[0].expense, Decimal("150.00"))

    def test_category_ranking(self) -> None:
        self.assertEqual(self.analysis.by_category["日用购物"], Decimal("300.00"))
        self.assertGreater(self.analysis.category_share("日用购物"), 0.8)

    def test_insights_are_generated(self) -> None:
        self.assertTrue(self.analysis.insights)

    def test_empty_input_is_safe(self) -> None:
        empty = analyze([])
        self.assertEqual(empty.total_expense, Decimal("0"))
        self.assertEqual(empty.monthly_average_expense, Decimal("0.00"))
        self.assertIn("账单侦探", render_text(empty))
        self.assertIn("<!DOCTYPE html>", render_html(empty))


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        transactions = [tx(date(2026, 6, 1), "25.00", "爱奇艺", "文化休闲")]
        self.analysis = analyze(transactions)

    def test_html_is_self_contained(self) -> None:
        html = render_html(self.analysis)
        self.assertIn("<!DOCTYPE html>", html)
        # No scripts, no remote assets — the report must work offline.
        self.assertNotIn("<script", html.lower())
        self.assertNotIn('<link rel="stylesheet"', html.lower())
        self.assertNotIn("<img", html.lower())

    def test_html_escapes_user_content(self) -> None:
        evil = analyze([tx(date(2026, 6, 1), "10.00", '<script>alert(1)</script>', "日用百货")])
        html = render_html(evil)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_text_report_mentions_totals(self) -> None:
        text = render_text(self.analysis)
        self.assertIn("总支出", text)
        self.assertIn("¥25", text)


if __name__ == "__main__":
    unittest.main()
