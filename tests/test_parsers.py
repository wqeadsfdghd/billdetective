"""Parser tests driven by real-world file shapes (encoding + preamble)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from billdetective.models import Direction
from billdetective.parsers import ParseError, load_statements

ALIPAY_PREAMBLE = (
    "支付宝交易记录明细查询\n"
    "账号:[demo@example.com]\n"
    "起始日期:[2026-06-01 00:00:00]    终止日期:[2026-06-30 23:59:59]\n"
    "---------------------------------交易记录明细列表------------------------------------\n"
)
ALIPAY_HEADER = (
    "交易时间,交易分类,交易对方,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注\n"
)
ALIPAY_BODY = (
    "2026-06-05 09:12:00,住房物业,房东张先生,房租,支出,3200.00,余额宝,交易成功,2026001,T001,\n"
    "2026-06-15 10:00:00,文化休闲,爱奇艺,黄金VIP会员连续包月,支出,25.00,花呗,交易成功,2026002,T002,\n"
    "2026-06-20 19:30:00,服饰装扮,优衣库,服装,支出,299.00,花呗,退款成功,2026003,T003,\n"
)

WECHAT_PREAMBLE = (
    "微信支付账单明细\n"
    "微信昵称：[示例用户]\n"
    "起始时间：[2026-06-01 00:00:00] 终止时间：[2026-06-30 23:59:59]\n"
    "导出类型：[全部]\n"
    "\n"
    "----------------------微信支付账单明细列表--------------------\n"
)
WECHAT_HEADER = (
    "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注\n"
)
WECHAT_BODY = (
    "2026-06-08 21:04:00,商户消费,腾讯视频,腾讯视频VIP连续包月,支出,¥30.00,招商银行(1234),支付成功,WX001,M001,\n"
    "2026-06-10 12:00:00,转账,招商银行信用卡,信用卡还款,支出,¥1520.00,零钱,支付成功,WX002,M002,\n"
)


class ParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, name: str, text: str, encoding: str) -> Path:
        path = self.tmp / name
        path.write_bytes(text.encode(encoding))
        return path

    def test_alipay_gbk_with_preamble(self) -> None:
        path = self._write("alipay.csv", ALIPAY_PREAMBLE + ALIPAY_HEADER + ALIPAY_BODY, "gb18030")
        result = load_statements([path])
        self.assertEqual(result.source_format, "merged")
        self.assertEqual(len(result.transactions), 3)

        first = result.transactions[0]
        self.assertEqual(first.counterparty, "房东张先生")
        self.assertEqual(str(first.amount), "3200.00")
        self.assertIs(first.direction, Direction.EXPENSE)

    def test_refund_row_is_flagged_void(self) -> None:
        path = self._write("alipay.csv", ALIPAY_PREAMBLE + ALIPAY_HEADER + ALIPAY_BODY, "gb18030")
        result = load_statements([path])
        refund = [t for t in result.transactions if t.counterparty == "优衣库"][0]
        self.assertFalse(refund.is_effective)

    def test_wechat_utf8_bom_and_yen_sign(self) -> None:
        path = self._write("wechat.csv", WECHAT_PREAMBLE + WECHAT_HEADER + WECHAT_BODY, "utf-8-sig")
        result = load_statements([path])
        self.assertEqual(len(result.transactions), 2)
        amounts = {str(t.amount) for t in result.transactions}
        self.assertIn("30.00", amounts)

    def test_merging_deduplicates_identical_rows(self) -> None:
        alipay = self._write("a.csv", ALIPAY_PREAMBLE + ALIPAY_HEADER + ALIPAY_BODY, "gb18030")
        result_one = load_statements([alipay])
        result_twice = load_statements([alipay, alipay])
        # Same file twice must not double every figure.
        self.assertEqual(len(result_one.transactions), len(result_twice.transactions))

    def test_generic_csv(self) -> None:
        text = "日期,金额,收/支,交易对方\n2026-06-01,25.00,支出,某商户\n"
        path = self._write("generic.csv", text, "utf-8")
        result = load_statements([path])
        self.assertEqual(len(result.transactions), 1)
        self.assertEqual(result.transactions[0].counterparty, "某商户")

    def test_non_bill_file_raises(self) -> None:
        path = self._write("random.csv", "a,b,c\n1,2,3\n", "utf-8")
        with self.assertRaises(ParseError):
            load_statements([path])


if __name__ == "__main__":
    unittest.main()
