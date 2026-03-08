# app/services/lineage_service.py
import json
import logging
import os
from io import StringIO
from typing import Dict
from uuid import UUID

import pandas as pd
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import LineageMetadataStore, lineage_metadata_store

logger = logging.getLogger(__name__)
settings = get_settings()


class LineageService:
    def __init__(self, storage_path: str, metadata_store: LineageMetadataStore | None = None):
        self.storage_path = storage_path
        self._metadata_store = metadata_store or lineage_metadata_store
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)
            logger.info(f"Created lineage storage directory at: {self.storage_path}")

    def enqueue_capture(
        self,
        calculation_id: UUID,
        calculation_type: str,
        request_model: BaseModel,
        response_model: BaseModel,
        calculation_details: Dict[str, pd.DataFrame],
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
    ) -> None:
        """Materializes lineage artifacts from a previously enqueued payload."""
        try:
            target_dir = os.path.join(self.storage_path, str(calculation_id))
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)

            with open(os.path.join(target_dir, "request.json"), "w") as f:
                f.write(request_json)

            with open(os.path.join(target_dir, "response.json"), "w") as f:
                f.write(response_json)

            for filename, csv_payload in calculation_details.items():
                with open(os.path.join(target_dir, filename), "w") as f:
                    f.write(csv_payload)

            artifact_names = ["request.json", "response.json", *calculation_details.keys()]
            manifest_data = self._metadata_store.get_record(calculation_id)
            with open(os.path.join(target_dir, "manifest.json"), "w") as f:
                json.dump(
                    {
                        "calculation_type": calculation_type,
                        "timestamp_utc": manifest_data.timestamp_utc if manifest_data else None,
                        "status": "complete",
                    },
                    f,
                    indent=2,
                )

            self._metadata_store.mark_complete(calculation_id=calculation_id, artifact_names=artifact_names)
            self._metadata_store.delete_payload(calculation_id)
            try:
                execution_registry.complete_stage(
                    calculation_id,
                    "lineage_materialization",
                    details={"artifact_names": sorted(artifact_names)},
                )
            except KeyError:
                logger.warning(
                    "Execution stage not found while marking lineage materialization complete: %s",
                    calculation_id,
                )

            logger.info(f"Successfully captured lineage data for calculation_id: {calculation_id}")

        except Exception as e:
            try:
                self._metadata_store.mark_failed(calculation_id=calculation_id, error_message=str(e))
            except Exception:
                logger.exception(
                    "Failed to mark lineage metadata record as failed for calculation_id=%s", calculation_id
                )
            try:
                execution_registry.fail_stage(calculation_id, "lineage_materialization", str(e))
            except KeyError:
                logger.warning(
                    "Execution stage not found while marking lineage materialization failed: %s",
                    calculation_id,
                )
            # Add robust logging to make silent errors visible in the server console
            logger.error(
                f"FATAL: Failed to capture lineage data for calculation_id: {calculation_id}. Reason: {e}",
                exc_info=True,
            )

    def _serialize_details(self, calculation_details: Dict[str, pd.DataFrame]) -> dict[str, str]:
        serialized: dict[str, str] = {}
        for filename, df in calculation_details.items():
            buffer = StringIO()
            df.to_csv(buffer, index=False)
            serialized[filename] = buffer.getvalue()
        return serialized

    def create_pending_record(self, calculation_id: UUID, calculation_type: str) -> None:
        self._metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type=calculation_type)


lineage_service = LineageService(storage_path=settings.LINEAGE_STORAGE_PATH)
