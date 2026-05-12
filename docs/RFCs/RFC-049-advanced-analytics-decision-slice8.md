# RFC 049 Slice 8 - Gated Advanced Composite Analytics Decision

Date: 2026-05-12
Branch: `draft/rfc-049-composite-performance-alignment`
PR: `sgajbi/lotus-performance#162`
Status: Implemented and locally validated

## Purpose

Slice 8 is a product and architecture gate. Its purpose is to prevent RFC 049 from turning into a
wide but shallow composite analytics implementation. The slice decides which advanced composite
analytics are included in this RFC and which remain explicit unsupported boundaries.

## Decision

RFC 049 will continue with persisted-fact composite TWR, source authority, inspection, evidence,
operational supportability, downstream realization, live proof, and implementation-backed
documentation.

RFC 049 will not implement the following advanced scopes in this wave:

1. composite contribution;
2. composite attribution;
3. composite MWR;
4. carve-outs;
5. sleeves;
6. model portfolios;
7. wrap programs;
8. pooled fund composites;
9. private-market composites;
10. portability records;
11. tax-aware composites;
12. leveraged composites;
13. long/short special composite structures;
14. multi-currency composite aggregation beyond the current single reporting-currency guard.

The reason is not that these are unimportant. The reason is that each requires additional source
authority, methodology, result-version storage, reconciliation, downstream realization, and live
evidence before it can be bank-buyable. Implementing any of them superficially would make
`lotus-performance` less trustworthy.

## Current Implemented Composite Boundary

The RFC 049 implementation currently supports these branch-level building blocks:

1. composite source-authority models;
2. effective-dated membership models;
3. persisted member-return facts;
4. asset-weighted composite TWR over persisted member-return facts;
5. public `POST /performance/composites/twr`;
6. `CompositePerformanceAnalytics:v1` data-product declaration and trust telemetry;
7. return-view separation for gross, net actual, and model-fee fact views;
8. single reporting-currency guard;
9. source fingerprint and restatement-version evidence;
10. public `POST /performance/composites/inspect` with classified evidence artifacts.

This is not yet a final supported-feature claim for demos or downstream consumers until the later
RFC 049 slices complete downstream realization, live proof, methodology documentation, wiki
productization, supported-feature updates, and final closure.

## Advanced-Scope Evaluation

| Scope | Decision | Why |
| --- | --- | --- |
| Composite contribution | Unsupported in RFC 049 | Needs composite result-version storage, benchmark/member reconciliation, position economics roll-up, and downstream proof. |
| Composite attribution | Unsupported in RFC 049 | Needs composite benchmark/version policy, classification versioning, residual materiality policy, and reconciliation to composite active return. |
| Composite MWR | Unsupported in RFC 049 | Composite performance source pack and current Lotus architecture point to persisted TWR member facts first; composite MWR needs separate cash-flow/member policy and investor-flow semantics. |
| Carve-outs and sleeves | Unsupported in RFC 049 | Need source-owned sleeve/carve-out definitions, cash/flow allocation policy, and audit-grade allocation evidence. |
| Model portfolios and wrap programs | Unsupported in RFC 049 | Need strategy/model authority, fee policy, sponsor/platform metadata, and presentation restrictions. |
| Pooled funds and private markets | Unsupported in RFC 049 | Need valuation-lag policy, stale-price handling, appraisal evidence, and private-market accounting semantics. |
| Portability records | Unsupported in RFC 049 | Need legal/audit provenance, prior-firm identity controls, and publication governance. |
| Tax-aware composites | Unsupported in RFC 049 | Need tax-lot/source authority and jurisdiction policy. |
| Leveraged and long/short special structures | Unsupported in RFC 049 | Need exposure, financing, and net/gross methodology beyond current persisted member-return facts. |
| Multi-currency special handling | Unsupported beyond current guard | Current composite TWR blocks mixed reporting currencies; FX-aware composite aggregation requires source-owned conversion evidence and policy. |

## Guardrails

1. Product docs must not claim composite contribution, composite attribution, composite MWR, sleeves,
   carve-outs, or special structures as supported.
2. Gateway and Workbench must not create their own composite contribution, attribution, MWR, sleeve,
   or carve-out behavior.
3. Composite TWR support must remain tied to persisted member-return facts, source fingerprints,
   restatement versions, return view, and reporting-currency evidence.
4. Any future advanced scope must reconcile to persisted composite result versions and must include
   source authority, tests, OpenAPI certification, downstream realization, live proof, and
   implementation-backed docs before it can become a supported claim.

## Validation Evidence

Local validation passed:

1. `python -m pytest tests\unit\docs\test_public_docs_contract.py -q`;
2. `python -m ruff check tests\unit\docs\test_public_docs_contract.py`;
3. `python -m ruff format --check tests\unit\docs\test_public_docs_contract.py`;
4. `git diff --check`.

## Slice 8 Conclusion

Slice 8 is complete. RFC 049 remains focused on making persisted-fact composite TWR bank-buyable
rather than diluting the delivery with unproven advanced scopes. Unsupported advanced boundaries are
explicit, tested, and demo-safe.
