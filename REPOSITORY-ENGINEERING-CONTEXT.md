# Repository Engineering Context

This file provides repository-local engineering context for `lotus-performance`.

Agent and engineer orientation:

1. Start with `AGENTS.md`; it is the governed operating contract and mandatory reading-order
   source.
2. Treat this file as step 4 in that sequence: repo-local implementation truth after platform
   quickstart and engineering context are loaded.
3. Use `../lotus-platform/context/CONTEXT-REFERENCE-MAP.md` to find relevant standards, RFCs,
   runbooks, and registries without loading broad context blindly.
4. Use `../lotus-platform/context/PROCEDURAL-MEMORY-INDEX.md` when the task is primarily about
   execution method, PR loops, fix-forward work, validation depth, or long-running task handoff.
5. Consult `../lotus-platform/context/LOTUS-SKILL-ROUTING-MAP.md` before choosing between
   overlapping Lotus skills.

## Repository Role

`lotus-performance` is the authoritative performance analytics service in Lotus.

It owns benchmark-aware performance calculations, contribution, attribution, returns series, execution tracking, and lineage capture for performance workflows.
Its benchmark exposure context integration surface supports `POSITION`, `SECTOR`, `ASSET_CLASS`,
and `ISSUER` grouping dimensions at `frequency=DAILY`; issuer grouping is a performance-owned
derived view over lotus-core index-catalog `classification_labels.issuer_id` and `issuer_name`
source labels.

## Business And Domain Responsibility

This repository owns:

1. time-weighted and money-weighted return workflows,
2. benchmark analytics,
3. contribution and attribution analytics,
4. mandate performance health context for bounded DPM supportability consumption,
5. performance execution lifecycle tracking,
6. performance lineage and reproducibility evidence.

## Current-State Summary

Current repository posture:

1. `lotus-performance` is the authoritative performance analytics engine consumed by `lotus-gateway`,
2. stateful integration with `lotus-core` is active and classified under the RFC-0082 upstream contract-family map,
3. the service already operates with enterprise-grade CI posture including security, migration,
   Docker gates, and container supply-chain evidence,
4. async execution, lineage capture, and benchmark-aware workflows are real parts of the contract, not future placeholders,
5. repo-native domain-product producer and consumer declarations now live under `contracts/domain-data-products/`
   with local validation through `make domain-product-validate`,
6. RFC-0087 trust telemetry proof lives under `contracts/trust-telemetry/` for every active
   governed producer product declared in
   `contracts/domain-data-products/lotus-performance-products.v1.json`, or must carry an explicit
   machine-readable exception policy before the product is treated as governed. The coverage rule
   is documented in `contracts/trust-telemetry/README.md` and enforced by
   `tests/unit/test_trust_telemetry.py` against repo-native declarations and, when available, the
   platform trust telemetry validator,
7. the TWR inspection supportability contract can now preserve bounded Lotus AI workflow-pack run
   posture and the optional `support_brief.md` artifact without making the inspection verdict
   dependent on Lotus AI availability,
8. completed TWR, MWR, contribution, and attribution responses expose the shared
   `calculation_supportability` block, publish the allowed `metric_labels`, and emit the bounded
   `lotus_performance_calculation_supportability_total` metric for front-office freshness and
   degraded-state handling. Tests prove the Prometheus exposition uses only bounded labels and does
   not promote portfolio, account, client, trace, correlation, calculation, benchmark, security, or
   request/response payload values into metric labels.
9. attribution emits `currency_attribution_totals` when the Karnosky-Singer
   `currency_mode=BOTH` path is source-ready, giving downstream Gateway, Workbench, reporting, and
   manage consumers a source-owned portfolio-level FX attribution total instead of requiring local
   row summation.
10. stateless MWR accepts complete `source_preconverted_fx_evidence`, validates per-input FX
    provenance for beginning market value, ending market value, and every cash flow, and emits
    `currency_evidence` while preserving the engine boundary that MWR calculates one
    reporting-currency schedule and does not perform in-engine FX conversion.
