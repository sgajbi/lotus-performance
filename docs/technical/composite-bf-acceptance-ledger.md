# Composite BF acceptance ledger

Issue [633](https://github.com/sgajbi/lotus-performance/issues/633) remains open.
PR [647](https://github.com/sgajbi/lotus-performance/pull/647) delivered the bounded single-period
arithmetic BF implementation. Its qualified main revision is
`02b3001ac9c8df8b6c6944cfe3f67f8f768e55a6`; that release does not establish all of issue 633's
source and downstream acceptance.

## Acceptance and remaining evidence

| Original criterion | Established boundary | Remaining evidence |
| --- | --- | --- |
| OR17 and every group effect | Independent arithmetic oracle, existing BF kernel, registered API and PostgreSQL original replay; decimal return units and `FLOAT64` execution | Financial acceptance of institution-supplied observations and elected policy remains separate from the synthetic oracle. |
| Original and corrected replay | Registered worker, real PostgreSQL, immutable retained inputs/results, fresh process, corrected benchmark/classification/member identity | Institution-supplied historical revisions and export custody have not been exercised as a joined producer flow. |
| Full population and financial refusals | Registered endpoint/worker refusal matrix below, plus existing precision, tenant, source identity and current-selection boundary tests | These are controlled source-port fixtures, not certification of an external source adapter. |
| Unsupported conventions | Zero/signed weights, off-benchmark groups and derivatives refuse before the kernel; observed zero and negative benchmark returns remain valid | Other conventions require separately elected methodology and observations. Fixed income, factors, linked attribution and currency attribution are subsequent increments. |
| Dataset and consumer preservation | Existing result endpoint retains full effects, units, method, original source bundle and approval; source-free original replay | Named OpenAPI request/accepted/ready/refusal families and capability example certification need closure. Actual Gateway/Report consumption, including unavailable states, needs joined consumer evidence. |
| Documentation | Caller guide, v3 method, executable OR17 output, source custody/replay diagrams and correction guidance | Keep named endpoint examples and any eventual downstream publication contract synchronized with executable behavior. |
| Source and financial authority | Deployment defaults refuse unavailable historical source and independent BF-purpose authority; synthetic qualification stays explicit | An actual source-owner adapter, independently approved BF-purpose policy and verifier, and their institutional acceptance have not been supplied or certified. |

The existing retained result endpoint is not an approved extension of the
`CompositePerformanceAnalytics:v1` TWR data product or `AttributionAnalytics:v1` portfolio
product. A new consumer binding requires its own reviewed publication contract. Report issue
[417](https://github.com/sgajbi/lotus-report/issues/417) owns the Composite review reporting
lifecycle; this ledger does not grant reporting acceptance or introduce a Report calculator.

## Registered financial-source refusal matrix

`tests/composite_attribution_refusal_helpers.py` owns the case identities and their exact error
codes. Both `tests/integration/test_composite_attribution_api.py` and
`tests/benchmarks/test_postgres_composite_attribution.py` execute the same cases through the
registered `POST /performance/composites/analytics`, existing worker and retained result `GET`.

The cases cover:

- missing included member, member/group observation, pooled group or expected benchmark group;
- omitted source components and a missing source page;
- zero or short pooled/benchmark weights, short member/group exposure, and derivatives;
- incompatible currency, fee view, period, policy currency or policy effective window;
- missing actual member/group, pooled-group or benchmark return in the consumed original wire;
- pooled group return inconsistent with the supplied member observations.

Each source cut is a validated source DTO with current signed **synthetic** BF-purpose evidence.
Missing-wire cases keep the changed wire's payload digest and approval valid while preserving
the discrepancy with its claimed normalized observation. This distinguishes an absent observed
return from an unsigned packet or a legitimate observed zero. Refusals must produce the exact
typed error, never enter the numerical kernel, and leave neither retained attribution input nor
financial result. Positive controls retain zero/negative benchmark returns, all original source
fields, units and method, and replay after source withdrawal.

Existing independent tests retain the strict-precision, two-tenant, conflicting revision,
stale-selection and correction boundaries; this matrix does not replace them.

## Scope decisions

This slice changes test evidence and the acceptance ledger. It changes no financial method,
runtime source provider, public schema, downstream publication contract, workflow or guard.
No wiki change is required: the published caller behavior, supported features and source
qualification are unchanged. No platform context or skill change is required: the existing
endpoint certification and real PostgreSQL contract lanes already govern this work.

Validation uses the existing focused API/unit suites and the registered
`tests/benchmarks/test_postgres_composite_attribution.py` target of
`scripts/postgres_concurrency_contracts_gate.py`. Hosted protected PR and exact-main checks
remain the release evidence; local synthetic results alone do not close issue 633.
