# Pooled Composite Money-Weighted Return

This metric measures the investor return on the composite's combined dated money.
It pools opening values, external contributions and withdrawals, membership
boundary capital, and terminal values before calling the existing MWR solver.
It does not average member IRRs.

The registered API, worker and immutable custody support controlled synthetic
qualification. The default supplier reader returns
`SOURCE_AUTHORITY_UNAVAILABLE`; real Core/Manage source applicability and
institutional attestation remain separate admission requirements.

## Submit and Read

Use `POST /performance/composites/analytics` with a signed bearer credential and
the matching `X-Tenant-Id`. Server-resolved grants require
`operations.runtime.manage` for submission and `operations.runtime.read` for
retained reads, plus scope over every historical member. An actor, role or
capability HTTP header cannot grant authority.

The request example in
[`app/api/examples/composite_pooled_mwr.json`](../../app/api/examples/composite_pooled_mwr.json)
selects `POOLED_MONEY_WEIGHTED_RETURN` / `XIRR:v1`, explicit dates, reporting
currency, return view, source manifest and policy binding. These identifiers must
resolve through deployment-owned trusted ports; submitting the example does not
install a source or approve its policy.

Submission returns `202` and provides `poll_path` for execution and `result_path`
for the retained dataset. The result path is
`/performance/composites/analytics/results/{calculation_id}`. A valid result can
be `AVAILABLE`, `NOT_CALCULABLE` or explicitly `FALLBACK_ANALYSIS`.
Always inspect `outcome.availability`, `actual_method`, units and reasons before
displaying a return. Ratios use `DECIMAL_FRACTION`: 0.10 means 10%.

## Source and Calculation Requirements

### Executable Controlled Examples

The original OR-15 example uses opening member values 50 + 50 on 2025-01-01,
terminal values 60 + 50 on 2026-01-01, and source-confirmed empty external flows.
Investor cash flows are therefore -100 and +110 exactly 365 days apart:
`-100 + 110 / (1 + r) = 0`, giving `r = 0.10`. Submit the following request
only with the explicitly installed controlled source and signing fixtures:

```json
{
  "composite_id": "CONTROLLED_POOL",
  "metric_id": "POOLED_MONEY_WEIGHTED_RETURN",
  "method": "XIRR:v1",
  "period_start": "2025-01-01",
  "period_end": "2026-01-01",
  "reporting_currency": "USD",
  "return_view": "GROSS",
  "source_manifest_id": "controlled-original-v1",
  "policy_binding_id": "controlled-xirr-policy-v1",
  "annualization": {"enabled": true, "basis": "ACT/365"},
  "fallback_policy": "REQUIRE_XIRR"
}
```

The original/replay registered test executes this request and asserts dated amounts,
fee basis, unique convergence and residual. The missing-terminal example removes
member-b's terminal source valuation: submission is accepted, the worker records
operational failure, no financial original is created, and retained GET returns 409.
The ambiguous example has investor amounts -100, +230, -132 at years 0, 1, 2;
both 10% and 20% solve the equation. With `REQUIRE_XIRR`, the retained outcome
is `NOT_CALCULABLE` with a null return and the actual multiple-root diagnostics.
Only explicit `ALLOW_MODIFIED_DIETZ` election permits `FALLBACK_ANALYSIS`.
These source variations belong to trusted fixture ports; the HTTP request cannot
provide or authorize financial source rows.

From the `lotus-performance` repository root, run all three registered examples
and their related controls with the repository's installed Python environment:

```powershell
python -m pytest tests/integration/test_composite_pooled_mwr_api.py -q
```

```bash
python -m pytest tests/integration/test_composite_pooled_mwr_api.py -q
```

The supplier resolves complete historical population metadata before any financial
source read. It independently verifies owner/policy authority. Performance then
checks the retained per-source cut/revision/digest vector, complete source pages,
policy election, dated membership, exact boundary valuations and complete flow
coverage. An empty flow array needs explicit source-owned empty coverage.

All monetary rows must already use one reporting currency. Exact source money
is preserved; the existing root solver uses FLOAT64 and reports that precision.
This contract admits ACT/365 only. Custom year divisors, ACT/ACT and BUS/252 refuse.

Unknown flow classifications, missing source dates, incomplete revision chains,
pending membership decisions and missing boundary values refuse. Internal transfers
cancel only when explicit source-linked counterparties and amounts reconcile.
No missing member or monetary observation is replaced with zero.

## Originals, Retries and Corrections

The worker binds full original inputs inside the existing active-claim database
transaction. Publication binds the original result to that retained input manifest.
Identical retries reuse the original without upstream financial reads. A changed
request or result under the same identity conflicts.

For a financial correction, use a new `calculation_id`, a new admitted source
manifest and `correction_of_calculation_id` identifying the retained original.
The composite, window, reporting currency, return view and method must match.
Both originals remain readable. A correction link does not supply approval,
official status or source authority.

Inputs and financial results have database immutability guards and are excluded
from ordinary retention. Their current indefinite fail-safe custody is interim:
governed purge and legal-hold lifecycle acceptance remains open. Operational
failures are recorded in the existing job/execution lifecycle, so a transient
failure cannot permanently freeze a financial failure result.

## Evidence and Limits

The [methodology](../methodologies/metrics/metric-composite-pooled-mwr.md) defines
signs, formulas, diagnostics and the tested two-year pooled oracle. Focused
registered API tests are in
[`tests/integration/test_composite_pooled_mwr_api.py`](../../tests/integration/test_composite_pooled_mwr_api.py).
Actual PostgreSQL tests in
[`tests/benchmarks/test_postgres_composite_pooled_mwr.py`](../../tests/benchmarks/test_postgres_composite_pooled_mwr.py)
cover active-claim contention, rollback, immutable guards, tenant isolation,
original/correction retention, source-independent retries and fresh interpreters.

The fresh-process read proof explicitly configures read-only repeatable-read
connections; it does not change production transaction defaults. It compares all
database tables before and after retained GETs, and separately checks unchanged
financial originals after retried POSTs. Controlled test signing keys and supplier
fixtures demonstrate behavior without claiming production IAM or bank qualification.
