import copy

from customers import get_customer, list_customers


def test_accepts_integer_id_and_returns_match():
    customers = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert get_customer(customers, 2) == {"id": 2, "name": "b"}


def test_accepts_string_id_and_returns_match():
    customers = [{"id": "abc", "name": "a"}, {"id": "xyz", "name": "b"}]
    assert get_customer(customers, "xyz") == {"id": "xyz", "name": "b"}


def test_uses_ordinary_equality_so_int_and_str_ids_do_not_cross_match():
    customers = [{"id": "1", "name": "string-one"}, {"id": 1, "name": "int-one"}]
    assert get_customer(customers, 1) is customers[1]
    assert get_customer(customers, "1") is customers[0]


def test_duplicate_ids_return_first_match():
    first = {"id": 7, "name": "first"}
    second = {"id": 7, "name": "second"}
    customers = [first, second]
    result = get_customer(customers, 7)
    assert result is first
    assert result["name"] == "first"


def test_returns_original_object_not_a_copy():
    target = {"id": 5, "name": "target"}
    customers = [{"id": 4}, target]
    assert get_customer(customers, 5) is target


def test_entries_without_id_are_ignored():
    no_id = {"name": "no id here"}
    target = {"id": 3, "name": "target"}
    customers = [no_id, target]
    assert get_customer(customers, 3) is target
    assert get_customer(customers, None) is None


def test_all_entries_missing_id_returns_none():
    customers = [{"name": "a"}, {"name": "b"}]
    assert get_customer(customers, 1) is None


def test_non_dict_entries_are_skipped_without_raising():
    target = {"id": 1, "name": "target"}
    customers = [None, "not-a-dict", 42, target]
    assert get_customer(customers, 1) is target


def test_empty_input_returns_none():
    assert get_customer([], 1) is None
    assert get_customer([], "1") is None


def test_no_match_returns_none():
    customers = [{"id": 1}, {"id": 2}]
    assert get_customer(customers, 99) is None
    assert get_customer(customers, "1") is None


def test_does_not_mutate_list_or_dictionaries_and_preserves_order():
    customers = [
        {"id": 2, "status": "active"},
        {"name": "no id"},
        {"id": 1, "status": "inactive"},
    ]
    snapshot = copy.deepcopy(customers)
    identities = [id(item) for item in customers]

    get_customer(customers, 1)
    get_customer(customers, "missing")

    assert customers == snapshot
    assert [id(item) for item in customers] == identities


def test_list_customers_behavior_unchanged():
    customers = [{"id": 2, "status": "active"}, {"id": 1, "status": "inactive"}]
    snapshot = copy.deepcopy(customers)

    result = list_customers(customers)

    assert result == customers
    assert result is not customers
    assert result[0] is customers[0]
    assert customers == snapshot
