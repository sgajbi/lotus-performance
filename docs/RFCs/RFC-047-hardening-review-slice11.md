# RFC 047 Slice 11 - Second-Last Hardening and Review

Status: Complete  
Date: 2026-05-10  
Performance branch: `docs/rfc-contribution-carino-alignment`  
Workbench hardening PR: `sgajbi/lotus-workbench#178`

## Purpose

Slice 11 performs the second-last RFC 047 review before final closure. It reviews contribution
correctness, API certification posture, Swagger/OpenAPI quality, error handling, security posture,
data mesh posture, downstream consumer behavior, documentation truth, and live evidence quality.

## Branch and Governance Check

Before starting this slice, stranded-truth reconciliation was run in `lotus-performance`:

```powershell
git fetch origin --prune
git branch -r --no-merged origin/main
```

Result: `origin/docs/rfc-contribution-carino-alignment` was the only unmerged branch returned and
was classified as `active` for RFC 047.

## Review Scope

Reviewed areas:

1. `POST /performance/contribution` stateless and stateful behavior;
2. contribution async result routes;
3. Carino smoothing evidence and residual handling;
4. source economics evidence and upstream lineage posture;
5. stateful contribution currency validation and error handling;
6. Gateway contribution contract preservation from Slice 7;
7. Workbench canonical validation and screenshot proof from Slice 10;
8. OpenAPI quality, API vocabulary, no-alias governance, and docs contracts;
9. live readiness, metrics, and structured logging evidence captured in Slice 10.

## Issues Found and Fixed

### Workbench Live Evidence Validation Was Too Weak

Slice 10 found that the live screenshot index marked `performance.evidence-live.png` as
`truthfully_degraded` even after Gateway evidence settled to `supported`. The production panel was
usable, but the validation harness was conservative in a way that could hide whether the evidence
panel was actually demo-ready.

Fix in `lotus-workbench#178`:

1. `scripts/live/validation/browser-workflows.mjs` now marks the performance evidence screenshot
   `demo_ready` only when the evidence support status strip is present;
2. the degraded screenshot state remains available when the evidence panel is partial or unavailable;
3. focused tests lock this behavior.

Validation:

```powershell
npm test -- --run tests/unit/live-validation-calculation-sanity.test.ts tests/unit/live-canonical-validation-script.test.ts
npm run typecheck
npm run lint
powershell -ExecutionPolicy Bypass -File scripts/live/Validate-LotusFrontOfficeCanonical.ps1 `
  -ScreenshotDirectory output/rfc047-slice11-validation-harness-proof-2
```

Live proof after the fix:

1. `performance-evidence-live.png` is now classified `demo_ready`;
2. `performance.evidence` panel classification is `ready`;
3. Gateway evidence capability state is `supported`;
4. live stack was left running by operator request.

### Contribution Source Economics Was Missing From Workbench Source-Supportability Checks

Slice 10 also found generic Workbench source-supportability metadata showing `unknown` even though
contribution-specific source economics evidence was present. This was a validation harness blind
spot, not a missing backend contract.

Fix in `lotus-workbench#178`:

1. `scripts/live/validation/calculation-sanity.mjs` now reads
   `contribution.source_economics_evidence`;
2. `SOURCE_LIMITED` maps to partial supportability instead of unknown;
3. `SOURCE_BACKED` and `CALLER_SUPPLIED` map to ready;
4. source owner is derived from upstream source contracts, so `PortfolioTimeseriesInput:v1` and
   `PositionTimeseriesInput:v1` classify the owner as `lotus-core`.

Live proof after the fix:

1. `performance.summary` source supportability state is `partial`;
2. source supportability services include `lotus-core`;
3. contribution panels remain ready while correctly exposing source limitations.

### Contribution Stateful Currency Validation Emitted a Deprecation Warning

The focused contribution integration suite surfaced a FastAPI status constant deprecation warning
from the stateful contribution currency validation path.

Fix in `lotus-performance`:

1. `app/services/stateful_contribution_input_service.py` now uses
   `status.HTTP_422_UNPROCESSABLE_CONTENT` in contribution-local stateful currency validation;