11. stateful contribution and attribution normalize source `position_currency`,
    `cash_flow_currency`, and `report_ccy` values by trimming whitespace and uppercasing before
    mixed-currency FX gating or cash-flow/position-currency comparison. Blank source currency
    metadata is treated as missing, not as a synthetic currency code.
12. `SI` is the canonical since-inception period code across current performance request examples,
    response keys, demo certification, and period resolution. Legacy `ITD`, `INCEPTION_TO_DATE`,
    and `SINCE_INCEPTION` aliases are accepted only as compatibility inputs and normalize to `SI`
    before calculations, lineage windows, or response metadata are built.
13. `MandatePerformanceHealthContext:v1` is a bounded performance-owned data product at
    `POST /performance/mandate-health-context` for DPM supportability consumers. It emits
    active-return threshold posture, methodology posture, request fingerprint, and reason codes;
    it does not create mandate actions, rebalance waves, client communications, orders, OMS
    actions, or execution instructions.
14. stateful contribution consumes `lotus-core:PerformanceComponentEconomics:v1` as optional
    source-economics evidence for cashflow, fee, income, tax, realized P&L, and FX-context
    component-family supportability. The consumer must traverse Core component-economics pages,
    preserve source rows, lineage, request fingerprints, retrieval metadata, and consumed-page
    totals, and use observed component families for source-backed contribution evidence only when
    the relevant position context contains actual Core-authored `source_rows`.
    `lotus-performance` still owns contribution methodology and treats non-200 or unavailable
    component-economics responses as degraded evidence rather than as a required-input failure.
15. `ReturnsSeriesBundle:v1` exposes source-owned return-series diagnostics for downstream
    consumers. `diagnostics.coverage` remains the coverage-quality signal, while
    `diagnostics.freshness` is the bounded freshness signal (`current` or `stale`) derived from
    source warnings so consumers such as `lotus-risk` and `lotus-idea` can preserve Performance
    evidence without reinterpreting return-series recency locally.
16. Benchmark composition-window and index price-series dependencies are repo-native active
    consumer declarations through `BenchmarkConstituentWindow:v1` and `IndexSeriesWindow:v1`.
    Benchmark definition, benchmark vendor return-series, index catalog, and FX operational-read
    dependencies remain governed by `docs/technical/RFC-0082-upstream-contract-family-map.md`
    until matching upstream producer declarations are onboarded for repo-native consumer coverage.
17. HTTP boundary hardening is centralized in `app.http_security`: `HTTP_ALLOWED_HOSTS` controls
    host allow-listing, `CORS_ALLOWED_ORIGINS` controls explicit browser origins, standard security
    headers are emitted on success and error responses, and `HTTP_SECURITY_HSTS_ENABLED` is used
    only when the service owns the HTTPS boundary rather than delegating TLS to ingress. Local
    canonical Docker deployments must allow `host.docker.internal` because `lotus-gateway` reaches
    `lotus-performance` through that Docker-to-host alias.
18. API runtime serialization uses standard FastAPI/Pydantic response-model behavior. Do not add
    global null stripping: OpenAPI nullable fields must be returned as explicit JSON `null` values
    unless a route explicitly documents sparse `response_model_exclude_none=True` behavior.
19. MWR cash-flow methodology is source-owned and window-bounded. Stateless MWR rejects cash-flow
    dates outside the resolved measurement window with `MWR_CASH_FLOW_OUT_OF_WINDOW`; stateful MWR
    uses the selected stateful input window, preserves source transaction/event lifecycle identity
    when supplied by `lotus-core`, reports bounded `source_cashflow_quality` inclusion/exclusion
    counts, and treats absent lifecycle identity as explicit supportability posture. Dietz
    annualization honors explicit `periods_per_year` first, then day-count conventions including
    `BUS/252`.

