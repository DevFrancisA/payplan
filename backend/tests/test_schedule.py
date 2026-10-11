from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.money import to_money
from app.services.schedule import Frequency, ScheduleCalculator

D = Decimal
calc = ScheduleCalculator()
START = date(2026, 10, 1)


def schedule(principal="1200.00", count=4, apr="0", frequency=Frequency.BIWEEKLY, start=START):
    return calc.calculate(D(principal), count, D(apr), frequency, start)


def test_zero_apr_splits_evenly():
    s = schedule("1200.00", 4)
    assert [i.amount for i in s.installments] == [D("300.00")] * 4
    assert s.total_interest == D("0.00")
    assert s.total_cost == D("1200.00")


def test_zero_apr_remainder_cents_go_on_first_installment():
    s = schedule("100.00", 3)
    assert [i.amount for i in s.installments] == [D("33.34"), D("33.33"), D("33.33")]


@pytest.mark.parametrize(
    ("principal", "count", "apr", "frequency"),
    [
        ("999.99", 7, "0", Frequency.WEEKLY),
        ("1234.56", 12, "19.99", Frequency.MONTHLY),
        ("50.01", 6, "35.9", Frequency.BIWEEKLY),
        ("100000.00", 60, "7.5", Frequency.MONTHLY),
    ],
)
def test_schedule_reconciles_to_the_cent(principal, count, apr, frequency):
    s = schedule(principal, count, apr, frequency)
    assert sum(i.principal for i in s.installments) == D(principal)
    assert sum(i.amount for i in s.installments) == s.total_cost
    assert s.total_cost == D(principal) + s.total_interest
    for i in s.installments:
        assert i.amount == i.principal + i.interest
        assert i.amount.as_tuple().exponent == -2


def test_amortized_payment_matches_standard_formula():
    # $1,000 at 12% APR over 12 months: textbook payment is $88.85.
    s = schedule("1000.00", 12, "12", Frequency.MONTHLY)
    assert all(i.amount == D("88.85") for i in s.installments[:-1])
    assert s.installments[0].interest == D("10.00")
    assert s.installments[-1].amount == D("88.84")
    assert s.total_interest == D("66.19")


def test_interest_accrues_on_declining_balance():
    s = schedule("1000.00", 12, "12", Frequency.MONTHLY)
    interests = [i.interest for i in s.installments]
    assert interests == sorted(interests, reverse=True)
    assert interests[1] == to_money(D("921.15") * D("0.01"))


def test_remaining_balance_counts_down_to_zero():
    s = schedule("1000.00", 6, "24", Frequency.MONTHLY)
    expected = s.total_cost
    for i in s.installments:
        expected -= i.amount
        assert i.remaining_balance == expected
    assert s.installments[-1].remaining_balance == D("0.00")


def test_single_installment_is_paid_in_full():
    s = schedule("49.99", 1, "0")
    assert len(s.installments) == 1
    assert s.installments[0].amount == D("49.99")
    assert s.installments[0].due_date == START


def test_weekly_due_dates():
    s = schedule(count=4, frequency=Frequency.WEEKLY)
    assert [i.due_date for i in s.installments] == [START + timedelta(weeks=n) for n in range(4)]


def test_biweekly_due_dates():
    s = schedule(count=4, frequency=Frequency.BIWEEKLY)
    assert [i.due_date for i in s.installments] == [
        START + timedelta(weeks=2 * n) for n in range(4)
    ]


def test_monthly_due_dates_clamp_to_month_end_in_leap_year():
    s = schedule(count=4, frequency=Frequency.MONTHLY, start=date(2028, 1, 31))
    assert [i.due_date for i in s.installments] == [
        date(2028, 1, 31),
        date(2028, 2, 29),
        date(2028, 3, 31),
        date(2028, 4, 30),
    ]


def test_monthly_due_dates_roll_over_year_end():
    s = schedule(count=3, frequency=Frequency.MONTHLY, start=date(2026, 12, 31))
    assert [i.due_date for i in s.installments] == [
        date(2026, 12, 31),
        date(2027, 1, 31),
        date(2027, 2, 28),
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2.675", "2.68"), ("0.005", "0.01"), ("10.004", "10.00")],
)
def test_to_money_rounds_half_up(raw, expected):
    assert to_money(D(raw)) == D(expected)


def test_to_money_rejects_floats():
    with pytest.raises(TypeError):
        to_money(2.675)


@pytest.mark.parametrize(
    ("principal", "count", "apr"),
    [("0.50", 4, "0"), ("100.00", 0, "0"), ("100.00", 4, "-1"), ("100.005", 4, "0")],
)
def test_invalid_terms_are_rejected(principal, count, apr):
    with pytest.raises(ValueError):
        schedule(principal, count, apr)
