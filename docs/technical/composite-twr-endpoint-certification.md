# Composite TWR Endpoint Certification

Status: certified for the RFC-049 supported composite TWR boundary after Slice 12 live proof,
Slice 13 hardening, and Slice 14 closure preparation.

Endpoints:

- `POST /performance/composites/twr`
- `POST /performance/composites/inspect`

Methodology:

- `persisted_member_return_asset_weighted_twr_v1`

## Endpoint Purpose

`POST /performance/composites/twr` calculates private-banking composite TWR from persisted
member-return facts. It is the persisted member-return facts endpoint for composite publication
evidence. Use it after composite definition, membership policy, member portfolio returns,
beginning assets, ending assets, fingerprints, and restatement versions are already materialized.

`POST /performance/composites/inspect` produces support-safe inspection findings and classified
artifacts over the same persisted facts and calculation evidence.

Do not use these endpoints for:

- ad hoc member return upload;
- hidden request-time member portfolio TWR fan-out;
- composite contribution, attribution, or MWR;
- sleeve, carve-out, pooled-fund, private-market, portability, tax-aware, leveraged, or long/short
  special composite structures;
- multi-currency composite aggregation beyond the single reporting-currency guard;
- benchmark active return.

## Supported Request Options

Validated request options:

- caller-provided or generated `calculation_id`;
- caller-provided or generated `inspection_id`;
- `composite_id`;
- inclusive `period_start` and `period_end`.

The request does not accept:

- inline member facts;
- membership-policy switches;
- benchmark switches;
- return-view conversion switches;
- FX conversion switches.

Those are source-authority and persisted-fact concerns, not request-time options.

## Required Figure Tie-Outs

Every certified composite calculation must satisfy these invariants for each calculable period:

- ready member beginning-asset weights sum to one, allowing only quantization dust;
- each member contribution equals `return_value * beginning_asset_weight`;
- summed member contributions reconcile to `periods[].return_value`;
- `periods[].cumulative_return` equals geometric linking of calculable period returns through that
  period;
- `cumulative_return` equals the latest non-null period cumulative return;
- `beginning_market_value` and `ending_market_value` equal sums across ready member facts;
- `member_count` equals ready fact count;
- `excluded_member_count` equals non-ready fact count;
- `dispersion_equal_weight` is null for one ready member and otherwise equals sample standard
  deviation with denominator `n - 1`;
- `source_fingerprints`, `restatement_versions`, and member `calculation_id` values match the
  persisted facts used by the calculation.

Blocked periods must not fabricate a zero return or alter cumulative growth.

## Error Behavior

| Case | Expected behavior |
| --- | --- |
| Missing composite definition | HTTP 404 with `COMPOSITE_DEFINITION_NOT_FOUND`. |
| Invalid date window | HTTP 422 request validation. |
| No persisted facts in requested window | HTTP 422 with `NO_MEMBER_RETURN_FACTS`. |
| Period facts exist but none are ready | Period `BLOCKED`; aggregate status is `BLOCKED` unless another period calculates. |
| Nonpositive beginning assets | Period `BLOCKED` with `nonpositive_composite_beginning_assets`. |
| Mixed return views | Period `BLOCKED` with `mixed_member_return_views`. |
| Mixed reporting currencies | Period `BLOCKED` with `mixed_member_reporting_currencies`. |
| Some non-ready facts excluded | Period and calculation can be `DEGRADED` with source reason codes. |

## Inspector Certification

The inspector must return:

- `status="complete"` for completed inspections;
- `verdict="supportable"` for ready calculations with no findings;
- `verdict="supportable_with_warnings"` for degraded calculations or warning findings;
- `verdict="not_supportable"` for blocked calculations;
- `NO_MEMBER_RETURN_FACTS` finding when no persisted facts are present;
- artifacts `member_inputs.csv`, `period_weights.csv`, `composite_returns.csv`,
  `lineage_manifest.json`, and `support_brief.md`.

Artifact classification:

- `member_inputs.csv`: `operator_only`;
- `period_weights.csv`: `operator_only`;
- `composite_returns.csv`: `customer_consumable`;
- `lineage_manifest.json`: `operator_only`;
- `support_brief.md`: `operator_only`.

## Data Product And Mesh Posture

Composite performance is declared as `lotus-performance:CompositePerformanceAnalytics:v1`.

Certification-relevant mesh controls:

- route: `/performance/composites/twr`;
- request scope: portfolio set;
- freshness class: batch;
- approved consumer: `lotus-gateway`;
- lineage version: `composite-lineage-v1`;
- required identifiers include `composite_id`;
- required trust metadata includes source fingerprints, request fingerprint, generation and as-of
  dates, source services, restatement evidence, and data-quality status.

## Test Pyramid Assessment

| Layer | Coverage | Assessment |
| --- | --- | --- |
| Model tests | Definition dates, membership dates, non-ready reason codes, negative asset rejection. | Good for contract validation. |
| Engine tests | Weighting, linking, degraded facts, no ready facts, no member facts, nonpositive assets, mixed return views, mixed currencies, one-member dispersion, inactive gaps, and reconciliation. | Strong for core methodology. |
| Service tests | Missing definitions, restated fact selection, persisted fact lookup, inspector findings and artifacts. | Strong for service behavior. |
| Integration tests | Public API success, missing definition, no persisted facts, degraded facts, invalid windows. | Strong for endpoint behavior. |
| OpenAPI tests | Persisted-fact contract text, schema descriptions, realistic error examples, and field descriptions. | Strong after Slice 13 Swagger hardening. |
| Downstream tests | Gateway route tests and Workbench typed BFF tests exist on their RFC-049 branches. | Strong after Slice 12 live direct API, Gateway, BFF, canonical front-office, and operations proof. |

## Current Evidence

Local validation:

- Slice 10 composite regression pack.
- Slice 12 live proof utilities and direct runtime probes.
- Slice 13 OpenAPI/API-certification hardening tests.
- Slice 14 docs contract and closure validation.

Remote CI evidence:

- PR `sgajbi/lotus-performance#162`
- Feature Lane and PR Merge Gate green after Slice 13 commit `60bf860`.

Live proof:

- direct `lotus-performance` composite TWR and inspector probes;
- Gateway composite TWR and inspector probes;
- Workbench BFF composite TWR and inspector probes;
- canonical Workbench validation for `PB_SG_GLOBAL_BAL_001`;
- operations evidence pack covering readiness, metrics, logs, Prometheus, and Grafana.
