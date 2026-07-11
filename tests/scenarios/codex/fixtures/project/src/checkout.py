def submit_order(order_id: str) -> str:
    """Submit an order through the synchronous checkout path."""
    return f"submitted:{order_id}"


def retry_order(order_id: str) -> str:
    """Retry an order from the asynchronous worker."""
    return submit_order(order_id)
