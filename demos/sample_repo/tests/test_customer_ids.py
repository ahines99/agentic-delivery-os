import copy

from customers import customer_ids, list_customers


def test_preserves_input_order():
    customers = [{"id": 3}, {"id": 1}, {"id": 2}]
    assert customer_ids(customers) == [3, 1, 2]


def test_preserves_duplicate_ids():
    customers = [{"id": 2}, {"id": 1}, {"id": 2}]
    assert customer_ids(customers) == [2, 1, 2]


def test_omits_dictionaries_without_id_key():
    customers = [{"id": 1}, {"status": "active"}, {"id": 5}, {}]
    assert customer_ids(customers) == [1, 5]


def test_retains_explicit_none_id():
    customers = [{"id": 1}, {"id": None}, {"status": "active"}, {"id": 2}]
    assert customer_ids(customers) == [1, None, 2]


def test_retains_other_falsy_id_values():
    customers = [{"id": 0}, {"id": ""}, {"id": False}]
    assert customer_ids(customers) == [0, "", False]


def test_empty_input_returns_empty_list():
    assert customer_ids([]) == []


def test_all_dictionaries_missing_id_returns_empty_list():
    customers = [{"status": "active"}, {}, {"name": "acme"}]
    assert customer_ids(customers) == []


def test_returns_a_new_list_object_each_call():
    customers = [{"id": 1}]
    first = customer_ids(customers)
    second = customer_ids(customers)
    assert first == second == [1]
    assert first is not second
    assert first is not customers


def test_does_not_mutate_input_list_or_dictionaries():
    customers = [{"id": 2, "status": "active"}, {"status": "inactive"}, {"id": None}]
    snapshot = copy.deepcopy(customers)
    dict_identities = [id(customer) for customer in customers]

    customer_ids(customers)

    assert customers == snapshot
    assert len(customers) == len(snapshot)
    assert [id(customer) for customer in customers] == dict_identities


def test_accepts_non_list_iterables_without_consuming_caller_list():
    customers = [{"id": 1}, {"id": 2}]
    assert customer_ids(tuple(customers)) == [1, 2]
    assert customers == [{"id": 1}, {"id": 2}]


def test_list_customers_still_copies_and_preserves_order():
    customers = [{"id": 2, "status": "active"}, {"id": 1, "status": "inactive"}]
    result = list_customers(customers)
    assert result == customers
    assert result is not customers
    assert all(a is b for a, b in zip(result, customers))
