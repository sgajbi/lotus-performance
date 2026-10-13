"""Read-only replay of retained portfolio source through the existing return engine."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from uuid import UUID

from app.models.returns_series import ResolvedWindow, ReturnsSeriesRequest
from app.services.execution_registry import ExecutionRegistry
from app.services.lineage_metadata_store import LineageMetadataStore, LineageStatus
from app.services.returns_series_service import daily_ror_from_portfolio_timeseries, points_from_df, resample_returns
from app.services.returns_series_source.archive import SourceArchiveError
from app.services.returns_series_source.capture import checked_source_file, source_directory, verify_source_bundle
from app.services.returns_series_source.materialization import verify_source_manifest
from app.services.stateful_input_service import (
    _merge_portfolio_observations,
    _PortfolioChunkAccumulator,
    _record_portfolio_chunk_payload,
)


def _source_inputs_from_archive(directory: Path, descriptor: dict) -> tuple[list[dict], str]:
    observations: list[dict] = []
    open_dates: list[str] = []
    accumulator = _PortfolioChunkAccumulator(observations=[])
    chunk = 0
    with checked_source_file(directory, descriptor["files"]["archive"]).open("rb") as body:
        with checked_source_file(directory, descriptor["files"]["index"]).open("rb") as index:
            next(index)  # Scope header was already authenticated by bundle verification.
            for line in index:
                page = json.loads(line)
                if page["chunk"] != chunk:
                    observations.extend(accumulator.observations)
                    if accumulator.portfolio_open_date is not None:
                        open_dates.append(accumulator.portfolio_open_date)
                    accumulator = _PortfolioChunkAccumulator(observations=[])
                    chunk = page["chunk"]
                _record_portfolio_chunk_payload(accumulator=accumulator, payload=json.loads(body.read(page["bytes"])))
    observations.extend(accumulator.observations)
    if accumulator.portfolio_open_date is not None:
        open_dates.append(accumulator.portfolio_open_date)
    if not open_dates:
        raise SourceArchiveError("Retained source has no portfolio opening date.")
    return _merge_portfolio_observations(observations), min(open_dates)


def replay_retained_portfolio_source(
    *, database_url: str, storage_path: str | Path, calculation_id: UUID, tenant_id: str
) -> dict:
    execution, record = _load_replay_records(database_url, calculation_id, tenant_id)
    if execution is None or execution.analytics_type != "ReturnsSeries":
        raise SourceArchiveError("Retained execution authority not found.")
    record = _require_replay_record(record, tenant_id)
    return _replay_source_record(record=record, storage_path=storage_path, tenant_id=tenant_id)


def _load_replay_records(database_url: str, calculation_id: UUID, tenant_id: str):
    execution_store = ExecutionRegistry(database_url)
    lineage_store = LineageMetadataStore(database_url)
    try:
        return (
            execution_store.get_execution_for_tenant(calculation_id, tenant_id=tenant_id),
            lineage_store.get_record(calculation_id),
        )
    finally:
        execution_store._engine.dispose()
        lineage_store._engine.dispose()


def _require_replay_record(record, tenant_id: str):
    if (
        record is None
        or record.source_tenant_id != tenant_id
        or record.status != LineageStatus.COMPLETE
        or record.source_custody_state != "complete"
        or record.source_root_digest is None
    ):
        raise SourceArchiveError("Complete retained source authority not found.")
    return record


def _replay_source_record(*, record, storage_path: str | Path, tenant_id: str) -> dict:
    calculation_id = record.calculation_id
    directory = source_directory(storage_path, str(calculation_id), create=False)
    verify_source_manifest(directory, record=record)
    descriptor = verify_source_bundle(
        directory, root=record.source_root_digest, tenant_id=tenant_id, calculation_id=str(calculation_id)
    )
    normalized = json.loads(checked_source_file(directory, descriptor["files"]["normalized"]).read_bytes())
    request = ReturnsSeriesRequest.model_validate(normalized["original_request"])
    inputs = normalized["source_inputs"]
    observations, performance_start = _source_inputs_from_archive(directory, descriptor)
    if observations != inputs["observations"] or performance_start != inputs["performance_start_date"]:
        raise SourceArchiveError("Retained raw pages differ from the consumed source normalization.")
    daily = daily_ror_from_portfolio_timeseries(
        observations=observations,
        performance_start_date=date.fromisoformat(performance_start),
        resolved_window=ResolvedWindow.model_validate(inputs["resolved_window"]),
        metric_basis=request.metric_basis.value,
    )
    points = points_from_df(resample_returns(daily, frequency=request.frequency))
    actual = [point.model_dump(mode="json") for point in points]
    expected = normalized["resolved"]["request"]["stateless_input"]["portfolio_returns"]
    if actual != expected:
        raise SourceArchiveError("Source-off portfolio replay differs from the consumed normalized return points.")
    return {
        "calculation_id": str(calculation_id),
        "source_root_digest": record.source_root_digest,
        "source_manifest_digest": record.source_manifest_digest,
        "metric_basis": request.metric_basis.value,
        "replayed_portfolio_points": len(points),
        "matched": True,
        "scope": "portfolio source to normalized return points; optional families and final response excluded",
    }
