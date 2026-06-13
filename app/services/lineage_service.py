# app/services/lineage_service.py
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import PurePath
from uuid import UUID

import pandas as pd
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR_INSPECTION
from app.services.durable_store_time import format_timestamp
from app.services.execution_registry import ExecutionRegistry, execution_registry
from app.services.execution_stage_names import (
    EXECUTION_STAGE_ARTIFACT_MATERIALIZATION,
    EXECUTION_STAGE_LINEAGE_MATERIALIZATION,
)
from app.services.lineage_metadata_store import LineageMetadataStore, lineage_metadata_store

logger = logging.getLogger(__name__)


def resolve_artifact_stage_name(*, calculation_type: str) -> str:
    if calculation_type == ANALYTICS_WORKFLOW_TWR_INSPECTION:
        return EXECUTION_STAGE_ARTIFACT_MATERIALIZATION
    return EXECUTION_STAGE_LINEAGE_MATERIALIZATION


class LineageService:
    def __init__(
        self,
        storage_path: str | None = None,
        metadata_store: LineageMetadataStore | None = None,
        execution_store: ExecutionRegistry | None = None,
    ):
        self._storage_path = storage_path
        self._metadata_store = metadata_store or lineage_metadata_store
        self._execution_store = execution_store or execution_registry
        self._ensure_storage_directory()

    @property
    def storage_path(self) -> str:
        return self._storage_path or get_settings().LINEAGE_STORAGE_PATH

    def _ensure_storage_directory(self) -> None:
        if os.path.isdir(self.storage_path):
            return
        os.makedirs(self.storage_path, exist_ok=True)
        logger.info("Created lineage storage directory at: %s", self.storage_path)

    def enqueue_capture(
        self,
        calculation_id: UUID,
        calculation_type: str,
        request_model: BaseModel,
        response_model: BaseModel,
        calculation_details: dict[str, pd.DataFrame],
    ) -> None:
        serialized_details = self._serialize_details(calculation_details)
        self._metadata_store.enqueue_lineage_payload(
            calculation_id=calculation_id,
            calculation_type=calculation_type,
            request_json=request_model.model_dump_json(indent=2),
            response_json=response_model.model_dump_json(indent=2),
            details=serialized_details,
        )

    def materialize_payload(
        self,
        *,
        calculation_id: UUID,
        calculation_type: str,
        request_json: str,
        response_json: str,
        calculation_details: dict[str, str],
    ) -> bool:
        """Materializes lineage artifacts from a previously enqueued payload."""
        try:
            self._ensure_storage_directory()
            target_dir, artifact_names = self._materialize_artifact_files(
                calculation_id=calculation_id,
                request_json=request_json,
                response_json=response_json,
                calculation_details=calculation_details,
            )
            completion_timestamp = datetime.now(timezone.utc)
            self._write_text_atomic(
                os.path.join(target_dir, "manifest.json"),
                json.dumps(
                    {
                        "calculation_type": calculation_type,
                        "timestamp_utc": format_timestamp(completion_timestamp) or "",
                        "status": "complete",
                        "artifact_names": sorted(artifact_names),
                    },
                    indent=2,
                ),
            )

            self._metadata_store.mark_complete(
                calculation_id=calculation_id,
                artifact_names=artifact_names,
                timestamp_utc=completion_timestamp,
            )
            try:
                self._execution_store.complete_stage(
                    calculation_id,
                    resolve_artifact_stage_name(calculation_type=calculation_type),
                    details={"artifact_names": sorted(artifact_names)},
                )
            except Exception:
                logger.warning(
                    "Execution stage unavailable while marking lineage materialization complete: %s",
                    calculation_id,
                    exc_info=True,
                )

            logger.info("Successfully captured lineage data for calculation_id: %s", calculation_id)
            return True

        except Exception as e:
            logger.error(
                "FATAL: Failed to capture lineage data for calculation_id: %s. Reason: %s",
                calculation_id,
                e,
                exc_info=True,
            )
            return False

    def _materialize_artifact_files(
        self,
        *,
        calculation_id: UUID,
        request_json: str,
        response_json: str,
        calculation_details: dict[str, str],
    ) -> tuple[str, list[str]]:
        target_dir = os.path.join(self.storage_path, str(calculation_id))
        os.makedirs(target_dir, exist_ok=True)

        self._write_text_atomic(os.path.join(target_dir, "request.json"), request_json)
        self._write_text_atomic(os.path.join(target_dir, "response.json"), response_json)

        detail_artifact_names: list[str] = []
        for filename, csv_payload in calculation_details.items():
            safe_filename = self._validate_artifact_filename(filename)
            self._write_text_atomic(os.path.join(target_dir, safe_filename), csv_payload)
            detail_artifact_names.append(safe_filename)

        return target_dir, ["request.json", "response.json", *detail_artifact_names]

    def _serialize_details(self, calculation_details: dict[str, pd.DataFrame]) -> dict[str, str]:
        serialized: dict[str, str] = {}
        for filename, df in calculation_details.items():
            safe_filename = self._validate_artifact_filename(filename)
            buffer = StringIO()
            df.to_csv(buffer, index=False)
            serialized[safe_filename] = buffer.getvalue()
        return serialized

    @staticmethod
    def _write_text_atomic(path: str, content: str) -> None:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".lineage-", suffix=".tmp", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    @staticmethod
    def _validate_artifact_filename(filename: str) -> str:
        candidate = filename.strip()
        path = PurePath(candidate)
        if (
            not candidate
            or candidate in {".", ".."}
            or path.is_absolute()
            or path.name != candidate
            or any(part == ".." for part in path.parts)
        ):
            raise ValueError(f"Unsafe lineage artifact filename: {filename}")
        return candidate

    def create_pending_record(self, calculation_id: UUID, calculation_type: str) -> None:
        self._metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type=calculation_type)


lineage_service = LineageService()
