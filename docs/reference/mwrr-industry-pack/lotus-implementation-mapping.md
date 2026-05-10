# Lotus MWRR Implementation Mapping

Status: implementation-backed mapping for `lotus-performance` branch `feat/mwr-industry-controls`

This page maps the supplied MWRR industry reference pack to the current Lotus implementation. The
files in this directory are retained as reference material for business, QA, engineering,
operations, sales, pre-sales, and future support-agent workflows. The implementation truth remains
the tested code, OpenAPI schema, methodology docs, certification docs, and repo-authored wiki.

## Reference Pack

| File | Purpose |
|---|---|
| `01-mwrr-methodology.md` | Business and methodology explanation of MWRR, TWRR contrast, usage, limitations, and interpretation. |
| `02-mwrr-calculation-methods.md` | XIRR, holding-period conversion, Modified Dietz, annualization, and worked calculation examples. |
| `03-mwrr-cash-flow-classification.md` | Cash-flow inclusion/exclusion policy, fee treatment, transfer treatment, and component caveats. |
| `04-mwrr-implementation-design.md` | Production design pattern, evidence model, status/reason codes, and implementation checklist. |
| `05-mwrr-solver-and-numerical-controls.md` | Solver bracketing, log-rate transformation, multiple-root handling, no-root handling, and tolerance controls. |
| `06-mwrr-edge-cases-and-controls.md` | Edge-case policy for zero NAV, negative NAV, missing data, stale values, corrected flows, and closed accounts. |
| `07-mwrr-qa-regression-pack.md` | Regression cases, property tests, UI acceptance checks, and defect taxonomy. |
| `08-mwrr-production-support-agent-playbook.md` | Support triage, user explanation templates, escalation patterns, and agent guardrails. |
| `mwrr-industry-playbook-all-in-one.md` | Combined reference pack for tools or agents that prefer one file. |

## Implemented And Test-Backed Now

| Industry expectation | Lotus implementation status | Evidence |
|---|---|---|
| XIRR-style dated MWRR is the primary method. | Implemented for `mwr_method="XIRR"` with dated year fractions. | `engine/mwr.py`, `tests/unit/engine/test_mwr.py`, `docs/methodologies/metrics/metric-mwr-xirr.md` |
| ACT/365 behavior should be explicit. | Implemented through `annualization.basis`; ACT/365 uses 365.0, ACT/ACT uses 365.25, and `periods_per_year` overrides. | `engine/mwr.py`, `docs/methodologies/metrics/metric-mwr-xirr.md` |
| Same-day flows should be normalized before solving. | Implemented in solver vector netting while preserving endpoint cash-flow echo evidence. | `engine/mwr.py`, `tests/unit/engine/test_mwr.py` |
| Solver should search for roots instead of using one arbitrary initial guess. | Implemented with log-rate scan plus bisection refinement. | `engine/mwr.py`, `tests/unit/engine/test_mwr.py` |
| Multiple-root and no-root cases should be controlled. | Implemented with `MULTIPLE_IRR_ROOTS_DETECTED` and `NO_ROOT_FOUND`; XIRR is not returned in those cases. | `engine/mwr.py`, `tests/unit/engine/test_mwr.py` |
| Fallbacks must be explicit. | Implemented with `status="FALLBACK_USED"`, `fallback_from`, `fallback_reason`, `reason_codes`, `warnings`, and `is_approximation`. | `app/models/mwr_responses.py`, `tests/integration/test_mwr_api.py` |
| Holding-period and annualized MWRR should not be confused. | Implemented with `holding_period_return` and `is_annualized_primary`. | `engine/mwr.py`, `tests/unit/engine/test_mwr.py` |
| Zero denominator should not masquerade as a normal zero return. | Implemented with `status="NOT_CALCULABLE"` and `ZERO_DENOMINATOR`. | `engine/mwr.py`, `tests/unit/engine/test_mwr.py` |
| No economic content should be explicitly labeled. | Implemented with `status="NOT_APPLICABLE"` and `NO_ECONOMIC_CONTENT`. | `engine/mwr.py`, `tests/unit/engine/test_mwr.py` |
| Downstream consumers should preserve method quality metadata. | Implemented in `lotus-gateway` performance workspace summary contract. | `lotus-gateway` branch `feat/mwr-industry-controls`, commit `4c03774` |
| Data mesh producer truth should remain in the producer. | Implemented through repo-native data-product validation, wiki guidance, and gateway preservation without recalculation. | `contracts/domain-data-products/`, `wiki/Mesh-Data-Products.md`, `make domain-product-validate` |

## Current Intentional Differences

| Reference expectation | Current Lotus position |
|---|---|
| Modified Dietz as a distinct weighted-flow approximation. | `mwr_method="MODIFIED_DIETZ"` currently maps to the implemented midpoint Dietz branch. It is documented as implementation reality and tracked as future methodology hardening, not mislabeled as full Modified Dietz. |
| FX-aware MWRR with per-flow reporting-currency conversion evidence. | Current public MWR contract expects values and flows in a consistent reporting currency. FX decomposition is not part of this endpoint. |
| Component-level MWRR. | Not supported. Contribution and attribution endpoints own component and factor explanations; component MWRRs must not be summed into portfolio MWRR. |
| Private-market since-inception MWRR with capital calls, distributions, and residual NAV policy. | Not currently a separate product capability. The current endpoint is portfolio-period MWR over supplied or statefully resolved flows and market values. |
| Dedicated operational metrics for root-count buckets and fallback-rate alerts. | Current supportability metrics cover calculation supportability. Root and fallback details are in response metadata, tests, docs, and lineage; dedicated Prometheus counters can be added in a future observability slice. |

## Remaining Backlog Candidates

1. Implement true Modified Dietz with date-weighted flows and keep the current Dietz branch as a
   separately named simple/midpoint fallback if product policy requires both.
2. Add optional flow-level source classification evidence to the public MWR response or lineage
   artifacts when support workflows need a richer cash-flow audit trail.
3. Add MWRR-specific observability counters for `FALLBACK_USED`, `NO_ROOT_FOUND`,
   `MULTIPLE_IRR_ROOTS_DETECTED`, extreme annualization, and zero denominator.
4. Add a client-demo runbook that pairs TWR and MWR examples for the same portfolio and explains
   legitimate divergence in plain business language.
5. Decide whether private-market and component-level MWRR belong in `lotus-performance` or in a
   separate product capability with a distinct data contract.

## Validation Evidence

Current branch evidence:

```bash
make check
python -m pytest tests/unit/docs/test_metric_methodology_docs.py tests/unit/docs/test_public_docs_contract.py -q
powershell -ExecutionPolicy Bypass -File ..\lotus-platform\automation\Sync-RepoWikis.ps1 -CheckOnly -AllowUnpublishedSourceChanges -Repository lotus-performance
```

The `make check` gate on this branch validates lint, format, monetary-float governance, no-alias
contract governance, mypy, OpenAPI quality, API vocabulary inventory, domain-product declarations,
and the unit/doc test suite.
