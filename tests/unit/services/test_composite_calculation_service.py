from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from app.models.composites import CompositeDefinition, CompositeMemberReturnFact
from app.observability import tenant_id_var
from app.services.composite_calculation_service import (
    CompositeDefinitionNotFoundError,
    calculate_composite_twr_from_persisted_facts,
)
from app.services.composite_metadata_store import CompositeMetadataStore


@pytest.mark.parametrize("optimized", [False, True])
def test_pinned_replay_boundaries_refuse_without_assertions(optimized):
    program = """
import json
from dataclasses import replace
from app.models.composites import CompositeTWRRequest
from app.models.composite_materialization import CompositeMaterializationState
from app.services.composite_calculation_service import (
    calculate_composite_twr_from_materializations, _selected_materializations, _window_evidence
)
from app.services.composite_materialization.records import MaterializationRecord
from core.errors import APIError
from tests.composite_materialization_helpers import command_for, admitted

command = command_for()
request = CompositeTWRRequest(composite_id=command.composite_id,
    period_start=command.period_start, period_end=command.period_end)
record = MaterializationRecord(command=command, actor_id='operator', source=None,
    outcomes=[], state=CompositeMaterializationState.COMPLETE, reason_code=None, revision=1)
result = {}
for name, operation in (
    ('missing_selection', lambda: calculate_composite_twr_from_materializations(tenant_id='tenant-a', request=request)),
    ('missing_source', lambda: _window_evidence(record, {})),
):
    try:
        operation()
    except APIError as error:
        result[name] = {'status': error.status_code, 'code': error.error_code}
    else:
        raise RuntimeError(name + ' unexpectedly accepted')
selected = _selected_materializations(request.model_copy(update={'materialization_ids': [command.materialization_id]}))
if selected != [command.materialization_id]:
    raise RuntimeError('Explicit selection changed')
evidence = _window_evidence(replace(record, source=admitted(command)), {})
if evidence.materialization_id != command.materialization_id or not evidence.retained_receipt_fingerprint.startswith('sha256:'):
    raise RuntimeError('Valid retained evidence changed')
result['valid_selection_and_evidence'] = True
result['optimized'] = not __debug__
print(json.dumps(result))
"""
    completed = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", program],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout) == {
        "missing_selection": {"status": 422, "code": "COMPOSITE_VECTOR_SELECTION_REQUIRED"},
        "missing_source": {"status": 409, "code": "REQUIRED_PERIOD_UNAVAILABLE"},
        "valid_selection_and_evidence": True,
        "optimized": optimized,
    }


@pytest.fixture(autouse=True)
def _admitted_composite_tenant():
    token = tenant_id_var.set("test-tenant")
    try:
        yield
    finally:
        tenant_id_var.reset(token)


def _store(tmp_path) -> CompositeMetadataStore:
    store = CompositeMetadataStore(f"sqlite:///{tmp_path / 'composite_metadata.db'}")
    store.create_schema()
    return store


def _definition() -> CompositeDefinition:
    return CompositeDefinition.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "display_name": "Private Banking Global Balanced USD Composite",
            "strategy_code": "GLOBAL_BALANCED",
            "reporting_currency": "USD",
            "inception_date": "2026-01-01",
            "source_authority": {
                "definition_owner": "lotus-manage",
                "membership_owner": "lotus-manage",
                "member_return_owner": "lotus-performance",
                "asset_owner": "lotus-core",
                "benchmark_owner": "lotus-core",
                "policy_version": "composite-source-authority.v1",
            },
        }
    )


def _fact(
    portfolio_id: str,
    return_value: str,
    beginning_market_value: str,
    *,
    ending_market_value: str = "1012500.00",
    restatement_version: str = "v1",
    restatement_sequence: int = 1,
    calculation_id: str | None = None,
    source_snapshot_id: str | None = None,
    source_fingerprint: str | None = None,
) -> CompositeMemberReturnFact:
    return CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": portfolio_id,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": return_value,
            "beginning_market_value": beginning_market_value,
            "ending_market_value": ending_market_value,
            "reporting_currency": "USD",
            "calculation_id": calculation_id or f"calc-{portfolio_id}",
            "source_snapshot_id": source_snapshot_id or f"snapshot-{portfolio_id}",
            "source_fingerprint": source_fingerprint or f"sha256:{portfolio_id}",
            "restatement_version": restatement_version,
            "restatement_sequence": restatement_sequence,
        }
    )


def _complete_publication(store: CompositeMetadataStore, *facts: CompositeMemberReturnFact) -> None:
    first = facts[0]
    store.complete_member_return_fact_publication(
        composite_id=first.composite_id,
        return_view=first.return_view,
        reporting_currency=first.reporting_currency,
        restatement_sequence=first.restatement_sequence,
        period_start=first.period_start,
        period_end=first.period_end,
        expected_families={(fact.portfolio_id, fact.period_start, fact.period_end) for fact in facts},
        source_fingerprint=f"sha256:test-publication-{first.return_view.value}-{first.restatement_sequence}",
    )


def test_calculate_composite_twr_from_persisted_facts_requires_definition(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(CompositeDefinitionNotFoundError):
        calculate_composite_twr_from_persisted_facts(
            composite_id="PB_GLOBAL_BALANCED_USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            store=store,
        )


def test_calculate_composite_twr_from_persisted_facts_reads_store(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition())
    facts = (_fact("P1", "0.0100", "100.00"), _fact("P2", "0.0300", "300.00"))
    for fact in facts:
        store.upsert_member_return_fact(fact)
    _complete_publication(store, *facts)

    result = calculate_composite_twr_from_persisted_facts(
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        store=store,
    )
    assert result.status == "READY"
    assert str(result.cumulative_return) == "0.025000000000"


def test_calculate_composite_twr_uses_latest_restated_member_fact(tmp_path):
    store = _store(tmp_path)
    store.upsert_definition(_definition())
    original = _fact("P1", "0.0100", "100.00", calculation_id="initial-calc")
    restated = _fact(
        "P1",
        "0.0200",
        "200.00",
        ending_market_value="204.00",
        restatement_version="v2",
        restatement_sequence=2,
        calculation_id="restated-calc",
        source_snapshot_id="restated-snapshot",
        source_fingerprint="sha256:restated-p1",
    )
    store.upsert_member_return_fact(original)
    store.upsert_member_return_fact(restated)
    _complete_publication(store, restated)

    result = calculate_composite_twr_from_persisted_facts(
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        store=store,
    )
    original_result = calculate_composite_twr_from_persisted_facts(
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        restatement_sequence=1,
        store=store,
    )

    period = result.period_results[0]
    assert result.status == "READY"
    assert str(result.cumulative_return) == "0.020000000000"
    assert str(period.beginning_market_value) == "200.000000"
    assert period.source_fingerprints == ["sha256:restated-p1"]
    assert period.restatement_versions == ["v2"]
    assert period.member_contributions[0].calculation_id == "restated-calc"
    assert str(original_result.cumulative_return) == "0.010000000000"
    assert original_result.period_results[0].restatement_versions == ["v1"]
