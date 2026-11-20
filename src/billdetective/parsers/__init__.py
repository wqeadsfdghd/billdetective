"""Statement parsing entry points."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..models import ParseResult
from .base import ParseError, load_generic, read_text_auto
from .formats import PARSERS, parse_file

__all__ = ["ParseError", "load_statement", "load_statements", "read_text_auto", "parse_file"]


def load_statement(path: str | Path) -> ParseResult:
    """Parse a single statement file, auto-detecting its format."""
    return parse_file(path)


def load_statements(paths: Iterable[str | Path]) -> ParseResult:
    """Parse and merge several statements into one result.

    Merging matters in practice: people pay with both Alipay and WeChat, and a
    subscription may be billed on either.  Analysing them separately hides the
    very thing this tool is looking for.
    """
    merged = ParseResult(source_format="merged")
    seen: set[tuple] = set()
    for path in paths:
        part = parse_file(path)
        merged.source_format = "merged" if merged.source_format != "merged" else merged.source_format
        for transaction in part.transactions:
            # Cross-file dedupe: same timestamp, amount and counterparty is the
            # same event exported twice, not two separate payments.
            key = (
                transaction.occurred_at,
                transaction.amount,
                transaction.direction,
                transaction.counterparty,
                transaction.description,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.transactions.append(transaction)
        merged.warnings.extend(part.warnings)
        merged.rows_total += part.rows_total
        merged.rows_skipped += part.rows_skipped
    return merged
