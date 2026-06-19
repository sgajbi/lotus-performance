from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.stateful_position_currency_support import (
    stateful_both_currency_requires_fx,
    stateful_position_currencies,
    validate_stateful_both_currency_support,
)


def test_validate_stateful_both_currency_support_uses_workflow_specific_error_text() -> None:
    with pytest.raises(HTTPException, match="Stateful contribution input requires report_ccy"):
        validate_stateful_both_currency_support(
            rows=[],
            reporting_currency=None,
            fx=None,
            workflow_name="contribution",
        )

    with pytest.raises(HTTPException, match="Stateful attribution input requires position_currency"):
        validate_stateful_both_currency_support(
            rows=[{"position_id": "POS_1"}],
            reporting_currency="USD",
            fx=None,
            workflow_name="attribution",
        )

    with pytest.raises(HTTPException, match="Stateful attribution input requires fx.rates"):
        validate_stateful_both_currency_support(
            rows=[{"position_id": "POS_1", "position_currency": "EUR"}],
            reporting_currency="USD",
            fx=None,
            workflow_name="attribution",
        )


def test_stateful_both_currency_support_accepts_reporting_currency_rows_without_fx() -> None:
    validate_stateful_both_currency_support(
        rows=[{"position_id": "POS_1", "position_currency": "USD"}],
        reporting_currency="USD",
        fx=None,
        workflow_name="contribution",
    )


def test_stateful_position_currency_helpers_preserve_existing_semantics() -> None:
    rows = [
        {"position_id": "POS_1", "position_currency": "EUR"},
        {"position_id": "POS_2", "position_currency": " "},
        {"position_id": "POS_3", "position_currency": ""},
        {"position_id": "POS_4", "position_currency": None},
        {"position_id": "POS_5", "position_currency": 123},
        {"position_id": "POS_6", "position_currency": "USD"},
    ]

    assert stateful_position_currencies(rows) == {" ", "EUR", "USD"}
    assert (
        stateful_both_currency_requires_fx(
            position_currencies={"USD"},
            reporting_currency="USD",
        )
        is False
    )
    assert (
        stateful_both_currency_requires_fx(
            position_currencies={"USD", "EUR"},
            reporting_currency="USD",
        )
        is True
    )
