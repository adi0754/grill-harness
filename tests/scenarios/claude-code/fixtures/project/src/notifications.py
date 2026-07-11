def send_notification(event_name: str, payload: dict[str, object]) -> None:
    """Synchronous placeholder; retry and idempotency are not implemented."""
    if event_name != "order.created":
        raise ValueError(f"unsupported event: {event_name}")
