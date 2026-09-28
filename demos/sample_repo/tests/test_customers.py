from customers import list_customers


def test_existing_list_preserves_order_and_does_not_mutate_input():
    customers = [{"id": 2, "status": "active"}, {"id": 1, "status": "inactive"}]
    assert list_customers(customers) == customers
    assert list_customers(customers) is not customers
