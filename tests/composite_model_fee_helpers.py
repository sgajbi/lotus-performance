"""Controlled periodic method wires and immutable internal-source pins, never official approval."""

from copy import deepcopy

from app.models.composite_authority import authority_digest
from app.services.composite_materialization.source_contract import PinnedCompositeSource
from tests.composite_authority_helpers import command_for_packet, internal_day_packet, rehash_definition


class SyntheticModelFeeApproval:
    """Frozen owning-test method configuration; no production issuer/verifier."""

    def __init__(self, wire, source):
        self.wire = deepcopy(wire)
        self.definition = source.definition.model_copy(deep=True)
        self.universe_digest = next(
            row.content_hash
            for row in source.attestation.source_products
            if row.authority_scope == "AUTHORITATIVE_UNIVERSE"
        )

    def verify(self, request):
        periods = [
            row
            for row in self.wire["periods"]
            if (row["period_start"], row["period_end"])
            == (str(request.command.period_start), str(request.command.period_end))
        ]
        if len(periods) != 1:
            return False
        return (
            request.purpose == "RETURN_METHOD_CALENDAR"
            and request.definition == self.definition
            and request.binding.digest == authority_digest(self.wire)
            and (request.method_evidence_wire is None or request.method_evidence_wire == self.wire)
            and request.universe_digest == self.universe_digest
            and request.command.return_view == "NET_MODEL_FEE"
            and request.command.model_fee_binding == request.binding
            and (request.tenant_id, request.composite_id, request.command.reporting_currency)
            == (self.wire["tenant_id"], self.wire["composite_id"], self.wire["reporting_currency"])
            and request.expected_members == tuple(row["member_id"] for row in periods[0]["member_rates"])
        )


def profile_wire():
    return {
        "product_name": "CompositePeriodicModelFeeProfile",
        "product_version": "v1",
        "profile_id": "synthetic.periodic.management",
        "revision": "profile.1",
        "tenant_id": "TENANT_A",
        "composite_id": "SYNTHETIC_MODEL_FEE_USD",
        "method_id": "periodic.wealth.haircut",
        "method_revision": "method.1",
        "schedule_id": "management.periodic",
        "schedule_revision": "schedule.1",
        "effective_from": "2026-01-01",
        "effective_to": "2026-02-28",
        "calendar_binding": {
            "product_name": "CompositeReturnCalendar",
            "product_version": "v1",
            "revision": "calendar.1",
            "digest": "sha256:" + "a" * 64,
        },
        "reporting_currency": "USD",
        "gross_source_basis": "GROSS",
        "fee_component": "MANAGEMENT_FEE_ONLY",
        "transaction_cost_treatment": "ALREADY_INCLUDED_IN_GROSS",
        "bundled_fee_context": "UNBUNDLED",
        "rate_basis": "EXPLICIT_PERIOD_WEALTH_FRACTION",
        "timing": "END_OF_COMPLETE_PERIOD_AFTER_GROSS_RETURN",
        "transformation": "MULTIPLICATIVE_WEALTH_HAIRCUT",
        "asset_treatment": "UNCHANGED_SOURCE_ASSETS_BEGINNING_ASSET_WEIGHTING",
        "monetary_precision": "DECIMAL_STRICT_NO_INTERMEDIATE_ROUNDING",
        "standards_applicability": "NOT_ASSESSED_ENGINEERING_METHOD_ONLY",
        "periods": [
            {
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "member_rates": [{"entry_id": "jan.member-a", "member_id": "MEMBER_A", "period_fee_fraction": "0.001"}],
            },
            {
                "period_start": "2026-02-01",
                "period_end": "2026-02-28",
                "member_rates": [{"entry_id": "feb.member-a", "member_id": "MEMBER_A", "period_fee_fraction": "0.002"}],
            },
        ],
    }


def model_fee_source_inputs(wire=None):
    packet = internal_day_packet()
    definition = packet["definition"]
    # This native-receipt method retains complete internal asset evidence, so
    # both asset endpoints are independently declared economic selections.
    selections = definition["source_authority"]["payload"]["selections"]
    ending = deepcopy(next(row for row in selections if row["fact"] == "BEGINNING_ASSETS"))
    ending.update(selection_id=ending["selection_id"] + ".ending", fact="ENDING_ASSETS")
    selections.append(ending)
    selections.sort(key=lambda row: row["selection_id"])
    if wire is None:
        wire = profile_wire()
        wire.update(
            tenant_id=definition["tenant_id"],
            composite_id=definition["composite_id"],
            effective_from="2026-01-05",
            effective_to="2026-01-05",
            periods=[
                {
                    "period_start": "2026-01-05",
                    "period_end": "2026-01-05",
                    "member_rates": [
                        {"entry_id": "day." + member, "member_id": member, "period_fee_fraction": rate}
                        for member, rate in [("A", "0.001"), ("B", "0.002"), ("C", "0")]
                    ],
                }
            ],
        )
    wire = deepcopy(wire)
    binding = {key: wire[key] for key in ["product_name", "product_version", "revision"]}
    binding["digest"] = authority_digest(wire)
    profile = definition["source_authority"]["payload"]
    profile["return_method_binding"] = deepcopy(binding)
    for selection in profile["selections"]:
        if selection["fact"] == "MEMBER_RETURN":
            selection["method_profile_binding"] = deepcopy(binding)
    definition["authority_approval"]["claims"]["method_evidence_digest"] = binding["digest"]
    rehash_definition(definition)
    command = command_for_packet(
        packet,
        period_start="2026-01-05",
        period_end="2026-01-05",
        return_view="NET_MODEL_FEE",
        model_fee_binding=binding,
    )
    source = PinnedCompositeSource.model_validate(
        {
            **{key: packet[key] for key in ["definition", "membership", "attestation"]},
            "wire_evidence": {key: packet[key] for key in ["definition", "membership", "attestation"]},
        }
    )
    return packet, wire, command, source
