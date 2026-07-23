# RFC-0002 Idea Opportunity Runtime Evidence

`lotus-performance` owns source proof for the Performance side of `lotus-idea` RFC-0002 opportunity
archetypes. The proof surface is intentionally narrow: it packages runtime `ReturnsSeriesBundle:v1`
execution evidence for downstream Idea consumption without moving performance methodology,
benchmark return calculation, or benchmark-readiness semantics into Idea.

## Command

```bash
make idea-opportunity-runtime-evidence
```

The command writes:

```text
output/idea-opportunity-runtime-evidence/latest.json
```

Validate the contract with:

```bash
make idea-opportunity-evidence-gate
```

## Evidence Boundary

The artifact proves:

- underperformance review evidence from Performance-owned returns-series execution,
- missing-benchmark readiness posture with current portfolio coverage and explicit missing
  benchmark-context state,
- execution receipt identity, input fingerprint, calculation hash, request/response digests,
  coverage, freshness, benchmark-context posture, and bounded metric summaries,
- source-safe payload handling: raw canonical portfolio identifiers and raw return-series
  observations are not emitted.

The artifact does not prove:

- `lotus-core` benchmark-assignment source authority,
- Gateway or Workbench runtime consumption,
- Idea candidate persistence,
- data-mesh certification,
- client publication,
- production deployment,
- supported-feature promotion for Idea.

## Downstream Use

`lotus-idea` may consume this artifact to clear only the Performance-owned RFC-0002 Slice 16/17
source-proof blockers for underperformance and missing-benchmark opportunity archetypes. Idea must
continue to treat official performance, benchmark, active-return, freshness, and coverage values as
Performance-owned source evidence and must not recompute or override them locally.
