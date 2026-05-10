# RFC-046 Slice 9 API Contract Realization

| Field | Value |
| --- | --- |
| RFC | RFC-046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening |
| Slice | 9 - API, OpenAPI, Vocabulary, and Cross-Repo Contract Realization |
| `lotus-performance` branch | `feat/rfc-046-twr-industry-evidence` |
| Downstream Gateway branch | `lotus-gateway/feat/rfc-046-twr-evidence-consumer` |
| Downstream Workbench branch | `lotus-workbench/feat/rfc-046-twr-evidence-consumer` |

## Implementation

Slice 9 reviewed the RFC-046 TWR response additions as a cross-repository contract change and
realized the implementation-backed evidence where downstream product surfaces need it.

The `lotus-performance` API contract remains additive for RFC-046 Slices 4-8. The service now
returns daily calculation evidence, linkability evidence, source-quality supportability, and
benchmark/FX/calendar supportability in the TWR response. OpenAPI, vocabulary, no-alias, docs
contract tests, and endpoint tests were already updated in the implementation slices that introduced
those fields.

The downstream review found one material realization gap: `lotus-gateway` parsed the TWR response
into performance workspace summaries but dropped `benchmark_context.supportability_evidence`. That
would have kept the new benchmark, FX, and calendar evidence out of Workbench product surfaces even
though `lotus-performance` produced it correctly.

Changes made:

- `lotus-gateway` PR `sgajbi/lotus-gateway#203`
  - preserves `benchmark_context.supportability_evidence` in performance workspace comparative
    summaries
  - exposes `benchmark_currency_state`, `benchmark_calendar_alignment_state`,
    `benchmark_warning_codes`, and `benchmark_missing_date_count`
  - updates workspace summary contract examples
  - adds a regression test proving TWR benchmark supportability evidence survives Gateway parsing
  - updates the monetary-float allowlist after repository-wide Ruff formatting shifted existing
    approved contract-field line numbers
- `lotus-workbench` PR `sgajbi/lotus-workbench#174`
  - adds typed performance workspace summary fields for the Gateway benchmark evidence
  - updates workspace fixtures
  - displays a compact `Benchmark Evidence` return-path metric when a benchmark is assigned
  - adds regression coverage proving the product summary can present the evidence

No `lotus-performance` API redesign was required in this slice. The additive response contract is
clean, OpenAPI-backed, and preserves existing TWR ownership boundaries.

## Inspector Assessment

RFC-046 did require inspector tightening, but not a separate inspector endpoint redesign in Slice 9.
The required inspector work was completed in Slice 5: calculation consistency inspection now checks
daily TWR evidence semantics, including signed adjusted capital, linkability status, episode status,
reason and warning consistency, and the rule that `not_calculated` rows cannot be linkable.

Slice 9 therefore focuses on product realization rather than duplicating inspection logic. The
calculation response carries the concise evidence required by product surfaces, while the inspection
subsystem remains the deeper supportability diagnostic surface.

## Cross-Repo Impact Review

| Repository | Classification | Evidence |
| --- | --- | --- |
| `lotus-gateway` | Changed | Gateway workspace summaries consumed TWR responses but dropped benchmark supportability evidence. PR `sgajbi/lotus-gateway#203` preserves and exposes it. |
| `lotus-workbench` | Changed | Workbench used Gateway workspace summaries and needed typed/presentation support. PR `sgajbi/lotus-workbench#174` adds the fields and return-path metric. |
| `lotus-report` | No code change required | Report-side review found generic metadata/dictionary consumption rather than strict TWR response parsing that would block RFC-046 evidence. |
| `lotus-ai` | No code change required | The implemented app path did not contain a strict TWR parser requiring contract changes. Static/demo references do not block RFC-046 API realization. |
| `lotus-risk` | No code change required | Risk consumes returns-series and risk analytics contracts rather than direct `/performance/twr` response evidence. |
| `lotus-core` | No code change required | RFC-046 source-quality and benchmark evidence can be realized from existing upstream source inputs; no new upstream source contract was required in this slice. |

## Validation

`lotus-performance` validation from the RFC-046 response-contract slices:

- `python -m pytest tests/unit/app/test_twr_openapi_contract.py tests/unit/docs/test_public_docs_contract.py tests/integration/test_performance_api.py tests/integration/test_execution_api.py tests/unit/services/test_compute_executor_worker.py tests/unit/services/test_twr_benchmark_supportability.py -q`
  - Result: passed during Slice 7 with `52 passed`
- `python -m pytest tests/unit/docs/test_public_docs_contract.py tests/unit/models/test_integration_capabilities_models.py tests/integration/test_integration_capabilities_api.py -q`
  - Result: passed during Slice 8 with `61 passed`
- `make lint`
  - Result: passed, including the monetary-float guard with `135` findings and `135` allowlisted findings
- `make typecheck`
  - Result: passed
- `python scripts/openapi_quality_gate.py`
  - Result: passed
- `python scripts/api_vocabulary_inventory.py --validate-only`
  - Result: passed with no vocabulary drift
- `python scripts/no_alias_contract_guard.py`
  - Result: passed

`lotus-gateway` local validation:

- `python -m pytest tests/unit/test_performance_workspace_service.py tests/integration/test_workbench_router.py tests/contract/test_workbench_contract.py -q`
  - Result: `79 passed`
- `make lint`
  - Result: passed, including monetary-float guard with `177` findings and `177` allowlisted findings
- `make typecheck`
  - Result: `Success: no issues found in 74 source files`
- `git diff --check`
  - Result: passed

`lotus-workbench` local validation:

- `npm test -- --run tests/unit/performance-summary-context-helpers.test.ts tests/unit/performance-workspace-client.test.tsx`
  - Result: `18` tests passed
- `npm run typecheck`
  - Result: passed
- `npm run lint`
  - Result: passed
- `git diff --check`
  - Result: passed

Remote CI:

- `lotus-gateway#203`
  - Feature Lane / Workflow Lint: passed
  - Feature Lane / Lint Typecheck Unit: passed
  - PR Merge Gate / Workflow Lint: passed
  - PR Merge Gate / Lint Typecheck Unit: passed
  - PR Merge Gate / Integration Tests: passed
  - PR Merge Gate / Coverage Gate: passed
  - PR Merge Gate / Validate Docker Build: passed
  - PR Merge Gate / CI Local Docker Parity: passed
- `lotus-workbench#174`
  - Feature Lane / Workflow Lint: passed
  - Feature Lane / Lint Typecheck Test: passed
  - PR Merge Gate / Workflow Lint: passed
  - PR Merge Gate / Lint Typecheck Coverage Build: passed
  - PR Merge Gate / Playwright Smoke: passed
  - PR Merge Gate / Validate Docker Build: passed
  - PR Merge Gate / CI Local Docker Parity: passed

Slice 9 is closed with downstream product realization implemented and remotely validated.
