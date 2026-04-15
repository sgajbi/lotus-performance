from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.services.lineage_metadata_store import LineageStatus


class ArtifactLink(BaseModel):
    url: str = Field(
        description="Controlled service-owned download URL for this lineage artifact.",
        examples=[
            "http://performance.dev.lotus/performance/lineage/2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e/artifacts/request.json"
        ],
    )


class LineageResponse(BaseModel):
    calculation_id: UUID = Field(
        description="Durable calculation identifier whose lineage is being inspected.",
        examples=["2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e"],
    )
    calculation_type: str = Field(
        description="Analytics family that produced the lineage payload.",
        examples=["TWR"],
    )
    timestamp_utc: str = Field(
        description="UTC timestamp from the durable lineage record or completed manifest.",
        examples=["2026-04-10T12:00:00Z"],
    )
    status: LineageStatus = Field(
        description="Durable lineage materialization status.",
        examples=["complete"],
    )
    artifacts: dict[str, ArtifactLink] = Field(
        description=(
            "Download links keyed by artifact filename. Empty while lineage is pending or failed, "
            "and populated only after manifest and on-disk artifact integrity checks pass."
        ),
        examples=[
            {
                "request.json": {
                    "url": (
                        "http://performance.dev.lotus/performance/lineage/"
                        "2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e/artifacts/request.json"
                    )
                }
            }
        ],
    )
    error_message: str | None = Field(
        default=None,
        description="Lineage materialization failure message when status is failed.",
        examples=["write failed"],
    )


class LineageManifest(BaseModel):
    calculation_type: str = Field(description="Analytics family recorded in manifest.", examples=["TWR"])
    timestamp_utc: str = Field(
        description="UTC completion timestamp recorded in manifest.", examples=["2026-04-10T12:00:00Z"]
    )
    status: str = Field(description="Manifest materialization status.", examples=["complete"])
    artifact_names: list[str] = Field(
        description="Sorted artifact filenames declared by the manifest.",
        examples=[["daily_results.csv", "request.json", "response.json"]],
    )