## Architecture And Module Map

Primary areas:

1. `app/`
   API and runtime application layer.
2. `engine/`
   Analytics and execution internals.
3. `core/`
   domain and calculation foundations.
4. `adapters/`
   integration seams and storage/runtime adapters.
5. `docs/`
   service guides, methodology, and technical runtime docs.
6. `contracts/trust-telemetry/`
   Repo-native RFC-0087 trust telemetry fixtures for governed first-wave performance products.
7. `wiki/`
   canonical authored source for GitHub wiki publication and repo-operator onboarding summaries.
8. `scripts/`
   quality gates, migration checks, and dependency-health tooling.
9. `tests/`
   unit, integration, e2e, and benchmark or characterization coverage.

## Runtime And Integration Boundaries

Runtime model:

1. API service plus compute, lineage, and storage/runtime components,
2. consumed primarily through `lotus-gateway`,
3. depends on `lotus-core` for stateful portfolio and benchmark sourcing.

Boundary rules:

1. performance analytics authority stays here,
2. gateway and UI should consume governed outputs rather than reimplement analytics logic,
3. async and lineage behavior are contract features and should remain explicit,
4. benchmark and stateful integration behavior must remain truthful and documented,
5. `lotus-core` must be consumed as a governed source-data and analytics-input authority, not as a provider of performance conclusions,
6. `PerformanceComponentEconomics:v1` evidence may improve contribution source-economics coverage
   only from complete, row-level Core evidence. Aggregate supportability family names without
   preserved source rows must not clear unsupported contribution economics, and the product must
   not be relabeled as contribution analytics, attribution analytics, performance returns, or full
   price/FX attribution.
7. MWR methodology, source cash-flow normalization, supportability evidence, and lifecycle identity
   projection remain design modules inside the existing performance service. Do not split them into
   a separate runtime service unless there is concrete evidence for independent scaling, failure
   isolation, security ownership, deployment cadence, or operator lifecycle boundaries.

## Repo-Native Commands

Use these commands as the primary local contract:

1. install
   `make install`
2. fast local gate
   `make check`
3. PR-grade local gate
   `make ci`
4. Docker-parity local gate
   `make ci-local`
5. full local test and characterization gate
   `make test-all`
6. run locally
   `make run`
7. repo-native domain-product declaration validation
   `make domain-product-validate`
8. report-only enterprise refactor quality baseline refresh
   `make quality-baseline`
9. demo API certification
   `make demo-api-certification`
10. repo-native observability-readiness marker gate
   `make quality-observability-readiness-gate`
11. repo-native repository hygiene gate
   `make repository-hygiene-gate`
12. report-only branch coverage baseline
   `make branch-coverage-baseline`
13. CI coverage shard target
   `make test-coverage-shard SUITE=<unit|integration|e2e> TEST_PATH=<tests/path>`
14. CI coverage artifact combine gate
   `make coverage-combine-gate COVERAGE_INPUTS=<coverage-paths> COVERAGE_FAIL_UNDER=99`

## Validation And CI Expectations

`lotus-performance` uses explicit CI lanes:

1. `Remote Feature Lane`
2. `Pull Request Merge Gate`
3. `Main Releasability Gate`

Important validation expectations:

1. OpenAPI and API vocabulary governance are active,
2. migration smoke and project-scoped dependency health are required,
3. unit, integration, e2e, coverage, Docker build, and container supply-chain evidence are part of
   the real merge contract,
4. analytics quality and runtime characterization matter because downstream product surfaces depend on the truthfulness of these results,
5. repo-native domain-product declaration validation is part of local ownership proof for RFC-0086 rollout,
6. public documentation is regression-tested and README or guide reshaping should preserve governed
   contract truth unless the underlying repo truth is intentionally changing.
