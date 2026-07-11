from decimal import Decimal

from src.notifications import send_notification


def order_total(prices: list[Decimal]) -> Decimal | None:
    if not prices:
        return None
    return sum(prices, start=Decimal("0"))


def create_order(order_id: str, prices: list[Decimal]) -> dict[str, object]:
    order = {"id": order_id, "total": order_total(prices)}
    send_notification("order.created", order)
    return order
