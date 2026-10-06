"""Frozen producer wires and independent, source-backed owning test ports."""

import copy
import json
from pathlib import Path

from app.models.composite_authority import authority_digest
from app.models.composite_materialization import CompositeMaterializationCommand
from app.ports import composite_external_evidence as ports
from app.services.composite_materialization import authority_policy

FIXTURES = Path(__file__).parent / "fixtures" / "composite_authority" / "shared-producer-v2.json"


def shared_packet(version="original"):
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["external_versions"][version]


def command_for_packet(packet, **overrides):
    d, m, a = (packet[key] for key in ("definition", "membership", "attestation"))
    return CompositeMaterializationCommand.model_validate(
        {
            "composite_id": d["composite_id"],
            "definition_version": d["definition_version"],
            "definition_content_hash": d["content_hash"],
            "membership_revision": m["membership_revision"],
            "membership_content_hash": m["content_hash"],
            "attestation_version": a["attestation_version"],
            "attestation_content_hash": a["content_hash"],
            "source_cut_id": m["source_cut_id"],
            "policy_version": m["policy_version"],
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "reporting_currency": "USD",
            "return_view": "GROSS",
            "restatement_sequence": 1,
            "member_calculations": [],
            **overrides,
        }
    )


def rehash_definition(wire, *, approval=True):
    p = wire["source_authority"]
    p["profile_digest"] = authority_digest(p["payload"])
    wire["definition_payload_digest"] = authority_digest(
        {k: v for k, v in wire.items() if k not in {"authority_approval", "definition_payload_digest", "content_hash"}}
    )
    if approval:
        claims = wire["authority_approval"]["claims"]
        claims.update(profile_digest=p["profile_digest"], definition_payload_digest=wire["definition_payload_digest"])
    wire["content_hash"] = authority_digest({k: v for k, v in wire.items() if k != "content_hash"})


class SyntheticRegistration:
    def __init__(self, record):
        self.record = copy.deepcopy(record)

    def resolve(self, request):
        r = self.record
        admitted = (
            request.tenant_id,
            request.provider_id,
            request.registry_revision,
            request.registry_digest,
            request.effective_from,
            request.effective_to,
        ) == (
            r["tenant_id"],
            r["provider_id"],
            r["registry_revision"],
            authority_digest(r),
            r["effective_from"],
            r["effective_to"],
        )
        if not admitted or request.source_product not in r["allowed_products"]:
            return authority_policy.ProviderTrustResolution("UNAVAILABLE", "SYNTHETIC_REGISTRATION_REFUSED")
        return authority_policy.ProviderTrustResolution(
            "SYNTHETIC_TEST_ONLY", "SYNTHETIC_REGISTRATION_ONLY", authority_digest(r)
        )


class SyntheticApproval:
    def __init__(self, packet, purpose):
        self.packet = copy.deepcopy(packet)
        self.purpose = purpose

    def verify(self, request):
        definition = self.packet["definition"]
        profile = definition["source_authority"]["payload"]
        support = self.packet["supporting_payloads"]
        universe = support["universe"]
        if request.universe_digest != authority_digest(universe) or request.expected_members != tuple(
            universe["expected_member_ids"]
        ):
            return False
        method = support["return_method"]
        if (authority_digest(method), method["payload_digest"], method["approval"]["claims"]["payload_digest"]) != (
            profile["return_method_binding"]["digest"],
            authority_digest(method["payload"]),
            method["payload_digest"],
        ):
            return False
        if (
            request.command.reporting_currency,
            str(request.command.return_view),
            str(request.command.period_start),
            str(request.command.period_end),
        ) != (
            method["payload"]["currency"],
            method["payload"]["fee_view"],
            method["payload"]["period_start"],
            method["payload"]["period_end"],
        ):
            return False
        eligibility = support["eligibility_evaluation"]
        if (
            authority_digest(eligibility),
            eligibility["payload_digest"],
            eligibility["approval"]["claims"]["payload_digest"],
            eligibility["payload"]["universe_digest"],
        ) != (
            profile["eligibility_evaluation_binding"]["digest"],
            authority_digest(eligibility["payload"]),
            eligibility["payload_digest"],
            request.universe_digest,
        ):
            return False
        key = (
            "eligibility_evaluation_binding"
            if self.purpose == "ELIGIBILITY_POLICY_EVALUATION"
            else "return_method_binding"
        )
        return (
            request.purpose == self.purpose
            and request.tenant_id == definition["tenant_id"]
            and request.definition.model_dump(mode="json") == definition
            and request.binding.model_dump() == profile[key]
            and (request.effective_from, request.effective_to) == (profile["effective_from"], profile["effective_to"])
        )


