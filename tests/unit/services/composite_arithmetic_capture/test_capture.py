"""Native source parity, exact KATs, sticky retries and immutable capsule custody."""

import copy
import decimal
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, text

from app.adapters.composite_arithmetic_capture.bundle import installed_source_digest, normalized_source
from app.adapters.composite_arithmetic_capture.codec import COMPARISON_EXCLUSIONS, comparison_digest, digest
from app.models.composite_arithmetic_capture import PROFILE, CompositeArithmeticCapture
from app.models.composites import CompositeMemberReturnFact, CompositeReturnView
from app.services.composite_arithmetic_capture.collector import ArithmeticCollector, context_payload
from app.services.composite_arithmetic_capture.replay import qualify
from app.services.composite_arithmetic_capture.response import composite_response
from app.services.composite_materialization.model_fee_calculation import calculate_with_model_fee_context
from core.errors import APIConflictError, APIError


def source_attempt(inputs, *, scheduled=False, observe=True):
    _, _, original_request, original_response, principal = inputs
    window = original_response.selection_manifest.windows[0].model_copy(deep=True)
    view = CompositeReturnView.NET_MODEL_FEE if scheduled else CompositeReturnView.NET_ACTUAL
    if scheduled:
        window.method_binding = {"product_name": "CompositeScheduledModelFeeProfile", "product_version": "v1"}
    request = original_request.model_copy(
        update={
            "calculation_id": uuid4(),
            "period_end": window.period_end,
            "materialization_ids": [window.materialization_id],
            "return_view": view,
        }
    )
    facts = []
    for member, assets, value in zip(original_response.periods[0].member_contributions, ("1", "2"), ("0.5", "0")):
        facts.append(
            CompositeMemberReturnFact(
                composite_id=request.composite_id,
                portfolio_id=member.portfolio_id,
                period_start=window.period_start,
                period_end=window.period_end,
                return_value=value,
                beginning_market_value=assets,
                ending_market_value=assets,
                return_view=view,
                reporting_currency="USD",
                calculation_id=None,
                source_authority_identity=member.source_authority_identity,
                source_snapshot_id=member.source_snapshot_id,
                source_fingerprint=member.source_fingerprint,
                restatement_version=member.restatement_version,
                restatement_sequence=1,
            )
        )
    collector = ArithmeticCollector() if observe else None
    if collector is not None:
        collector.select(facts, [window])
    result = calculate_with_model_fee_context(
        composite_id=request.composite_id, facts=facts, scheduled=scheduled, observer=collector
    )
    return request, composite_response(request, result, [window], principal.tenant_id), collector, facts


def capture_attempt(inputs, attempt, candidate_id=None):
    store, results, _, _, principal = inputs
    request, response, collector, _ = attempt
    return store.capture_result_candidate(
        candidate_id=candidate_id or uuid4(),
        request=request,
        response=response,
        principal=principal,
        result_store=results,
        observer=collector,
        precision_capture_profile=PROFILE,
    )


