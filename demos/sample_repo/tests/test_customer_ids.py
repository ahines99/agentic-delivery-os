import copy

from customers import customer_ids, list_customers


def test_preserves_input_order_and_duplicate_ids():
    customers = [{"id": 2}, {"id": 1}, {"id": 2}]
    assert customer_ids(customers) == [2, 1, 2]


def test_preserves_order_with_extra_keys_and_mixed_id_types():
    customers = [
        {"id": "b", "status": "active"},
        {"id": 0, "status": "inactive"},
        {"id": "", "status": "active"},
        {"id": False},
    ]
    assert customer_ids(customers) == ["b", 0, "", False]


def test_omits_dicts_without_id_but_keeps_explicit_none():
    customers = [{"id": 1}, {"status": "active"}, {"id": None}, {"name": "no id"}]
    assert customer_ids(customers) == [1, None]


def test_returns_empty_list_for_empty_input():
    assert customer_ids([]) == []


def test_returns_empty_list_when_every_dict_lacks_id():
    customers = [{"status": "active"}, {"name": "x"}, {}]
    assert customer_ids(customers) == []


def test_does_not_mutate_input_list_or_dicts():
    customers = [{"id": 2, "status": "active"}, {"status": "inactive"}, {"id": None}]
    before = copy.deepcopy(customers)

    result = customer_ids(customers)

    assert result == [2, None]
    assert customers == before
    for original, current in zip(before, customers, strict=True):
        assert current == original
    assert result is not customers


def test_result_is_new_list_each_call():
    customers = [{"id": 1}]
    first = customer_ids(customers)
    second = customer_ids(customers)
    assert first == second == [1]
    assert first is not second


def test_accepts_non_list_iterable_of_dicts():
    customers = ({"id": 3}, {"status": "active"}, {"id": 3})
    assert customer_ids(customers) == [3, 3]


def test_list_customers_behavior_is_preserved():
    customers = [{"id": 2, "status": "active"}, {"id": 1, "status": "inactive"}]
    before = copy.deepcopy(customers)

    result = list_customers(customers)

    assert result == customers
    assert result is not customers
    assert customers == before
