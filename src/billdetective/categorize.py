"""Rule-based transaction categorisation.

Design notes
------------
1. **Platform label wins.**  Alipay/WeChat already classify most rows; if that
   label maps onto a known internal category we trust it, because it is derived
   from real merchant registration data.
2. **Merchant keywords come second.**  When the platform label is missing or
   vague (``商户消费``), merchant and description text are matched against an
   ordered rule table.  More specific rules sit earlier so ``滴滴打车`` is not
   swallowed by the generic ``打车`` bucket before its own rule fires.
3. **Never silently guess.**  Anything unmatched lands in ``其他`` and is
   surfaced in the report as uncategorised spending, which is itself a useful
   signal for the user.
"""

from __future__ import annotations

from .models import Direction, Transaction

__all__ = ["CATEGORIES", "categorize", "categorize_all", "UNCATEGORIZED"]

UNCATEGORIZED = "其他"

CATEGORIES: tuple[str, ...] = (
    "餐饮美食",
    "交通出行",
    "日用购物",
    "服饰美妆",
    "休闲娱乐",
    "订阅服务",
    "生活缴费",
    "医疗健康",
    "教育培训",
    "住房租物",
    "数码电器",
    "人情往来",
    "转账理财",
    "收入",
    UNCATEGORIZED,
)

#: Alipay / WeChat native labels -> internal categories.
PLATFORM_LABEL_MAP: dict[str, str] = {
    # Alipay 交易分类
    "餐饮美食": "餐饮美食",
    "交通出行": "交通出行",
    "日用百货": "日用购物",
    "服饰装扮": "服饰美妆",
    "美容美发": "服饰美妆",
    "休闲娱乐": "休闲娱乐",
    "酒店旅游": "休闲娱乐",
    "医疗健康": "医疗健康",
    "教育培训": "教育培训",
    "住房物业": "住房租物",
    "投资理财": "转账理财",
    "转账红包": "人情往来",
    "充值缴费": "生活缴费",
    "数码电器": "数码电器",
    "商业服务": "其他",
    "信用借还": "转账理财",
    "保险": "生活缴费",
    # WeChat 交易类型
    "商户消费": "",
    "转账": "人情往来",
    "红包": "人情往来",
    "群收款": "人情往来",
    "二维码收款": "收入",
    "扫二维码付款": "",
    "微信红包": "人情往来",
}

