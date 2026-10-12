#!/usr/bin/env python3
"""Command-line interface for expense_analyzer.

Thin wrapper around ``expense_analyzer.main`` (the single-module CLI).

Usage:
    python cli.py expenses.csv
    python cli.py expenses.csv --json
    python cli.py expenses.csv --top 10
    python cli.py expenses.csv --budgets budgets.json
"""

from __future__ import annotations

import sys

from expense_analyzer import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
