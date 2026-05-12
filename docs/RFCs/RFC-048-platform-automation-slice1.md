# RFC 048 Slice 1 - Platform Automation and Scaffolding Evidence

| Field | Value |
| --- | --- |
| RFC | RFC-048 - Attribution Industry Methodology Alignment and Evidence Contract |
| Slice | 1 - Platform Automation and Scaffolding Improvement |
| Status | Complete |
| Date | 2026-05-11 |
| `lotus-performance` branch | `feat/rfc-048-attribution-industry-alignment` |
| `lotus-platform` branch | `feat/rfc048-attribution-analytics-scaffold` |
| `lotus-platform` PR | `sgajbi/lotus-platform#323` |
| `lotus-platform` feature commit | `217ad4ea8b61e672407a2c90dcc66c05fd6bb48d` |
| `lotus-platform` merge commit | `df085a5194235cae15968a54471f51e4400e49cc` |

## Purpose

Slice 1 ensures RFC 048 does not solve repeatable attribution and benchmark-relative analytics
governance gaps only inside `lotus-performance`. Attribution is a methodology-backed analytics
data product, so future Lotus analytics products should start with scaffolded controls for status,
materiality, source alignment, and support-safe evidence.

## Platform Gap Ledger

| Area | Current platform posture | RFC 048 gap assessment | Slice 1 action |
| --- | --- | --- | --- |
| Analytics data-product onboarding | RFC 047 added `lotus-analytics-data-product-profile` scaffolding with methodology, raw/final evidence, reconciliation, reason codes, downstream realization, and live proof requirements. | RFC 048 proves a reusable analytics gap: benchmark-relative and source-comparative analytics need explicit status contracts, residual/materiality-threshold policy, source-alignment controls, and support-safe daily or observation-level evidence. | Strengthened `lotus-platform/automation/generate_domain_product_onboarding.py` so generated analytics profiles and certification checklists require these controls by default. |
| Residual and materiality policy | Platform scaffold required reconciliation evidence, but not materiality-threshold policy or classification. | Attribution residuals must not be only numeric; operations needs materiality classification and escalation posture. This applies to other analytics products too. | Added `materiality_threshold_policy_required` to generated analytics computation contracts and checklist guidance. |
| Status and reason-code contract | Platform scaffold required reason codes. | Reason codes without an explicit status contract are not enough for downstream degraded-state handling. | Added `status_contract_required` to generated analytics computation contracts and checklist guidance. |
| Source alignment | Platform scaffold required source authority maps. | Attribution requires benchmark/calendar/classification/currency alignment controls. The same concern exists for any benchmark-relative, model-relative, or source-comparative analytics output. | Added `source_alignment_controls_required` to generated analytics computation contracts and certification guidance. |
| Daily/observation evidence | Platform scaffold required raw-vs-final evidence. | Support teams need safe daily/observation-level evidence for period outputs without exposing unsafe raw payloads. | Added `support_safe_daily_evidence_required` to generated analytics computation contracts and checklist guidance. |
| API certification, Swagger quality, health, logging, observability, CI, security, and wiki scaffolding | Existing Lotus platform scaffolds and governance already cover baseline API certification, OpenAPI quality, health/readiness, structured logging, bounded metrics, CI lane defaults, security checks, docs/wiki publication, and governance hooks. | No new reusable defect beyond analytics-product control scaffolding was proven during Slice 1. | Deliberate no-change decision for these areas. Later RFC 048 slices must return any newly proven repeatable gap to `lotus-platform`. |

## Implemented Platform Changes

`lotus-platform` PR `sgajbi/lotus-platform#323` implements the reusable change:

1. `automation/generate_domain_product_onboarding.py`
   - Adds required analytics computation-contract controls:
     - `materiality_threshold_policy_required`
     - `status_contract_required`
     - `source_alignment_controls_required`
     - `support_safe_daily_evidence_required`
   - Updates generated onboarding checklist text so analytics products must define status,
     materiality thresholds, source alignment, downstream realization, and live proof before
     promotion.
   - Updates generated analytics certification checklist text to require materiality
     classification, source-alignment controls, and support-safe daily or observation-level
     evidence.
   - Extends validation so weak analytics profiles fail if the new controls are missing or false.
2. `tests/unit/test_domain_product_onboarding_generator.py`
   - Verifies generated analytics profiles include the new required controls.
   - Verifies generated certification checklist guidance includes materiality classification,
     source-alignment controls, and support-safe daily evidence.

The change is platform-level because attribution is only the current visible driver. Any future
methodology-backed analytics data product that explains portfolio, benchmark, model, risk, or
source-relative output should start with the same controls.

## Validation Evidence

`lotus-platform` local validation completed on 2026-05-11 from branch
`feat/rfc048-attribution-analytics-scaffold`:

1. `python -m ruff format automation\generate_domain_product_onboarding.py tests\unit\test_domain_product_onboarding_generator.py` - passed
2. `python -m ruff check automation\generate_domain_product_onboarding.py tests\unit\test_domain_product_onboarding_generator.py` - passed
3. `python -m pytest tests\unit\test_domain_product_onboarding_generator.py -q` - `6 passed`
4. `git diff --check` - passed

`lotus-platform` GitHub validation for PR `sgajbi/lotus-platform#323`:

1. `Cross-App Vocabulary Gate` - passed
2. `Feature Lane / Workflow Lint` - passed
3. `Feature Lane / Platform Repo Contracts` - passed
4. `PR Merge Gate / Workflow Lint` - passed
5. `PR Merge Gate / Platform Repo Contracts` - passed

PR `sgajbi/lotus-platform#323` was merged to `lotus-platform/main` on 2026-05-10 UTC as
`df085a5194235cae15968a54471f51e4400e49cc`.

## Slice 1 Review

The implementation is deliberately narrow and durable:

1. it strengthens generator output rather than copying an attribution-only checklist into
   `lotus-performance`;
2. it is validator-backed by extending the same generator test that protects the analytics profile;
3. it benefits future analytics products, including contribution-like, attribution-like,
   benchmark-relative, risk-relative, and model-relative products;
4. it avoids changing unrelated scaffolding where no repeatable defect was proven.

Slice 1 leaves RFC 048 ready for app-local cleanup and structure work. Future slices must use the
new platform scaffold expectations when promoting `AttributionAnalytics:v1` as a governed data
product.

## Closure Decision

Slice 1 is complete:

1. the repeatable platform gap was identified;
2. the reusable automation change was implemented in `lotus-platform`;
3. local and GitHub validation passed;
4. the platform PR was merged to `main`;
5. no local-only workaround remains in `lotus-performance`.
