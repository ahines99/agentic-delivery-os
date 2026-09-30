"""Small, dependency-free target for controlled delivery demonstrations."""


def list_customers(customers):
    """Return customers in their original order."""
    return list(customers)


def customer_ids(customers):
    """Return a new list of ``id`` values from ``customers`` in input order.

    Dictionaries that do not contain an ``id`` key are skipped. A key that is
    present with a value of ``None`` is kept, so membership is tested rather
    than truthiness or a ``get`` default. Neither the input sequence nor the
    contained dictionaries are modified.
    """
    ids = []
    for customer in customers:
        if "id" in customer:
            ids.append(customer["id"])
    return ids
