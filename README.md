# expense-analyzer

A tiny, dependency-free personal expense analyzer in pure Python. Point it at a
CSV of bank or credit-card transactions and get monthly summaries, spending by
category, top merchants, recurring-charge detection, and biggest expenses.

## Usage

```bash
python expense_analyzer.py sample_expenses.csv
python expense_analyzer.py expenses.csv --json
python expense_analyzer.py expenses.csv --top 5
```

The CSV needs a header row with `date`, `description`, and `amount` columns
(names are matched flexibly). Amounts may include `$` and commas; `(12.34)`
parenthesized negatives are understood. Negative amounts are spending,
positive amounts are income.

## Example output

```
EXPENSE REPORT
Transactions: 55  Range: 2026-07-01 to 2026-09-18

== Monthly summary ==
2026-07: spent $1511.04 | income $6400.00 | net $+4888.96
...

== Spending by category ==
housing         $  2850.00 ( 38.2%) ###################
groceries       $   806.85 ( 10.8%) #####

== Recurring charges ==
- netflix.com: $16.99/mo (3 months)
- spotify: $10.99/mo (3 months)
```

## How it works

- **Auto-categorization**: keyword rules map merchant descriptions to 13
  categories (groceries, dining, transport, utilities, subscriptions, …).
  Positive amounts are always income.
- **Recurring charges**: same normalized merchant + same amount across 2+
  months → flagged as a likely subscription or bill.
- **Merchant normalization**: store numbers and extra whitespace are stripped
  so `COSTCO WHOLESALE #112` and `#118` group together.

## Tests

```bash
pytest
```

18 tests covering parsing (malformed rows, amount formats, date formats),
categorization, monthly/category summaries, merchant normalization, recurring
detection, and edge cases.
