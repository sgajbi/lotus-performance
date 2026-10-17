# Core service execution context

Performance can opt into Core's existing `lotus-enterprise-auth-context-v1` HMAC
protocol for source reads. The API and compute executor use the same existing
`build_stateful_input_service` composition. The worker restores the exact durable
job tenant before that factory runs; it does not replay the original user's
identity or an old signature.

## Operator configuration

`CORE_REQUEST_CONTEXT_ENABLED` defaults to `false`. Disabled mode deliberately
keeps tenant plus trace propagation for base compatibility. It does not bypass an
enforcing Core deployment: Core can refuse those unsigned calls. Enabled mode
requires every field below and fails closed at settings validation if incomplete.
There is no enabled-mode unsigned fallback.

| Environment variable | Operator-owned input |
| --- | --- |
| `CORE_REQUEST_CONTEXT_SERVICE_IDENTITY` | Exact separately admitted service execution identity. |
| `CORE_REQUEST_CONTEXT_KEY_ID` | Explicit key id matching Core's admitted primary key. |
| `CORE_REQUEST_CONTEXT_SECRET` | Secret supplied by the deployment's approved secret mechanism; Core must verify with the matching secret. |
| `CORE_REQUEST_CONTEXT_ACTOR_ID` | Explicit service execution actor, independent of the original user. |
| `CORE_REQUEST_CONTEXT_ROLE` | Explicit execution role. |
| `CORE_REQUEST_CONTEXT_TENANTS` | JSON array of exact admitted tenant identifiers; no wildcard, duplicates, or default tenant. |
| `CORE_REQUEST_CONTEXT_CAPABILITIES` | JSON array of exact independently admitted capabilities; no wildcard, duplicates, comma injection, or route-derived grants. |

Identity fields and allowlist entries are trimmed and bounded to 128 printable
ASCII characters. Secrets follow Core's trimmed-secret protocol. Do not place
secret values in source, examples, CLI arguments, logs, job payloads, or artifacts.
The existing app-local `docker-compose.yml` shares one declaration between API
and compute executor; external deployment manifests must provide the same profile
to both processes. Concrete identity/key/grant admission and deployment secret
delivery remain operator responsibilities. This change defines no issuer or
credential-provisioning framework.

## Source-call behavior

Each logical source request signs a new private final header map after tenant
admission. The tenant must be in the independent execution allowlist; an outside
tenant receives nonretryable `CORE_EXECUTION_SCOPE_DENIED`. Missing tenant remains
the existing tenant refusal. Tracing supplies correlation metadata only; actor,
role, service identity and capabilities come solely from configured authority.
No bearer token is forwarded as Core identity. Shared pooled client headers are
never changed.

At this source boundary, correlation metadata must fit Core's 128-character
printable ASCII bound. Invalid propagated correlation receives the typed,
nonretryable 400 `CORE_REQUEST_CONTEXT_MALFORMED` before any Core transport call;
the signer never truncates it or changes global ingress policy. The native
printable `<not-set>` sentinel remains signed exactly as presented; Core treats
it as absent lineage metadata rather than rejecting its HMAC context.

The signer normalizes header names and values, sorts exact capabilities and signs
Core's v1 canonical field order using HMAC-SHA256. It creates timestamps and
signatures in memory only. Pages, chunks, subsequent source calls and delayed
worker execution sign independently. Retry attempts within one logical read keep
the same context and existing retry/refusal policy. The enabled logical call has
a total 290-second deadline across connection, reads, retry sleeps and attempts;
expiration cancels the call and returns the existing safe 503 communication-failure
shape. Caller cancellation still propagates. Disabled calls retain existing timeout behavior.

The deadline assumes Core's default 300-second context maximum age. Operators
must align that verifier policy and synchronize clocks before activation. The
ten-second margin does not guarantee freshness under arbitrary clock skew;
Core remains authoritative and stale context is refused without fallback.

These source products require separately admitted native Core capabilities when
used; listing them here grants nothing:

| Performance source method | Native Core capability |
| --- | --- |
| Portfolio timeseries | `source_data.portfolio_timeseries_input.read` |
| Portfolio analytics reference | `source_data.portfolio_analytics_reference.read` |
| Benchmark assignment | `source_data.benchmark_assignment.read` |
| Benchmark definition | `source_data.benchmark_definition.read` |
| Benchmark return series | `source_data.benchmark_return_series_window.read` |

Other source methods use the same signer and require their own operator-admitted
capabilities under Core's route policy. Do not infer authority from an operation
name. Core 401/403 responses remain deterministic refusals, without fabricated
source data or retries intended to evade admission.

## Validation and acceptance boundary

Run focused synthetic checks from the `lotus-performance` repository root. The
same command works in PowerShell and POSIX shells with the repository environment
active:

```text
python -m pytest tests/unit/services/test_core_request_context_security.py tests/unit/services/test_core_integration_service.py tests/unit/services/test_core_tenant_admission_contract.py tests/unit/services/test_portfolio_source_service.py -q --no-cov
```

The tests exercise explicit configuration, a fixed protocol vector, concurrent
tenant isolation, worker restoration, cancellation, bounded retry and deadline,
and disabled compatibility. Independent offline evaluation additionally runs the
actual pinned Core verifier and middleware with synthetic credentials and source
responders. That harness is evaluation evidence outside the product, not a
repository runtime dependency or live supplier proof.

Installed API and worker images, real credential admission, fresh stateful jobs,
paged/chunked acquisition, persisted terminal outcomes and downstream Composite
use still require Root's reserved runtime evaluation. Authentication alone does
not qualify financial inputs, source cuts, methodology or institutional approval.
