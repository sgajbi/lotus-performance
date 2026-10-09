"""Immutable analytical inputs, never a substitute cash-flow ledger.

Writes use the public Connection supplied by ComputeJobStore's active-claim
transaction. This adapter never acquires a lease, commits, or uses another
store's engine/session. Inputs remain retained if execution cleanup is interrupted.
"""

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import insert, select, text
from sqlalchemy.engine import Connection

from app.adapters.durable_schema.catalog import verify_durable_schema
from app.models.composite_authority import authority_digest
from app.models.composite_pooled_mwr import CompositePooledMWRRequest, PooledMonetaryObservation
from app.ports.composite_pooled_mwr import PooledSourceAdmissionError
from app.services.composite_pooled_mwr.admission import admit_pooled_observation
from app.services.composite_pooled_mwr.schema import (
    immutable_guards,
    install_guards,
    metadata,
    pooled_inputs,
    preflight_schema,
)
from app.services.core_tenant_authority import admitted_tenant_authority, require_composite_tenant_authority
from app.services.durable_database_engine import create_durable_database_engine
from app.services.durable_schema_creation import create_durable_schema
from app.services.durable_store_runtime import RuntimeStoreProxy, resolve_runtime_store


@dataclass(frozen=True)
class PooledInputSnapshot:
    request: CompositePooledMWRRequest
    observation: PooledMonetaryObservation


def _tenant(tenant_id: str) -> str:
    return require_composite_tenant_authority(admitted_tenant_authority(tenant_id)).tenant_id


def _payload(request: CompositePooledMWRRequest, observation: PooledMonetaryObservation, tenant_id: str) -> dict:
    admitted = admit_pooled_observation(request, observation.source_bundle, tenant_id=tenant_id)
    if admitted.model_dump(mode="json") != observation.model_dump(mode="json"):
        raise PooledSourceAdmissionError(
            "INPUT_CUSTODY_CONFLICT", "Projection differs from its original source bundle."
        )
    return {"request": request.model_dump(mode="json"), "observation": admitted.model_dump(mode="json")}


class CompositePooledMWRInputStore:
    def __init__(self, database_url: str):
        self._engine = create_durable_database_engine(database_url)

    def close(self) -> None:
        self._engine.dispose()

    def create_schema(self) -> None:
        create_durable_schema(
            self._engine, metadata, schema_preflights=(preflight_schema,), schema_upgrades=(install_guards,)
        )

    def verify_schema(self) -> None:
        verify_durable_schema(self._engine, metadata, managed_guards=immutable_guards(self._engine.dialect.name))

    def bind(
        self,
        connection: Connection,
        *,
        tenant_id: str,
        request: CompositePooledMWRRequest,
        observation: PooledMonetaryObservation,
    ) -> PooledInputSnapshot:
        """Bind once inside the existing locked job transaction; identical retries replay.

        The caller must use run_with_active_lease_transaction. Its job lock
        serializes competing claims before this tenant/calculation compare-and-set.
        """
        tenant_id = _tenant(tenant_id)
        payload = _payload(request, observation, tenant_id)
        existing = self._read(connection, tenant_id, request.calculation_id)
        if existing is not None:
            if _payload(existing.request, existing.observation, tenant_id) != payload:
                raise PooledSourceAdmissionError(
                    "INPUT_CUSTODY_CONFLICT", "Calculation already binds different original inputs."
                )
            return existing
        connection.execute(
            insert(pooled_inputs).values(
                tenant_id=tenant_id,
                calculation_id=str(request.calculation_id),
                input_manifest_digest=observation.input_manifest_digest,
                payload_digest=authority_digest(payload),
                payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            )
        )
        return PooledInputSnapshot(request, observation)

    def get(self, calculation_id: UUID, *, tenant_id: str) -> PooledInputSnapshot | None:
        with self._engine.connect() as connection:
            return self._read(connection, _tenant(tenant_id), calculation_id)

    def read_in_transaction(
        self, connection: Connection, calculation_id: UUID, *, tenant_id: str
    ) -> PooledInputSnapshot | None:
        """Replay inputs inside the same public active-claim transaction."""
        return self._read(connection, _tenant(tenant_id), calculation_id)

    def get_member_scope(self, calculation_id: UUID, *, tenant_id: str) -> tuple[str, ...] | None:
        """Project identity metadata before an HTTP caller can access financial rows."""
        with self._engine.connect() as connection:
            projection = (
                "payload_json::jsonb #>> '{observation,source_bundle,expected_portfolio_ids}'"
                if connection.dialect.name == "postgresql"
                else "json_extract(payload_json, '$.observation.source_bundle.expected_portfolio_ids')"
            )
            raw = connection.execute(
                text(
                    f"SELECT {projection} FROM composite_pooled_mwr_inputs WHERE tenant_id=:tenant AND calculation_id=:id"
                ),
                {"tenant": _tenant(tenant_id), "id": str(calculation_id)},
            ).scalar_one_or_none()
        if raw is None:
            return None
        return self._parse_member_scope(raw)

    @staticmethod
    def _parse_member_scope(raw):
        members = json.loads(raw)
        if (
            not isinstance(members, list)
            or not members
            or any(not isinstance(member, str) or not member for member in members)
            or len(set(members)) != len(members)
        ):
            raise PooledSourceAdmissionError("INPUT_CUSTODY_CORRUPT", "Retained population metadata is invalid.")
        return tuple(members)

    @staticmethod
    def _read(connection: Connection, tenant_id: str, calculation_id: UUID) -> PooledInputSnapshot | None:
        row = (
            connection.execute(
                select(pooled_inputs).where(
                    pooled_inputs.c.tenant_id == tenant_id, pooled_inputs.c.calculation_id == str(calculation_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        if authority_digest(payload) != row["payload_digest"]:
            raise PooledSourceAdmissionError("INPUT_CUSTODY_CORRUPT", "Retained original input digest differs.")
        request = CompositePooledMWRRequest.model_validate(payload["request"])
        observation = PooledMonetaryObservation.model_validate(payload["observation"])
        if (
            str(request.calculation_id) != row["calculation_id"]
            or observation.input_manifest_digest != row["input_manifest_digest"]
        ):
            raise PooledSourceAdmissionError("INPUT_CUSTODY_CORRUPT", "Retained input identity differs.")
        _payload(request, observation, tenant_id)
        return PooledInputSnapshot(request, observation)


_store_cache: dict[str, CompositePooledMWRInputStore] = {}


def get_composite_pooled_mwr_input_store(*, database_url: str | None = None) -> CompositePooledMWRInputStore:
    return resolve_runtime_store(cache=_store_cache, factory=CompositePooledMWRInputStore, database_url=database_url)


composite_pooled_mwr_input_store = RuntimeStoreProxy(get_composite_pooled_mwr_input_store)