7. `make lint` includes `scripts/check_monetary_float_usage.py`; that guard matches allowlisted
   findings by file path and source expression, not line number alone. When refactoring existing
   reviewed monetary-float conversions, preserve the reviewed expression or remediate the float use
   rather than refreshing `docs/standards/monetary-float-allowlist.json` as incidental churn.
8. `make lint` includes `make repository-hygiene-gate`, which blocks tracked local byproducts such
   as Python caches, virtual environments, local coverage files, build outputs, logs, and local
   database files. `make clean` delegates to `scripts/clean_generated_artifacts.py` and removes
   ignored runtime/evidence roots such as `artifacts/`, `output/`, and `lineage_data/` plus local
   SQLite/log sidecars while preserving source truth under `docs/`, `contracts/`, `wiki/`, and
   `quality/`, so cleanup behavior remains reviewable and test-backed.
9. `make lint` includes `make github-action-runtime-guard`, which blocks stale GitHub artifact
   action majors and any workflow job missing a role-sized `timeout-minutes` value. New workflow
   jobs must declare bounded execution budgets rather than relying on GitHub's broad platform
   default timeout.
10. `make quality-baseline` is the single local report-only baseline refresh command for the
   enterprise refactor stream. It runs `scripts/generate_quality_baseline.py --write`, writes raw
   scanner snapshots under ignored `output/quality-baseline/`, and refreshes
   `quality/baseline_report.md`. The Quality Baseline Snapshot workflow calls this same target so
   local and GitHub evidence stay aligned, while `quality/refactor_health_report.md` and
   `quality/quality_scorecard.md` remain curated source reports updated by meaningful slices.
11. `make demo-api-certification` is the single local demo-readiness API sweep. It calls the
   supported demo-critical calculation and integration APIs with deterministic synthetic data,
   seeds composite persisted-fact data repeatably, validates expected figures and capability
   publication, and writes reviewed evidence under `output/demo-api-certification/`. The Quality
   Baseline Snapshot workflow runs it as report-only CI evidence and uploads the JSON artifact; it
   is not yet a blocking readiness gate. The audience-facing evidence review guide is
   `docs/guides/demo_readiness.md`.
12. `make quality-observability-readiness-gate` blocks missing health/metrics endpoint,
   correlation propagation, structured logging, metrics, health/readiness implementation markers,
   deployable Prometheus alert rules, dashboard panels, alert/dashboard metric references, links,
   and sensitive-label regressions through
   `scripts/python_observability_readiness_inventory.py --max-missing 0`. Broader observability
   maturity scoring remains measured in `quality/observability_readiness_inventory.md` rather than
   claimed as complete.
13. `make branch-coverage-baseline` is the report-only branch coverage measurement path. It runs
    unit, integration, and e2e suites with `pytest --cov-branch`, writes raw JSON under
    `output/branch-coverage/`, and refreshes `quality/coverage_inventory.md`. The current baseline
    is measured but not enforced; branch-coverage threshold, exception policy, and CI lane placement
    require separate governance before promotion.
14. PR Merge Gate and Main Releasability route matrix test coverage through
    `make test-coverage-shard` and combined coverage enforcement through `make coverage-combine-gate`
    so workflow YAML does not become a second source of truth for pytest or coverage behavior.
    `make quality-test-taxonomy-gate` now enforces the current measured preservation baseline
    directly: at least `648` API/runtime test functions, at least `127` contract/governance test
    functions, and no more than `982` uncategorized test functions.
15. `make container-supply-chain-evidence` is the repo-native container release-evidence command.
    It builds `lotus-performance:ci`, writes a CycloneDX SBOM and high/critical Trivy vulnerability
    report under ignored `output/container-security/`, and is published by PR Merge Gate and Main
    Releasability. Main Releasability also attests SBOM provenance. `make
    container-vulnerability-gate` exists for later strict promotion after the first PR/main image
    baseline and high/critical exception policy are reviewed.
