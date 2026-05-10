# MWR Production Support Playbook

This playbook supports `lotus-performance` MWR triage for operations, support, business users, and
client-facing teams. It is written against the current `/performance/mwr` implementation and should
not be used to infer unsupported calculation behavior.

## First Response Checklist

1. Confirm the request mode: `stateless` or `stateful`.
2. Confirm portfolio id, reporting window, valuation dates, and cash-flow dates.
3. Check `status`, `method`, `reason_codes`, `warnings`, `fallback_from`, `fallback_reason`, and
   `is_approximation`.
4. Compare `money_weighted_return` with `holding_period_return` before discussing short-period
   results with business users.
5. Review `convergence` for root count, residual NPV, day-count basis, solver bounds, and normalized
   flow count.
6. For stateful requests, review `calculation_supportability` and source lineage before escalating
   to `lotus-core` data owners.
7. Check `/metrics` for
   `lotus_performance_mwr_solver_outcome_total{input_mode,method,status,reason_code,fallback_used}`
   when triaging repeated fallback, no-root, or multiple-root patterns.

## Reason-Code Triage

| Reason code | Meaning | Support action |
| --- | --- | --- |
| `MULTIPLE_IRR_ROOTS_DETECTED` | The cash-flow profile can produce more than one valid IRR root. | Do not quote an arbitrary XIRR. Explain that the profile is economically ambiguous for IRR-style reporting and use the labeled fallback if present. |
| `NO_ROOT_FOUND` | No root was found inside the configured solver interval. | Check for unusual valuation/cash-flow scale, data sign issues, and whether fallback was enabled. |
| `NO_POSITIVE_AND_NEGATIVE_CASH_FLOW` | Investor cash flows do not contain both signs after normalization. | Validate the caller's contribution/withdrawal classification and source transaction mapping. |
| `NO_ECONOMIC_CONTENT` | The request has no meaningful valuation or cash-flow economics. | Treat as not applicable, not as a normal zero return. |
| `ZERO_DENOMINATOR` | The fallback denominator is zero or unusable. | Check beginning market value and weighted cash-flow profile. |
| `FALLBACK_USED` | Lotus returned a labeled approximation because primary XIRR was unavailable. | Confirm `fallback_from`, `fallback_reason`, and `is_approximation=true` are preserved in the consumer surface. |

## Client-Safe Explanation Language

- Standard MWR: "Lotus reports money-weighted return as the investor capital-timing return for the
  period. It includes the timing and size of investor cash flows."
- Short window: "The primary MWR value is annualized. The holding-period return is provided
  separately so the period result can be discussed without annualization distortion."
- Fallback: "The cash-flow profile did not support a unique XIRR result. Lotus therefore returned a
  labeled approximation and included the reason code rather than selecting an arbitrary root."
- Not applicable: "The input did not contain enough economic content to calculate an investor
  money-weighted return. Lotus reports that explicitly instead of presenting a misleading zero."

## Escalation Boundaries

Escalate to `lotus-performance` engineering when:

- solver metadata is absent from a response that should include it;
- `lotus-gateway` or another consumer drops status, reason codes, warnings, or approximation flags;
- a documented reason code is missing from OpenAPI or API vocabulary artifacts;
- repeated stateful requests show inconsistent supportability metadata for the same input evidence.
- `lotus_performance_mwr_solver_outcome_total` stops emitting bounded `reason_code`, `status`, or
  `fallback_used` labels for completed MWR responses.

Escalate to upstream data ownership when:

- source observations in `lotus-core` have missing valuation anchors;
- investor cash flows are misclassified, duplicated, or sign-inverted before reaching
  `lotus-performance`;
- carry-forward adjustments are missing for a stateful window that requires them.
