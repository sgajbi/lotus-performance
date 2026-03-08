# app/services/lineage_service.py
import json
import logging
import os
from typing import Dict
from uuid import UUID

import pandas as pd
from pydantic import BaseModel

from app.core.config import get_settings
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

    def capture(
        self,
        calculation_id: UUID,
        calculation_type: str,
        request_model: BaseModel,
        response_model: BaseModel,
        calculation_details: Dict[str, pd.DataFrame],
    ):
        """Captures all artifacts for a calculation and saves them to storage."""
        try:
            target_dir = os.path.join(self.storage_path, str(calculation_id))
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)

            # Save request and response JSON
            with open(os.path.join(target_dir, "request.json"), "w") as f:
                f.write(request_model.model_dump_json(indent=2))

            with open(os.path.join(target_dir, "response.json"), "w") as f:
                f.write(response_model.model_dump_json(indent=2))

            # Save detailed calculation CSVs
            for filename, df in calculation_details.items():
                df.to_csv(os.path.join(target_dir, filename), index=False)

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

            logger.info(f"Successfully captured lineage data for calculation_id: {calculation_id}")

        except Exception as e:
            try:
                self._metadata_store.mark_failed(calculation_id=calculation_id, error_message=str(e))
            except Exception:
                logger.exception(
                    "Failed to mark lineage metadata record as failed for calculation_id=%s", calculation_id
                )
            # Add robust logging to make silent errors visible in the server console
            logger.error(
                f"FATAL: Failed to capture lineage data for calculation_id: {calculation_id}. Reason: {e}",
                exc_info=True,
            )

    def create_pending_record(self, calculation_id: UUID, calculation_type: str) -> None:
        self._metadata_store.create_pending_record(calculation_id=calculation_id, calculation_type=calculation_type)


lineage_service = LineageService(storage_path=settings.LINEAGE_STORAGE_PATH)
