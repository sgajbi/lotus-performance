# RFC-047 Slice 1 - Platform Automation and Scaffolding Evidence

| Field | Value |
| --- | --- |
| RFC | RFC-047 - Contribution Carino Methodology Alignment and Evidence Contract |
| Slice | 1 - Platform Automation and Scaffolding Improvement |
| Status | Complete for Slice 1 implementation, pending final RFC merge closure |
| Date | 2026-05-10 |
| `lotus-performance` branch | `docs/rfc-contribution-carino-alignment` |
| `lotus-platform` branch | `feat/rfc047-analytics-product-onboarding` |
| `lotus-platform` PR | `sgajbi/lotus-platform#319` |
| `lotus-platform` commit | `26993e8d7a2876c5ea6c802832acebf3c8e3a05b` |
| `lotus-platform` merge commit | `c7cae07f999e91373a7670a443c88d2bbe2918c9` |

## Purpose

Slice 1 ensures RFC-047 does not solve repeatable analytics data-product governance gaps only
inside `lotus-performance`. Contribution analytics is a methodology-backed analytics output, not a
raw source feed, so platform onboarding must scaffold the evidence shape future analytics products
need before they are promoted as governed Lotus data products.

## Platform Gap Ledger

| Area | Current platform posture | RFC-047 gap assessment | Slice 1 action |
| --- | --- | --- | --- |
| Analytics data-product onboarding | `generate_domain_product_onboarding.py` scaffolded domain-product metadata, telemetry, SLO, access, evidence, source API, and ingestion-pipeline artifacts. | The scaffold was strong for source-oriented data products but did not create an analytics-product profile for methodology-backed outputs such as `ContributionAnalytics:v1`. | Added analytics product profile generation under `contracts/analytics-products/` with methodology, computation evidence, downstream realization, and proof requirements. |
| Methodology proof | Platform docs required certification generally, but onboarding did not force methodology documents, formulas, deterministic examples, edge behavior, or unsupported-state catalog for analytics outputs. | RFC-047 needs Carino formula proof, raw-vs-smoothed evidence, invalid-domain posture, and worked examples. These are repeatable analytics requirements. | Added analytics profile fields and a generated `ANALYTICS-DATA-PRODUCT-CERTIFICATION-CHECKLIST.md` requiring methodology proof. |
| Raw/final computation evidence | Existing evidence contracts covered data-product evidence policy but did not specifically require raw result, final result, reconciliation residual, reason codes, and restatement posture for analytics outputs. | Contribution must expose raw contribution, smoothed contribution, residuals, status, and reason codes without hidden recomputation. | Added analytics profile computation-contract requirements for raw-vs-final evidence, reconciliation evidence, reason codes, lineage, and restatement policy. |
| Downstream realization | RFC-046 already strengthened generated backend evidence manifests for same-RFC source/consumer realization. | Analytics data products still needed onboarding-level guidance that Gateway and Workbench must preserve source-owned analytics status rather than invent it downstream. | Added downstream realization requirements for Gateway contract, Workbench product surface, consumer search before API change, and same-RFC consumer updates. |
| API certification and Swagger quality | Existing Lotus governance covers OpenAPI quality, vocabulary, no-alias rules, and API certification. | No new platform-level API-certification defect was proven beyond analytics product profile and checklist requirements. | No local-only change. Later RFC-047 API slices must use the existing API certification gates and fix app-specific gaps in `lotus-performance` and consumers. |
| Health, observability, logging, CI, security, and wiki scaffolding | Existing platform scaffolding and AGENTS/context rules cover health/readiness, bounded telemetry, structured logging, CI lanes, security posture, docs, and wiki publication. | No broader reusable platform automation defect was proven during Slice 1. | Explicit no-change decision for Slice 1. Later slices must return any newly proven repeatable scaffold gap to platform rather than leaving it app-local. |

## Implemented Platform Changes

`lotus-platform` PR `sgajbi/lotus-platform#319` implements the reusable Slice 1 improvement:

1. `automation/generate_domain_product_onboarding.py`
   - Adds `lotus-analytics-data-product-profile` scaffold output.
   - Writes analytics profiles under `contracts/analytics-products/<product>.analytics-profile.v1.json`.
   - Adds methodology, computation, downstream realization, and proof requirements for analytics
     products.
   - Writes `docs/ANALYTICS-DATA-PRODUCT-CERTIFICATION-CHECKLIST.md`.
   - Validates analytics profile identity, contract id, and required governance booleans.
2. `tests/unit/test_domain_product_onboarding_generator.py`
   - Verifies generated analytics profile and certification checklist content.
   - Verifies weak analytics profiles fail validation.

The change is platform-level because `ContributionAnalytics:v1` is only the first visible consumer
of this gap. Any future Lotus analytics product that publishes methodology-backed results should
start with the same product profile, proof posture, and downstream realization expectations.

## Validation Evidence

`lotus-platform` local validation completed on 2026-05-10 from branch
`feat/rfc047-analytics-product-onboarding`:

1. `python -m ruff format --check automation/generate_domain_product_onboarding.py tests/unit/test_domain_product_onboarding_generator.py` - passed
2. `python -m ruff check automation/generate_domain_product_onboarding.py tests/unit/test_domain_product_onboarding_generator.py` - passed
3. `python -m pytest tests/unit/test_domain_product_onboarding_generator.py -q` - `6 passed`
4. `git diff --check` - passed

`lotus-platform` GitHub validation for PR `sgajbi/lotus-platform#319`:

1. `Cross-App Vocabulary Gate` - passed
2. `Feature Lane / Workflow Lint` - passed
3. `PR Merge Gate / Workflow Lint` - passed
4. `Feature Lane / Platform Repo Contracts` - passed
5. `PR Merge Gate / Platform Repo Contracts` - passed

PR `sgajbi/lotus-platform#319` was merged to `lotus-platform` `main` on 2026-05-10 as
`c7cae07f999e91373a7670a443c88d2bbe2918c9`.

## Slice 1 Review

The implemented change is intentionally narrow and durable. It does not add contribution-specific
templates to `lotus-performance`; it improves the platform scaffold so any analytics data product
starts with:

1. methodology proof requirements,
2. raw-versus-final computation evidence requirements,
3. reason-code and lineage expectations,
4. same-RFC downstream realization requirements,
5. live/e2e proof expectations before supported-feature promotion.

The following areas were reviewed and left unchanged for Slice 1 because existing platform
automation already provides the baseline, or because later RFC-047 slices must first prove an
actual reusable gap:

1. generic Swagger/OpenAPI scaffolding,
2. health, liveness, and readiness scaffolding,
3. structured logging and trace propagation scaffolding,
4. standard error-response scaffolding,
5. CI lane defaults,
6. security baseline checks,
7. repo-local wiki scaffolding,
8. supported-features and vocabulary governance hooks.

## Closure Decision

Slice 1 is complete for RFC-047 implementation:

1. the platform/scaffolding gap ledger exists,
2. the reusable analytics data-product onboarding gap is fixed and merged in `lotus-platform`,
3. platform tests and GitHub checks pass,
4. no-change decisions are recorded for scaffold areas without a proven reusable defect,
5. the output benefits future Lotus applications and not only `lotus-performance`.

Final RFC closure still requires all remaining RFC-047 implementation, downstream consumer changes,
wiki/source documentation updates, live proof, and branch cleanup to be merged to `main`.
