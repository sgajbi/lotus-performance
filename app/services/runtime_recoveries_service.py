from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.api.http_status import HTTP_422_UNPROCESSABLE
from app.models.runtime_recoveries import RuntimeRecoveriesResponse, build_runtime_recoveries_response
from app.services.runtime_recovery_service import build_runtime_recovery_snapshot

RuntimeRecoveriesQueue = Literal["both", "compute", "lineage"]


@dataclass(frozen=True)
class RuntimeRecoveriesValidationProblem:
    code: str
    fields: list[str]
    message: str

    def as_detail(self) -> dict[str, object]:
        return {"code": self.code, "fields": self.fields, "message": self.message}


@dataclass(frozen=True)
class RuntimeRecoveriesValidationError(ValueError):
    status_code: int
    detail: dict[str, object]

    @classmethod
    def from_problem(cls, problem: RuntimeRecoveriesValidationProblem) -> "RuntimeRecoveriesValidationError":
        return cls(status_code=HTTP_422_UNPROCESSABLE, detail=problem.as_detail())

    def __init__(self, status_code: int, detail: dict[str, object]):
        super().__init__(detail.get("message"))
        object.__setattr__(self, "status_code", status_code)
        object.__setattr__(self, "detail", detail)


def build_runtime_recoveries_response_for_query(
    *,
    queue: RuntimeRecoveriesQueue,
    limit: int,
    offset: int,
    recovered_after: datetime | None,
    recovered_before: datetime | None,
    cursor_recovered_before: datetime | None,
    cursor_calculation_id_before: str | None,
    compute_analytics_type: str | None,
    lineage_calculation_type: str | None,
    calculation_id_contains: str | None = None,
) -> RuntimeRecoveriesResponse:
    _validate_runtime_recoveries_query(
        recovered_after=recovered_after,
        recovered_before=recovered_before,
        cursor_recovered_before=cursor_recovered_before,
        cursor_calculation_id_before=cursor_calculation_id_before,
    )

    snapshot = build_runtime_recovery_snapshot(
        queue_filter=queue,
        limit=limit,
        offset=offset,
        recovered_after=recovered_after,
        recovered_before=recovered_before,
        cursor_recovered_before=cursor_recovered_before,
        cursor_calculation_id_before=cursor_calculation_id_before,
        calculation_id_contains=calculation_id_contains,
        compute_analytics_type=compute_analytics_type,
        lineage_calculation_type=lineage_calculation_type,
    )
    return build_runtime_recoveries_response(snapshot)


def _validate_runtime_recoveries_query(
    *,
    recovered_after: datetime | None,
    recovered_before: datetime | None,
    cursor_recovered_before: datetime | None,
    cursor_calculation_id_before: str | None,
) -> None:
    if _has_inverted_recovery_time_window(
        recovered_after=recovered_after,
        recovered_before=recovered_before,
    ):
        raise RuntimeRecoveriesValidationError.from_problem(
            RuntimeRecoveriesValidationProblem(
                code="invalid_recovery_time_window",
                fields=["recovered_after", "recovered_before"],
                message="recovered_after must be less than or equal to recovered_before.",
            )
        )

    if _has_incomplete_recovery_cursor(
        cursor_recovered_before=cursor_recovered_before,
        cursor_calculation_id_before=cursor_calculation_id_before,
    ):
        raise RuntimeRecoveriesValidationError.from_problem(
            RuntimeRecoveriesValidationProblem(
                code="incomplete_recovery_cursor",
                fields=["cursor_recovered_before", "cursor_calculation_id_before"],
                message="cursor_calculation_id_before requires cursor_recovered_before.",
            )
        )


def _has_inverted_recovery_time_window(
    *,
    recovered_after: datetime | None,
    recovered_before: datetime | None,
) -> bool:
    if recovered_after is None or recovered_before is None:
        return False
    return recovered_after > recovered_before


def _has_incomplete_recovery_cursor(
    *,
    cursor_recovered_before: datetime | None,
    cursor_calculation_id_before: str | None,
) -> bool:
    return cursor_calculation_id_before is not None and cursor_recovered_before is None
