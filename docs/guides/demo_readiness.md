# Demo Readiness Guide

This guide explains how to prepare and review `lotus-performance` API evidence before a demo,
client evaluation, or internal delivery review.

It is intentionally evidence-first. A demo is ready when the current implementation, deterministic
synthetic data, API responses, expected calculation figures, and generated evidence agree. This
guide does not certify every deployment, entitlement model, SLO, or production operating context.

## Audience Map

| Audience | What to use this guide for | Primary evidence |
| --- | --- | --- |
| Business and sales | Build an implementation-backed story around supported performance analytics without overclaiming roadmap work. | [Supported Features](../../wiki/Supported-Features.md), `output/demo-api-certification/latest.json` |
| Demo operators | Run one repeatable certification command and review the generated evidence before presenting. | `make demo-api-certification` |
| Engineers | Confirm that demo-critical API routes, calculations, capability publication, and docs truth still line up. | `scripts/demo_api_certification.py`, `tests/integration/test_demo_api_certification.py` |
| Operations and support | Explain readiness, degraded states, lineage, runtime status, and supportability boundaries. | [Operations Runbook](../../wiki/Operations-Runbook.md), [Validation and CI](../../wiki/Validation-and-CI.md) |

## One Command Certification

Run:

```bash
make demo-api-certification
```

The command prepares deterministic local runtime storage, seeds repeatable composite persisted-fact
data, calls real FastAPI routes through the application test client, asserts expected domain
figures, verifies enabled demo capability publication, and writes machine-readable evidence to:

```text
output/demo-api-certification/latest.json
```

Expected successful console summary:

```text
Demo API certification passed: checks=8, api_calls=12
```

The Quality Baseline Snapshot workflow also runs this command as report-only CI evidence and
uploads the JSON artifact. It is not yet a blocking readiness gate; promote it only after
CI-enforcement governance proves the signal is deterministic, low-noise, policy-backed, and stable
across the intended lane.

## Certified Demo Surface

The current certification sweep covers these request-level surfaces:

| Check | API routes called | What is asserted |
| --- | --- | --- |
| Capability registry | `GET /health`, `GET /health/ready`, `GET /integration/capabilities` | Health/readiness are available, supported demo paths are present, enabled, and expose the expected input modes. |
| TWR, contribution, attribution story | `POST /performance/twr`, `POST /performance/contribution`, `POST /performance/attribution` | Portfolio return is `2.0%`, benchmark return is `1.5%`, active return is `0.5%`, contribution total equals portfolio return, and attribution active return/effects reconcile to active return. |
| MWR XIRR | `POST /performance/mwr` | Response is `CALCULATED`, method is `XIRR`, convergence is true, and the expected money-weighted return is emitted. |
| Benchmark analytics | `POST /performance/benchmark` | Component contribution rows and total return match deterministic benchmark input. |
| Returns series | `POST /integration/returns/series` | Portfolio, benchmark, active, cumulative, and provenance fields match expected deterministic values. |
| Workspace summary | `POST /performance/workspace-summary` | Summary economics and supportability match the synthetic workspace story. |
| Mandate health context | `POST /performance/mandate-health-context` | Active-return posture, methodology posture, threshold posture, and reason codes match the expected DPM-supportability contract. |
| Composite TWR | `POST /performance/composites/twr` | Seeded persisted-member-fact composite data returns `READY` posture with expected composite return evidence. |

This sweep intentionally focuses on demo-critical paths. It is not a claim that every API route,
upstream stateful integration, downstream Workbench panel, security control, or production
deployment path has been fully certified.

## Evidence Review Checklist

Before presenting:

1. Run `make demo-api-certification` on the branch or build being demonstrated.
2. Open `output/demo-api-certification/latest.json`.
3. Confirm `status` is `passed`.
4. Confirm `api_call_count` is `12`.
5. Confirm there are `8` checks.
6. Confirm `feature_families` includes TWR, MWR, benchmark, returns series, contribution,
   attribution, workspace summary, mandate health context, and composite TWR.
7. Review the `assertions` for the story you plan to show; do not present unsupported figures that
   are absent from the evidence.
8. Cross-check product claims against [Supported Features](../../wiki/Supported-Features.md) and
   roadmap claims against [Roadmap](../../wiki/Roadmap.md).

## Demo Story Boundaries

Safe implementation-backed stories:

1. performance numbers are shown with supportability, warning, reason-code, benchmark-context,
   lineage, and runtime posture where the workflow emits them;
2. `lotus-performance` owns performance methodology and emitted analytics contracts;
3. `lotus-core` owns source portfolio, benchmark, index, FX, and reference truth;
4. Gateway and Workbench should consume emitted contracts rather than reconstructing calculations;
5. composite TWR is supported through persisted member-return facts at
   `POST /performance/composites/twr`, not through portfolio TWR request-time fan-out.

Do not claim:

1. blanket bank-buyable or production certification for every client environment;
2. full UI demo readiness from this backend API sweep alone;
3. production entitlement, SLO, observability backend, or deployment certification unless those
   controls have separate current evidence;
4. support for roadmap-only analytics such as composite contribution, composite attribution,
   composite MWR, fixed-income factor attribution, derivative attribution, or arbitrary
   multi-currency composite aggregation.

## Related Navigation

- README front door: [README.md](../../README.md)
- Current implementation-backed feature ledger: [Supported Features](../../wiki/Supported-Features.md)
- API grouping and route navigation: [API Surface](../../wiki/API-Surface.md)
- CI and documentation contract proof: [Validation and CI](../../wiki/Validation-and-CI.md)
- Complete service reference: [complete_service_reference.md](complete_service_reference.md)
- Demo certification implementation: [scripts/demo_api_certification.py](../../scripts/demo_api_certification.py)
