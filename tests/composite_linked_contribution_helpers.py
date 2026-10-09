"""Independent OR13 input/reference and bounded synthetic authority controls."""

from decimal import Decimal, localcontext

from app.models.composite_authority import authority_digest
from tests.composite_authority_helpers import (
    command_for_packet,
    oracle_month_packet,
    refresh_support_bindings,
    rehash_definition,
)

LINKED_PATH = "/performance/composites/analytics"
OR13_EXPECTED = (
    Decimal("0.030274630541907723798278421725685604316257567000362"),
    Decimal("-0.000074630541907723798278421725685604316257567000360925"),
)


def independent_reference(period_returns, contributions):
    # Independent log identity, no production factors or service as oracle.
    with localcontext() as context:
        context.prec = 90
        returns = list(map(Decimal, period_returns))
        cumulative = Decimal(1)
        for ret in returns:
            cumulative *= 1 + ret
        cumulative -= 1
        logs = [(1 + ret).ln() if ret else Decimal(0) for ret in returns]
        denominator = sum(logs, Decimal(0))
        total_factor = cumulative / denominator if denominator else Decimal(1)
        return [
            sum(
                (
                    Decimal(value) * (log / ret if ret else Decimal(1)) * total_factor
                    for value, ret, log in zip(member, returns, logs, strict=True)
                ),
                Decimal(0),
            )
            for member in contributions
        ]


def linked_packet(
    month, *, corrected=False, returns=None, missing_member=False, member_b="external-member-b", excluded_b=False
):
    packet, wire = oracle_month_packet(month, corrected=corrected, composite_id="SYNTHETIC_LINKED_USD")
    values = returns or (("0.05", "-0.03") if month == 1 else ("0.01", "0.03"))
    if corrected and returns is None:
        values = ("0.06", "-0.02")
    with localcontext() as context:
        context.prec = 90
        for row, ret in zip(wire["rows"], values, strict=True):
            row.update(
                beginning_assets="100",
                member_return=format(Decimal(ret), "f"),
                ending_assets=str(Decimal(100) * (1 + Decimal(ret))),
                cash_flows=[],
            )
    if missing_member:
        wire["rows"].pop()
    if member_b != "external-member-b":

        def rename(value):
            if isinstance(value, dict):
                return {key: rename(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rename(item) for item in value]
            return member_b if value == "external-member-b" else value

        packet, wire = rename(packet), rename(wire)
    if excluded_b:
        packet["membership"]["decisions"][1].update(status="EXCLUDED", reason_code="APPROVED_POLICY_EXCLUSION")
    refresh_support_bindings(packet)
    wire["method_profile_binding"] = packet["definition"]["source_authority"]["payload"]["return_method_binding"].copy()
    for selection in packet["definition"]["source_authority"]["payload"]["selections"]:
        selection["source_digest"] = authority_digest(wire)
    rehash_definition(packet["definition"])
    return packet, wire


def publish_pairs(client, pairs, *, sequence_start=1):
    commands = []
    for sequence, (packet, wire) in enumerate(pairs, sequence_start):
        command = command_for_packet(
            packet, period_start=wire["period_start"], period_end=wire["period_end"], restatement_sequence=sequence
        )
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        from app.workers.compute_executor_worker import process_pending_jobs

        assert process_pending_jobs(limit=1) == 1
        commands.append(command)
    return commands


def linked_request(commands):
    return {
        "composite_id": commands[0].composite_id,
        "period_start": str(commands[0].period_start),
        "period_end": str(commands[-1].period_end),
        "return_view": "GROSS",
        "reporting_currency": "USD",
        "calculation_id": "06310000-0000-4000-8000-000000000001",
        "materialization_ids": [str(command.materialization_id) for command in commands],
        "method": "CARINO:v1",
        "metric_id": "LINKED_MEMBER_CONTRIBUTION",
    }


def assert_or13(body):
    expected = independent_reference((".01", ".02"), ((".025", ".005"), ("-.015", ".015")))
    for row, original, reference in zip(body["members"], OR13_EXPECTED, expected, strict=True):
        actual = Decimal(row["linked_contribution"])
        assert abs(actual - original) < Decimal("1e-12")
        assert abs(actual - reference) < Decimal("1e-70")
    assert abs(Decimal(body["total_linked_contribution"]) - Decimal(".0302")) < Decimal("1e-70")
    assert body["units"] == "DECIMAL_RETURN" and body["method"] == "CARINO:v1"
    assert body["constituent_decomposition"] == "AVAILABLE"
    assert body["qualification"] == "RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED"
