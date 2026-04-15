# TWR Inspection Endpoint Certification

This note records the certification state for the TWR supportability inspection endpoint family:

- `POST /performance/inspections/twr`
- `GET /performance/inspections/{inspection_id}`
- `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}`

## Purpose And Ownership

The TWR inspector is an operator and supportability surface, not a replacement for
`POST /performance/twr`.

Use it when a TWR result exists or a proposed TWR request can be formed, but the result needs a
structured explanation across source quality, source economics, reconciliation, and calculation
consistency. The endpoint returns owner-routed findings and downloadable evidence so support, front
office, performance engineering, and upstream core teams can triage the same issue without changing
the TWR calculation contract.

Do not use the inspector for normal front-office return display. Front-office display should use
`POST /performance/twr`, `POST /performance/workspace-summary`, and their result routes. Use the
inspector as a quality gate or support drill-through when a returned TWR number is not explainable or
when a governed validation workflow requires evidence.

## Supported Contract Options

`POST /performance/inspections/twr` accepts two subject modes:

| Option | Use | Required companion input |
| --- | --- | --- |
| `subject_type=twr_calculation` | Inspect an existing durable TWR execution and its lineage. | `subject_calculation_id` |
| `subject_type=twr_request` | Inspect a proposed request payload without mutating the TWR calculation contract. | `request` |

The validator rejects mixed subject inputs. `twr_calculation` cannot include an embedded request, and
`twr_request` cannot include `subject_calculation_id`.

Supported profiles:

| Profile | Intended use |
| --- | --- |
| `support_triage` | Default bounded support flow for unexplained TWR results. |
| `canonical_validation` | Governed seeded-portfolio validation profile for canonical portfolios such as `PB_SG_GLOBAL_BAL_001`. |
| `deep_reconciliation` | Heavier upstream-state and source-economics evidence for escalation. |

The submit route is async-only. It returns:

- `inspection_id`
- `poll_path=/performance/executions/{inspection_id}`
- `result_path=/performance/inspections/{inspection_id}`

## Output Contract

The completed inspection result returns every field needed for supportability triage:

| Field | Meaning |
| --- | --- |
| `inspection_id` | Durable inspection identity used for polling, result retrieval, and artifacts. |
| `subject_type` | Whether the inspected subject was an existing TWR calculation or request payload. |
| `inspection_profile` | Bounded profile used for the inspection. |
| `subject_calculation_id` | Existing TWR calculation id when applicable. |
| `portfolio_id` | Portfolio resolved from the subject or existing execution. |
| `status` | Terminal inspection result status. |
| `verdict` | `supportable`, `supportable_with_warnings`, `not_supportable`, or `inspection_failed`. |
| `findings[]` | Stable finding code, severity, category, owner repo, summary, explanation, action, and evidence. |
| `owner_summary` | Primary and secondary repositories implied by finding ownership and severity. |
| `evidence_summary` | Flat counts and summary metrics emitted by completed check families. |
| `check_coverage` | Completed and pending check families, preventing false clean-bill interpretation. |
| `related_lineage` | Pointer back to inspected TWR lineage for existing-calculation inspections. |
| `artifacts` | Artifact-name to route map for durable support evidence. |
| `generated_at_utc` | UTC response generation timestamp. |

Current artifact names:

- `inspection_summary.json`
- `findings.json`
- `source_quality_summary.json`
- `reconciliation_summary.json`
- `source_economics_summary.json`

The artifact route is part of the public supportability contract and is documented in Swagger. Unknown
artifact names return `404`; durable metadata that declares a missing artifact returns `503`.

## Figure And Evidence Tie-Outs

The endpoint does not emit a headline return figure. It certifies whether the return is supportable.
The figures that matter are diagnostic counts, sampled values, owner-routed findings, and artifact
payload fields. Current route and service tests verify:

- source-quality counts for weekend observations, business-date gaps, stale valuation runs,
  nonpositive capital-base dates, mandate move outliers, return concentration, repeated moves,
  monthly day dominance, and extreme daily moves;
- calculation-consistency checks for relative-performance arithmetic, benchmark/relative block
  presence, breakdown cardinality, bucket alignment, period-return arithmetic, cumulative-return
  arithmetic, and geometric linking;
- reconciliation counts and samples for mixed position epochs, duplicate position rows, invalid
  epochs, invalid selected values, portfolio-position gaps, and unexplained position begin-value
  carry-forward breaks;
- source-economics counts and samples for fee normalization, external cash-flow normalization,
  duplicate source signals, explicit-source total mismatches, malformed cash-flow collections,
  missing labels, noncanonical labels, governed aliases, unsupported labels, timing contradictions,
  and mixed timing buckets;
