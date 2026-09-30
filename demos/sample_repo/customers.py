"""Small, dependency-free target for controlled delivery demonstrations."""


def list_customers(customers):
    """Return customers in their original order."""
    return list(customers)


def customer_ids(customers):
    """Return a new list of ``id`` values from ``customers`` in input order.

    Duplicate ids are preserved. Customers that do not contain an ``id`` key
    are omitted, while an explicitly present ``id`` of ``None`` contributes
    ``None`` to the result. The input list and its dictionaries are never
    modified.
    """
    return [customer["id"] for customer in customers if "id" in customer]
