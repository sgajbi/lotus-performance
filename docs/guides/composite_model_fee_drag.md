# Composite model-fee drag

Submit `MODEL_FEE_DRAG` to `POST /performance/composites/analytics` with the existing tenant header
and the exact complete chronological `NET_MODEL_FEE` materialization vector. Gross is taken from
the original receipts retained with those same model facts. The method is
`ADDITIVE_GROSS_MINUS_MODEL:v1`; no new schedule, current gross source or fee override is accepted.

The [complete request and response example](../../app/api/examples/composite_fee_drag.json) is also
published as the OpenAPI `model_fee_drag` example. Its identifiers refer to synthetic test records,
not deployed records. Use your own admitted materialization IDs. Missing records return 404;
invalid views, methods, mixed bindings and incomplete vectors return 422 without financial output.

The [methodology](../methodologies/metrics/metric-composite-model-fee-drag.md) defines units and
calculation steps. Period drag is gross minus model-net return. Horizon drag subtracts separately
linked gross and model-net returns; do not sum period drag. The response includes full method
binding, original gross/model receipt pairs and the selection manifest. Preserve all of these for
audit and replay. Monetary fee amounts cannot be inferred from this return difference.

This is a retained-source calculated analysis, not live institutional qualification. The
[configured receipt verifier](composite_receipt_verification.md) supports signed synthetic
method/calendar receipts only. Missing policy and financial-source verifier peers still refuse
materialization. Whole-cost component supplier admission and real institutional authority remain
separate unresolved requirements.

From the `lotus-performance` repository root, Windows PowerShell or POSIX:

```text
python -m pytest tests/unit/services/test_composite_fee_drag.py tests/integration/test_composite_fee_drag_application.py tests/integration/test_composite_receipt_verifier_admission.py -q
```

Tests exercise registered HTTP dispatch, exact complete example bodies, tenant refusal, changed
binding, reopen/replay, original receipt pins, scheduled and periodic source methods and zero fees.
The published example fixes synthetic IDs and upstream retrieval-recording time before storage;
production calculation and receipt hashes are not normalized.