def install_test_authorities(monkeypatch, packet):
    """Exact test records only; never a production factory/flag/configuration."""
    packets = packet if isinstance(packet, list) else [packet]

    class RegistrySet:
        def resolve(self, request):
            for item in packets:
                support = item["supporting_payloads"]
                for record in support.get("registries", [support["registry"]]):
                    result = SyntheticRegistration(record).resolve(request)
                    if result.posture == "SYNTHETIC_TEST_ONLY":
                        return result
            return authority_policy.ProviderTrustResolution("UNAVAILABLE", "SYNTHETIC_REGISTRATION_REFUSED")

    class ApprovalSet:
        def __init__(self, purpose):
            self.purpose = purpose

        def verify(self, request):
            return any(SyntheticApproval(item, self.purpose).verify(request) for item in packets)

    monkeypatch.setattr(authority_policy, "provider_trust_resolver", RegistrySet)
    for factory, purpose in (
        ("authority_approval_verifier", "COMPOSITE_ECONOMIC_AUTHORITY_PROFILE"),
        ("eligibility_approval_verifier", "ELIGIBILITY_POLICY_EVALUATION"),
        ("method_approval_verifier", "RETURN_METHOD_CALENDAR"),
    ):
        monkeypatch.setattr(ports, factory, lambda purpose=purpose: ApprovalSet(purpose))


def observation_packet(*, ending_assets=True, corrected=False, two_members=False):
    """Separate explicit observations; original producer pack remains byte-for-byte unchanged."""
    from app.services.composite_materialization.source_contract import source_digest

    packet = shared_packet("corrected" if corrected else "original")
    method = packet["definition"]["source_authority"]["payload"]["return_method_binding"]
    rows = []
    for member, beginning, ret, ending, flow in (
        ("external-member-a", "100.00", "0.10", "160.00", "50.00"),
        (
            "external-member-b",
            "310.00" if corrected else "300.00",
            "-0.02",
            "283.80" if corrected else "274.00",
            "-20.00",
        ),
        ("external-member-c", "200.00", "0.03", "206.00", "0.00"),
    ):
        rows.append(
            {
                "member_id": member,
                "source_member_id": member,
                "member_return": ret,
                "beginning_assets": beginning,
                "beginning_assets_date": "2026-09-01",
                "ending_assets": ending if ending_assets else None,
                "ending_assets_date": "2026-09-30" if ending_assets else None,
                "cash_flows": [{"business_date": "2026-09-30", "amount": flow, "placement": "PERIOD_END_AFTER_RETURN"}],
            }
        )
    wire = {
        "product_name": "CompositeExternalMemberFacts",
        "product_version": "v1",
        "tenant_id": "synthetic-tenant-a",
        "provider_id": "synthetic-provider-a",
        "revision": "observation.corrected" if corrected else "observation.original",
        "watermark": "observation.corrected" if corrected else "observation.original",
        "source_cut_id": packet["membership"]["source_cut_id"],
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "currency": "USD",
        "return_view": "GROSS",
        "return_units": "DECIMAL_FRACTION",
        "asset_units": "CURRENCY_AMOUNT",
        "method_profile_binding": method,
        "rows": rows,
    }
    definition = packet["definition"]
    profile = definition["source_authority"]["payload"]
    profile["profile_revision"] = wire["revision"]
    definition["definition_version"] = wire["revision"]
    definition["authority_approval"]["claims"].update(
        definition_version=wire["revision"], profile_revision=wire["revision"]
    )
    registry = packet["supporting_payloads"]["registry"]
    registry["allowed_products"] = ["CompositeExternalMemberFacts"]
    profile["providers"][0]["registry_digest"] = authority_digest(registry)
    for selection in profile["selections"]:
        selection.update(
            source_product=wire["product_name"],
            source_revision=wire["revision"],
            source_watermark=wire["watermark"],
            source_digest=authority_digest(wire),
        )
    if ending_assets:
        ending = copy.deepcopy(profile["selections"][0])
        ending.update(selection_id="ending_assets", fact="ENDING_ASSETS")
        profile["selections"].insert(1, ending)
    if two_members:
        wire["rows"] = wire["rows"][:2]
        wire["rows"][1].update(
            ending_assets="309.00" if ending_assets else None,
            cash_flows=[{"business_date": "2026-09-30", "amount": "15.00", "placement": "PERIOD_END_AFTER_RETURN"}],
        )
        members = [row["member_id"] for row in wire["rows"]]
        profile["member_identities"] = profile["member_identities"][:2]
        for selection in profile["selections"]:
            selection.update(member_ids=members, source_digest=authority_digest(wire))
        packet["membership"]["decisions"] = packet["membership"]["decisions"][:2]
        packet["attestation"].update(
            expected_portfolio_ids=members, expected_portfolio_count=2, observed_portfolio_count=2
        )
        packet["supporting_payloads"]["universe"].update(expected_count=2, expected_member_ids=members)
        eligibility = packet["supporting_payloads"]["eligibility_evaluation"]
        eligibility["payload"]["results"] = eligibility["payload"]["results"][:2]
        refresh_support_bindings(packet)
        wire["method_profile_binding"] = copy.deepcopy(profile["return_method_binding"])
        for selection in profile["selections"]:
            selection["source_digest"] = authority_digest(wire)
    rehash_definition(definition)
    for name in ("membership", "attestation"):
        packet[name]["definition_version"] = wire["revision"]
    packet["membership"]["content_hash"] = source_digest(packet["membership"])
    packet["attestation"]["membership_content_hash"] = packet["membership"]["content_hash"]
    packet["attestation"]["content_hash"] = source_digest(packet["attestation"])
    return packet, wire