16. `PR Auto Merge` must use `LOTUS_AUTOMERGE_TOKEN` as the merge actor. If that governed token is
    absent, the workflow skips with a warning instead of merging with `GITHUB_TOKEN`, so the merged
    mainline commit can receive normal Main Releasability evidence from an authorized merge actor.
17. `ENTERPRISE_RUNTIME_PROFILE=production`, `prod`, or `staging` is production-like and fails
    startup when enterprise write authz, privileged-read authz, runtime-config enforcement, or
    `ENTERPRISE_PRIMARY_KEY_ID` is missing. Local relaxed mode remains explicit through
    `ENTERPRISE_RUNTIME_PROFILE=local` or an unset runtime profile with disabled authz switches.
18. Lineage inventory and TWR inspection evidence endpoints are controlled evidence-access
    surfaces. When privileged-read authz is enabled, `/performance/lineage/{calculation_id}`,
    `/performance/lineage/{calculation_id}/artifacts/{artifact_name}`,
    `/performance/inspections/{inspection_id}`, and
    `/performance/inspections/{inspection_id}/artifacts/{artifact_name}` require
    `operations.runtime.read` through the central enterprise capability rule map.
19. Execution polling and endpoint-specific async result retrieval use the shared
    `app.services.calculation_result_access` policy. When privileged-read authz is enabled,
    callers need enterprise identity plus either `operations.runtime.read` or `X-Portfolio-Id`
    matching the durable execution `portfolio_id`; a calculation id alone is not an authorization
    boundary.
20. Compute-worker success finalization is recoverable. The worker publishes the successful async
    result before marking the compute job complete, never treats a post-success job-completion
    failure as a calculation failure, and reconciles stale compute jobs with an existing successful
    async result to `complete` instead of overwriting the result with a terminal failure.
21. Durable worker and operator-action finalization is ownership-aware. Compute-job finalization,
    lineage payload completion/deletion, and governed operator-action lock release must compare the
    active lease owner or acquisition token before mutating terminal state, deleting work, or
    exposing async/lineage success evidence after stale reclaim.
22. Runtime-retention cleanup is a database-native durable-store workflow. Async-result and
    compute-job preview/apply paths use count and set-based delete operations, execution and
    lineage paths enumerate calculation ids only where child rows or artifact directories require
    deterministic cleanup, and durable schema creation repairs the retention indexes for existing
    runtime stores.
23. Lineage inspection list queries are query-plan governed operator paths. Active, failed, all,
    and reclaimable inspection statements must keep `calculation_type` filters index-backed through
    lineage-record and lineage-payload composite indexes; PostgreSQL plan-contract tests cover the
    active, failed, all, and reclaimable statements, allowing derived-order sorts only where the
    view orders by computed active-since age.
24. Upstream lotus-core and Lotus AI HTTP calls use the shared resilience layer and, under the
    FastAPI lifespan, a managed `httpx.AsyncClient` pool keyed by timeout. Stateful chunked
    retrieval should tune `STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS` together with
    `UPSTREAM_HTTP_MAX_CONNECTIONS`, `UPSTREAM_HTTP_MAX_KEEPALIVE_CONNECTIONS`, and
    `UPSTREAM_HTTP_KEEPALIVE_EXPIRY_SECONDS` before proposing a runtime transport split.
25. Application services should use framework-neutral `core.errors.APIError` subclasses for
    validation, source-unavailable, not-found, conflict, and retryability semantics. FastAPI
    `HTTPException`, `status`, and `JSONResponse` belong at the API adapter boundary. When a
    service must express an explicit HTTP outcome such as `202 Accepted` or authorization denial,
    return `app.core.application_responses.ApplicationHttpResponse` and let endpoint adapters call
    `app.api.http_response_adapter.to_fastapi_response(...)`. The shared stateful source helpers,
    input-mode helper, benchmark-assignment helper, stateful position-currency helper, compute
    executor, async-result resolver, calculation-result access policy, execution polling service,
    stateful execution policy service, submission fencing service, returns-series workflow,
    workspace-summary workflow, TWR-inspection submission workflow, lineage artifact service, and
    TWR-inspection artifact service now follow this pattern, and
    `tests/unit/services/test_service_framework_boundary_inventory.py` prevents new service-level
    FastAPI coupling while the remaining #331 debt is migrated in smaller slices.
    Contribution workflow services must preserve framework-neutral `APIError` subclasses through
    execution-failure recording so stateful validation defects such as missing mixed-currency FX
    coverage return governed `422` responses instead of broad unexpected `500` envelopes.
