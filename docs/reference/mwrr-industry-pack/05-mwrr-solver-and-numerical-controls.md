# MWRR Solver and Numerical Controls

**Status:** Draft numerical design guide  
**Audience:** Developers, quant/dev, QA, production support  
**Last updated:** 2026-05-08

## 1. Why solver design matters

MWRR looks simple conceptually, but production-grade IRR solving requires care.

Common issues:

- no valid root,
- multiple valid roots,
- convergence to different roots depending on initial guess,
- extreme annualized values for short periods,
- instability near `r = -100%`,
- near-zero NAV or cash-flow scale problems,
- floating-point precision and residual tolerance disputes.

A production engine should not rely only on a spreadsheet-style single initial guess.

## 2. XIRR function

Given dated cash flows:

```text
(date_i, CF_i)
```

Define:

```text
tau_i = days_between(anchor_date, date_i) / day_count_basis
```

The function is:

```text
f(r) = sum_i CF_i / (1 + r) ^ tau_i
```

The solver finds:

```text
f(r) = 0
```

Domain:

```text
r > -1
```

The domain exists because `(1 + r)` appears in the denominator.

## 3. Recommended solver approach

Recommended production sequence:

1. normalize and net cash flows,
2. validate at least one positive and one negative cash flow,
3. transform rate domain if useful,
4. scan a grid for sign-changing brackets,
5. refine each bracket using Brent or bisection,
6. de-duplicate roots within tolerance,
7. classify root count,
8. return result only when policy permits.

Avoid a default design that does only:

```text
Newton(initial_guess = 10%)
```

Newton may be fast, but it can fail or converge to an arbitrary root.

## 4. Rate domain

Lower bound must be greater than -100%.

Suggested lower bound:

```text
r_min = -0.999999999
```

Suggested upper bound should be configurable.

Example:

```text
r_max = 1000.0
```

This means 100,000% annualized. Extreme values should be flagged, not necessarily blocked.

## 5. Log-rate transformation

For numerical stability, solve in log-rate space:

```text
x = ln(1 + r)
r = exp(x) - 1
```

Then:

```text
f(x) = sum_i CF_i * exp(-x * tau_i)
```

Benefits:

- avoids direct singularity at `r = -1`,
- supports wide rate ranges,
- handles extreme annualized short-period results better,
- makes bracketing more stable across large rate ranges.

Example bounds:

```text
x_min = ln(1 + r_min)
x_max = ln(1 + r_max)
```

## 6. Bracket scanning

A bracket exists when `f(a)` and `f(b)` have opposite signs.

Basic approach:

```text
for each adjacent pair in grid:
    if f(x_left) == 0:
        record root
    if f(x_left) * f(x_right) < 0:
        refine bracket
```

Grid strategies:

| Strategy | Notes |
|---|---|
| Linear grid in rate space | Simple but poor near -100% and extreme rates. |
| Linear grid in log-rate space | More stable across wide rate ranges. |
| Adaptive grid | More work, better for unusual streams. |
| Multi-pass grid | Coarse scan, then dense scan near sign changes. |

Recommended default:

```text
log-rate grid + bracketed refinement
```

## 7. Root refinement

Preferred algorithms:

| Algorithm | Pros | Cons |
|---|---|---|
| Brent | Fast and robust for bracketed roots | More implementation complexity. |
| Bisection | Very stable and simple | Slower. |
| Secant | Faster than bisection | Less robust without bracket. |
| Newton | Fast near solution | Can fail, diverge, or find arbitrary root. |

Recommended:

```text
Use Brent when available. Use bisection as safe fallback.
```

## 8. Root classification

| Root count | Status | Recommended behavior |
|---:|---|---|
| 0 | `NO_ROOT_FOUND` | Return not calculable or explicit fallback. |
| 1 | `CONVERGED_UNIQUE_ROOT` | Return result. |
| >1 | `MULTIPLE_IRR_ROOTS_DETECTED` | Return not calculable by default. |

## 9. Multiple-root example

Cash flows:

| Date | Cash flow |
|---|---:|
| 2026-01-01 | -100 |
| 2027-01-01 | +230 |
| 2028-01-01 | -132 |

For annual periods, the equation becomes:

```text
-100 + 230 / (1 + r) - 132 / (1 + r)^2 = 0
```

This has roots:

```text
r = 10%
r = 20%
```

Production behavior should not silently select one.

Recommended response:

```json
{
  "status": "NOT_CALCULABLE",
  "reason_code": "MULTIPLE_IRR_ROOTS_DETECTED",
  "solver": {
    "root_count_detected": 2
  }
}
```

## 10. No-root cases

A no-root case occurs when the cash-flow function does not cross zero within the configured domain.

Recommended behavior:

- return `NOT_CALCULABLE`,
- include `NO_ROOT_FOUND`,
- include search bounds,
- include cash-flow summary,
- optionally compute Modified Dietz separately if policy allows.

Do not force a root by widening bounds indefinitely without governance. Extremely wide bounds can produce unstable or economically meaningless results.

## 11. Tolerances

Suggested tolerances:

| Tolerance | Suggested default | Notes |
|---|---:|---|
| Rate tolerance | `1e-10` | Raw rate precision. |
| NPV absolute residual | `0.01` reporting currency | Good for money-scale checks. |
| NPV relative residual | `1e-10` of gross cash-flow scale | Helps across different portfolio sizes. |
| Root de-duplication tolerance | `1e-8` rate | Avoid duplicate adjacent-bracket roots. |
| Max iterations | 100 to 200 | Depends on algorithm. |

