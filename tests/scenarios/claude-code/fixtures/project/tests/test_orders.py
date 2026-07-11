from decimal import Decimal

from src.orders import order_total


def test_order_total_adds_prices() -> None:
    assert order_total([Decimal("2.50"), Decimal("3.00")]) == Decimal("5.50")


def test_empty_order_total_is_zero() -> None:
    assert order_total([]) == Decimal("0")
