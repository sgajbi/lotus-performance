# Group-Return Evidence Endpoint Certification

`POST /integration/attribution/group-return-evidence/v1` is the Performance-owned producer for
Risk's empirical active-risk input. It publishes aligned portfolio and benchmark group economics;
it does not calculate risk attribution, grant a tenant, or substitute for a Core booking source.

## Contract and ownership

One request names one portfolio, optional explicit benchmark, inclusive daily window, grouping
(`ASSET_CLASS`, `COUNTRY`, `CURRENCY`, or `SECTOR`) and required uppercase reporting currency.
The route obtains the admitted tenant only from request authority. It has no tenant default and
uses that authority for every Core retrieval and durable execution record.

Each row is expressed as decimal ratios and contains group identity/label, date,
`portfolio_group_return`, `benchmark_group_return`, `portfolio_weight`, `benchmark_weight`, and
the exact group active-contribution formula:

`portfolio_weight * portfolio_group_return - benchmark_weight * benchmark_group_return`

`aggregate_returns` carries the authoritative source portfolio return, benchmark component return,
and active return for the same date. It also carries the group-weighted portfolio return and both
reconciliation deltas. A response is `COMPLETE` only when every daily difference is within the
published `coverage.reconciliation_tolerance` of `0.000001` return ratio (0.01 basis point).
`valuation_basis` declares source-reported beginning and ending market values in the required
reporting currency. `weight_basis` declares that portfolio beginning-capital weights are signed;
negative-capital hedge groups therefore retain their signed contribution rather than being
silently omitted or reweighted.

The endpoint refuses, rather than filling or renormalizing, incomplete retained position rows,
missing classifications, duplicate source observations, non-finite economics, source-calendar
gaps, benchmark weights not reconciling to one, failed upstream snapshots, non-positive portfolio
capital, conflicting labels, stale or foreign snapshot scope, and currency mismatch. Explicit zero
group points are published only from a complete source position calendar.

Canonical Core `income` cash-flow facts remain source return economics, not an invented external
flow. Fees and externally timed flows retain the existing Performance valuation normalization.

## Lineage and replay

The response records the tenant-bound `execution_id`, the effective date and exact durable upstream
retrieval fingerprints. Snapshot scope is checked against the requested portfolio, benchmark,
as-of date and window end date before publication. Core's current contract does not provide an
upstream native revision identifier, so `upstream_revision_status` truthfully reads
`NOT_PROVIDED_BY_SOURCE`.

`source_cut_id` is a stable SHA-256 digest of only consumed economic context, canonical upstream
snapshot fingerprints, and produced evidence rows. It deliberately excludes execution IDs, serving
timestamps, and unrelated source metadata; identical reads produce the same cut, while a source
restatement/fingerprint change, portfolio scope change, currency, window, benchmark, grouping, or
evidence-row change produces a different cut.

Risk must independently accept this producer contract before it removes its
`group_return_series_unavailable` limitation. It must not use a response with a failed lineage or
reconciliation condition as empirical attribution input.

## Focused certification

From the `lotus-performance` checkout:

```powershell
python -m pytest tests/unit/services/test_group_return_evidence_service.py tests/unit/services/test_group_return_evidence_workflow_service.py tests/integration/test_group_return_evidence_api.py -q
```

The focused suite proves independently derived heterogeneous and signed-hedge figures,
zero-exposure treatment, canonical income handling, restatement and portfolio-scope source-cut
changes, currency and label-conflict refusal, stale/foreign and failed source-lineage refusal,
execution registration, and the served versioned HTTP contract. Run the repository premerge gate
before promotion; focused tests are not release evidence.