def quantity(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def counts(store):
    with store._engine.connect() as connection:
        return tuple(
            connection.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in ("analytics_async_result", "composite_result_candidates")
        )


def test_independent_intermediate_rounding_known_answer_and_installed_replay(precision_inputs):
    with decimal.localcontext() as context:
        context.prec = 28
        context.clear_flags()
        attempt = source_attempt(precision_inputs)
        captured = capture_attempt(precision_inputs, attempt)
        capsule = captured["arithmetic_capture"]["payload"]
        checkpoint = capsule["checkpoints"][0]
        assert checkpoint["weighted_return"] == "0.1666666666666666666666666666"
        assert checkpoint["next_cumulative_growth"] == "1.166666666666666666666666667"
        assert checkpoint["cumulative_return_before_quantize"] == "0.166666666666666666666666667"
        qualification = capsule["projection_replay"]
        assert quantity(qualification["mathematical_return"]) == Fraction(1, 6)
        assert quantity(qualification["internal_arithmetic_error"]) == Fraction(1, 3 * 10**27)
        assert quantity(qualification["output_quantization_error"]) == Fraction(1, 3 * 10**12) - Fraction(1, 3 * 10**27)
        before = context_payload(context)
        assert qualify(capsule, captured["response"]) == qualification
        assert context_payload(context) == before
        assert captured["arithmetic_capture"]["digest"] == digest(capsule)


def test_sequential_sticky_flag_and_different_allocations_converge(precision_inputs):
    with decimal.localcontext() as context:
        context.prec = 28
        context.clear_flags()
        first_attempt = source_attempt(precision_inputs)
        first = capture_attempt(precision_inputs, first_attempt)
        second_attempt = source_attempt(precision_inputs)
        assert not first_attempt[2].context["entry_flags"]["Inexact"]
        assert second_attempt[2].context["entry_flags"]["Inexact"]
        assert capture_attempt(precision_inputs, second_attempt) == first
        assert counts(precision_inputs[0]) == (1, 1)
        assert not first["arithmetic_capture"]["payload"]["effective_context"]["entry_flags"]["Inexact"]


@pytest.mark.parametrize("scheduled", [False, True])
@pytest.mark.parametrize("preset", [False, True])
def test_observer_numeric_flag_scope_and_trap_parity(precision_inputs, scheduled, preset):
    with decimal.localcontext() as context:
        context.prec = 28
        context.clear_flags()
        context.flags[decimal.Inexact] = preset
        initial = context.copy()
        plain = source_attempt(precision_inputs, scheduled=scheduled, observe=False)
        plain_exit = context_payload(context)
        decimal.setcontext(initial.copy())
        observed = source_attempt(precision_inputs, scheduled=scheduled)
        observed_exit = context_payload(decimal.getcontext())
        a, b = plain[1].model_dump(mode="json"), observed[1].model_dump(mode="json")
        for value in (a, b):
            del value["calculation_id"]
            del value["selection_manifest"]["calculation_fingerprint"]
        assert a == b
        assert plain_exit == observed_exit
        if scheduled:
            assert observed[2].context["prec"] >= 80
        captured = capture_attempt(precision_inputs, observed)
        assert captured["arithmetic_capture"]["payload"]["context_route"] == (
            "SCHEDULED_COMPONENT_SCOPED" if scheduled else "AMBIENT"
        )


def test_observer_preserves_native_trapped_error_and_flags(precision_inputs):
    for observed in (False, True):
        with decimal.localcontext() as context:
            context.prec = 28
            context.clear_flags()
            context.traps[decimal.Inexact] = True
            with pytest.raises(decimal.Inexact):
                source_attempt(precision_inputs, observe=observed)
            assert context.flags[decimal.Inexact]


def test_real_concurrent_different_id_winner_has_no_orphan(precision_inputs):
    barrier = Barrier(2)

    def run():
        with decimal.localcontext() as context:
            context.prec = 28
            context.clear_flags()
            attempt = source_attempt(precision_inputs)
            barrier.wait(timeout=10)
            return capture_attempt(precision_inputs, attempt)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        first, second = [future.result(timeout=20) for future in futures]
    assert first == second
    assert counts(precision_inputs[0]) == (1, 1)


def test_changed_numeric_context_conflicts_even_when_reported_output_matches(precision_inputs):
    with decimal.localcontext() as context:
        context.prec = 28
        first = capture_attempt(precision_inputs, source_attempt(precision_inputs))
        context.prec = 29
        second = source_attempt(precision_inputs)
        assert (
            second[1].cumulative_return == first["response"]["cumulative_return"]
            or str(second[1].cumulative_return) == first["response"]["cumulative_return"]
        )
        with pytest.raises(APIConflictError, match="arithmetic"):
            capture_attempt(precision_inputs, second)
        assert counts(precision_inputs[0]) == (1, 1)


@pytest.mark.parametrize("boundary", ["analytics_async_result", "composite_result_candidates"])
def test_precision_sidecar_atomic_write_failure(precision_inputs, boundary):
    attempt = source_attempt(precision_inputs)

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith(f"INSERT INTO {boundary}"):
            raise RuntimeError("precision write fault")

    event.listen(precision_inputs[0]._engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="precision write fault"):
            capture_attempt(precision_inputs, attempt)
    finally:
        event.remove(precision_inputs[0]._engine, "after_cursor_execute", fail)
    assert counts(precision_inputs[0]) == (0, 0)
    assert (
        capture_attempt(precision_inputs, attempt)["arithmetic_capture"]["payload"]["projection_replay"]["status"]
        == "MATCHED"
    )


@pytest.mark.parametrize("pointer", ["checkpoint", "context", "fact", "output", "kernel"])
def test_exact_replay_refuses_changed_evidence(precision_inputs, pointer):
    captured = capture_attempt(precision_inputs, source_attempt(precision_inputs))
    capsule, response = copy.deepcopy(captured["arithmetic_capture"]["payload"]), copy.deepcopy(captured["response"])
    if pointer == "checkpoint":
        capsule["checkpoints"][0]["weighted_return"] = "0"
    elif pointer == "context":
        capsule["effective_context"]["rounding"] = "ROUND_DOWN"
    elif pointer == "fact":
        capsule["ordered_facts"][0]["fact"]["return_value"] = "0.6"
    elif pointer == "output":
        response["cumulative_return"] = "0"
    else:
        capsule["algorithm"]["kernel_source_digest"] = "sha256:" + "0" * 64
    with pytest.raises((APIError, ValueError)):
        qualify(capsule, response)


def test_strict_model_nonrecursive_refs_and_unknown_fields(precision_inputs):
    capsule = capture_attempt(precision_inputs, source_attempt(precision_inputs))["arithmetic_capture"]["payload"]
    for change in (
        "self_ref",
        "unknown",
        "signal_missing",
        "signal_integer",
        "runtime_extra",
        "window_extra",
        "control_boolean",
    ):
        bad = copy.deepcopy(capsule)
        if change == "self_ref":
            bad["source_refs"][0]["kind"] = "ARITHMETIC_CAPTURE"
        elif change == "unknown":
            bad["unreviewed_numeric_field"] = "1"
        elif change == "signal_missing":
            del bad["effective_context"]["entry_flags"]["Rounded"]
        elif change == "signal_integer":
            bad["exit_flags"]["Rounded"] = 1
        elif change == "runtime_extra":
            bad["algorithm"]["runtime"]["extra"] = "unknown"
        elif change == "window_extra":
            bad["scope"]["windows"][0]["unknown"] = "not silently discarded"
        else:
            bad["effective_context"]["capitals"] = True
        with pytest.raises(ValidationError):
            CompositeArithmeticCapture.model_validate(bad)


def test_portable_source_kernel_and_named_comparison_exclusions(precision_inputs):
    assert normalized_source(b"first\r\nsecond\r\n") == normalized_source(b"first\nsecond\n")
    with pytest.raises(ValueError):
        normalized_source(b"first\rsecond")
    assert installed_source_digest().startswith("sha256:")
    captured = capture_attempt(precision_inputs, source_attempt(precision_inputs))
    capsule = captured["arithmetic_capture"]["payload"]
    before = comparison_digest(capsule, captured["response"])
    for pointer in COMPARISON_EXCLUSIONS:
        bad = copy.deepcopy(capsule)
        keys = pointer[1:].split("/")
        target = bad
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = {"audit_only": True}
        assert comparison_digest(bad, captured["response"]) == before
    for setting in ("prec", "rounding", "Emin", "Emax", "capitals", "clamp", "traps"):
        bad = copy.deepcopy(capsule)
        bad["effective_context"][setting] = "changed"
        assert comparison_digest(bad, captured["response"]) != before


def test_retained_read_and_replay_do_not_resolve_live_sources(precision_inputs, monkeypatch):
    captured = capture_attempt(precision_inputs, source_attempt(precision_inputs))
    monkeypatch.setattr(
        "app.services.composite_calculation_service.get_composite_materialization_store",
        lambda: pytest.fail("live source read during retained replay"),
    )
    store, results, _, _, principal = precision_inputs
    retained = store.get_result_candidate(
        candidate_id=captured["candidate_id"], tenant_id=principal.tenant_id, result_store=results, principal=principal
    )
    assert retained == captured
    assert qualify(retained["arithmetic_capture"]["payload"], retained["response"])["status"] == "MATCHED"


@pytest.mark.parametrize("boundary", ["analytics_async_result", "composite_result_candidates"])
def test_abrupt_precision_process_failure_leaves_no_half_capture(precision_inputs, boundary):
    store = precision_inputs[0]
    result = subprocess.run(
        [sys.executable, "-m", "tests.benchmarks.composite_candidate_crash_controls", boundary, "precision"],
        env={**os.environ, "LINEAGE_METADATA_DATABASE_URL": store._engine.url.render_as_string(hide_password=False)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 73, result.stdout + result.stderr
    assert "reached_actual_write_boundary=" + boundary in result.stdout
    assert counts(store) == (0, 0)
    assert capture_attempt(precision_inputs, source_attempt(precision_inputs))["arithmetic_capture"]


def test_input_resource_guards_accept_complete_small_input_and_refuse_bad_inputs(precision_inputs):
    attempt = source_attempt(precision_inputs)
    collector = ArithmeticCollector()
    collector.select(attempt[3], attempt[2].windows)
    assert len(collector.facts) == 2
    with pytest.raises(APIError, match="bounded input"):
        collector.select([attempt[3][0]] * 120001, attempt[2].windows)
    large = attempt[3][0].model_copy(update={"source_snapshot_id": "x" * (8 * 1024 * 1024)})
    with pytest.raises(APIError, match="eight MiB"):
        collector.select([large], attempt[2].windows)
    extreme = attempt[3][0].model_copy(update={"return_value": decimal.Decimal("0E+161")})
    with pytest.raises(APIError, match="numeric envelope"):
        collector.select([extreme], attempt[2].windows)
    with decimal.localcontext() as context:
        context.prec = 1000
        high_precision = source_attempt(precision_inputs)
        with pytest.raises(APIError, match="checkpoints"):
            capture_attempt(precision_inputs, high_precision)
    assert counts(precision_inputs[0]) == (0, 0)


def test_installed_source_mutation_is_rejected_without_path_or_line_ending_dependence(monkeypatch):
    from app.adapters.composite_arithmetic_capture import bundle

    assert bundle.installed_source_digest().startswith("sha256:")
    before = bundle.source_manifest
    changed = before()
    changed["files"][0]["sha256"] = "0" * 64
    monkeypatch.setattr(bundle, "source_manifest", lambda: changed)
    with pytest.raises(ValueError, match="trusted manifest"):
        bundle.installed_source_digest()


def test_strict_capture_decoder_rejects_duplicate_keys_and_nonfinite_tokens():
    from app.adapters.composite_arithmetic_capture.codec import decode

    assert decode('{"version":"v1"}') == {"version": "v1"}
    for value in ('{"version":"v1","version":"v2"}', '{"return":NaN}', '{"return":0.5}'):
        with pytest.raises(ValueError):
            decode(value)


def test_complete_candidate_and_rational_guards_have_valid_and_invalid_controls(precision_inputs):
    from app.adapters.composite_arithmetic_capture import storage
    from app.services.composite_arithmetic_capture.replay import bounded_fraction

    captured = capture_attempt(precision_inputs, source_attempt(precision_inputs))
    row = type("ReceiptRow", (), captured)()
    row.arithmetic_capture_digest = captured["arithmetic_capture"]["digest"]
    payload = captured["arithmetic_capture"]["payload"]
    storage.require_candidate_bounds(row, captured["response"], payload)
    oversized_response = copy.deepcopy(captured["response"])
    oversized_response["methodology"] = "x" * storage.MAX_CAPTURE_BYTES
    with pytest.raises(APIError, match="complete candidate"):
        storage.require_candidate_bounds(row, oversized_response, payload)
    assert bounded_fraction(Fraction(1, 6)) == Fraction(1, 6)
    with pytest.raises(APIError, match="rational envelope"):
        bounded_fraction(Fraction(1, 2**13600))


def test_preset_flags_converge_but_source_order_and_own_exit_flags_remain_evidence(precision_inputs):
    with decimal.localcontext() as context:
        context.prec = 28
        context.clear_flags()
        first = capture_attempt(precision_inputs, source_attempt(precision_inputs))
        context.flags[decimal.Subnormal] = True
        assert capture_attempt(precision_inputs, source_attempt(precision_inputs)) == first
    capsule = copy.deepcopy(first["arithmetic_capture"]["payload"])
    before = comparison_digest(capsule, first["response"])
    capsule["ordered_facts"].reverse()
    assert comparison_digest(capsule, first["response"]) != before
    capsule = copy.deepcopy(first["arithmetic_capture"]["payload"])
    capsule["exit_flags"]["Rounded"] = not capsule["exit_flags"]["Rounded"]
    assert comparison_digest(capsule, first["response"]) == before
    with pytest.raises(APIError, match="status flags"):
        qualify(capsule, first["response"])