def internal_day_packet():
    """New synthetic profile for registered stateful receipts, never the frozen pack."""
    replacements = {
        "2026-09-01": "2026-01-05",
        "2026-09-30": "2026-01-05",
        "external-member-a": "A",
        "external-member-b": "B",
        "external-member-c": "C",
    }

    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return replacements.get(value, value)

    packet = replace(shared_packet())
    profile = packet["definition"]["source_authority"]["payload"]
    profile["mode"] = "INTERNAL"
    profile["providers"] = [
        {
            "provider_id": owner,
            "source_kind": kind,
            "registry_revision": "controlled.internal.r1",
            "registry_digest": authority_digest({"provider_id": owner, "posture": "SYNTHETIC_TEST_ONLY"}),
            "trust_registration_ref": "controlled-internal-receipts",
        }
        for owner, kind in (("lotus-core", "LOTUS_CORE"), ("lotus-performance", "LOTUS_PERFORMANCE"))
    ]
    registries = []
    for provider in profile["providers"]:
        record = copy.deepcopy(packet["supporting_payloads"]["registry"])
        record.update(
            provider_id=provider["provider_id"],
            source_kind=provider["source_kind"],
            allowed_products=["CompositeMemberSourceEvidence"],
            registry_revision=provider["registry_revision"],
        )
        registries.append(record)
        provider["registry_digest"] = authority_digest(record)
    packet["supporting_payloads"]["registries"] = registries
    for identity in profile["member_identities"]:
        identity.update(identity_kind="CORE_PORTFOLIO", provider_id="lotus-core", namespace="lotus.core")
    refresh_support_bindings(packet)
    return packet


def independent_ending_packet():
    packet, wire = observation_packet()
    ending_wire = copy.deepcopy(wire)
    ending_wire.update(
        provider_id="synthetic-provider-ending",
        revision="independent.ending.r1",
        watermark="independent.ending.watermark",
        source_cut_id="independent-provider-ending-cut",
    )
    profile = packet["definition"]["source_authority"]["payload"]
    provider = copy.deepcopy(profile["providers"][0])
    provider["provider_id"] = ending_wire["provider_id"]
    registry = copy.deepcopy(packet["supporting_payloads"]["registry"])
    registry["provider_id"] = provider["provider_id"]
    provider["registry_digest"] = authority_digest(registry)
    profile["providers"].append(provider)
    packet["supporting_payloads"]["registries"] = [packet["supporting_payloads"]["registry"], registry]
    ending = next(s for s in profile["selections"] if s["fact"] == "ENDING_ASSETS")
    ending.update(
        provider_id=provider["provider_id"],
        economic_authority=provider["provider_id"],
        source_revision=ending_wire["revision"],
        source_watermark=ending_wire["watermark"],
        source_cut_id=ending_wire["source_cut_id"],
        source_digest=authority_digest(ending_wire),
    )
    rehash_definition(packet["definition"])
    return packet, wire, ending_wire


def refresh_support_bindings(packet):
    """Rebind changed synthetic supporting content before installing exact test approvals."""
    from app.services.composite_materialization.source_contract import source_digest

    definition, support = packet["definition"], packet["supporting_payloads"]
    profile, claims = definition["source_authority"]["payload"], definition["authority_approval"]["claims"]
    universe_digest = authority_digest(support["universe"])
    for provider in profile["providers"]:
        for record in support.get("registries", []):
            if record["provider_id"] == provider["provider_id"]:
                provider["registry_digest"] = authority_digest(record)
    eligibility = support["eligibility_evaluation"]
    eligibility["payload"]["universe_digest"] = universe_digest
    eligibility["approval"]["claims"]["universe_digest"] = universe_digest
    for name, binding, evidence in (
        ("return_method", "return_method_binding", "method_evidence_digest"),
        ("eligibility_evaluation", "eligibility_evaluation_binding", "eligibility_evidence_digest"),
    ):
        item = support[name]
        item["payload_digest"] = authority_digest(item["payload"])
        item["approval"]["claims"]["payload_digest"] = item["payload_digest"]
        profile[binding]["digest"] = authority_digest(item)
        claims[evidence] = authority_digest(item)
    for selection in profile["selections"]:
        if selection["fact"] == "MEMBER_RETURN":
            selection["method_profile_binding"] = copy.deepcopy(profile["return_method_binding"])
    for source in packet["attestation"]["source_products"]:
        if source["authority_scope"] == "AUTHORITATIVE_UNIVERSE":
            source["content_hash"] = universe_digest
    rehash_definition(definition)
    packet["membership"]["content_hash"] = source_digest(packet["membership"])
    packet["attestation"]["membership_content_hash"] = packet["membership"]["content_hash"]
    packet["attestation"]["content_hash"] = source_digest(packet["attestation"])
