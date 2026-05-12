# RFC 049 Slice 12 - Implementation Proof

Status: complete on branch, pending PR merge.

## Purpose

Slice 12 proves the RFC-049 composite performance implementation against the live canonical
front-office stack. The proof intentionally exercises persisted composite member-return facts
through `lotus-performance`, `lotus-gateway`, and the `lotus-workbench` BFF path instead of relying
only on unit or integration tests.

## Live Proof Utilities

This slice added repeatable proof helpers:

| Artifact | Purpose |
| --- | --- |
| `scripts/seed_composite_performance_fixture.py` | Seeds deterministic private-banking composite definitions, memberships, and persisted member-return facts into the configured durable metadata store. |
| `scripts/capture_rfc049_live_composite_proof.py` | Captures and verifies direct performance, Gateway, and Workbench BFF composite evidence into non-committed `output/` artifacts. |
| `tests/unit/scripts/test_seed_composite_performance_fixture.py` | Proves the live fixture utility creates the expected definitions, memberships, ready facts, and degraded fact. |

The fixture writes through `CompositeMetadataStore` and `bootstrap_durable_metadata_stores()`, so
live proof uses the same durable composite store read by the application. In Docker, this is the
Postgres-backed store configured by `LINEAGE_METADATA_DATABASE_URL`.

## Live Fixture

Seeded composites:

| Composite | Purpose |
| --- | --- |
| `PB_GLOBAL_BALANCED_USD` | Ready two-period asset-weighted composite TWR proof. |
| `PB_GLOBAL_BALANCED_USD_DEGRADED` | Degraded one-period proof with one excluded member-return fact. |

Ready fixture facts:

| Period | Portfolio | Beginning assets | Return | Expected weight | Expected contribution |
| --- | --- | ---: | ---: | ---: | ---: |
| 2026-01-01 to 2026-01-31 | `PB_SG_GLOBAL_BAL_001` | 100.00 | 0.0100 | 0.250000000000 | 0.002500000000 |
| 2026-01-01 to 2026-01-31 | `PB_SG_GLOBAL_BAL_002` | 300.00 | 0.0300 | 0.750000000000 | 0.022500000000 |
| 2026-02-01 to 2026-02-28 | `PB_SG_GLOBAL_BAL_001` | 110.00 | -0.0100 | 0.250000000000 | -0.002500000000 |
| 2026-02-01 to 2026-02-28 | `PB_SG_GLOBAL_BAL_002` | 330.00 | 0.0300 | 0.750000000000 | 0.022500000000 |

Expected period returns:

- January 2026: `0.025000000000`
- February 2026: `0.020000000000`
- Cumulative linked return: `(1.025 * 1.020) - 1 = 0.045500000000`

The degraded fixture keeps `PB_SG_GLOBAL_BAL_001` ready and marks `PB_SG_GLOBAL_BAL_002` as
`DEGRADED` with reason code `missing_final_valuation`, proving fail-soft exclusion and reason-code
propagation.

## Evidence Captured

Local evidence directory:

```text
output/rfc-049-slice12-live-proof/
```

Captured artifacts:

| Artifact | Verified behavior |
| --- | --- |
| `performance-ready-twr.json` | Direct `lotus-performance` ready composite TWR over persisted facts. |
| `performance-inspection.json` | Direct inspection verdict, evidence summary, classified CSV/JSON/Markdown artifacts, and lineage manifest. |
| `performance-degraded-twr.json` | Direct degraded status, reason code, included/excluded member counts, and usable ready-member return. |
| `performance-no-facts-error.json` | Direct fail-closed no-facts error contract with `NO_MEMBER_RETURN_FACTS`. |
| `gateway-ready-twr.json` | Gateway route preserves source-owned payload, `source_service=lotus-performance`, correlation id, headers, and calculations. |
| `gateway-inspection.json` | Gateway inspection route preserves source-owned artifacts and support verdict. |
| `workbench-bff-ready-twr.json` | Workbench BFF path reaches the Gateway composite TWR route and preserves source-owned composite result. |
| `workbench-bff-inspection.json` | Workbench BFF path reaches the Gateway inspection route and preserves source-owned artifacts. |
| `rfc-049-slice12-live-proof-manifest.json` | Machine-readable proof manifest and arithmetic/supportability checks. |

Verified checks from the manifest:

```text
performance-ready-twr: cumulative_return=0.045500000000
performance-ready-twr: period returns, weights, currency, return view, and member inclusion verified
performance-inspection: verdict and classified artifacts verified
performance-degraded-twr: degraded status, reason code, exclusion count, and usable member return verified
performance-no-facts-error: no-facts error contract verified with status 422
gateway-ready-twr: cumulative_return=0.045500000000
gateway-ready-twr: period returns, weights, currency, return view, and member inclusion verified
gateway-inspection: verdict and classified artifacts verified
workbench-bff-ready-twr: cumulative_return=0.045500000000
workbench-bff-ready-twr: period returns, weights, currency, return view, and member inclusion verified
workbench-bff-inspection: verdict and classified artifacts verified
```