26. API routers should not own analytics workflow orchestration. Routers own HTTP route metadata,
    request/response DTO mapping, auth dependency extraction, and API adapter conversion. Offload
    threshold decisions, durable requested-window projection, request hashing, submission fencing,
    execution lifecycle transitions, failure recording, and accepted-response factory ownership
    belong in named application workflow services. `workspace_summary_calculation_workflow_service`
    and `inspection/twr_inspection_workflow_service.py` are the current pattern for behavior-
    preserving design modularity without introducing a separately scalable runtime service.
27. API routers should not import durable stores directly for lineage, inspection, execution, or
    async-result supportability policy. Durable metadata lookup, manifest consistency checks,
    declared-artifact eligibility, retained-payload fallback, and missing-storage degradation
    decisions belong in application services such as `lineage_artifact_service.py` and
    `inspection/twr_inspection_artifact_service.py`. Routers may construct route URLs and convert
    typed artifact references into `FileResponse` or `Response`, while explicit public 5xx details
    remain an API-boundary mapping concern.
28. Calculation-methodology and source-contract defects must be fixed across all owned input modes,
    fallback paths, and evidence surfaces in the same slice when practical. For MWR this means
    stateless validation, stateful source normalization, direct engine guards, Modified Dietz/XIRR
    fallback behavior, supportability/audit evidence, OpenAPI models, domain data-product
    declarations, methodology docs, API guides, and repo-authored wiki source. Do not aggregate
    away lifecycle identity, source exclusions, or measurement-window failures when downstream
    operators need that evidence to explain private-banking performance results.
29. Stateful position-timeseries normalization must preserve source position grain. Deduplicate
    source rows by `valuation_date`, business `position_id`, and `source_position_key`; derive that
    key from source-provided account, custody, book, sleeve, strategy, mandate, or tax-lot
    discriminators when upstream does not provide it. Contribution and attribution builders should
    use `source_position_key` as the engine position/instrument identity and preserve the original
    business `position_id` as metadata when source grain is more specific.
30. Contribution average-weight methodology must remain consistent across flat and hierarchy
    outputs. When reset-aware average-weight promotion is enabled for a clean candidate period, the
    selected denominator must drive residual allocation, `position_contributions[].average_weight`,
    hierarchy `levels[].rows[].weight_avg`, and `average_weight_methodology_status` together. If a
    period is blocked, keep the legacy denominator and expose blocker reason codes instead of
    silently mixing denominators across surfaces.
31. Runtime operator and status surfaces should degrade per source or component, not per endpoint.
    Work-item and recovery reads for compute and lineage queues must keep the healthy queue usable
    when the other queue fails. Runtime status must mark only the failed component unavailable when
    queue, history, preview, or governed-action snapshot reads fail. Public reasons must be stable
    operational codes rather than raw exception class names, and structured support-safe diagnostics
    must include source/component, operation, stable reason, exception class, and safe context. Do
    not log raw calculation-id fragments or cursor identifiers from operator filters.
32. Application-service port-boundary evidence is now measured separately from enforced router and
    engine/core import rules. `scripts/python_architecture_boundary_inventory.py` reports
    `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` findings as report-only while `--max-findings 0`
    continues to enforce zero router/core violations. `execution_polling_service` is the pilot
    migrated seam: the API dependency provides an `ExecutionPollingStore`, the application service
    depends on that port, and the durable adapter owns concrete execution, compute-job, and async
    result stores. Continue migrating one workflow seam at a time instead of introducing a runtime
    service split.
