from app.services.operator_action_history_filters import generated_at_within_bounds, parse_generated_at_bounds


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
