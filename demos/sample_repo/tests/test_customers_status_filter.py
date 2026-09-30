import copy

from customers import list_customers


def _sample():
    return [
        {"id": 1, "status": "active"},
        {"id": 2, "status": "inactive"},
        {"id": 3, "status": "active"},
        {"id": 4},
        {"id": 5, "status": "Active"},
    ]


def test_default_call_returns_all_customers_in_original_order():
    customers = _sample()
    assert list_customers(customers) == customers


def test_explicit_none_status_returns_all_customers_in_original_order():
    customers = _sample()
    result = list_customers(customers, status=None)
    assert result == customers
    assert result is not customers
    assert [c["id"] for c in result] == [1, 2, 3, 4, 5]


def test_none_status_passed_positionally_matches_default_behavior():
    customers = _sample()
    assert list_customers(customers, None) == list_customers(customers)


def test_filter_active_returns_only_active_preserving_input_order():
    customers = [
        {"id": 3, "status": "active"},
        {"id": 1, "status": "inactive"},
        {"id": 2, "status": "active"},
    ]
    result = list_customers(customers, status="active")
    assert result == [{"id": 3, "status": "active"}, {"id": 2, "status": "active"}]
    assert [c["id"] for c in result] == [3, 2]


def test_filter_other_status_values():
    customers = _sample()
    assert list_customers(customers, status="inactive") == [{"id": 2, "status": "inactive"}]


def test_status_match_is_exact_and_case_sensitive():
    customers = _sample()
    assert list_customers(customers, status="active") == [
        {"id": 1, "status": "active"},
        {"id": 3, "status": "active"},
    ]
    assert list_customers(customers, status="Active") == [{"id": 5, "status": "Active"}]
    assert list_customers(customers, status="ACTIVE") == []


def test_status_match_does_not_trim_or_substring_match():
    customers = [
        {"id": 1, "status": " active"},
        {"id": 2, "status": "active "},
        {"id": 3, "status": "inactive"},
    ]
    assert list_customers(customers, status="active") == []
    assert list_customers(customers, status=" active") == [{"id": 1, "status": " active"}]


def test_customers_missing_status_field_never_match():
    customers = [{"id": 1}, {"id": 2, "status": "active"}]
    assert list_customers(customers, status="active") == [{"id": 2, "status": "active"}]
    assert list_customers(customers, status="inactive") == []
    assert list_customers(customers, status="") == []


def test_customers_missing_status_field_do_not_raise():
    customers = [{"id": 1}, {"id": 2}]
    assert list_customers(customers, status="active") == []


def test_explicit_empty_string_status_uses_exact_equality():
    customers = [{"id": 1, "status": ""}, {"id": 2, "status": "active"}, {"id": 3}]
    assert list_customers(customers, status="") == [{"id": 1, "status": ""}]


def test_no_matches_returns_empty_list():
    customers = _sample()
    result = list_customers(customers, status="archived")
    assert result == []
    assert isinstance(result, list)


def test_empty_input_returns_empty_list_with_and_without_filter():
    assert list_customers([]) == []
    assert list_customers([], status=None) == []
    assert list_customers([], status="active") == []


def test_does_not_mutate_input_list_or_dicts_when_filtering():
    customers = _sample()
    snapshot = copy.deepcopy(customers)
    list_customers(customers, status="active")
    assert customers == snapshot


def test_does_not_mutate_input_list_or_dicts_without_filter():
    customers = _sample()
    snapshot = copy.deepcopy(customers)
    list_customers(customers)
    list_customers(customers, status=None)
    assert customers == snapshot


def test_returns_new_list_object_referencing_same_customer_dicts():
    customers = _sample()
    unfiltered = list_customers(customers)
    filtered = list_customers(customers, status="active")
    assert unfiltered is not customers
    assert filtered is not customers
    assert unfiltered[0] is customers[0]
    assert filtered[0] is customers[0]


def test_mutating_returned_list_does_not_affect_input_list():
    customers = _sample()
    original_length = len(customers)
    result = list_customers(customers, status="active")
    result.append({"id": 99, "status": "active"})
    result.clear()
    assert len(customers) == original_length


def test_accepts_non_list_iterable_input():
    customers = (
        {"id": 1, "status": "active"},
        {"id": 2, "status": "inactive"},
    )
    assert list_customers(customers) == [
        {"id": 1, "status": "active"},
        {"id": 2, "status": "inactive"},
    ]
    assert list_customers(customers, status="inactive") == [{"id": 2, "status": "inactive"}]
