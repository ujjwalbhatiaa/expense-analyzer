"""Tests for expense_analyzer. Run with: pytest"""

from datetime import date

import pytest

from expense_analyzer import (
    Transaction,
    analyze,
    biggest_single_expenses,
    categorize,
    category_breakdown,
    format_report,
    monthly_summary,
    parse_csv,
    recurring_charges,
    top_merchants,
)


def txn(day, desc, amount, category="other"):
    return Transaction(date=date(2026, 7, day), description=desc,
                       amount=amount, category=category)


# --- categorization ---------------------------------------------------------

def test_categorize_groceries():
    assert categorize("COSTCO WHOLESALE #112", -184.22) == "groceries"
    assert categorize("Save-On-Foods #3310", -50.0) == "groceries"


def test_categorize_dining():
    assert categorize("TIM HORTONS #4821", -6.45) == "dining"
    assert categorize("Uber Eats", -31.24) == "dining"


def test_categorize_transport():
    assert categorize("UBER TRIP HELP", -18.30) == "transport"
    assert categorize("SHELL CANADA", -55.0) == "transport"


def test_categorize_income_by_sign():
    assert categorize("PAYROLL DEPOSIT ACME CORP", 3200.00) == "income"


def test_categorize_income_by_keyword():
    assert categorize("INTERAC E-TRANSFER IN", 50.0) == "income"


def test_categorize_unknown_is_other():
    assert categorize("SOME RANDOM VENDOR XYZ", -10.0) == "other"


def test_categorize_case_insensitive():
    assert categorize("netflix.com", -16.99) == "subscriptions"


# --- parsing ----------------------------------------------------------------

def test_parse_sample_csv(tmp_path=None):
    parsed = parse_csv("/tmp/expense-analyzer/sample_expenses.csv")
    assert parsed.skipped_rows == 0
    assert len(parsed.transactions) > 40
    # sorted by date
    dates = [t.date for t in parsed.transactions]
    assert dates == sorted(dates)
    # categories assigned
    cats = {t.category for t in parsed.transactions}
    assert "groceries" in cats and "income" in cats and "housing" in cats


