# Roadmap

## Current phase

`lotus-performance` is in an active hardening and operator-readiness phase rather than initial
scaffolding.

RFC 049 is the active composite-performance implementation RFC. It does not mean composite
performance is already supported. Current supported-feature truth remains portfolio-level until
RFC 049 delivers, proves, documents, and promotes composite capability through the supported-features
ledger and wiki.

## Delivered foundations

- stateful `lotus-core` sourcing for major performance workflows
- durable async execution lifecycle
- lineage-backed reproducibility
- benchmark-aware analytics and workspace summary surfaces
- runtime-status, recovery, and retention operator APIs

## Intentional limitations

- upstream source-data authority remains outside this repo
- transport optimization to `lotus-core` is deferred until retrieval-shape evidence justifies it
- wiki pages should stay navigational and operational, not duplicate the full guide and RFC estate

## Near-term focus

- deliver RFC 049 slice by slice, starting from source authority, persisted member-return facts,
  batch/recalculation controls, composite TWR, inspector/export evidence, lineage, downstream
  realization, and implementation-backed documentation
- keep public docs and wiki aligned with the shipped contract
- keep operator/runtime guidance easier to navigate for support workflows
- continue reducing drift between code surfaces, deep docs, and onboarding material
