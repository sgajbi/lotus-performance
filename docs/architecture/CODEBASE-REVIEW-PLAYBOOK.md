# Codebase Review Playbook

## Purpose

This playbook defines how `lotus-performance` is reviewed for correctness, durability,
operational safety, and maintainability.

The goal is not one cleanup pass. The goal is a durable review program with:

- explicit review scopes
- pattern-first review order
- evidence-based sign-off
- a persistent ledger of findings, fixes, and remaining work

The companion ledger is:

- [CODEBASE-REVIEW-LEDGER.md](./CODEBASE-REVIEW-LEDGER.md)
- [ISSUE-FIX-CLOSURE-MATRIX.md](./ISSUE-FIX-CLOSURE-MATRIX.md) for active GitHub issue batches
  before PR creation or issue closure.

## Review principles

1. Review by pattern first, not by random file traversal.
2. Record every meaningful finding with a concrete class:
   - stale code
   - duplication
   - modularity problem
   - query/performance risk
   - race-condition or correctness risk
   - observability gap
   - test gap
   - documentation drift
3. Push broad-runtime failures down into lower-level tests whenever possible.
4. Prefer the smallest coherent fix slice that closes a real invariant.
5. Sign-off requires code or characterization evidence, not opinion.

## Review units

Use one of:

1. Pattern review
- best default
- examples:
  - async orchestration and stage transitions
  - replay/idempotency/fencing
  - durable queue claim semantics
  - worker startup/shutdown and quiescence
  - OpenAPI/example consistency
  - stale or duplicate service logic

2. Domain review
- use when the ownership boundary is the real risk unit
- examples:
  - returns-series orchestration
  - lineage persistence
  - stateful input retrieval

3. File review
- use only when one file is the real failure boundary

## Status model

Each ledger row uses one of:

- `Not Started`
- `In Review`
- `Refactor Needed`
- `Hardened`
- `Signed Off`
- `Archived`

Use them precisely:

- `Refactor Needed` means material issues were found and not fully addressed.
- `Hardened` means fixes and evidence landed, but broader follow-up may remain.
- `Signed Off` means the reviewed scope is complete for now, with any residual work explicitly deferred.

## Required fields for each ledger entry

Every ledger entry must capture:

- review id
- review date
- scope/pattern
- status
- findings
- actions taken
- follow-up
- evidence

## Review checklist

### 1. Runtime correctness

- Are state transitions monotonic and durable?
- Can concurrent workers double-claim or double-complete work?
- Can retries or stale leases produce duplicate side effects?
- Is failure recovery explicit and observable?

### 2. Replay, idempotency, and fencing

- Are repeated submissions safe?
- Are stale attempts fenced at the durable-store boundary?
- Is async result state consistent with execution state?

### 3. Query shape and storage

- Are queue claim/read paths index-friendly?
- Are worker queries bounded and correctly ordered?
- Are locking semantics explicit for competing workers?

### 4. Modularity and ownership

- Is orchestration logic duplicated across endpoints/services?
- Are domain boundaries explicit?
- Is ownership clear for runtime control paths?

### 5. Observability and operations

- Can operators see backlog, stale work, and failed work?
- Are logs and metrics tied to durable state?
- Are health and support APIs reflecting real runtime behavior?

### 6. API and documentation quality

- Are request/response contracts descriptive and test-backed?
- Do architecture docs match the runtime?
- Do RFC and implementation docs describe current behavior truthfully?

### 7. Test coverage

- Is the invariant expressed at the lowest useful level?
- Are unit/integration tests proving the real failure mode?
- Is E2E retained as proof, not as the primary debugging loop?

## Workflow

1. Create or update the ledger entry with `In Review`.
2. Inspect the pattern, tests, and docs before editing.
3. Record concrete findings.
4. Fix the smallest coherent slice.
5. Add lower-level tests for the fixed invariant.
6. Run the smallest meaningful validation pack first.
7. Update the ledger with actions, evidence, and status.
8. Continue to the next highest-value pattern.

## Initial review queue

1. Async orchestration, worker leasing, and quiescence
2. Replay/idempotency/fencing across durable execution state
3. Hot-path DB claim/query shape and indexing
4. Ownership and duplicate orchestration logic
5. Observability and control-plane visibility
6. OpenAPI/example and vocabulary consistency
7. Stale code and documentation drift

## Sign-off standard

A scope is only `Signed Off` when:

- the material findings in that scope are addressed or explicitly deferred
- lower-level tests exist for the key invariants
- relevant runtime or integration evidence exists where applicable
- the ledger records exact evidence

If any of those are missing, do not mark it `Signed Off`.
