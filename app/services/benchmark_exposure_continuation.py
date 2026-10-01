"""Source-bound continuation policy for the benchmark exposure integration view."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass

from app.models.benchmark_exposure_context import (
    BenchmarkExposureContextRequest,
    BenchmarkExposureRow,
    BenchmarkExposureSourceQuality,
)
from app.services.offset_pagination import parse_offset_page_token
from core.errors import APIConflictError, APIUnprocessableEntityError
from core.repro import generate_canonical_hash_from_value

_TOKEN_PATTERN = re.compile(r"v1\.(0|[1-9][0-9]{0,8})\.([0-9a-f]{64})\Z")
_INVALID_PAGE_CONTINUATION_DETAIL = "page.page_token must be a continuation returned by lotus-performance."
_NEGATIVE_PAGE_CONTINUATION_DETAIL = "page.page_token must be non-negative."
_STALE_PAGE_CONTINUATION_DETAIL = "Benchmark exposure source changed during pagination; restart from the first page."


@dataclass(frozen=True)
class BenchmarkExposureContinuationPage:
    rows: list[BenchmarkExposureRow]
    next_page_token: str | None
    consistency: str


def _economic_fingerprint(
    *,
    request: BenchmarkExposureContextRequest,
    benchmark_id: str,
    tenant_id: str,
    rows: list[BenchmarkExposureRow],
    source_quality: BenchmarkExposureSourceQuality,
) -> str:
    payload = {
        "tenant_id": tenant_id,
        "portfolio_id": request.portfolio_id,
        "benchmark_id": benchmark_id,
        "as_of_date": request.as_of_date.isoformat(),
        "window": request.window.model_dump(mode="json"),
        "frequency": request.frequency.value,
        "reporting_currency": request.reporting_currency,
        "grouping_dimensions": [dimension.value for dimension in request.grouping_dimensions],
        "rows": [
            {
                **row.model_dump(mode="json", exclude={"weight"}),
                "weight": str(row.weight.normalize()),
            }
            for row in rows
        ],
        "source_quality": source_quality.model_dump(mode="json"),
    }
    fingerprint, _ = generate_canonical_hash_from_value(payload, "benchmark-exposure-continuation-v1")
    return fingerprint.removeprefix("sha256:")


def _continuation_start(page_token: str | None, *, fingerprint: str) -> tuple[int, str]:
    if not page_token:
        return 0, "source_bound"
    match = _TOKEN_PATTERN.fullmatch(page_token)
    if match is not None:
        if not hmac.compare_digest(match.group(2), fingerprint):
            raise APIConflictError(
                _STALE_PAGE_CONTINUATION_DETAIL,
                error_code="BENCHMARK_EXPOSURE_PAGE_SOURCE_CHANGED",
            )
        return int(match.group(1)), "source_bound"
    if page_token.startswith("v1."):
        raise APIUnprocessableEntityError(_INVALID_PAGE_CONTINUATION_DETAIL)
    return (
        parse_offset_page_token(
            page_token,
            invalid_detail=_INVALID_PAGE_CONTINUATION_DETAIL,
            negative_detail=_NEGATIVE_PAGE_CONTINUATION_DETAIL,
        ),
        "legacy_offset_unbound",
    )


def page_benchmark_exposure_rows(
    *,
    request: BenchmarkExposureContextRequest,
    benchmark_id: str,
    tenant_id: str,
    rows: list[BenchmarkExposureRow],
    source_quality: BenchmarkExposureSourceQuality,
) -> BenchmarkExposureContinuationPage:
    """Re-read Core for each page, refusing a changed derived economic state."""
    fingerprint = _economic_fingerprint(
        request=request,
        benchmark_id=benchmark_id,
        tenant_id=tenant_id,
        rows=rows,
        source_quality=source_quality,
    )
    start, consistency = _continuation_start(request.page.page_token, fingerprint=fingerprint)
    end = start + request.page.page_size
    next_token = f"v1.{end}.{fingerprint}" if end < len(rows) else None
    return BenchmarkExposureContinuationPage(
        rows=rows[start:end],
        next_page_token=next_token,
        consistency=consistency,
    )
