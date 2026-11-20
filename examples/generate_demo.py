"""Generate synthetic demo statements.

Every figure here is fabricated.  The point is to exercise the real parsing
path — Alipay written as GBK with a preamble, WeChat as UTF-8 with a BOM and a
16-line preamble — while shipping data that is safe to commit.

Run:  python examples/generate_demo.py
"""

from __future__ import annotations

import calendar
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
RNG = random.Random(20261120)

START = date(2026, 6, 1)
END = date(2026, 11, 30)

ALIPAY_HEADER = [
    "交易时间", "交易分类", "交易对方", "商品说明", "收/支", "金额",
    "收/付款方式", "交易状态", "交易订单号", "商家订单号", "备注",
]
WECHAT_HEADER = [
    "交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)",
    "支付方式", "当前状态", "交易单号", "商户单号", "备注",
]


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def months_span() -> list[date]:
    result: list[date] = []
    cursor = date(START.year, START.month, 1)
    while cursor <= END:
        result.append(cursor)
        cursor = add_months(cursor, 1)
    return result


def stamp(day: date, hour: int, minute: int) -> str:
    return f"{day:%Y-%m-%d} {hour:02d}:{minute:02d}:00"


def order_id(prefix: str, counter: list[int]) -> str:
    counter[0] += 1
    return f"{prefix}{20260000000 + counter[0]}"


def alipay_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    counter = [0]

    def emit(day, category, party, desc, direction, amount, method, status="交易成功"):
        rows.append([
            stamp(day, RNG.randint(7, 22), RNG.randint(0, 59)),
            category, party, desc, direction, f"{amount:.2f}",
            method, status, order_id("2026", counter), order_id("T", counter), "",
        ])

    for month in months_span():
        # --- recurring: rent, phone, utilities, subscriptions
        emit(add_months(month, 0).replace(day=5), "住房物业", "房东张先生", "房租", "支出", 3200.00, "余额宝")
        emit(month.replace(day=12), "充值缴费", "中国移动", "话费充值", "支出", 59.00, "花呗")
        emit(month.replace(day=18), "充值缴费", "国家电网", "电费", "支出", round(RNG.uniform(80, 160), 2), "余额宝")
        emit(month.replace(day=15), "文化休闲", "爱奇艺", "黄金VIP会员连续包月", "支出", 25.00, "花呗")
        emit(month.replace(day=3), "文化休闲", "Apple", "iCloud+ 50GB 订阅", "支出", 6.00, "花呗")
        emit(month.replace(day=20), "文化休闲", "网易云音乐", "黑胶VIP连续包月", "支出", 15.00, "花呗")

        # --- daily life, randomised
        for _ in range(RNG.randint(26, 34)):
            day = month + timedelta(days=RNG.randint(0, 27))
            if day > END:
                continue
            emit(day, "餐饮美食", RNG.choice(["沙县小吃", "兰州拉面", "瑞幸咖啡", "公司食堂", "蜜雪冰城", "老乡鸡"]),
                 "餐饮消费", "支出", round(RNG.uniform(9, 48), 2), "余额宝")
        for _ in range(RNG.randint(14, 20)):
            day = month + timedelta(days=RNG.randint(0, 27))
            if day > END:
                continue
            emit(day, "交通出行", "上海地铁", "地铁乘车", "支出", round(RNG.uniform(3, 9), 2), "余额宝")
        for _ in range(RNG.randint(3, 6)):
            day = month + timedelta(days=RNG.randint(0, 27))
            if day > END:
                continue
            emit(day, "日用百货", RNG.choice(["盒马鲜生", "永辉超市", "全家便利店"]),
                 "日用采购", "支出", round(RNG.uniform(28, 320), 2), "花呗")
        for _ in range(RNG.randint(1, 3)):
            day = month + timedelta(days=RNG.randint(0, 27))
            if day > END:
                continue
            emit(day, "服饰装扮", "优衣库", "服装", "支出", round(RNG.uniform(99, 499), 2), "花呗")

    # --- income
    for month in months_span():
        rows.append([
            stamp(month.replace(day=10), 9, 30), "转账红包", "某某科技有限公司", "工资", "收入",
            f"{RNG.uniform(14800, 15200):.2f}", "余额", "交易成功",
            order_id("2026", counter), order_id("T", counter), "",
        ])

    # --- rows that must NOT count: refunds and closed orders
    rows.append([
        stamp(date(2026, 8, 9), 14, 12), "服饰装扮", "优衣库", "服装", "支出", "299.00",
        "花呗", "退款成功", order_id("2026", counter), order_id("T", counter), "",
    ])
    rows.append([
        stamp(date(2026, 9, 21), 20, 3), "数码电器", "京东", "蓝牙耳机", "支出", "459.00",
        "花呗", "交易关闭", order_id("2026", counter), order_id("T", counter), "",
    ])
    rows.append([
        stamp(date(2026, 10, 2), 11, 45), "投资理财", "余额宝", "转入余额宝", "不计收支", "2000.00",
        "余额", "交易成功", order_id("2026", counter), order_id("T", counter), "",
    ])

    rows.sort(key=lambda row: row[0])
    return rows


