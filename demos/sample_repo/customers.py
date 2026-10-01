"""Small, dependency-free target for controlled delivery demonstrations."""


def list_customers(customers):
    """Return customers in their original order."""
    return list(customers)


def sort_customers(customers):
    """Return a new list of customers sorted by ascending numeric ``id``.

    The sort is stable, so customers sharing the same ``id`` keep their relative
    input order. Neither the input list nor the customer dictionaries are mutated.
    """
    return sorted(customers, key=lambda customer: customer["id"])
