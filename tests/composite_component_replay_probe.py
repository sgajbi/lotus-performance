"""Fresh-process retained replay under independently frozen synthetic test authorities."""

import json
import sys
from pathlib import Path

import pytest

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.core.config import get_settings
from app.models.composite_fee_drag import CompositeFeeDragRequest
from app.models.composite_materialization import CompositeMaterializationCommand
from app.ports import composite_external_evidence, composite_model_fees
from app.services.composite_fee_drag.application import calculate_model_fee_drag
from app.services.composite_materialization.model_fee_source_admission import model_fee_resolution_request
from app.services.composite_materialization.source_contract import PinnedCompositeSource
from tests.composite_authority_helpers import install_test_authorities
from tests.composite_component_source_helpers import FrozenFinancialVerifier
from tests.composite_model_fee_helpers import SyntheticModelFeeApproval


def replay(path):
    capture = json.loads(Path(path).read_text(encoding="utf-8"))
    packet, profile = capture["packet"], capture["profile"]
    command = CompositeMaterializationCommand.model_validate(capture["command"])
    source = PinnedCompositeSource.model_validate(
        {
            **{key: packet[key] for key in ("definition", "membership", "attestation")},
            "wire_evidence": {key: packet[key] for key in ("definition", "membership", "attestation")},
        }
    )
    request = model_fee_resolution_request(source, command, tenant_id=profile["tenant_id"])
    financial_verifier = FrozenFinancialVerifier(capture["financial"], request, source.definition.definition_version)
    approval = SyntheticModelFeeApproval(profile, source)

    class NeverResolveCurrent:
        def resolve(self, request):
            raise AssertionError("Fresh-process historical replay may not fetch current financial/method wires")

    with pytest.MonkeyPatch.context() as controls:
        controls.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", capture["database_url"])
        install_test_authorities(controls, packet)
        controls.setattr(composite_external_evidence, "method_approval_verifier", lambda: approval)
        controls.setattr(composite_external_evidence, "composite_receipt_verifier", lambda: financial_verifier)
        controls.setattr(composite_model_fees, "composite_model_fee_resolver", NeverResolveCurrent)
        controls.setattr(composite_model_fees, "composite_gross_cost_resolver", NeverResolveCurrent)
        store = CompositeMaterializationStore(capture["database_url"])
        try:
            retained = store.get(command.materialization_id, tenant_id=profile["tenant_id"])
            assert retained.source.gross_component_wire["source"] == capture["financial"]
            assert retained.source.model_fee_wire == profile
            assert retained.state == "COMPLETE"
            analysis = calculate_model_fee_drag(
                CompositeFeeDragRequest.model_validate(capture["analysis_request"]), tenant_id=profile["tenant_id"]
            )
            assert analysis.model_dump(mode="json") == capture["analysis_response"]
            print(
                json.dumps(
                    {
                        "state": "COMPLETE",
                        "receipt_version": "composite-member-source.v6",
                        "members": len(retained.outcomes),
                        "fresh_process": True,
                        "qualification": "SYNTHETIC_TEST_ONLY",
                        "current_source_reads": 0,
                    }
                )
            )
        finally:
            store.close()


if __name__ == "__main__":
    replay(sys.argv[1])
