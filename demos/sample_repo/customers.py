"""Small, dependency-free target for controlled delivery demonstrations."""


def list_customers(customers):
    """Return customers in their original order."""
    return list(customers)


def customer_ids(customers):
    """Return the ``id`` values of ``customers`` as a new list, in input order.

    Duplicate ids are preserved. Dictionaries without an ``id`` key are omitted,
    while an explicitly present ``id`` of ``None`` contributes ``None``. The
    input list and its dictionaries are never modified.
    """
    return [customer["id"] for customer in customers if "id" in customer]