def wechat_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    counter = [0]

    def emit(day, kind, party, desc, direction, amount, method, status="支付成功"):
        rows.append([
            stamp(day, RNG.randint(7, 23), RNG.randint(0, 59)),
            kind, party, desc, direction, f"¥{amount:.2f}",
            method, status, order_id("WX", counter), order_id("M", counter), "",
        ])

    for month in months_span():
        # Tencent Video — the classic "I forgot I subscribed" case.
        emit(month.replace(day=8), "商户消费", "腾讯视频", "腾讯视频VIP连续包月", "支出", 30.00, "招商银行(1234)")
        # Gym membership, billed yearly-ish but steady monthly.
        emit(month.replace(day=1), "商户消费", "乐刻健身", "月卡续费", "支出", 199.00, "招商银行(1234)")

        for _ in range(RNG.randint(8, 14)):
            day = month + timedelta(days=RNG.randint(0, 27))
            if day > END:
                continue
            emit(day, "商户消费", RNG.choice(["美团外卖", "肯德基", "星巴克", "便利蜂"]),
                 "餐饮", "支出", round(RNG.uniform(15, 68), 2), "零钱")
        for _ in range(RNG.randint(4, 8)):
            day = month + timedelta(days=RNG.randint(0, 27))
            if day > END:
                continue
            emit(day, "商户消费", "滴滴出行", "快车", "支出", round(RNG.uniform(12, 56), 2), "零钱")

    # Structural periodicity that is NOT a subscription: card repayment.
    for month in months_span():
        emit(month.replace(day=25), "转账", "招商银行信用卡", "信用卡还款", "支出",
             round(RNG.uniform(1200, 2600), 2), "零钱")

    # A red packet — neutral-ish, must not inflate spending.
    emit(date(2026, 9, 15), "微信红包", "家庭群", "中秋红包", "支出", 200.00, "零钱")

    rows.sort(key=lambda row: row[0])
    return rows


def write_alipay(path: Path) -> None:
    preamble = [
        ["支付宝交易记录明细查询"],
        ["账号:[demo@example.com]"],
        [f"起始日期:[{START} 00:00:00]    终止日期:[{END} 23:59:59]"],
        ["---------------------------------交易记录明细列表------------------------------------"],
    ]
    with path.open("w", encoding="gb18030", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(preamble)
        writer.writerow(ALIPAY_HEADER)
        writer.writerows(alipay_rows())


def write_wechat(path: Path) -> None:
    preamble = [
        ["微信支付账单明细"],
        ["微信昵称：[示例用户]"],
        [f"起始时间：[{START} 00:00:00] 终止时间：[{END} 23:59:59]"],
        ["导出类型：[全部]"],
        [f"导出时间：[{datetime(2026, 11, 20, 10, 0, 0)}]"],
        [""],
        ["共 N 笔记录"],
        [""],
        ["----------------------微信支付账单明细列表--------------------"],
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(preamble)
        writer.writerow(WECHAT_HEADER)
        writer.writerows(wechat_rows())


def main() -> None:
    alipay = OUT_DIR / "alipay_demo_2026H2.csv"
    wechat = OUT_DIR / "wechat_demo_2026H2.csv"
    write_alipay(alipay)
    write_wechat(wechat)
    print(f"已生成 {alipay.name}（GBK 编码，{len(alipay_rows())} 条）")
    print(f"已生成 {wechat.name}（UTF-8-BOM 编码，{len(wechat_rows())} 条）")
    print("全部为合成数据，不含任何真实账户信息。")


if __name__ == "__main__":
    main()
