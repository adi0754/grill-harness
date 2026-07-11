from src.checkout import retry_order, submit_order


def test_checkout_paths():
    assert submit_order("A") == "submitted:A"
    assert retry_order("A") == "submitted:A"
