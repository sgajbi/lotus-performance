"""Cross-field bindings for exact source evidence; no live source resolution."""


def retained_refs(windows, tenant):
    return [
        {
            "kind": "RETAINED_MATERIALIZATION",
            "owner": "lotus-performance",
            "tenant_id": tenant,
            "materialization_id": item["materialization_id"],
            "retained_receipt_fingerprint": item["retained_receipt_fingerprint"],
            "source_cut_id": item["source_cut_id"],
        }
        for item in windows
    ]


def validate_vector(payload, response):
    windows = response["selection_manifest"]["windows"]
    scope = payload["scope"]
    if scope["windows"] != windows:
        raise ValueError("Arithmetic capture window binding differs")
    if scope["materialization_vector"] != [item["materialization_id"] for item in windows]:
        raise ValueError("Arithmetic capture vector differs")
    _request_binding(payload, response)
    _period_basis(scope, response)
    _fact_coverage(payload, windows)
    if payload["source_refs"] != retained_refs(windows, payload["source"]["tenant_id"]):
        raise ValueError("Arithmetic capture source references differ")


def _request_binding(payload, response):
    request, scope = payload["calculation_request"], payload["scope"]
    keys = ("composite_id", "period_start", "period_end")
    expected = tuple(response[key] for key in keys)
    if tuple(scope[key] for key in keys) != expected or tuple(request[key] for key in keys) != expected:
        raise ValueError("Arithmetic request/response scope differs")
    actual = (
        request["calculation_id"],
        request["materialization_ids"],
        request["return_view"],
        payload["algorithm"]["engine_version"],
        payload["projection_replay"]["input_digest"],
    )
    expected = (
        payload["source"]["calculation_id"],
        scope["materialization_vector"],
        scope["return_view"],
        response["selection_manifest"]["engine_version"],
        payload["input_digest"],
    )
    if actual != expected or request["reporting_currency"] not in (None, scope["reporting_currency"]):
        raise ValueError("Arithmetic request/method binding differs")


def _period_basis(scope, response):
    bases = {(item["return_view"], item["reporting_currency"]) for item in response["periods"]}
    if bases != {(scope["return_view"], scope["reporting_currency"])}:
        raise ValueError("Arithmetic period basis differs")


def _fact_coverage(payload, windows):
    keys = set()
    for index, item in enumerate(payload["ordered_facts"]):
        if item["window_ordinal"] >= len(windows):
            raise ValueError("Arithmetic window ordinal is absent")
        fact, window = item["fact"], windows[item["window_ordinal"]]
        _fact_binding(index, item, payload["scope"], window)
        key = (item["window_ordinal"], fact["portfolio_id"])
        if key in keys:
            raise ValueError("Duplicate arithmetic member occurrence")
        keys.add(key)


def _fact_binding(index, item, scope, window):
    fact = item["fact"]
    actual = (
        item["ordinal"],
        fact["composite_id"],
        fact["period_start"],
        fact["period_end"],
        fact["return_view"],
        fact["reporting_currency"],
    )
    expected = (
        index,
        scope["composite_id"],
        window["period_start"],
        window["period_end"],
        scope["return_view"],
        scope["reporting_currency"],
    )
    if actual != expected:
        raise ValueError("Arithmetic capture fact order/scope differs")
