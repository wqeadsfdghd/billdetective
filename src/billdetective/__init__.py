"""BillDetective — 本地账单侦探.

Finds the money quietly leaving your account: recurring subscriptions, price
creep, and the categories you would never guess.  Everything runs on your
machine; nothing is uploaded.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .analyze import Analysis, analyze
from .categorize import categorize, categorize_all
from .models import Direction, ParseResult, Transaction
from .parsers import ParseError, load_statement, load_statements
from .report import render_html, render_text
from .subscriptions import Subscription, detect_subscriptions

__all__ = [
    "__version__",
    "Analysis",
    "analyze",
    "categorize",
    "categorize_all",
    "Direction",
    "ParseResult",
    "Transaction",
    "ParseError",
    "load_statement",
    "load_statements",
    "render_html",
    "render_text",
    "Subscription",
    "detect_subscriptions",
]