Use both absolute and relative checks. A residual of 0.01 may be too strict for tiny portfolios and too loose for very large portfolios if used alone.

## 12. Money precision

Recommended:

- persist money using decimal or integer minor units,
- do not persist rounded intermediate cash flows unless source accounting does,
- convert to solver numeric type only after final normalized amounts are prepared,
- store raw return at high precision,
- round only for display.

Avoid binary floating-point for persisted money.

## 13. Scaling cash flows

IRR is scale-invariant. Multiplying all cash flows by a positive constant should not change MWRR.

Example:

```text
[-100, -100, +230]
```

and

```text
[-1,000,000, -1,000,000, +2,300,000]
```

should return the same MWRR if dates are identical.

This is a useful property test.

## 14. Same-day netting and ordering

Solver results should not depend on source-event ordering.

Recommended process:

1. normalize signs,
2. group by effective date,
3. sum amounts,
4. remove zero net amounts if desired,
5. sort by date.

Keep pre-netted source evidence for audit.

## 15. Anchor date

Common choice:

```text
anchor_date = earliest cash-flow date in solver vector
```

In normal portfolio-period MWRR, this is the period start because the BMV flow is inserted at period start.

If BMV is zero and omitted, anchor date may become the first investment flow date.

Document the policy for:

- zero start,
- delayed first deposit,
- account reopening,
- since-inception calculation.

## 16. Negative rates and annualization

The rate domain is:

```text
r > -100%
```

A holding-period return of `-100%` cannot be annualized using normal compounding because `1 + return = 0`.

A result close to `-100%` should be flagged:

```text
EXTREME_NEGATIVE_RETURN
```

## 17. Extreme positive rates

Extreme positive annualized returns can happen when:

- period is very short,
- beginning value is tiny,
- large gain occurs soon after investment,
- leveraged NAV is near zero,
- cash-flow timing creates high IRR.

Do not automatically reject extreme positive rates, but warn and provide holding-period return and cash-flow context.

Suggested warning:

```text
EXTREME_ANNUALIZED_RETURN
```

## 18. Solver diagnostics

Return or store:

| Field | Purpose |
|---|---|
| algorithm | Brent, bisection, Newton, etc. |
| root_count_detected | Detect ambiguity. |
| iterations | Debug performance. |
| residual_npv | Confirms solve quality. |
| rate_lower_bound | Evidence of search domain. |
| rate_upper_bound | Evidence of search domain. |
| day_count_basis | Required for reproduction. |
| anchor_date | Required for reproduction. |
| normalized_flow_count | Debug vector construction. |
| gross_cash_flow_scale | Relative residual checks. |
| convergence_status | Support and monitoring. |

## 19. Modified Dietz fallback controls

If Modified Dietz fallback is enabled:

- return `method = MODIFIED_DIETZ`,
- return `fallback_from = XIRR`,
- return `fallback_reason`,
- return `is_approximation = true`,
- show warning,
- preserve XIRR failure diagnostics.

Example:

```json
{
  "status": "FALLBACK_USED",
  "method": "MODIFIED_DIETZ",
  "fallback_from": "XIRR",
  "fallback_reason": "MULTIPLE_IRR_ROOTS_DETECTED",
  "is_approximation": true
}
```

## 20. Pseudocode: root search

```python
def find_xirr_roots(cash_flows, policy):
    # cash_flows are sorted and same-day-netted.
    # amounts use investor-perspective sign convention.

    anchor = cash_flows[0].date

    def tau(flow):
        return days_between(anchor, flow.date) / policy.day_count_denominator

    taus = [tau(flow) for flow in cash_flows]
    amounts = [flow.amount for flow in cash_flows]

    def f_x(x):
        # x = ln(1 + r)
        return sum(amount * exp(-x * t) for amount, t in zip(amounts, taus))

    x_min = log(1 + policy.rate_min)
    x_max = log(1 + policy.rate_max)
    grid = make_grid(x_min, x_max, policy.grid_size)

    brackets = []
    prev_x = grid[0]
    prev_y = f_x(prev_x)

    for x in grid[1:]:
        y = f_x(x)
        if is_close(prev_y, 0, policy.npv_tolerance):
            brackets.append((prev_x, prev_x))
        elif prev_y * y < 0:
            brackets.append((prev_x, x))
        prev_x = x
        prev_y = y

    roots = []
    for left, right in brackets:
        if left == right:
            root_x = left
        else:
            root_x = brent_or_bisect(f_x, left, right, policy)
        root_r = exp(root_x) - 1
        roots.append(root_r)

    roots = deduplicate_roots(roots, policy.root_dedupe_tolerance)
    return roots
```

## 21. QA expectations for solver

Solver tests should prove:

- no-flow one-year simple case returns simple return,
- mid-year deposit case matches expected XIRR,
- same-day netting is order-independent,
- all-positive and all-negative streams are rejected,
- multiple-root case is detected,
- no-root cases are detected,
- short-period annualized values are converted correctly,
- scale invariance holds,
- residual tolerance is enforced,
- fallback is clearly labeled,
- solver bounds are configurable.