- artifact payload fallback when lineage metadata retains JSON content but the file has not been
  materialized yet.

The support-facing check inventory is maintained in `docs/guides/twr_inspection_checks.md`.

## Upstream Integration

For existing stateful TWR inspections, the inspector reads source state through the same
lotus-core query-control-plane analytics-input boundary as the stateful analytics engine:

- `POST /integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries`
- `POST /integration/portfolios/{portfolio_id}/analytics/position-timeseries`

These calls are routed through `CORE_CONTROL_PLANE_BASE_URL`. The inspector does not call stale
query-service GET routes and does not ask lotus-core to compute performance. Lotus-core remains the
source-data authority; lotus-performance owns inspection interpretation and performance
supportability findings.

Performance posture is bounded:

- `twr_request` inspections run request-local checks only and do not make unnecessary upstream calls;
- stateful reconciliation and source-economics calls run only when the inspected lineage contains a
  resolved stateful TWR request and portfolio identity;
- heavy evidence generation is async and separated from the normal TWR result path.

## Downstream Consumers

Current direct downstream usage search across `lotus-gateway`, `lotus-risk`, `lotus-workbench`,
`lotus-report`, `lotus-advise`, and `lotus-manage` found no direct caller of
`/performance/inspections/twr` or `/performance/inspections/{inspection_id}`.

That is acceptable for the current supportability posture. The strategic downstream pattern is:

- normal front-office display uses TWR, MWR, workspace-summary, contribution, attribution, and
  returns-series endpoints;
- gateway or Workbench may add a support drill-through or validation gate that submits an inspection
  only when a portfolio window needs supportability evidence;
- risk should continue to consume `POST /integration/returns/series` for aligned return series rather
  than reconstructing source-quality logic from the inspector.

No duplicate or dead endpoint was identified for this slice. The inspection endpoint is distinct
from TWR because it answers supportability, lineage, owner routing, and evidence questions rather
than returning the performance result.

## GitHub Issue Posture

Open issue search was performed for the owning repo and known downstream repos using the terms
`twr inspection`, `inspector`, `supportability`, and `performance inspections`.

Findings:

- no open `lotus-performance` issue was found for the TWR inspection endpoint family;
- no open `lotus-gateway`, `lotus-risk`, or `lotus-workbench` issue was found for direct inspector
  integration;
- existing `lotus-gateway#108` remains the downstream long-window TWR gating issue and is tracked
  by the TWR endpoint certification, not this supportability endpoint certification.

No issue needed to be closed or opened during this pass.

## Swagger Readiness

Swagger now documents:

- when to submit an inspection and when not to use it;
- accepted async response and polling/result paths;
- result retrieval while queued or running;
- artifact download route, supported artifact-name expectations, and `404`/`503` behavior;
- field-level descriptions and domain-specific examples for inspection request, accepted response,
  completed response, findings, owner summary, check coverage, and related lineage.

## Test Pyramid Assessment

| Layer | Coverage | Assessment |
| --- | --- | --- |
| Model tests | Subject-mode validation rejects mixed or missing companion inputs. | Strong for request contract guardrails. |
| Service tests | Runtime failure preservation, partial evidence behavior, verdict synthesis, owner summary, window scoping, and artifact materialization failures. | Strong for core orchestration behavior. |
| Check-family unit tests | Source quality, calculation consistency, reconciliation, and source economics each have focused tests for domain-specific defect patterns. | Strong and domain-aware. |
| Integration tests | Async submission, execution polling, completed result retrieval, artifact file retrieval, retained-payload artifact fallback, missing-artifact errors, existing-calculation lineage, stateful reconciliation, and source-economics artifacts. | Strong route-level coverage. |
| Docs/OpenAPI tests | TWR OpenAPI contract and public docs tests now cover supportability purpose, result behavior, artifact route, schema examples, and check inventory documentation. | Strong after this pass. |
| Live canonical validation | `scripts/validate_canonical_twr_inspection.py` validates `PB_SG_GLOBAL_BAL_001` as of `2026-04-10` against live performance and lotus-core control-plane services. | Available as runtime proof; run before PR or release evidence when the local stack is up. |

## Validation Commands

Focused validation for this certification slice:

```bash
python -m pytest tests/unit/app/test_twr_openapi_contract.py tests/integration/test_inspections_api.py tests/unit/models/test_inspection_requests.py tests/unit/docs/test_public_docs_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python -m ruff check app/api/endpoints/inspections.py app/models/inspection_requests.py app/models/inspection_responses.py tests/unit/app/test_twr_openapi_contract.py
python -m ruff format --check app/api/endpoints/inspections.py app/models/inspection_requests.py app/models/inspection_responses.py tests/unit/app/test_twr_openapi_contract.py
```
