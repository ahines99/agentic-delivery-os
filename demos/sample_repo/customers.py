"""Small, dependency-free target for controlled delivery demonstrations."""


def list_customers(customers, status=None):
    """Return customers in their original order, optionally filtered by status.

    Args:
        customers: An iterable of dict-like customer records.
        status: Optional status to filter on. When ``None`` (the default),
            every customer is returned. When an explicit value is given, only
            customers whose ``"status"`` field is exactly equal (``==``) to it
            are returned; customers missing a ``"status"`` key never match.

    Returns:
        A new list preserving the input order. The input list and the customer
        dictionaries are never mutated; the returned list references the same
        customer objects.
    """
    if status is None:
        return list(customers)
    return [customer for customer in customers if customer.get("status") == status]
