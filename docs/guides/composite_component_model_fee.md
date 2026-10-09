# Component-periodic model fees and original gross-cost custody

Publish `CompositeComponentPeriodicModelFeeProfile:v1` through the existing
`POST /performance/composites/model-fee-profiles`; read its exact immutable revision using the
existing GET operation. Publication remains `UNAPPROVED_METHOD_INPUT`. Submit the existing
materialization command with `NET_MODEL_FEE` and the full profile binding. No new API, store,
financial calculator or job family is introduced.

## Separate financial supply

`app/ports/composite_model_fees.py:composite_gross_cost_resolver` is a separate financial-source
port from the method catalog. Its deployment default is unavailable. Core's existing
`PerformanceComponentEconomics:v1` supplies underlying transaction-cost rows; it does not map
them to the selected gross receipt's included economic charges or wealth reference base.
No Core, Manage or Platform source-selection contract is changed by this consumer implementation.

The supplier returns the strict whole `CompositeGrossCostSource:v1` wire: product/version/revision,
producer identity, cut/watermark, exact definition/membership/attestation hashes, full model-profile
binding and sorted complete members. Each member retains the original gross receipt digest,
tenant/composite/member/complete period/currency/method/calendar/base, complete included-component
wire with economic-charge identity/fraction/original source evidence, and explicit completeness.
`COMPLETE_ZERO` means a complete declaration of no included components; missing data cannot become zero.

The reference wealth amount is explicit and must equal original beginning assets times one plus
the original gross return. This denominator check does not post a monetary charge or convert
monetary fees into fractions. Every component uses the same reference binding. The base binding
hashes the original gross digest, reporting currency, exact amount string and named convention
`BEGINNING_ASSETS_TIMES_GROSS_WEALTH_FACTOR`. The member evidence binding hashes every member
payload field except its own `evidence.evidence_binding`; all nested hashes are preserved.
Source and retained envelope are bounded to one MiB canonical JSON, with at most 1,000 members.

Independent verification uses the existing receipt-verification port with `PROVIDER_REGISTRATION`,
source product `CompositeGrossCostSource`, the whole source binding/hash, exact command/definition
and complete period. The verifier's independently expected issuer must equal the source producer.
The configured method/calendar adapter cannot supply this financial verification. A different
purpose, issuer, source content or verification receipt is refused. Current software admission
uses the existing synthetic receipt posture; production issuer qualification remains open.

## Durable execution and replay

The existing ledger pins the method and financial wire under its optimistic revision and lease
fence. The worker checks the complete selected native gross/cost population before its first
READY member write, then uses `component_model_net_return`, which delegates the original
periodic wealth transform. Bundle containers never add another charge; exact same-charge inclusion
offsets once. Member receipt `composite-member-source.v6` retains original gross evidence, full
fee entry, selected financial payload, whole financial-source binding and rederived total,
included and deducted fractions. Beginning assets and financial source identities stay intact.

Ledger reopen rechecks the retained original method, financial wire, verification and member math.
A fresh-process integration probe reproduces the complete fee-drag response without current
method/financial source reads. Existing database transactions, revision fencing, immutable catalog
identity and publication behavior remain the transaction boundary; there is no distributed commit.

Missing/catalog-only, foreign, incomplete, changed-cut, nested-hash tampering or independently
verified wrong-base inputs produce BLOCKED, zero READY facts and unavailable public analytics.
Production financial-source qualification, actual fees/rebates/crystallization, annual component
composition and specialized wrap/G5 correction remain outside this software increment.

## Validation

From the `lotus-performance` repository root, run on PowerShell or Bash with the repository's
activated Python environment:

```text
python -m pytest tests/unit/services/test_composite_component_cost_admission.py tests/integration/test_composite_component_model_fee_api.py -q
python -m pytest tests/unit/services/test_composite_scheduled_model_fee_catalog_upgrade.py -q
python scripts/postgres_concurrency_contracts_gate.py --target tests/benchmarks/test_postgres_composite_component_model_fee.py --target tests/integration/test_composite_component_model_fee_api.py
```

For PostgreSQL, set `LOTUS_POSTGRES_PLAN_DATABASE_URL` to an owned test instance before the same
integration command. The existing benchmark fixture allocates and cleans one isolated schema;
it does not modify other schemas. Root's exact rational example remains gross .02, total .010,
same-charge inclusion .002 -> .01184; distinct-charge full deduction -> .00980. Registered controls
also test complete zero, original asset weights, full source pins, hostile Decimal context and replay.
The existing required PostgreSQL gate includes both component targets. It rejects skips, empty
collection and nonzero subprocess exits; there are no component exceptions or threshold changes.
The migration target checks populated periodic/scheduled custody, owner-only expansion, rollback,
unknown schemas and concurrent immutable identity. This proof belongs in the existing PR/main
integration lane because SQLite cannot establish PostgreSQL DDL and concurrency behavior.

[Methodology](../methodologies/metrics/metric-composite-component-model-fee.md)