2. behavior remains HTTP `422`;
3. the contribution integration suite now runs without that warning.

## Validation Evidence

Performance validation:

```powershell
python -m pytest tests/integration/test_contribution_api.py -q
python -m pytest tests/unit/models/test_contribution_models.py `
  tests/unit/services/test_contribution_source_economics.py `
  tests/unit/app/test_contribution_endpoint_helpers.py `
  tests/unit/app/test_contribution_endpoint_async_paths.py -q
python -m pytest tests/unit/app/test_contribution_endpoint_async_paths.py `
  tests/unit/app/test_contribution_endpoint_helpers.py `
  tests/unit/docs/test_metric_methodology_docs.py -q
python -m pytest tests/unit/docs/test_public_docs_contract.py `
  tests/unit/app/test_execution_openapi_contract.py `
  tests/unit/app/test_lineage_openapi_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python scripts/no_alias_contract_guard.py
python -m ruff check app/services/stateful_contribution_input_service.py
```

Results:

1. contribution integration: `40 passed`;
2. focused contribution model/source/endpoint units: `47 passed`;
3. contribution endpoint/docs methodology pack: `36 passed`;
4. docs and execution/lineage OpenAPI pack: `45 passed`;
5. OpenAPI quality gate: passed;
6. API vocabulary inventory gate: passed with no drift;
7. no-alias contract guard: passed;
8. ruff on the edited contribution service: passed.

Workbench validation:

1. focused live validation tests: `16 passed`;
2. `npm run typecheck`: passed;
3. `npm run lint`: passed;
4. canonical live validation passed against the running stack and wrote
   `C:\Users\Sandeep\projects\lotus-workbench\output\rfc047-slice11-validation-harness-proof-2`.

## API Certification Review

Contribution API posture after this slice:

1. `POST /performance/contribution` supports stateless and stateful input modes;
2. stateful mode resolves source-owned portfolio and position timeseries through governed upstream
   contracts;
3. Carino smoothing evidence is explicit and reason-coded;
4. source economics is explicit and reason-coded;
5. unsupported source-owned component P&L families are reported as unsupported rather than guessed;
6. async result routes preserve calculation ids and result replay behavior;
7. invalid stateful currency combinations return HTTP `422`;
8. OpenAPI quality, vocabulary, no-alias, and docs checks pass.

No duplicate strategic contribution endpoint was found in this slice. Gateway and Workbench consume
the strategic `lotus-performance` contribution output through the governed Gateway performance
workspace routes.

## Security and Operational Review

Security posture:

1. PR Merge Gate security audit was green on the Slice 10 commit;
2. no new dependency or secret posture change was introduced in Slice 11;
3. edited Workbench validation code is local validation harness logic and does not expose customer
   data;
4. performance logs reviewed in Slice 10 carried correlation, request, and trace ids without
   exposing restricted customer data.

Operational posture:

1. readiness endpoint returned `ready`;
2. Prometheus supportability and HTTP request metrics were present;
3. execution lineage exposes retrieval, normalization, execution, and lineage materialization
   stages;
4. live stack remains running by operator request.

## Documentation and Wiki Decision

No wiki product-page change was needed in this slice. Slice 11 fixed validation harness truth and a
contribution-local deprecation warning; the implementation-backed product documentation from Slice 9
remains accurate.

The RFC ledger is updated so this hardening evidence is not stranded outside the execution record.

## Residual Risk and Go/No-Go

Residual observations:

1. `SOURCE_LIMITED` remains the correct production posture for component P&L economics because the
   upstream source contract does not yet author those components;
2. the canonical seed data still surfaces small position-flow residual diagnostics; those diagnostics
   are visible and bounded rather than hidden;
3. risk panel source supportability remains outside RFC 047 contribution scope.

Go/no-go conclusion: go for Final Closure. The contribution implementation, downstream realization,
live proof, validation harness, OpenAPI governance, and documentation posture are strong enough to
move to Slice 12, subject to Workbench PR `sgajbi/lotus-workbench#178` CI remaining green and being
merged before final closure.
