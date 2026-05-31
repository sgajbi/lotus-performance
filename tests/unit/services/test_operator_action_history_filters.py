from app.services.operator_action_history_filters import (
    build_applied_history_filters,
    generated_at_within_bounds,
    parse_generated_at_bounds,
)


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


def test_build_applied_history_filters_omits_empty_common_values():
    assert (
        build_applied_history_filters(
            limit=None,
            offset=0,
            optional_filters=(("operator_id", None),),
            generated_after=None,
            generated_before=None,
        )
        == {}
    )