#: Ordered keyword rules; first hit wins.  Order = specificity, not alphabet.
CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("订阅服务", (
        "会员", "订阅", "包月", "包年", "vip", "svip", "自动续费", "连续包月",
        "连续包季", "连续包年", "netflix", "spotify", "youtube", "icloud",
        "apple music", "爱奇艺", "腾讯视频", "优酷", "芒果tv", "哔哩哔哩",
        "bilibili", "网易云音乐", "qq音乐", "酷狗", "百度网盘", "阿里云盘",
        "夸克", "wps会员", "office365", "chatgpt", "openai", "claude",
        "midjourney", "notion", "figma", "github", "cursor", "语雀", "印象笔记",
        "石墨", "腾讯文档", "剪映", "醒图",
    )),
    ("餐饮美食", (
        "餐", "饭", "面", "粉", "粥", "饺子", "包子", "烧烤", "火锅", "麻辣烫",
        "奶茶", "咖啡", "茶饮", "星巴克", "瑞幸", "库迪", "蜜雪", "肯德基",
        "麦当劳", "汉堡", "披萨", "外卖", "饿了么", "美团外卖", "食堂",
        "早餐", "午餐", "晚餐", "小吃", "烘焙", "蛋糕", "水果", "生鲜", "菜市场",
        "便利店", "711", "全家", "罗森", "超市",
    )),
    ("交通出行", (
        "地铁", "公交", "打车", "滴滴", "高德", "曹操", "t3", "出租车", "网约车",
        "加油", "中石化", "中石油", "停车", "高速", "etc", "火车", "高铁",
        "12306", "机票", "航空", "共享单车", "哈啰", "青桔", "摩拜", "充电桩",
    )),
    ("生活缴费", (
        "电费", "水费", "燃气", "物业", "取暖", "话费", "流量", "宽带",
        "电信", "移动", "联通", "电费代扣", "国家电网", "缴费",
    )),
    ("医疗健康", (
        "医院", "药", "诊所", "体检", "门诊", "挂号", "口腔", "牙科", "眼科",
        "医保", "检验", "康复", "中医",
    )),
    ("教育培训", (
        "学费", "培训", "课程", "教育", "网校", "考试", "报名费", "驾校",
        "书店", "图书", "得到", "知乎盐选",
    )),
    ("住房租物", ("房租", "租金", "中介", "押金", "家政", "保洁", "维修", "搬家")),
    ("服饰美妆", (
        "服饰", "衣", "鞋", "裤", "裙", "帽", "优衣库", "无印良品", "淘宝",
        "天猫", "京东", "唯品会", "化妆品", "护肤", "彩妆", "香水", "理发",
        "美发", "美甲", "丝芙兰", "屈臣氏",
    )),
    ("数码电器", (
        "苹果", "apple store", "小米", "华为", "电脑", "手机", "耳机",
        "显示器", "键盘", "鼠标", "相机", "充电", "数码",
    )),
    ("休闲娱乐", (
        "电影", "影院", "ktv", "游戏", "steam", "网吧", "健身", "游泳",
        "球馆", "旅游", "酒店", "民宿", "景区", "门票", "演唱会", "剧本杀",
        "桌游", "盲盒", "手办",
    )),
    ("人情往来", (
        "红包", "转账", "礼金", "份子", "代付", "亲属卡",
    )),
    ("转账理财", (
        "余额宝", "基金", "理财", "股票", "证券", "还款", "信用卡还款",
        "花呗", "借呗", "白条", "提现", "充值", "转入", "转出",
    )),
)


#: Movements between the user's own accounts, or repayment of money already
#: spent.  Counting these as expenses double-counts the original purchase — the
#: single biggest source of inflated "total spending" in bill analysers.
INTERNAL_TRANSFER_HINTS: tuple[str, ...] = (
    "信用卡还款", "花呗还款", "借呗还款", "白条还款", "还款",
    "转入余额宝", "转出余额宝", "余额宝转入", "零钱通", "理财通",
    "提现", "自动转入", "自动转出", "本人账户", "内部转账",
)


def _is_internal_transfer(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in INTERNAL_TRANSFER_HINTS)


def _match_keywords(text: str) -> str | None:
    lowered = text.lower()
    for category, keywords in CATEGORY_RULES:
        for keyword in keywords:
            if keyword in lowered:
                return category
    return None


def categorize(transaction: Transaction) -> Transaction:
    """Return a copy of ``transaction`` with ``category`` filled in."""
    if transaction.direction is Direction.INCOME:
        return transaction.with_category("收入")

    haystack = f"{transaction.counterparty} {transaction.description} {transaction.category_raw}"

    # 0) Internal transfers are not spending, whatever the platform labelled them.
    if transaction.direction is Direction.EXPENSE and _is_internal_transfer(haystack):
        return transaction.with_direction(Direction.NEUTRAL).with_category("转账理财")

    # 1) Trust the platform's own label when it maps cleanly.
    label = PLATFORM_LABEL_MAP.get(transaction.category_raw, None)
    if label:
        return transaction.with_category(label)

    # 2) Merchant + description keywords.
    keyword_category = _match_keywords(haystack)
    if keyword_category:
        return transaction.with_category(keyword_category)

    # 3) Platform label as-is if it is already one of ours.
    if transaction.category_raw in CATEGORIES:
        return transaction.with_category(transaction.category_raw)

    return transaction.with_category(UNCATEGORIZED)


def categorize_all(transactions: list[Transaction]) -> list[Transaction]:
    return [categorize(t) for t in transactions]