def test_parse_skips_malformed_rows(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("date,description,amount\n"
                 "2026-07-01,GOOD STORE,-10.00\n"
                 "not-a-date,BAD STORE,-5.00\n"
                 "2026-07-02,ANOTHER BAD,not-a-number\n")
    parsed = parse_csv(str(p))
    assert len(parsed.transactions) == 1
    assert parsed.skipped_rows == 2


def test_parse_amount_formats(tmp_path):
    p = tmp_path / "amt.csv"
    p.write_text("date,description,amount\n"
                 "2026-07-01,A,\"$1,234.56\"\n"
                 "2026-07-02,B,(45.67)\n")
    parsed = parse_csv(str(p))
    assert parsed.transactions[0].amount == pytest.approx(1234.56)
    assert parsed.transactions[1].amount == pytest.approx(-45.67)


def test_parse_missing_columns_raises(tmp_path):
    p = tmp_path / "nocol.csv"
    p.write_text("foo,bar\n1,2\n")
    with pytest.raises(ValueError):
        parse_csv(str(p))


# --- analysis ---------------------------------------------------------------

def _sample():
    return [
        txn(1, "PAYROLL", 3000.0, "income"),
        txn(2, "COSTCO", -100.0, "groceries"),
        txn(3, "NETFLIX", -17.0, "subscriptions"),
        txn(4, "COSTCO", -50.0, "groceries"),
    ]


def test_monthly_summary():
    txns = _sample() + [Transaction(date=date(2026, 8, 1), description="RENT",
                                    amount=-900.0, category="housing")]
    ms = monthly_summary(txns)
    assert ms["2026-07"]["spending"] == pytest.approx(167.0)
    assert ms["2026-07"]["income"] == pytest.approx(3000.0)
    assert ms["2026-07"]["net"] == pytest.approx(2833.0)
    assert ms["2026-08"]["spending"] == pytest.approx(900.0)


def test_category_breakdown_shares():
    bd = category_breakdown(_sample())
    assert bd[0]["category"] == "groceries"
    assert bd[0]["total"] == pytest.approx(150.0)
    assert abs(sum(c["share"] for c in bd) - 100.0) < 0.2


def test_top_merchants_normalizes_store_numbers():
    txns = [txn(1, "COSTCO WHOLESALE #112", -100.0, "groceries"),
            txn(2, "COSTCO WHOLESALE #118", -60.0, "groceries"),
            txn(3, "NETFLIX", -17.0, "subscriptions")]
    top = top_merchants(txns, n=2)
    assert top[0]["merchant"] == "costco wholesale"
    assert top[0]["total"] == pytest.approx(160.0)


def test_recurring_charges_detected():
    txns = [
        Transaction(date=date(2026, 7, 5), description="NETFLIX.COM",
                    amount=-16.99, category="subscriptions"),
        Transaction(date=date(2026, 8, 5), description="NETFLIX.COM",
                    amount=-16.99, category="subscriptions"),
        Transaction(date=date(2026, 9, 5), description="NETFLIX.COM",
                    amount=-16.99, category="subscriptions"),
        txn(1, "ONE OFF STORE", -200.0, "shopping"),
    ]
    rec = recurring_charges(txns)
    assert len(rec) == 1
    assert rec[0]["merchant"] == "netflix.com"
    assert rec[0]["occurrences"] == 3


def test_recurring_ignores_varying_amounts():
    txns = [
        Transaction(date=date(2026, 7, 5), description="EPCOR",
                    amount=-78.44, category="utilities"),
        Transaction(date=date(2026, 8, 5), description="EPCOR",
                    amount=-81.02, category="utilities"),
    ]
    assert recurring_charges(txns) == []


def test_biggest_single_expenses():
    txns = [txn(1, "A", -10.0), txn(2, "B", -500.0), txn(3, "C", -50.0)]
    big = biggest_single_expenses(txns, n=2)
    assert [b["description"] for b in big] == ["B", "C"]


def test_analyze_empty():
    report = analyze([])
    assert report["transaction_count"] == 0
    assert report["monthly_summary"] == {}
    assert "EXPENSE REPORT" in format_report(report)


# --- budget alerts --------------------------------------------------------

from expense_analyzer import budget_alerts  # noqa: E402


def budget_txns():
    return [
        txn(3, "COSTCO WHOLESALE #112", -250.00, "groceries"),
        txn(10, "SAFEWAY #22", -180.00, "groceries"),
        txn(12, "TIM HORTONS #4821", -12.00, "dining"),
        txn(15, "NETFLIX.COM", -16.99, "subscriptions"),
        txn(20, "PAYROLL DEPOSIT", 3200.00, "income"),
    ]


def test_budget_alerts_flags_overrun():
    alerts = budget_alerts(budget_txns(), {"groceries": 400.0})
    assert len(alerts) == 1
    a = alerts[0]
    assert a["month"] == "2026-07"
    assert a["category"] == "groceries"
    assert a["spent"] == 430.00
    assert a["budget"] == 400.00
    assert a["over_by"] == 30.00
    assert a["over_pct"] == 7.5


def test_budget_alerts_within_budget_is_silent():
    assert budget_alerts(budget_txns(), {"groceries": 500.0}) == []


def test_budget_alerts_ignores_unbudgeted_categories():
    # dining and subscriptions have no budget entries: never flagged
    alerts = budget_alerts(budget_txns(), {"dining": 1000.0})
    assert alerts == []


def test_budget_alerts_ignores_income():
    alerts = budget_alerts(budget_txns(), {"income": 100.0})
    assert alerts == []


def test_budget_alerts_sorted_by_over_by():
    txns = budget_txns() + [txn(25, "STARBUCKS #7", -60.00, "dining")]
    alerts = budget_alerts(txns, {"groceries": 400.0, "dining": 50.0})
    assert [a["category"] for a in alerts] == ["groceries", "dining"]
    assert alerts[0]["over_by"] == 30.00
    assert alerts[1]["over_by"] == 22.00


def test_analyze_includes_budget_alerts():
    report = analyze(budget_txns(), budgets={"groceries": 400.0})
    assert len(report["budget_alerts"]) == 1
    assert report["budgets_set"] is True


def test_analyze_no_budgets_empty_alerts():
    report = analyze(budget_txns())
    assert report["budget_alerts"] == []
    assert report["budgets_set"] is False
    assert "(no budgets set)" in format_report(report)


def test_format_report_shows_alert_line():
    report = analyze(budget_txns(), budgets={"groceries": 400.0})
    text = format_report(report)
    assert "== Budget alerts ==" in text
    assert "groceries" in text
    assert "over by $30.00" in text


def test_format_report_all_within_budget():
    report = analyze(budget_txns(), budgets={"groceries": 900.0})
    assert "(all categories within budget)" in format_report(report)
