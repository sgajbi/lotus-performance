"""One pending-only source-pinning transition for retained FX and model methods."""

from app.adapters.composite_member_result_source import member_outcome
from app.models.composite_materialization import CompositeMaterializationState, CompositeMemberOutcomeState
from core.errors import APIError


def pin_currency_source(record, *, tenant_id, ledger, fence):
    from app.services.composite_materialization.currency_source_admission import (
        admit_composite_fx_source,
        fx_resolution_for_command,
        require_composite_native_currency,
        require_fx_normalization_route,
    )

    def source_wire():
        require_fx_normalization_route(record.source.definition)
        admitted = admit_composite_fx_source(fx_resolution_for_command(record.command, tenant_id=tenant_id))
        require_composite_native_currency(admitted, record.source.definition)
        return admitted.source_wire

    return _pin_source_wire(
        record,
        binding="currency_normalization_binding",
        wire="currency_normalization_wire",
        code="COMPOSITE_CURRENCY_SOURCE",
        refusal_code="COMPOSITE_FX_SOURCE_REFUSED",
        resolve=source_wire,
        tenant_id=tenant_id,
        ledger=ledger,
        fence=fence,
    )


def pin_model_fee_source(record, *, tenant_id, ledger, fence):
    from app.services.composite_materialization.model_fee_source_admission import admit_model_fee_source

    return _pin_source_wire(
        record,
        binding="model_fee_binding",
        wire="model_fee_wire",
        code="COMPOSITE_MODEL_FEE_SOURCE",
        refusal_code="COMPOSITE_MODEL_FEE_SOURCE_REFUSED",
        resolve=lambda: admit_model_fee_source(record.source, record.command, tenant_id=tenant_id).source_wire,
        tenant_id=tenant_id,
        ledger=ledger,
        fence=fence,
    )


def _pin_source_wire(record, *, binding, wire, code, refusal_code, resolve, tenant_id, ledger, fence):
    if getattr(record.command, binding) is None or getattr(record.source, wire) is not None:
        return record
    try:
        resolved = resolve()
    except APIError as error:
        fence()
        ledger.save(
            record.command.materialization_id,
            tenant_id=tenant_id,
            expected_revision=record.revision,
            source=record.source,
            outcomes=_refusal_outcomes(record.outcomes, error, default_code=refusal_code),
            state=CompositeMaterializationState.WAITING if error.retryable else CompositeMaterializationState.BLOCKED,
            reason_code=code + ("_UNAVAILABLE" if error.retryable else "_REFUSED"),
        )
        raise
    fence()
    return ledger.save(
        record.command.materialization_id,
        tenant_id=tenant_id,
        expected_revision=record.revision,
        source=record.source.model_copy(update={wire: resolved}),
        outcomes=record.outcomes,
        state=CompositeMaterializationState.WAITING,
        reason_code="COMPOSITE_MEMBERS_PENDING",
    )


def _refusal_outcomes(outcomes, error, *, default_code):
    return [
        member_outcome(
            row.portfolio_id, code=error.error_code or default_code, retryable=bool(error.retryable)
        ).model_copy(update={"inspection_attempts": row.inspection_attempts})
        if row.state == CompositeMemberOutcomeState.WAITING
        else row
        for row in outcomes
    ]
