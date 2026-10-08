"""Controlled source wires; no production fixing authority."""

from app.models.composite_authority import authority_digest
from app.models.composite_currency_normalization import CompositeFXVerificationReceipt
from app.ports.composite_currency_normalization import CompositeFXVerificationExpectation, VerifiedCompositeFXEvidence
from app.services.composite_materialization.currency_source_admission import verification_request_digest


def synthetic_fx_verification(request):
    expectation = CompositeFXVerificationExpectation(
        request=request,
        verifier_id="test-fx-verifier",
        issuer_id="test-fx-issuer",
        artifact_revision="approval1",
        artifact_digest="sha256:" + "9" * 64,
    )
    wire = {
        "product_name": "CompositeFXVerificationReceipt",
        "product_version": "v1",
        "qualification": "SYNTHETIC_TEST_ONLY",
        "official_activation": "UNAVAILABLE",
        "tenant_id": request.resolution.tenant_id,
        "composite_id": request.resolution.composite_id,
        "verifier_id": expectation.verifier_id,
        "issuer_id": expectation.issuer_id,
        "artifact_revision": expectation.artifact_revision,
        "artifact_digest": expectation.artifact_digest,
        "source_digest": request.source_digest,
        "method_digest": request.method_digest,
        "request_digest": verification_request_digest(request),
    }
    wire["content_hash"] = authority_digest(wire)
    return VerifiedCompositeFXEvidence(
        expectation=expectation, verification_receipt=CompositeFXVerificationReceipt.model_validate(wire)
    )


def normalization_wire():
    calendar = {
        "product_name": "Calendar",
        "product_version": "v1",
        "revision": "natural1",
        "digest": "sha256:" + "a" * 64,
    }
    method = {
        "product_name": "CompositeFXMethod",
        "product_version": "v1",
        "revision": "method1",
        "effective_from": "2026-01-01",
        "effective_to": "2026-01-31",
        "mode": "UNHEDGED",
        "return_method": "EXISTING_DAILY_MEMBER_ENGINE",
        "calendar": "NATURAL_DAILY",
        "calendar_binding": calendar,
        "fixing_timezone": "UTC",
        "fixing_time_utc": "21:00:00",
        "maximum_observation_age_seconds": 60,
        "return_fixing": "EXACT_PRIOR_AND_CURRENT_EOD",
        "beginning_asset_fixing": "PRIOR_DAY_EOD",
        "ending_asset_fixing": "VALUATION_DAY_EOD",
        "flow_fixing": "ECONOMIC_DAY_EOD",
        "supported_flow_placement": "END_OF_DAY",
        "monetary_precision": "DECIMAL_STRICT_NO_INTERMEDIATE_ROUNDING",
    }
    fixings = [
        {
            "fixing_date": day,
            "source_currency": "EUR",
            "reporting_currency": "USD",
            "quote_direction": "REPORTING_UNITS_PER_SOURCE_UNIT",
            "rate": rate,
            "observed_at": day + "T21:00:00Z",
            "revision_available_at": day + "T21:01:00Z",
            "provider_id": "synthetic-fx-provider",
            "source_product": "SyntheticFXFixings",
            "source_revision": "rates1",
            "source_cut_id": "cut1",
            "source_watermark": "watermark1",
            "source_content_hash": "sha256:" + "b" * 64,
            "fixing_kind": "EOD",
            "calendar_binding": calendar,
            "provenance": "DIRECT",
        }
        for day, rate in [("2026-01-04", "1.3"), ("2026-01-05", "1.4")]
    ]
    return {
        "product_name": "CompositeFXNormalizationSource",
        "product_version": "v1",
        "tenant_id": "tenant-a",
        "composite_id": "COMPOSITE",
        "revision": "normalization1",
        "definition_content_hash": "sha256:" + "c" * 64,
        "membership_content_hash": "sha256:" + "d" * 64,
        "attestation_content_hash": "sha256:" + "e" * 64,
        "source_cut_id": "cut1",
        "source_as_of_cut": "2026-01-06T01:00:00Z",
        "period_start": "2026-01-05",
        "period_end": "2026-01-05",
        "composite_native_currency": "USD",
        "reporting_currency": "USD",
        "return_view": "GROSS",
        "method": method,
        "method_binding": {
            "product_name": "CompositeFXMethod",
            "product_version": "v1",
            "revision": "method1",
            "digest": authority_digest(method),
        },
        "members": [
            {
                "member_id": "A",
                "portfolio_reference_currency": "GBP",
                "source_money_currency": "EUR",
                "input_fingerprint": "sha256:" + "f" * 64,
                "calculation_hash": "sha256:" + "0" * 64,
                "conversion_kind": "DIRECT",
                "fixings": fixings,
            }
        ],
    }
