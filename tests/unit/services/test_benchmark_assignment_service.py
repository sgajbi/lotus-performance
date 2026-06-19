from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.benchmark_assignment_service import (
    _benchmark_id_from_assignment_payload,
    _resolved_assignment_identity,
    resolve_benchmark_identity,
)


class _BenchmarkAssignmentStub:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    async def get_benchmark_assignment(self, **kwargs):
        self.calls.append(kwargs)
        return self.status_code, self.payload


def test_resolved_assignment_identity_projects_evidence_and_rejects_empty_identity():
    identity = _resolved_assignment_identity(
        portfolio_id="PORT_1",
        assignment_status=200,
        assignment_payload={"benchmark_id": "BMK_ASSIGNED"},
    )
    assert identity.benchmark_id == "BMK_ASSIGNED"
    assert identity.source_details == {"resolved_benchmark_assignment": 1}

    with pytest.raises(HTTPException, match="payload missing benchmark_id"):
        _resolved_assignment_identity(
            portfolio_id="PORT_1",
            assignment_status=200,
            assignment_payload={"benchmark_id": ""},
        )


@pytest.mark.parametrize("payload", [{"benchmark_id": ""}, {"benchmark_id": 123}, {}])
def test_benchmark_id_from_assignment_payload_rejects_unusable_identity(payload):
    with pytest.raises(HTTPException, match="payload missing benchmark_id"):
        _benchmark_id_from_assignment_payload(payload)


def test_benchmark_id_from_assignment_payload_returns_valid_identity():
    assert _benchmark_id_from_assignment_payload({"benchmark_id": "BMK_ASSIGNED"}) == "BMK_ASSIGNED"


@pytest.mark.asyncio
async def test_resolve_benchmark_identity_preserves_explicit_identity_without_source_call():
    source = _BenchmarkAssignmentStub(200, {"benchmark_id": "IGNORED"})

    identity = await resolve_benchmark_identity(
        stateful_input_service=source,
        portfolio_id="PORT_1",
        as_of_date=date(2025, 1, 2),
        reporting_currency="USD",
        calculation_id=uuid4(),
        benchmark_id="BMK_EXPLICIT",
    )

    assert identity.benchmark_id == "BMK_EXPLICIT"
    assert identity.source_details == {}
    assert source.calls == []


@pytest.mark.asyncio
async def test_resolve_benchmark_identity_records_assignment_evidence():
    calculation_id = uuid4()
    source = _BenchmarkAssignmentStub(200, {"benchmark_id": "BMK_ASSIGNED"})

    identity = await resolve_benchmark_identity(
        stateful_input_service=source,
        portfolio_id="PORT_1",
        as_of_date=date(2025, 1, 2),
        reporting_currency="USD",
        calculation_id=calculation_id,
        benchmark_id=None,
    )

    assert identity.benchmark_id == "BMK_ASSIGNED"
    assert identity.source_details == {"resolved_benchmark_assignment": 1}
    assert source.calls == [
        {
            "portfolio_id": "PORT_1",
            "as_of_date": date(2025, 1, 2),
            "reporting_currency": "USD",
            "calculation_id": calculation_id,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "payload", "error_match"),
    [
        (404, {}, "No benchmark assignment found"),
        (503, {}, "benchmark assignment source unavailable"),
        (200, {}, "benchmark assignment payload missing benchmark_id"),
    ],
)
async def test_resolve_benchmark_identity_rejects_unusable_assignment(
    status_code: int,
    payload: dict[str, object],
    error_match: str,
):
    with pytest.raises(HTTPException, match=error_match):
        await resolve_benchmark_identity(
            stateful_input_service=_BenchmarkAssignmentStub(status_code, payload),
            portfolio_id="PORT_1",
            as_of_date=date(2025, 1, 2),
            reporting_currency="USD",
            calculation_id=uuid4(),
            benchmark_id=None,
        )