## Canonical Front-Office Validation

Canonical validation command:

```text
powershell -ExecutionPolicy Bypass -File scripts/live/Validate-LotusFrontOfficeCanonical.ps1 -PortfolioId PB_SG_GLOBAL_BAL_001 -BenchmarkCode BMK_PB_GLOBAL_BALANCED_60_40 -ScreenshotDirectory C:\Users\Sandeep\projects\lotus-performance\output\rfc-049-slice12-front-office-validation
```

Result:

```text
Live canonical Workbench validation passed for PB_SG_GLOBAL_BAL_001.
```

Evidence directory:

```text
output/rfc-049-slice12-front-office-validation/
```

The validation summary proves:

- governed canonical contract `canonical-front-office-demo-data-contract` version `1.0.0`;
- portfolio `PB_SG_GLOBAL_BAL_001`;
- benchmark `BMK_PB_GLOBAL_BALANCED_60_40`;
- canonical as-of date `2026-04-10`;
- DNS, Gateway, Workbench, performance, risk, advise, manage, report, archive, render, AI, and
  core host readiness;
- Gateway API readiness for foundation workspace, platform capabilities, performance summary,
  performance details, risk, advisor brief, DPM flows, report/archive/render readiness, and
  Workbench routes;
- browser-level demo-ready screenshots for portfolio, performance, risk, evidence, and DPM panels;
- panel classifications recorded as governed `ready` states for the validated front-office surfaces.

The wider canonical validation summary records `lotusManageActionRegister.state=stale`. The
validator classified this source-supportability condition without failing because the DPM panel
proof was still governed by its command-center, wave, outcome-review, proof-pack, and
portfolio-memory contracts. This is not an RFC-049 composite performance defect.

## Operations Evidence

Companion evidence command:

```text
npm run live:evidence
```

Evidence pack:

```text
C:\Users\Sandeep\projects\lotus-workbench\output\observability-live\20260512-135320
```

Manifest:

```text
C:\Users\Sandeep\projects\lotus-workbench\output\observability-live\20260512-135320\observability-evidence-manifest.json
```

The pack captured:

- DNS resolution;
- container inventory through captured logs;
- Gateway, Workbench, manage, report, archive, render, platform capability, performance summary,
  risk summary, and advisor brief API samples;
- Workbench Prometheus metrics;
- Prometheus target and `up` query samples;
- Grafana health;
- bounded log tails, including `performance-analytics` and `lotus-gateway`;
- Workbench evidence, risk, Prometheus, and Grafana screenshots.

## Issues Found And Treatment

| Issue | Severity | Finding | Treatment |
| --- | --- | --- | --- |
| Stale live containers did not expose composite routes | High for proof validity | The first direct probe against `http://performance.dev.lotus/performance/composites/twr` returned `404`, and container route introspection showed no composite routes in running `performance-analytics` or `lotus-gateway` images while local source exposed them. | Rebuilt and restarted only impacted `lotus-performance` and `lotus-gateway` containers, preserving the wider stack. Re-ran route introspection, reseeded the persisted composite fixture, and captured passing live proof. |
| Misused `npm run live:validate -- --ScreenshotDirectory ...` invocation | Low, operator command issue | The positional argument was treated as `PortfolioId`, causing expected `404` for an invalid portfolio id. | Re-ran the validator directly with explicit `-PortfolioId`, `-BenchmarkCode`, and `-ScreenshotDirectory` parameters. The corrected run passed. |

## Validation

Passed:

```text
python -m ruff check scripts\seed_composite_performance_fixture.py scripts\capture_rfc049_live_composite_proof.py tests\unit\scripts\test_seed_composite_performance_fixture.py
```

Passed:

```text
python -m pytest tests\unit\scripts\test_seed_composite_performance_fixture.py -q
1 passed
```

Passed after targeted rebuild and reseed:

```text
python scripts\capture_rfc049_live_composite_proof.py --output-dir output\rfc-049-slice12-live-proof
```

Passed:

```text
powershell -ExecutionPolicy Bypass -File scripts/live/Validate-LotusFrontOfficeCanonical.ps1 -PortfolioId PB_SG_GLOBAL_BAL_001 -BenchmarkCode BMK_PB_GLOBAL_BALANCED_60_40 -ScreenshotDirectory C:\Users\Sandeep\projects\lotus-performance\output\rfc-049-slice12-front-office-validation
```

Passed:

```text
npm run live:evidence
```

## Closure Assessment

Slice 12 proves the implemented composite TWR and inspection paths end to end across:

- persisted composite member-return facts;
- direct `lotus-performance` APIs;
- Gateway composite routes;
- Workbench BFF consumers;
- arithmetic and status verification;
- correlation, trace, and request headers;
- classified inspection artifacts;
- canonical front-office API and browser validation;
- operational metrics, logs, and dashboard evidence.

No RFC-049 composite implementation defects remain open from this slice. The live stack was left
running for continued agent work.
