import copy

from customers import list_customers, sort_customers


def test_sorts_by_ascending_id():
    customers = [{"id": 3}, {"id": 1}, {"id": 2}]

    assert [customer["id"] for customer in sort_customers(customers)] == [1, 2, 3]


def test_sorts_negative_and_float_ids_ascending():
    customers = [{"id": 2.5}, {"id": -1}, {"id": 0}, {"id": 2}]

    assert [customer["id"] for customer in sort_customers(customers)] == [-1, 0, 2, 2.5]


def test_equal_ids_keep_relative_input_order():
    first = {"id": 1, "name": "first"}
    second = {"id": 1, "name": "second"}
    third = {"id": 1, "name": "third"}
    customers = [{"id": 2, "name": "later"}, first, second, third]

    result = sort_customers(customers)

    assert [customer["name"] for customer in result] == ["first", "second", "third", "later"]
    assert result[0] is first
    assert result[1] is second
    assert result[2] is third


def test_empty_input_returns_empty_list():
    customers = []

    result = sort_customers(customers)

    assert result == []
    assert result is not customers


def test_single_customer_returns_new_list_with_same_dict():
    only = {"id": 7}
    customers = [only]

    result = sort_customers(customers)

    assert result == [only]
    assert result is not customers
    assert result[0] is only


def test_does_not_mutate_input_list_or_dictionaries():
    customers = [{"id": 3, "status": "active"}, {"id": 1, "status": "inactive"}]
    expected_snapshot = copy.deepcopy(customers)
    originals = list(customers)

    result = sort_customers(customers)

    assert customers == expected_snapshot
    assert [id(customer) for customer in customers] == [id(customer) for customer in originals]
    assert result is not customers
    assert sorted(id(customer) for customer in result) == sorted(
        id(customer) for customer in originals
    )


def test_sorting_result_is_independent_of_input_list():
    customers = [{"id": 2}, {"id": 1}]

    result = sort_customers(customers)
    result.append({"id": 99})

    assert len(customers) == 2


def test_list_customers_still_preserves_order_and_does_not_mutate_input():
    customers = [{"id": 5, "status": "active"}, {"id": 2, "status": "inactive"}]
    expected_snapshot = copy.deepcopy(customers)

    result = list_customers(customers)

    assert result == expected_snapshot
    assert result is not customers
    assert customers == expected_snapshot
