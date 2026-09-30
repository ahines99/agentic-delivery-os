"""Unit tests for ``customers.customer_ids`` (AC1-AC5).

AC5 asks for these tests to live in ``tests/test_customers.py``. That exact
path is enumerated in this change's protected paths (".github/", "AGENTS.md",
"CODEOWNERS", "Dockerfile", "infra/", ".env", "tests/test_customers.py") and
the delivery constraints forbid modifying protected paths or pre-existing
tests, so the new tests live in this sibling module instead. It is collected
by the same pytest run and exercises the same public API.

So that the behavioural half of AC5 is still covered by the *new* tests, the
``list_customers`` guarantees (original order, equality with the input, a
distinct returned object, no mutation of the caller's list) are re-asserted
below, together with the empty-input edge case that the pre-existing test does
not cover. The pre-existing test in ``tests/test_customers.py`` remains
unmodified.
"""

import copy

from customers import customer_ids, list_customers


def test_preserves_input_order_and_duplicate_ids():
    customers = [{"id": 2}, {"id": 1}, {"id": 2}]
    assert customer_ids(customers) == [2, 1, 2]


def test_preserves_order_with_mixed_id_types():
    customers = [{"id": "b"}, {"id": 10}, {"id": "a"}, {"id": 10}]
    assert customer_ids(customers) == ["b", 10, "a", 10]


def test_single_element_input():
    assert customer_ids([{"id": 7, "status": "active"}]) == [7]


def test_omits_missing_id_key_but_retains_explicit_none():
    customers = [{"id": 1}, {"status": "x"}, {"id": None}]
    assert customer_ids(customers) == [1, None]


def test_consecutive_missing_keys_do_not_shift_order():
    customers = [{"status": "x"}, {"id": 1}, {}, {"name": "n"}, {"id": None}, {"id": 1}]
    assert customer_ids(customers) == [1, None, 1]


def test_retains_falsy_ids_that_are_present():
    customers = [{"id": 0}, {"id": ""}, {"id": False}, {"status": "x"}]
    assert customer_ids(customers) == [0, "", False]


def test_empty_input_returns_empty_list():
    result = customer_ids([])
    assert result == []
    assert isinstance(result, list)


def test_all_dicts_missing_id_returns_empty_list():
    customers = [{"status": "active"}, {"name": "a"}, {}]
    assert customer_ids(customers) == []


def test_does_not_mutate_input_list_or_dicts():
    customers = [{"id": 1, "status": "active"}, {"status": "x"}, {"id": None}]
    snapshot = copy.deepcopy(customers)
    original_dicts = list(customers)

    result = customer_ids(customers)

    assert customers == snapshot
    assert len(customers) == len(snapshot)
    for original, expected in zip(customers, snapshot):
        assert original == expected
    # The input list still holds the very same dict objects (none replaced).
    for before, after in zip(original_dicts, customers):
        assert before is after
    assert result is not customers


def test_mutable_id_values_are_not_copied_or_modified():
    shared_id = ["a"]
    customers = [{"id": shared_id}]

    result = customer_ids(customers)

    assert result == [["a"]]
    assert result[0] is shared_id
    assert customers == [{"id": ["a"]}]


def test_result_is_independent_of_later_mutation():
    customers = [{"id": 1}, {"id": 2}]
    result = customer_ids(customers)

    result.append(99)

    assert customers == [{"id": 1}, {"id": 2}]
    assert customer_ids(customers) == [1, 2]


def test_list_customers_behaviour_unchanged():
    customers = [{"id": 2, "status": "active"}, {"id": 1, "status": "inactive"}]
    snapshot = copy.deepcopy(customers)

    result = list_customers(customers)

    assert result == customers
    assert result == snapshot
    assert result is not customers
    assert customers == snapshot


def test_list_customers_handles_empty_input():
    customers = []
    result = list_customers(customers)

    assert result == []
    assert result is not customers
