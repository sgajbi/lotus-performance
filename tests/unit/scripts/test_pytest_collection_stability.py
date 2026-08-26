from subprocess import CompletedProcess

import pytest

from scripts import pytest_collection_stability


def test_collect_node_ids_returns_only_collected_tests(monkeypatch):
    completed = CompletedProcess(
        args=[],
        returncode=0,
        stdout="tests/unit/test_example.py::test_one\n\n1 test collected\n",
        stderr="",
    )
    monkeypatch.setattr(pytest_collection_stability.subprocess, "run", lambda *args, **kwargs: completed)

    assert pytest_collection_stability.collect_node_ids("tests/unit", 7) == {"tests/unit/test_example.py::test_one"}


def test_validate_collection_stability_accepts_identical_sets(monkeypatch):
    monkeypatch.setattr(
        pytest_collection_stability,
        "collect_node_ids",
        lambda test_path, seed: frozenset({"test_a", "test_b"}),
    )

    assert pytest_collection_stability.validate_collection_stability("tests/unit", [1, 2, 3]) == 2


def test_validate_collection_stability_reports_the_set_difference(monkeypatch):
    collections = {
        1: frozenset({"test_a", "test_b"}),
        2: frozenset({"test_b", "test_c"}),
    }
    monkeypatch.setattr(
        pytest_collection_stability,
        "collect_node_ids",
        lambda test_path, seed: collections[seed],
    )

    with pytest.raises(RuntimeError, match=r"missing=\['test_a'\].*unexpected=\['test_c'\]"):
        pytest_collection_stability.validate_collection_stability("tests/unit", [1, 2])


def test_shared_payload_fixture_is_function_scoped_and_returns_fresh_nested_state():
    from tests.conftest import happy_path_payload

    assert happy_path_payload._fixture_function_marker.scope == "function"

    first = happy_path_payload.__wrapped__()
    second = happy_path_payload.__wrapped__()
    first["positions_data"].append({"position_id": "MUTATED"})
    first["positions_data"][0]["meta"]["sector"] = "MUTATED"

    assert len(second["positions_data"]) == 1
    assert second["positions_data"][0]["meta"]["sector"] == "Technology"
