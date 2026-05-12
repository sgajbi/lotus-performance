# RFC 049 Slice 7A - Composite Inspector and Evidence Export

Date: 2026-05-12
Branch: `draft/rfc-049-composite-performance-alignment`
PR: `sgajbi/lotus-performance#162`
Status: Implemented and locally validated

## Purpose

Slice 7A adds a composite-specific inspection surface for persisted-fact composite TWR. The goal is
to make the new composite capability explainable to support, operations, audit, and client-facing
teams without overloading the existing portfolio TWR inspector or introducing hidden request-time
portfolio calculation fan-out.

## Implemented Changes

### Composite Inspection API

Added `POST /performance/composites/inspect` with request fields:

1. `inspection_id`;
2. `composite_id`;
3. `period_start`;
4. `period_end`.

The endpoint reads persisted composite member-return facts, runs the same asset-weighted composite
TWR engine used by `POST /performance/composites/twr`, and returns a support-safe inspection
response with:

1. execution status;
2. supportability verdict;
3. ordered findings;
4. evidence summary;
5. classified text artifacts.

The endpoint returns `COMPOSITE_NOT_FOUND` with HTTP 404 when the composite definition is missing.

### Supportability Findings

The inspector emits bounded findings grounded in persisted facts and engine reason codes. Current
coverage includes:

1. no persisted facts for the requested inspection window;
2. blocked calculation reason codes such as mixed reporting currencies;
3. warning-level findings for degraded calculation states.

The verdict is:

1. `supportable` when the calculation is ready and no findings are present;
2. `supportable_with_warnings` when findings or degraded states exist;
3. `not_supportable` when the underlying calculation is blocked.

### Classified Evidence Artifacts

The response includes classified artifacts with explicit `artifact_name`, `content_type`,
`access_classification`, and `artifact_content` fields. The initial bounded artifact set is:

1. `member_inputs.csv` classified as `operator_only`;
2. `period_weights.csv` classified as `operator_only`;
3. `composite_returns.csv` classified as `customer_consumable`;
4. `lineage_manifest.json` classified as `operator_only`;
5. `support_brief.md` classified as `operator_only`.

The public contract deliberately uses `artifact_content` instead of generic `content` so API
vocabulary remains precise and collision-resistant.

### Lineage Manifest and Support Brief

The lineage manifest records:

1. composite identifier;
2. calculation status;
3. source fingerprints used by persisted member facts;
4. restatement versions used by persisted member facts.

The support brief gives a concise operator explanation of the inspected composite, inspected
periods, member-return fact count, status, and reason codes.

## Scope Boundaries

Slice 7A does not implement:

1. asynchronous artifact download;
2. persisted artifact retention;
3. Excel workbook export;
4. benchmark active-return export;
5. restatement diff export;
6. entitlement/audit events for artifact reads beyond the current classified response contract.

Those capabilities remain tied to later RFC 049 result-version, operational API, and publication
control slices. The implemented surface is still production-relevant because it gives immediate
support and audit evidence for the already exposed persisted-fact composite TWR API.

## Validation Evidence

Local validation passed:

1. `python -m ruff check app\api\endpoints\composites.py app\models\composites.py app\services\composite_inspection_service.py tests\unit\services\test_composite_inspection_service.py tests\integration\test_composites_api.py`;
2. `python -m ruff format --check app\api\endpoints\composites.py app\models\composites.py app\services\composite_inspection_service.py tests\unit\services\test_composite_inspection_service.py tests\integration\test_composites_api.py`;
3. `python -m pytest tests\unit\services\test_composite_inspection_service.py tests\integration\test_composites_api.py -q`;
4. `python -m mypy --config-file mypy.ini`;
5. `python scripts\openapi_quality_gate.py`;
6. `make api-vocabulary-gate`;
7. `python -m pytest tests\unit\docs\test_public_docs_contract.py -q`;
8. `git diff --check`.

## Slice 7A Conclusion

Slice 7A is complete for the currently implemented persisted-fact composite TWR surface. Composite
results are now inspectable through a dedicated endpoint, findings are grounded in calculation
reason codes, artifacts are classified, lineage evidence is explicit, and the API vocabulary remains
more precise after replacing generic artifact `content` with `artifact_content`.
