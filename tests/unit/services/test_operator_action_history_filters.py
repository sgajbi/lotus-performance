from dataclasses import dataclass

from app.services.operator_action_history_filters import (
    build_applied_history_filters,
    filter_history_entries,
    generated_at_within_bounds,
    parse_generated_at_bounds,
)


@dataclass(frozen=True)
class _HistoryEntry:
    operator_id: str
    status: str
    generated_at_utc: str


def test_generated_at_bounds_accepts_values_inside_inclusive_range():
    bounds = parse_generated_at_bounds(
        generated_after="2026-03-15T00:00:00Z",
        generated_before="2026-03-15T23:59:59Z",
    )

    assert bounds.has_bounds
    assert generated_at_within_bounds("2026-03-15T12:00:00Z", bounds=bounds)


def test_generated_at_bounds_rejects_values_outside_range():
    bounds = parse_generated_at_bounds(
        generated_after="2026-03-15T00:00:00Z",
        generated_before="2026-03-15T23:59:59Z",
    )

    assert not generated_at_within_bounds("2026-03-14T23:59:59Z", bounds=bounds)
    assert not generated_at_within_bounds("2026-03-16T00:00:00Z", bounds=bounds)


def test_generated_at_bounds_supports_open_range():
    bounds = parse_generated_at_bounds(generated_after="2026-03-15T00:00:00Z", generated_before=None)

    assert generated_at_within_bounds("2026-03-15T00:00:00Z", bounds=bounds)
    assert not generated_at_within_bounds("2026-03-14T23:59:59Z", bounds=bounds)


def test_build_applied_history_filters_keeps_common_and_optional_filters():
    assert build_applied_history_filters(
        limit=25,
        offset=50,
        optional_filters=(
            ("operator_id", "ops-user"),
            ("job_id", None),
            ("status", "passed"),
        ),
        generated_after="2026-03-15T00:00:00Z",
        generated_before=None,
    ) == {
        "limit": 25,
        "offset": 50,
        "operator_id": "ops-user",
        "status": "passed",
        "generated_after": "2026-03-15T00:00:00Z",
    }


def test_build_applied_history_filters_trims_optional_string_filters():
    assert build_applied_history_filters(
        limit=None,
        offset=0,
        optional_filters=(
            ("operator_id", " ops-user "),
            ("status", " passed "),
        ),
        generated_after=None,
        generated_before=None,
    ) == {
        "operator_id": "ops-user",
        "status": "passed",
    }


def test_build_applied_history_filters_preserves_integer_optional_filters():
    assert build_applied_history_filters(
        limit=None,
        offset=0,
        optional_filters=(("retention_days", 30),),
        generated_after=None,
        generated_before=None,
    ) == {"retention_days": 30}


def test_build_applied_history_filters_omits_empty_common_values():
    assert (
        build_applied_history_filters(
            limit=None,
            offset=0,
            optional_filters=(("operator_id", None), ("status", " ")),
            generated_after=None,
            generated_before=None,
        )
        == {}
    )


def test_filter_history_entries_applies_exact_filters_and_time_bounds():
    entries = [
        _HistoryEntry(operator_id="ops-a", status="passed", generated_at_utc="2026-03-15T00:00:00Z"),
        _HistoryEntry(operator_id="ops-a", status="failed", generated_at_utc="2026-03-16T00:00:00Z"),
        _HistoryEntry(operator_id="ops-b", status="passed", generated_at_utc="2026-03-15T12:00:00Z"),
    ]

    filtered = filter_history_entries(
        entries,
        exact_filters=(
            ("ops-a", lambda entry: entry.operator_id),
            ("passed", lambda entry: entry.status),
        ),
        generated_after="2026-03-15T00:00:00Z",
        generated_before="2026-03-15T23:59:59Z",
        get_generated_at_utc=lambda entry: entry.generated_at_utc,
    )

    assert filtered == [entries[0]]


def test_filter_history_entries_trims_expected_string_filters():
    entries = [
        _HistoryEntry(operator_id="ops-a", status="passed", generated_at_utc="2026-03-15T00:00:00Z"),
        _HistoryEntry(operator_id="ops-b", status="passed", generated_at_utc="2026-03-15T12:00:00Z"),
    ]

    filtered = filter_history_entries(
        entries,
        exact_filters=((" ops-a ", lambda entry: entry.operator_id),),
        generated_after=None,
        generated_before=None,
        get_generated_at_utc=lambda entry: entry.generated_at_utc,
    )

    assert filtered == [entries[0]]


def test_filter_history_entries_ignores_blank_expected_string_filters():
    entries = [
        _HistoryEntry(operator_id="ops-a", status="passed", generated_at_utc="2026-03-15T00:00:00Z"),
        _HistoryEntry(operator_id="ops-b", status="failed", generated_at_utc="2026-03-15T12:00:00Z"),
    ]

    filtered = filter_history_entries(
        entries,
        exact_filters=((" ", lambda entry: entry.operator_id),),
        generated_after=None,
        generated_before=None,
        get_generated_at_utc=lambda entry: entry.generated_at_utc,
    )

    assert filtered == entries


def test_filter_history_entries_ignores_none_expected_filters():
    entries = [
        _HistoryEntry(operator_id="ops-a", status="passed", generated_at_utc="2026-03-15T00:00:00Z"),
        _HistoryEntry(operator_id="ops-b", status="failed", generated_at_utc="2026-03-15T12:00:00Z"),
    ]

    filtered = filter_history_entries(
        entries,
        exact_filters=((None, lambda entry: entry.operator_id),),
        generated_after=None,
        generated_before=None,
        get_generated_at_utc=lambda entry: entry.generated_at_utc,
    )

    assert filtered == entries
