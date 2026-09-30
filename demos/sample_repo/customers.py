"""Small, dependency-free target for controlled delivery demonstrations."""


def list_customers(customers):
    """Return customers in their original order."""
    return list(customers)


def get_customer(customers, customer_id):
    """Return the first customer dictionary whose ``id`` equals ``customer_id``.

    The lookup uses ordinary Python equality, so ``1`` and ``"1"`` are distinct.
    Entries that are not dictionaries, or dictionaries without an ``id`` key,
    are ignored. The matching element is returned by reference (not a copy).
    Returns ``None`` when the input is empty or nothing matches. Neither the
    list nor the contained dictionaries are mutated.
    """
    for customer in customers:
        if not isinstance(customer, dict):
            continue
        if "id" not in customer:
            continue
        if customer["id"] == customer_id:
            return customer
    return None
