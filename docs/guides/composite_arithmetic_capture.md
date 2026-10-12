# Composite source arithmetic capture and replay

The existing result-candidate POST accepts optional `precision_capture_profile: "AW_TWR_DECIMAL_REPLAY.v1"`. It collects source-time evidence from the admitted complete retained materialization vector. No caller-supplied capsule is accepted. Ordinary TWR and candidate calls without the profile retain their existing response shape. Historical candidates without a sidecar remain readable and are not backfilled.

The candidate response adds `arithmetic_capture: {digest, payload}` only when captured. The existing original response and its canonical bytes remain authoritative. This evidence neither approves a candidate nor qualifies financial sources, institutions, fees, reports or distribution.

## Captured arithmetic

The capsule binds verified tenant and creator, candidate and calculation identities, original response digest, semantic request binding, release commit, engine version, installed source digest, Python/Decimal runtime, exact retained windows and source references, and original ordered member facts. References point to retained materializations; the capsule never references its own digest.

An observer records existing Decimal controls, all nine entry and exit signal flags, and each period's already-computed assets, weighted return, next cumulative growth and cumulative return before final quantization. It performs no arithmetic, clears no flags and introduces no source context scope. Ordinary calculations use their existing ambient context; scheduled component calculations retain their existing scoped precision.

Installed replay restores that capture's own controls, traps and entry flags in an isolated context and calls the existing engine and shared response mapper. It requires exact original response, checkpoint and exit-flag equality, without reading current facts or resolving live upstream sources. Runtime or installed source changes refuse replay rather than executing historical code.

The separate rational audit records mathematical ideal M, native internal H, reported Q, internal arithmetic error H-M and final output error Q-H. The q12 HALF_EVEN bound is 0.5 × 10^-12 for Q-H only; it is not a bound on total Q-M error. The audit does not replace the native calculator.

## Identity and convergence

Full custody hashes every canonical capsule field, including all sticky signal histories. Equivalent retries return the first winning original response and full capsule, including its original IDs and creator. Different executor/candidate UUIDs and ordinary sticky-flag histories can converge; changed arithmetic controls, traps, facts, order, checkpoints, qualification numbers or source identities conflict even when the reported q12 return matches.

`CandidateArithmeticComparison.v1` excludes exactly these JSON pointers from the capsule comparison:

```text
/source/candidate_id
/source/calculation_id
/source/original_response_digest
/calculation_request/calculation_id
/response_binding/original_response_digest
/capture_binding/captured_by
/capture_binding/captured_at_utc
/capture_binding/credential_id
/capture_binding/principal_kind
/capture_binding/delegated_actor
/effective_context/entry_flags
/exit_flags
/evidence_binding_digest
```

The comparison also uses the existing candidate financial-response projection, which excludes only `/calculation_id` and `/selection_manifest/calculation_fingerprint`. The input digest includes scope, source references and ordered facts. Numeric controls and traps remain compared. No entire context, receipt or numeric/audit mixed digest is dropped.

## Resource and custody limits

Capture supports at most 120 windows and 120,000 original facts, an eight-MiB original input envelope, and an eight-MiB complete candidate result. Original finite numeric representations are limited to 160 characters and exponent magnitude 160. Checkpoint strings are bounded at 160 characters; exact reduced integer fractions have at most 4,096 digits (a conservative 13,600-bit computation guard). Unsupported controls, incomplete source coverage, projection mismatch or exceeded resources refuse before a successful candidate write.

Two nullable columns on the existing immutable descriptor retain canonical sidecar JSON and its SHA-256 digest. Database insertion guards require a paired bounded sidecar; the application additionally verifies exact bytes, digest, schema and custody bindings. Original and descriptor writes use the existing single database transaction, including concurrent winner recovery. No second financial ledger or new service is introduced.

The explicit durable schema owner upgrades the known legacy schema additively and preserves existing rows with a null pair. Half upgrades and unfamiliar schemas refuse. Runtime verification performs no repair. Apply the owner before deploying this reader/writer. Rollback must preserve populated tables, originals and paired sidecars; do not drop columns or tables to make an older writer start.

## Native verification

From the `lotus-performance` repository root with the pinned Python environment, both PowerShell and Bash use:

```text
python -m app.adapters.composite_arithmetic_capture.bundle
python -m pytest tests/unit/services/composite_arithmetic_capture tests/unit/services/test_composite_result_candidates.py tests/integration/test_composite_result_candidate_api.py
python scripts/durable_schema_apply.py --output-dir artifacts/durable-schema-apply
```

The bundle command emits the manifest for review; it does not silently rewrite the trusted manifest. The trusted fixed source paths use UTF-8, repository-relative POSIX identities and CRLF-to-LF normalization, preserving final newlines and refusing BOMs or isolated carriage returns. The manifest ships with the installed package and must match its actual source closure before capture/replay.

Unit and API controls cover known answers, observer/context/trap parity, sticky-flag convergence, changed arithmetic conflicts, concurrent IDs, retained reads, write faults, abrupt subprocess failure, legacy migration and strict wire refusal. SQLite controls do not establish PostgreSQL or deployed-stack qualification. Run the existing required PostgreSQL lane against its separately reserved test database before release.

S1 is source capture and per-side installed replay only. Any-two explanation, comparability, inventories, bridges, WVI/X, consumer acceptance and authority remain later work under Performance #656 and Platform #954.
