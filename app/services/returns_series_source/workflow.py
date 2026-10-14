"""Bind ReturnsSeries resolution to the existing execution and lineage owners."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pandas as pd

from app.core.config import get_settings
from app.observability import tenant_id_var
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.returns_series_source.capture import (
    PortfolioSourceCapture,
    active_source_capture,
    checked_source_file,
    source_directory,
    verify_source_bundle,
)
from app.services.returns_series_source.custody import (
    SourceCustodyClaim,
    SourceCustodyConflict,
    SourceMaterializationPayload,
)

if TYPE_CHECKING:
    from app.models.returns_series import ReturnsSeriesRequest
    from app.services.compute_job_store import ComputeJobStore
    from app.services.durable_store_runtime import RuntimeStoreProxy
    from app.services.returns_series_service import ResolvedStatefulReturnsSeriesRequest


logger = logging.getLogger(__name__)
active_compute_source_claim: ContextVar[
    tuple[ComputeJobStore | RuntimeStoreProxy[ComputeJobStore], SourceCustodyClaim] | None
] = ContextVar("returns_compute_source_claim", default=None)


def _frame_records(frame: pd.DataFrame | None) -> list[dict[str, str]] | None:
    if frame is None:
        return None
    return [
        {"date": pd.Timestamp(row["date"]).isoformat(), "return_value": str(row["return_value"])}
        for row in frame[["date", "return_value"]].to_dict("records")
    ]


def _resolved_payload(resolved: ResolvedStatefulReturnsSeriesRequest) -> dict[str, Any]:
    return {
        "request": resolved.request.model_dump(mode="json"),
        "identity_payload": resolved.identity_payload,
        "input_count": resolved.input_count,
        "resolved_benchmark_id": resolved.resolved_benchmark_id,
        "resolved_benchmark_return_source": resolved.resolved_benchmark_return_source,
        "benchmark_work_units": resolved.benchmark_work_units,
        "freshness_portfolio_df": _frame_records(resolved.freshness_portfolio_df),
        "freshness_benchmark_df": _frame_records(resolved.freshness_benchmark_df),
        "freshness_risk_free_df": _frame_records(resolved.freshness_risk_free_df),
        "risk_free_source_quality": (
            resolved.risk_free_source_quality.model_dump(mode="json") if resolved.risk_free_source_quality else None
        ),
    }


def _restore_resolved(payload: dict[str, Any]) -> ResolvedStatefulReturnsSeriesRequest:
    from decimal import Decimal

    from app.models.returns_series import ReturnsSeriesRequest, RiskFreeSourceQuality
    from app.services.returns_series_service import ResolvedStatefulReturnsSeriesRequest

    fields = dict(payload)
    fields["request"] = ReturnsSeriesRequest.model_validate(fields["request"])
    quality = fields["risk_free_source_quality"]
    fields["risk_free_source_quality"] = RiskFreeSourceQuality.model_validate(quality) if quality else None
    for name in ("freshness_portfolio_df", "freshness_benchmark_df", "freshness_risk_free_df"):
        rows = fields[name]
        fields[name] = (
            None
            if rows is None
            else pd.DataFrame(
                [{"date": pd.Timestamp(row["date"]), "return_value": Decimal(row["return_value"])} for row in rows],
                columns=["date", "return_value"],
            )
        )
    return ResolvedStatefulReturnsSeriesRequest(**fields)


async def resolve_with_source_custody(
    request: ReturnsSeriesRequest,
    resolver: Callable[[ReturnsSeriesRequest], Awaitable[ResolvedStatefulReturnsSeriesRequest]],
) -> ResolvedStatefulReturnsSeriesRequest:
    binding = _resolution_binding(request.calculation_id)
    if binding is None:
        return await resolver(request)
    owner, claim = binding
    selected = owner.select_returns_series_source_root(claim=claim, root_digest=None)
    if selected.root_digest is not None:
        # Already selected input is read-only. New-publication failure must not
        # replace it with a fresh upstream retrieval during an admitted retry.
        frozen_directory = source_directory(
            get_settings().LINEAGE_STORAGE_PATH, str(claim.calculation_id), create=False
        )
        return _load_frozen_resolution(frozen_directory, root=selected.root_digest, claim=claim, request=request)
    directory = _capture_directory(owner, claim)
    if directory is None:
        return await resolver(request)
    if selected.state == "failed":
        return await resolver(request)
    capture = _begin_capture(directory, owner, claim)
    token = active_source_capture.set(capture)
    try:
        resolved = await resolver(request)
    finally:
        active_source_capture.reset(token)
    if capture is not None:
        _freeze_resolution(capture, owner=owner, claim=claim, request=request, resolved=resolved)
    return replace(resolved, source_custody_claim=claim)


def _resolution_binding(calculation_id: UUID):
    active = active_compute_source_claim.get()
    if active is None and not tenant_id_var.get():
        # Preserve the existing Core tenant refusal, including its HTTP mapping.
        return None
    owner, claim = (
        active
        if active is not None
        else (
            execution_registry,
            SourceCustodyClaim(calculation_id, tenant_id_var.get() or "", uuid4().hex, 0),
        )
    )
    if claim.calculation_id != calculation_id:
        raise SourceCustodyConflict("Source capture calculation differs from the execution claim.")
    engines = (owner._engine, execution_registry._engine, lineage_metadata_store._engine)
    _require_shared_database(engines)
    return owner, claim


def _require_shared_database(engines) -> None:
    if any(engine.url != engines[0].url for engine in engines[1:]):
        raise SourceCustodyConflict("Source custody requires one durable metadata database.")
    if engines[0].url.get_backend_name() == "sqlite" and engines[0].url.database in (None, "", ":memory:"):
        if any(engine is not engines[0] for engine in engines[1:]):
            raise SourceCustodyConflict("Separate in-memory stores cannot establish shared custody.")


def _capture_directory(owner, claim: SourceCustodyClaim) -> Path | None:
    try:
        return source_directory(get_settings().LINEAGE_STORAGE_PATH, str(claim.calculation_id))
    except OSError:
        owner.select_returns_series_source_root(claim=claim, root_digest=None, failure="Source storage unavailable.")
        return None


def _load_frozen_resolution(
    directory: Path, *, root: str, claim: SourceCustodyClaim, request: ReturnsSeriesRequest
) -> ResolvedStatefulReturnsSeriesRequest:
    descriptor = verify_source_bundle(
        directory, root=root, tenant_id=claim.tenant_id, calculation_id=str(request.calculation_id)
    )
    normalized = json.loads(checked_source_file(directory, descriptor["files"]["normalized"]).read_bytes())
    if normalized["original_request"] != request.model_dump(mode="json"):
        raise SourceCustodyConflict("Frozen source request differs from the admitted request.")
    return replace(_restore_resolved(normalized["resolved"]), source_custody_claim=claim)


def _begin_capture(directory: Path, owner, claim: SourceCustodyClaim) -> PortfolioSourceCapture | None:
    try:
        return PortfolioSourceCapture(
            directory=directory,
            calculation_id=str(claim.calculation_id),
            tenant_id=claim.tenant_id,
            attempt_id=claim.attempt_id,
        )
    except OSError:
        owner.select_returns_series_source_root(claim=claim, root_digest=None, failure="Source spool unavailable.")
        return None


def _freeze_resolution(
    capture: PortfolioSourceCapture,
    *,
    owner,
    claim: SourceCustodyClaim,
    request: ReturnsSeriesRequest,
    resolved: ResolvedStatefulReturnsSeriesRequest,
) -> None:
    try:
        normalized = {
            "original_request": request.model_dump(mode="json"),
            "resolved": _resolved_payload(resolved),
            "source_inputs": capture.normalized_sources,
        }
        root, _ = capture.freeze(normalized)
        owner.select_returns_series_source_root(claim=claim, root_digest=root)
    except (OSError, ValueError, TypeError) as exc:
        logger.error("ReturnsSeries source custody failed for %s: %s", request.calculation_id, type(exc).__name__)
        owner.select_returns_series_source_root(
            claim=claim, root_digest=None, failure="Source capture or durable verification failed."
        )


def enqueue_source_response(
    *, calculation_id: UUID, response_json: str, inline_claim: SourceCustodyClaim | None, stateful: bool
) -> None:
    if not stateful:
        return
    active = active_compute_source_claim.get()
    if active is None and inline_claim is None:
        return
    owner, claim = active if active is not None else (execution_registry, inline_claim)
    if claim is None or claim.calculation_id != calculation_id:
        raise SourceCustodyConflict("Source enqueue claim differs from the calculation.")
    _enqueue_claim_response(owner=owner, claim=claim, response_json=response_json)


def _enqueue_claim_response(*, owner, claim: SourceCustodyClaim, response_json: str) -> None:
    calculation_id = claim.calculation_id
    record = lineage_metadata_store.get_record(calculation_id)
    if record is None or record.source_custody_state == "failed" or record.source_root_digest is None:
        return
    try:
        directory = source_directory(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id))
        descriptor = verify_source_bundle(
            directory, root=record.source_root_digest, tenant_id=claim.tenant_id, calculation_id=str(calculation_id)
        )
        normalized = json.loads(checked_source_file(directory, descriptor["files"]["normalized"]).read_bytes())
        owner.select_returns_series_source_root(
            claim=claim,
            root_digest=record.source_root_digest,
            materialization=SourceMaterializationPayload(
                json.dumps(normalized["original_request"], sort_keys=True),
                response_json,
            ),
        )
    except Exception as exc:
        # Arithmetic success is independent, but custody cannot be advertised as
        # complete. A stale owner still cannot mutate failure state.
        logger.error("ReturnsSeries source enqueue failed for %s: %s", calculation_id, type(exc).__name__)
        try:
            owner.select_returns_series_source_root(
                claim=claim, root_digest=None, failure="Source materialization enqueue failed."
            )
        except Exception as failure:
            logger.error(
                "ReturnsSeries source custody failure could not be persisted for %s: %s",
                calculation_id,
                type(failure).__name__,
            )
