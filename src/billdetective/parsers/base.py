"""Shared plumbing for statement parsers.

Chinese payment exports are hostile to naive CSV readers:

* Alipay writes GBK, WeChat writes UTF-8 with a BOM.
* Both prepend a dozen lines of human-readable preamble *before* the real header.
* Column names drift between versions (``金额`` / ``金额(元)`` / ``交易金额``).
* Amounts arrive decorated: ``"¥1,234.50"``.

Rather than hard-coding offsets, every parser here *discovers* the header row
and *fuzzily maps* columns onto internal field names.  That keeps the tool
working on exports it has never seen.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from ..models import (
    Direction,
    ParseResult,
    Transaction,
    normalize_direction,
    parse_amount,
    parse_datetime,
)

__all__ = [
    "read_text_auto",
    "ColumnMap",
    "split_rows",
    "find_header_row",
    "build_transactions",
    "ParseError",
]

#: Encodings tried in order.  ``gb18030`` decodes almost anything, so it must
#: come last or it would mask genuine UTF-8 files.
ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")

#: How far into the file the real header may live.
HEADER_SCAN_LIMIT = 40

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "time": (
        "交易时间", "交易创建时间", "付款时间", "创建时间", "交易日期",
        "记账时间", "时间", "日期",
    ),
    "direction": (
        "收支", "收/支", "收支类型", "资金流向", "借贷标志", "借贷",
        "收付标志", "方向",
    ),
    "amount": (
        "金额元", "交易金额元", "金额", "交易金额", "发生额", "金额元",
        "交易额", "支出金额", "人民币金额",
    ),
    "counterparty": (
        "交易对方", "对方名称", "商户名称", "交易对手", "收款方",
        "付款方", "对方", "商户",
    ),
    "description": (
        "商品说明", "商品名称", "交易说明", "商品", "摘要", "用途", "备注说明",
    ),
    "category_raw": (
        "交易分类", "交易类型", "分类", "业务类型", "交易场景",
    ),
    "method": (
        "收付款方式", "收/付款方式", "支付方式", "付款方式", "资金渠道", "渠道",
    ),
    "status": (
        "交易状态", "当前状态", "订单状态", "状态",
    ),
    "order_id": (
        "交易订单号", "交易单号", "订单号", "流水号", "交易号",
    ),
}

_BRACKETED = re.compile(r"[\(（][^\)）]*[\)）]")
_NOISE = re.compile(r"[\s\-_/\\:：·|]+")


class ParseError(Exception):
    """Raised when a file cannot be understood as a bill at all."""


def read_text_auto(path: str | Path) -> tuple[str, str]:
    """Decode a statement file, returning ``(text, encoding_used)``."""
    data = Path(path).read_bytes()
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    # Never fail outright: mojibake beats a crash for the end user.
    return data.decode("utf-8", errors="replace"), "utf-8/replace"


def split_rows(text: str) -> list[list[str]]:
    """Parse CSV text into raw rows, tolerating ragged line lengths."""
    # Strip the BOM defensively even when the encoding name lies.
    text = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text, newline=""))
    rows: list[list[str]] = []
    for row in reader:
        rows.append([cell.strip() for cell in row])
    return rows


def _normalize_cell(text: str) -> str:
    """Reduce a header cell to a comparable key.

    ``"金额(元)"`` -> ``"金额"``; ``"收 / 支"`` -> ``"收支"``.
    """
    cleaned = _BRACKETED.sub("", str(text))
    cleaned = _NOISE.sub("", cleaned)
    return cleaned.strip()


@dataclass(slots=True)
class ColumnMap:
    """Resolved column indices for one statement."""

    indices: dict[str, int] = field(default_factory=dict)
    header_row: int = -1
    headers: Sequence[str] = ()

    def has(self, name: str) -> bool:
        return name in self.indices

    def get(self, row: Sequence[str], name: str, default: str = "") -> str:
        idx = self.indices.get(name)
        if idx is None or idx >= len(row):
            return default
        return row[idx]

    @property
    def score(self) -> int:
        """How many recognised fields we managed to bind."""
        return len(self.indices)

    def missing_critical(self) -> list[str]:
        return [f for f in ("time", "amount") if f not in self.indices]


def resolve_columns(headers: Sequence[str]) -> ColumnMap:
    """Bind detected header cells onto internal field names.

    Two passes: exact normalised match first (so ``交易类型`` cannot steal
    ``交易时间``), then substring match, longest alias first.
    """
    normalized = [_normalize_cell(h) for h in headers]
    indices: dict[str, int] = {}
    used: set[int] = set()

    # Pass 1 — exact matches.
    for name, aliases in FIELD_ALIASES.items():
        normalized_aliases = {_normalize_cell(a) for a in aliases}
        for idx, cell in enumerate(normalized):
            if idx in used or not cell:
                continue
            if cell in normalized_aliases:
                indices[name] = idx
                used.add(idx)
                break

    # Pass 2 — substring matches for anything still unbound.
    ordered = sorted(
        ((name, _normalize_cell(alias)) for name, aliases in FIELD_ALIASES.items() for alias in aliases),
        key=lambda pair: len(pair[1]),
        reverse=True,
    )
    for name, alias in ordered:
        if name in indices or not alias:
            continue
        for idx, cell in enumerate(normalized):
            if idx in used or not cell:
                continue
            if alias in cell:
                indices[name] = idx
                used.add(idx)
                break

    return ColumnMap(indices=indices, headers=tuple(headers))


def find_header_row(rows: Sequence[Sequence[str]]) -> ColumnMap | None:
    """Return the best-scoring header candidate within the scan window."""
    best: ColumnMap | None = None
    for idx, row in enumerate(rows[:HEADER_SCAN_LIMIT]):
        if len(row) < 3:
            continue
        candidate = resolve_columns(row)
        if candidate.missing_critical():
            continue
        if best is None or candidate.score > best.score:
            candidate.header_row = idx
            best = candidate
    return best


def _direction_from_amount_text(row: Sequence[str], amount_idx: int | None) -> Direction:
    """Fall back to the sign of the amount when there is no 收/支 column."""
    if amount_idx is None or amount_idx >= len(row):
        return Direction.UNKNOWN
    text = str(row[amount_idx])
    if text.strip().startswith("-"):
        return Direction.EXPENSE
    return Direction.UNKNOWN


def build_transactions(
    rows: Sequence[Sequence[str]],
    columns: ColumnMap,
    *,
    source: str,
    source_file: str,
    result: ParseResult,
) -> None:
    """Turn raw rows into :class:`Transaction` objects, recording skips."""
    data_rows = rows[columns.header_row + 1 :]
    for row in data_rows:
        if not any(cell.strip() for cell in row):
            continue

        result.rows_total += 1

        when = parse_datetime(columns.get(row, "time"))
        amount = parse_amount(columns.get(row, "amount"))
        if when is None or amount is None:
            result.rows_skipped += 1
            continue

        raw_direction = columns.get(row, "direction")
        direction = normalize_direction(raw_direction)
        if direction is Direction.UNKNOWN:
            direction = _direction_from_amount_text(row, columns.indices.get("amount"))

        transaction = Transaction(
            occurred_at=when,
            amount=amount,
            direction=direction,
            counterparty=columns.get(row, "counterparty").strip(),
            description=columns.get(row, "description").strip(),
            category_raw=columns.get(row, "category_raw").strip(),
            method=columns.get(row, "method").strip(),
            status=columns.get(row, "status").strip(),
            source=source,
            source_file=source_file,
            raw={"raw_direction": raw_direction},
        )
        result.transactions.append(transaction)

    if result.rows_skipped:
        result.warnings.append(
            f"跳过 {result.rows_skipped} 行无法解析的记录（缺少时间或金额）"
        )


def load_generic(path: str | Path, *, source: str = "csv") -> ParseResult:
    """Best-effort parser used when no vendor format matches."""
    text, encoding = read_text_auto(path)
    rows = split_rows(text)
    columns = find_header_row(rows)
    if columns is None:
        raise ParseError(
            "无法识别表头：文件里没有同时包含「时间」和「金额」的列。"
            "请确认导出的是 CSV 账单，而不是 PDF 或截图。"
        )

    result = ParseResult(source_format=source)
    build_transactions(
        rows,
        columns,
        source=source,
        source_file=Path(path).name,
        result=result,
    )
    result.warnings.insert(0, f"使用通用解析器（编码 {encoding}）")
    return result
