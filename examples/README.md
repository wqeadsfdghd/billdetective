# 示例数据

**这里的每一行都是程序生成的，不含任何真实账户信息。**

| 文件 | 说明 |
|---|---|
| `alipay_demo_2026H2.csv` | 支付宝格式，GBK 编码，带 4 行前导说明 |
| `wechat_demo_2026H2.csv` | 微信支付格式，UTF-8-BOM 编码，带 9 行前导说明 |
| `generate_demo.py` | 生成脚本，固定随机种子，可复现 |
| `demo_report.html` | 用这两个文件生成的报告样例 |

数据覆盖 2026-06 至 2026-11，刻意构造了这些场景：

- 4 项真实订阅（腾讯视频、爱奇艺、网易云音乐、iCloud），用于验证检测
- 3 项固定账单（房租、话费、健身月卡），用于验证「非隐形」判定
- 高频餐饮与打车消费，用于验证不产生误报
- 每月信用卡还款，用于验证内部转账不计入支出
- 2 条退款/关闭交易和 1 条「不计收支」，用于验证排除逻辑

重新生成：

```bash
python examples/generate_demo.py
```

重新生成报告：

```bash
python -m billdetective examples/alipay_demo_2026H2.csv \
                           examples/wechat_demo_2026H2.csv \
                           --out examples/demo_report.html
```
