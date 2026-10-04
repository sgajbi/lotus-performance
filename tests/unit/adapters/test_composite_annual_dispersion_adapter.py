import pytest

from app.adapters.composite_annual_dispersion import RetainedAnnualDispersionReceiptReader
from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.models.composite_materialization import CompositeMaterializationState
from app.services.composite_annual_dispersion.application import calculate_annual_member_dispersion
from app.services.composite_metadata_store import CompositeMetadataStore
from core.errors import APINotFoundError
from tests.unit.services.test_composite_annual_dispersion_service import annual_request, year_records


def persist_records(url, records):
    ledger, facts = CompositeMaterializationStore(url), CompositeMetadataStore(url)
    try:
        facts.create_schema()
        ledger.create_schema()
        for record in records:
            command = record.command
            facts.upsert_definition(record.source.definition.performance_definition(), tenant_id="tenant-a")
            ledger.register(command, tenant_id="tenant-a", actor_id="operator")
            ledger.save(
                command.materialization_id,
                tenant_id="tenant-a",
                expected_revision=0,
                source=record.source,
                outcomes=record.outcomes,
                state=CompositeMaterializationState.PUBLISHING,
                reason_code=None,
            )
            for outcome in record.outcomes:
                if outcome.fact is not None:
                    facts.upsert_member_return_fact(outcome.fact, tenant_id="tenant-a")
            facts.complete_member_return_fact_publication(
                tenant_id="tenant-a",
                composite_id=command.composite_id,
                return_view=command.return_view,
                reporting_currency=command.reporting_currency,
                restatement_sequence=command.restatement_sequence,
                period_start=command.period_start,
                period_end=command.period_end,
                expected_families={
                    (outcome.portfolio_id, command.period_start, command.period_end)
                    for outcome in record.outcomes
                    if outcome.fact is not None
                },
                source_fingerprint=command.attestation_content_hash,
            )
            ledger.save(
                command.materialization_id,
                tenant_id="tenant-a",
                expected_revision=1,
                source=record.source,
                outcomes=record.outcomes,
                state=CompositeMaterializationState.COMPLETE,
                reason_code=None,
            )
    finally:
        facts.close()
        ledger.close()


def test_read_only_receipt_adapter_replays_original_corrected_after_reopen_and_hides_other_tenant(tmp_path):
    url = "sqlite:///" + (tmp_path / "annual.db").as_posix()
    original, corrected = year_records(), year_records(corrected=True)
    persist_records(url, original + corrected)
    store = CompositeMaterializationStore(url)
    try:
        reader = RetainedAnnualDispersionReceiptReader(store)
        old = calculate_annual_member_dispersion(annual_request(original), tenant_id="tenant-a", reader=reader)
        new = calculate_annual_member_dispersion(annual_request(corrected), tenant_id="tenant-a", reader=reader)
        assert str(old.value) == "0.018708286934"
        assert old.members[0].annual_return != new.members[0].annual_return
        assert old.result_fingerprint != new.result_fingerprint
        with pytest.raises(APINotFoundError):
            reader.get(original[0].command.materialization_id, tenant_id="tenant-b")
        store.close()
        store = CompositeMaterializationStore(url)
        assert (
            calculate_annual_member_dispersion(
                annual_request(original), tenant_id="tenant-a", reader=RetainedAnnualDispersionReceiptReader(store)
            )
            == old
        )
    finally:
        store.close()