33. API request DTOs must cross into analytics workflow services through explicit request mappers
    and workflow command objects. TWR, workspace-summary, contribution, benchmark, and
    returns-series routes now map validated request DTOs in `app.api.mappers` before calling the
    application workflow entry point. `ROUTE_WORKFLOW_DTO_DIRECT_CALL` is enforced by the
    architecture inventory so route code cannot reintroduce direct `calculate_*_workflow(request)`
    calls for those governed workflows. The current command objects intentionally preserve the
    validated request identity while the deeper field-native command migration proceeds in smaller
    behavior-preserving slices.

## Standards And RFCs That Govern This Repository

Most relevant current governance:

1. `../lotus-platform/rfcs/RFC-0022-performance-analytics-engineering-alignment-to-dpm-standard.md`
2. `../lotus-platform/rfcs/RFC-0065-lotus-performance-to-lotus-performance-and-lotus-risk-split.md`
3. `../lotus-platform/rfcs/RFC-0067-centralized-api-vocabulary-inventory-and-openapi-documentation-governance.md`
4. `../lotus-platform/rfcs/RFC-0072-platform-wide-multi-lane-ci-validation-and-release-governance.md`
5. `../lotus-platform/rfcs/RFC-0073-lotus-ecosystem-engineering-context-and-agent-guidance-system.md`
6. `../lotus-platform/rfcs/RFC-0082-lotus-core-domain-authority-and-analytics-serving-boundary-hardening.md`
7. `docs/technical/RFC-0082-upstream-contract-family-map.md`
8. `docs/technical/architecture.md`
9. `docs/technical/runtime_topology.md`

## Known Constraints And Implementation Notes

1. this service carries both analytics correctness and product-facing integration consequences, so changes must be checked for downstream gateway and UI impact,
2. async execution and lineage are already part of the contract and should not be treated as optional infrastructure details,
3. benchmark-aware stateful behavior must remain aligned with `lotus-core` sourcing, RFC-0082 contract-family classification, and gateway expectations,
4. methodology and reproducibility documentation matter here as much as code,
5. transport optimization between `lotus-performance` and `lotus-core` should start with retrieval-shape evidence before any gRPC proposal,
6. repo-local `wiki/` content should stay concise, operator-focused, and derived from repo truth rather
   than becoming a second uncontrolled documentation tree,
7. `tests/unit/docs/test_public_docs_contract.py` is a meaningful guardrail for README and public-guide
   changes and should be part of targeted validation when documentation slices touch contract-facing pages.

## Context Maintenance Rule

Update this document when:

1. major analytics capabilities or runtime topology change,
2. repo-native commands or lane expectations change,
3. stateful integration boundaries with `lotus-core` change,
4. methodology, lineage, or execution posture changes materially,
5. current product-support posture changes,
6. RFC-0082 upstream contract-family classification or consumer conformance posture changes,
7. repo-native domain-product declaration paths or validation commands change,
8. README or `wiki/` structure changes the repository-local onboarding or operator navigation model.

## Cross-Links

1. `../lotus-platform/context/LOTUS-QUICKSTART-CONTEXT.md`
2. `../lotus-platform/context/LOTUS-ENGINEERING-CONTEXT.md`
3. `../lotus-platform/context/CONTEXT-REFERENCE-MAP.md`
4. `../lotus-platform/context/Repository-Engineering-Context-Contract.md`
5. [Lotus Developer Onboarding](../lotus-platform/docs/onboarding/LOTUS-DEVELOPER-ONBOARDING.md)
6. [Lotus Agent Ramp-Up](../lotus-platform/docs/onboarding/LOTUS-AGENT-RAMP-UP.md)
