#!/usr/bin/env python3
"""Command-line interface for expense_analyzer.

Usage:
    python cli.py analyze data/sample_transactions.csv
    python cli.py analyze mystatement.csv --rules my_rules.json --json out.json
    python cli.py analyze mystatement.csv --charts charts/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expense_analyzer.categorizer import categorize_all, load_rules
from expense_analyzer.parser import ParseError, parse_csv_file
from expense_analyzer.summary import (
    category_totals,
    month_over_month_change,
    summarize_by_month,
    top_merchants,
)


def _fmt_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def build_report(pairs, months, cat_totals, mom, merchants) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("EXPENSE ANALYZER REPORT")
    lines.append("=" * 60)
    lines.append(f"Transactions parsed: {len(pairs)}")
    lines.append("")

    lines.append("-- Monthly summary --")
    for key in sorted(months.keys()):
        m = months[key]
        change = mom.get(key)
        change_str = f"  ({change:+.1f}% vs prior month)" if change is not None else ""
        lines.append(
            f"  {key}: income {_fmt_money(m.total_income):>12}  "
            f"expenses {_fmt_money(-m.total_expenses):>12}  "
            f"net {_fmt_money(m.net):>12}{change_str}"
        )
    lines.append("")

    lines.append("-- Spending by category (all time) --")
    grand_total = sum(cat_totals.values()) or 1.0
    for category, total in cat_totals.items():
        pct = (total / grand_total) * 100
        lines.append(f"  {category:<24} {_fmt_money(-total):>12}  ({pct:5.1f}%)")
    lines.append("")

    lines.append(f"-- Top {len(merchants)} merchants by spend --")
    for desc, total, count in merchants:
        lines.append(f"  {desc:<30} {_fmt_money(-total):>12}  ({count} txns)")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a bank-statement CSV.")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Parse, categorize, and summarize a CSV.")
    analyze.add_argument("csv_path", help="Path to the transactions CSV.")
    analyze.add_argument("--rules", help="Optional JSON file of category -> [keywords] overrides.")
    analyze.add_argument("--json", dest="json_out", help="Write the summary as JSON to this path.")
    analyze.add_argument(
        "--charts", dest="charts_dir", help="Directory to write monthly_spend.png and category_breakdown.png"
    )
    analyze.add_argument("--top-n", type=int, default=5, help="Number of top merchants to show (default 5).")

    args = parser.parse_args(argv)

    if args.command == "analyze":
        try:
            transactions = parse_csv_file(args.csv_path)
        except ParseError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if not transactions:
            print("No transactions found in file.", file=sys.stderr)
            return 1

        rules = load_rules(args.rules)
        pairs = categorize_all(transactions, rules)
        months = summarize_by_month(pairs)
        cat_totals = category_totals(pairs)
        mom = month_over_month_change(months)
        merchants = top_merchants(pairs, n=args.top_n)

        print(build_report(pairs, months, cat_totals, mom, merchants))

        if args.json_out:
            payload = {
                "transaction_count": len(pairs),
                "months": {
                    k: {
                        "income": v.total_income,
                        "expenses": v.total_expenses,
                        "net": v.net,
                        "by_category": v.by_category,
                        "transaction_count": v.transaction_count,
                        "pct_change_vs_prior_month": mom.get(k),
                    }
                    for k, v in months.items()
                },
                "category_totals": cat_totals,
                "top_merchants": [
                    {"description": d, "total": t, "count": c} for d, t, c in merchants
                ],
            }
            json_path = Path(args.json_out)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(payload, indent=2))
            print(f"\nJSON summary written to {args.json_out}")

        if args.charts_dir:
            from expense_analyzer.charts import plot_category_breakdown, plot_monthly_spend

            out_dir = Path(args.charts_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            p1 = plot_monthly_spend(months, out_dir / "monthly_spend.png")
            p2 = plot_category_breakdown(cat_totals, out_dir / "category_breakdown.png")
            print(f"\nCharts written: {p1}, {p2}")

        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
