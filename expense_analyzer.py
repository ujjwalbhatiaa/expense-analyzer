#!/usr/bin/env python3
"""expense-analyzer: a tiny, dependency-free personal expense analyzer.

Reads transactions from a CSV file, auto-categorizes each one, and reports
monthly summaries, category breakdowns, top merchants, and recurring charges.
Pure standard library.

CSV format (header row required; column names are flexible):
    date,description,amount
    2026-07-03,COSTCO WHOLESALE #112,-184.22

Amounts may include currency symbols and thousands separators.
Negative amounts are spending, positive amounts are income.

Usage:
    python expense_analyzer.py expenses.csv
    python expense_analyzer.py expenses.csv --json
    python expense_analyzer.py expenses.csv --top 10
    python expense_analyzer.py expenses.csv --budgets budgets.json

budgets.json maps category -> monthly spending cap, e.g.:
    {"groceries": 400.0, "dining": 150.0}
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    date: date
    description: str
    amount: float  # negative = spending, positive = income
    category: str = "other"


@dataclass
class ParseResult:
    transactions: list[Transaction] = field(default_factory=list)
    skipped_rows: int = 0


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------

# Ordered (category, keywords). First match wins; checked against the
# lowercased description. Keep the lists lowercase.
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("income", ("payroll", "salary", "paycheque", "paycheck", "employer deposit")),
    ("housing", ("rent", "landlord", "property management", "mortgage")),
    ("groceries", (
        "costco", "safeway", "sobeys", "save-on", "save on", "superstore",
        "loblaws", "no frills", "nofrills", "freshco", "whole foods",
        "t&t", "tt supermarket", "walmart supercentre",
    )),
    ("dining", (
        "mcdonald", "tim hortons", "starbucks", "subway", "pizza", "sushi",
        "uber eats", "ubereats", "doordash", "skip the dishes", "skipthedishes",
        "restaurant", "cafe", "coffee", "burger", "kfc", "a&w", "taco",
        "ramen", "pho ", "bistro", "grill house", "donut",
    )),
    ("transport", (
        "uber", "lyft", "esso", "shell", "petro-canada", "petro canada",
        "chevron", "husky", "parking", "impark", "ets ", "transit",
        "presto", "compass card", "arc card", "taxi", "car share",
    )),
    ("utilities", (
        "epcor", "atco", "enmax", "telus", "shaw", "rogers", "bell ",
        "koodo", "fido", "hydro", "water bill", "power bill",
    )),
    ("subscriptions", (
        "netflix", "spotify", "disney+", "disney plus", "prime video",
        "youtube premium", "icloud", "google one", "gym membership",
        "audible",
    )),
    ("entertainment", (
        "cineplex", "landmark cinema", "steam", "playstation", "xbox",
        "nintendo", "concert", "theatre", "theater", "escape room",
    )),
    ("shopping", (
        "amazon", "best buy", "ikea", "canadian tire", "uniqlo", "h&m",
        "zara", "sport chek", "sportchek", "mark's", "marks.com",
        "dollarama", "winners", "homesense",
    )),
    ("health", (
        "shoppers drug", "pharmacy", "rexall", "dentist", "dental",
        "optometry", "clinic", "goodlife", "planet fitness",
    )),
    ("travel", (
        "air canada", "westjet", "porter airlines", "hotel", "airbnb",
        "booking.com", "expedia", "flair airlines",
    )),
    ("education", (
        "ualberta", "university of alberta", "tuition", "textbook",
        "udemy", "coursera", "skillshare",
    )),
]

INCOME_KEYWORDS = ("payroll", "salary", "deposit", "refund", "e-transfer in",
                   "etransfer in", "interest", "cashback")


def categorize(description: str, amount: float) -> str:
    """Assign a category from the description and amount sign."""
    desc = description.lower()
    if amount > 0 or any(k in desc for k in INCOME_KEYWORDS):
        return "income"
    for category, keywords in CATEGORY_KEYWORDS:
        if category == "income":
            continue
        if any(k in desc for k in keywords):
            return category
    return "other"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d",
                 "%d-%m-%Y", "%m-%d-%Y", "%b %d, %Y", "%d %b %Y")


def _parse_date(raw: str) -> date:
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            from datetime import datetime
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {raw!r}")


def _parse_amount(raw: str) -> float:
    cleaned = re.sub(r"[^\d.\-+()]", "", raw.strip())
    if cleaned.startswith("(") and cleaned.endswith(")"):  # (12.34) = -12.34
        cleaned = "-" + cleaned[1:-1]
    return float(cleaned)


def _find_column(fieldnames: list[str], *candidates: str) -> str | None:
    lowered = {f.lower().strip(): f for f in fieldnames}
    for cand in candidates:
        if cand in lowered:
            return lowered[cand]
    return None


def parse_csv(path: str) -> ParseResult:
    """Parse a CSV of transactions. Returns transactions + skipped row count."""
    result = ParseResult()
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return result
        date_col = _find_column(reader.fieldnames, "date", "transaction date", "posted")
        desc_col = _find_column(reader.fieldnames, "description", "merchant",
                                "details", "narrative")
        amt_col = _find_column(reader.fieldnames, "amount", "value", "debit",
                               "total")
        if not (date_col and desc_col and amt_col):
            raise ValueError(
                f"CSV must have date/description/amount columns; found: "
                f"{reader.fieldnames}")
        for row in reader:
            try:
                txn_date = _parse_date(row[date_col] or "")
                amount = _parse_amount(row[amt_col] or "")
                desc = (row[desc_col] or "").strip()
                if not desc:
                    raise ValueError("empty description")
            except (ValueError, TypeError):
                result.skipped_rows += 1
                continue
            result.transactions.append(Transaction(
                date=txn_date,
                description=desc,
                amount=amount,
                category=categorize(desc, amount),
            ))
    result.transactions.sort(key=lambda t: t.date)
    return result


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _normalize_merchant(description: str) -> str:
    """Collapse a raw description to a merchant-ish name for grouping."""
    name = description.lower()
    name = re.sub(r"#\d+|\b\d{3,}\b", "", name)      # store numbers
    name = re.sub(r"\s+", " ", name).strip(" -")
    return name


def monthly_summary(transactions: Iterable[Transaction]) -> dict[str, dict]:
    """Per-month totals: spending, income, net, and per-category spending."""
    months: dict[str, dict] = {}
    for t in transactions:
        key = t.date.strftime("%Y-%m")
        m = months.setdefault(key, {"spending": 0.0, "income": 0.0,
                                   "by_category": defaultdict(float)})
        if t.amount < 0:
            m["spending"] += -t.amount
            m["by_category"][t.category] += -t.amount
        else:
            m["income"] += t.amount
    for m in months.values():
        m["net"] = round(m["income"] - m["spending"], 2)
        m["spending"] = round(m["spending"], 2)
        m["income"] = round(m["income"], 2)
        m["by_category"] = dict(sorted(m["by_category"].items(),
                                       key=lambda kv: -kv[1]))
    return dict(sorted(months.items()))


def category_breakdown(transactions: Iterable[Transaction]) -> list[dict]:
    """Total spending per category with share of all spending."""
    totals: dict[str, float] = defaultdict(float)
    for t in transactions:
        if t.amount < 0:
            totals[t.category] += -t.amount
    grand = sum(totals.values()) or 1.0
    return [
        {"category": c, "total": round(v, 2),
         "share": round(v / grand * 100, 1)}
        for c, v in sorted(totals.items(), key=lambda kv: -kv[1])
    ]


def top_merchants(transactions: Iterable[Transaction], n: int = 10) -> list[dict]:
    """Highest-spend merchants by normalized name."""
    totals: dict[str, float] = defaultdict(float)
    for t in transactions:
        if t.amount < 0:
            totals[_normalize_merchant(t.description)] += -t.amount
    return [
        {"merchant": m, "total": round(v, 2)}
        for m, v in sorted(totals.items(), key=lambda kv: -kv[1])[:n]
    ]


def recurring_charges(transactions: Iterable[Transaction],
                      min_months: int = 2) -> list[dict]:
    """Charges from the same merchant for the same amount across months.

    A likely subscription/bill: same normalized merchant and same rounded
    amount appearing in at least `min_months` distinct months.
    """
    seen: dict[tuple[str, float], set[str]] = defaultdict(set)
    for t in transactions:
        if t.amount < 0:
            key = (_normalize_merchant(t.description), round(t.amount, 2))
            seen[key].add(t.date.strftime("%Y-%m"))
    out = [
        {"merchant": merchant, "amount": -amount,
         "months": sorted(months), "occurrences": len(months)}
        for (merchant, amount), months in seen.items()
        if len(months) >= min_months
    ]
    return sorted(out, key=lambda r: -r["amount"])


def biggest_single_expenses(transactions: Iterable[Transaction],
                            n: int = 5) -> list[dict]:
    """Largest individual spending transactions."""
    spends = sorted((t for t in transactions if t.amount < 0),
                    key=lambda t: t.amount)
    return [
        {"date": t.date.isoformat(), "description": t.description,
         "amount": -t.amount, "category": t.category}
        for t in spends[:n]
    ]


def budget_alerts(transactions: Iterable[Transaction],
                  budgets: dict[str, float]) -> list[dict]:
    """Flag month/categories where spending exceeded the monthly budget.

    `budgets` maps category -> monthly spending cap. Only overruns are
    reported (spent > budget); categories without a budget entry are ignored.
    """
    spent: dict[tuple[str, str], float] = defaultdict(float)
    for t in transactions:
        if t.amount < 0:
            budget = budgets.get(t.category)
            if budget is not None and budget > 0:
                spent[(t.date.strftime("%Y-%m"), t.category)] += -t.amount
    alerts = [
        {"month": month, "category": category,
         "spent": round(total, 2), "budget": round(budgets[category], 2),
         "over_by": round(total - budgets[category], 2),
         "over_pct": round((total / budgets[category] - 1) * 100, 1)}
        for (month, category), total in spent.items()
        if total > budgets[category]
    ]
    return sorted(alerts, key=lambda a: (-a["over_by"], a["month"],
                                        a["category"]))


def analyze(transactions: list[Transaction], top_n: int = 10,
            budgets: dict[str, float] | None = None) -> dict:
    """Run the full analysis suite and return a JSON-serializable report."""
    return {
        "transaction_count": len(transactions),
        "date_range": (
            [transactions[0].date.isoformat(), transactions[-1].date.isoformat()]
            if transactions else [None, None]
        ),
        "monthly_summary": monthly_summary(transactions),
        "category_breakdown": category_breakdown(transactions),
        "top_merchants": top_merchants(transactions, top_n),
        "recurring_charges": recurring_charges(transactions),
        "biggest_single_expenses": biggest_single_expenses(transactions),
        "budget_alerts": budget_alerts(transactions, budgets) if budgets else [],
        "budgets_set": budgets is not None,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report(report: dict) -> str:
    """Render the analysis as a human-readable text report."""
    lines = []
    lines.append("EXPENSE REPORT")
    lines.append(f"Transactions: {report['transaction_count']}  "
                 f"Range: {report['date_range'][0]} to {report['date_range'][1]}")
    lines.append("")
    lines.append("== Monthly summary ==")
    for month, m in report["monthly_summary"].items():
        lines.append(f"{month}: spent ${m['spending']:.2f} | "
                     f"income ${m['income']:.2f} | net ${m['net']:+.2f}")
    lines.append("")
    lines.append("== Spending by category ==")
    for c in report["category_breakdown"]:
        bar = "#" * int(c["share"] // 2)
        lines.append(f"{c['category']:<15} ${c['total']:>9.2f} "
                     f"({c['share']:>5.1f}%) {bar}")
    lines.append("")
    lines.append("== Top merchants ==")
    for i, mch in enumerate(report["top_merchants"], 1):
        lines.append(f"{i:>2}. {mch['merchant']:<40} ${mch['total']:.2f}")
    lines.append("")
    lines.append("== Recurring charges ==")
    if report["recurring_charges"]:
        for r in report["recurring_charges"]:
            lines.append(f"- {r['merchant']}: ${r['amount']:.2f}/mo "
                         f"({r['occurrences']} months)")
    else:
        lines.append("(none detected)")
    lines.append("")
    lines.append("== Biggest single expenses ==")
    for e in report["biggest_single_expenses"]:
        lines.append(f"- {e['date']} {e['description'][:45]:<45} "
                     f"${e['amount']:.2f} [{e['category']}]")
    if report.get("budget_alerts") is not None and "budget_alerts" in report:
        lines.append("")
        lines.append("== Budget alerts ==")
        if report["budget_alerts"]:
            for a in report["budget_alerts"]:
                lines.append(f"- {a['month']} {a['category']:<15} "
                             f"spent ${a['spent']:.2f} of ${a['budget']:.2f} "
                             f"budget (over by ${a['over_by']:.2f}, "
                             f"+{a['over_pct']:.1f}%)")
        elif report.get("budgets_set"):
            lines.append("(all categories within budget)")
        else:
            lines.append("(no budgets set)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze a CSV of bank/credit-card transactions.")
    parser.add_argument("csv_file", help="CSV with date, description, amount columns")
    parser.add_argument("--json", action="store_true",
                        help="print the report as JSON instead of text")
    parser.add_argument("--top", type=int, default=10,
                        help="number of top merchants to show (default: 10)")
    parser.add_argument("--budgets",
                        help="JSON file mapping category -> monthly spending"
                             " cap; overruns are reported as budget alerts")
    args = parser.parse_args(argv)

    try:
        parsed = parse_csv(args.csv_file)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if parsed.skipped_rows:
        print(f"warning: skipped {parsed.skipped_rows} malformed row(s)",
              file=sys.stderr)

    budgets = None
    if args.budgets:
        try:
            with open(args.budgets, encoding="utf-8") as fh:
                budgets = {str(k): float(v) for k, v in json.load(fh).items()}
        except (OSError, ValueError, TypeError) as exc:
            print(f"error: cannot read budgets file: {exc}", file=sys.stderr)
            return 1

    report = analyze(parsed.transactions, top_n=args.top, budgets=budgets)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
