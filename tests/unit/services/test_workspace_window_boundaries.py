"""A window with no published observations must not resolve to a boundary.

Issue #469: `POST /performance/workspace-summary` returned a generic `500
INTERNAL_SERVER_ERROR` with `retryable: true` for a deterministic business condition — a
monthly breakdown whose window ends after the last published observation. Retrying can never
help, and the sanitised log carried no exception class, so a correlation id resolved to
nothing.

This module pins the proximate cause rather than the symptom.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from app.models.workspace_summary_responses import WorkspaceBreakdownItem
from app.services.workspace_summary_service import (
    MissingWindowBoundaryError,
    _date_from_boundary,
)


def test_nat_is_a_date_subclass_which_is_why_the_guard_leaked() -> None:
    """Pin the language fact the original guard was defeated by.

    `_date_from_boundary` ended in `raise TypeError(...)` and read as fail-closed. It was not:
    `NaTType` subclasses `datetime.date`, so `isinstance(value, date)` accepted `NaT` and
    returned it as though it were a real boundary. The guard excluded everything except the
    one bad value that actually occurs.
    """

    assert not isinstance(pd.NaT, pd.Timestamp)
    assert isinstance(pd.NaT, datetime.date)


def test_an_empty_window_slice_yields_nat_boundaries() -> None:
    """This is what a window ending after the last published observation produces."""

    empty = pd.DataFrame({"perf_date": pd.Series([], dtype="datetime64[ns]")})

    assert empty["perf_date"].min() is pd.NaT
    assert empty["perf_date"].max() is pd.NaT


def test_missing_boundary_is_refused_with_a_named_condition() -> None:
    """The refusal must say what happened, so a correlation id resolves to a cause."""

    with pytest.raises(MissingWindowBoundaryError) as excinfo:
        _date_from_boundary(pd.NaT)

    assert "no published observations" in str(excinfo.value)


def test_a_real_boundary_is_still_resolved() -> None:
    """The guard must not change the ordinary path."""

    assert _date_from_boundary(pd.Timestamp("2026-04-10")) == datetime.date(2026, 4, 10)
    assert _date_from_boundary(datetime.date(2026, 4, 10)) == datetime.date(2026, 4, 10)


def test_an_unsupported_boundary_type_is_still_a_type_error() -> None:
    with pytest.raises(TypeError):
        _date_from_boundary("2026-04-10")


def test_a_leaked_nat_boundary_produces_an_unattributable_error_downstream() -> None:
    """Why leaking `NaT` produced an opaque 500 rather than a usable failure.

    Left to travel, `NaT` reaches the response models and raises a bare `TypeError` with a
    message about floats and integers — no field, no window, no mention of observations. The
    workflow catch-all then maps it to `INTERNAL_SERVER_ERROR` / `retryable: true`, which is
    how a deterministic data-coverage condition became a retryable server fault.
    """

    with pytest.raises(TypeError) as excinfo:
        WorkspaceBreakdownItem.model_validate({"period": "2026-04", "period_start": pd.NaT, "period_end": pd.NaT})

    message = str(excinfo.value)
    assert "observation" not in message
    assert "period" not in message
    # The message names neither the field nor the condition — it is unattributable.
    assert "integer" in message
