"""Vendor-specific statement parsers.

Each parser only contributes *detection* — the actual row handling is shared,
because after normalisation Alipay and WeChat exports differ mainly in the
preamble text and a couple of header spellings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..models import ParseResult
from .base import (
    ColumnMap,
    ParseError,
    build_transactions,
    find_header_row,
    read_text_auto,
    split_rows,
)

__all__ = ["AlipayParser", "WechatParser", "GenericParser", "PARSERS", "parse_file"]


class BaseParser:
    """Contract for a vendor parser."""

    name = "base"
    display_name = "未知格式"

    def detect(self, text: str, rows: Sequence[Sequence[str]], columns: ColumnMap | None) -> bool:
        raise NotImplementedError

    def parse(self, path: str | Path) -> ParseResult:
        text, encoding = read_text_auto(path)
        rows = split_rows(text)
        columns = find_header_row(rows)
        if columns is None:
            raise ParseError(f"{Path(path).name}: 找不到账单表头行")

        result = ParseResult(source_format=self.name)
        build_transactions(
            rows,
            columns,
            source=self.name,
            source_file=Path(path).name,
            result=result,
        )
        result.warnings.append(f"{self.display_name}解析成功（编码 {encoding}，{len(result.transactions)} 条）")
        return result


class AlipayParser(BaseParser):
    name = "alipay"
    display_name = "支付宝账单"

    def detect(self, text: str, rows: Sequence[Sequence[str]], columns: ColumnMap | None) -> bool:
        head = "\n".join(",".join(row) for row in rows[:6])
        if "支付宝" in head:
            return True
        if columns is not None and "商家订单号" in columns.headers:
            return True
        if columns is not None and "收付款方式" in "".join(columns.headers):
            return True
        return False


class WechatParser(BaseParser):
    name = "wechat"
    display_name = "微信支付账单"

    def detect(self, text: str, rows: Sequence[Sequence[str]], columns: ColumnMap | None) -> bool:
        head = "\n".join(",".join(row) for row in rows[:20])
        if "微信支付" in head or "微信昵称" in head:
            return True
        if columns is not None and "商户单号" in columns.headers:
            return True
        return False


class GenericParser(BaseParser):
    name = "generic"
    display_name = "通用 CSV 账单"

    def detect(self, text: str, rows: Sequence[Sequence[str]], columns: ColumnMap | None) -> bool:
        # Always matches: it is the fallback.
        return columns is not None


#: Order matters — specific formats are probed before the fallback.
PARSERS: tuple[type[BaseParser], ...] = (AlipayParser, WechatParser, GenericParser)


def parse_file(path: str | Path) -> ParseResult:
    """Detect the statement format and parse it."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    text, _ = read_text_auto(path)
    rows = split_rows(text)
    columns = find_header_row(rows)

    for parser_cls in PARSERS:
        parser = parser_cls()
        if parser.detect(text, rows, columns):
            if columns is None:
                raise ParseError(f"{path.name}: 无法定位表头，可能不是 CSV 账单")
            return parser.parse(path)

    raise ParseError(f"{path.name}: 未识别的账单格式")
