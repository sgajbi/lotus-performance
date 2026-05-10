# MWR Industry Review Findings

This record converts the supplied MWRR material into Lotus implementation truth. The source material
was used as a review input; the durable documentation is now Lotus-authored and tied to tested
`lotus-performance` behavior.

## Adopted Into The Current Contract

| Industry review theme | Lotus outcome |
| --- | --- |
| Use dated XIRR as the primary MWR calculation. | `/performance/mwr` uses XIRR-style dated cash-flow solving on an ACT/365 basis. |
| Do not hide solver failures. | Responses carry `status`, `reason_codes`, `warnings`, `fallback_from`, `fallback_reason`, and `is_approximation`. |
| Detect multiple roots and no-root profiles. | The solver scans the configured interval and emits `MULTIPLE_IRR_ROOTS_DETECTED` or `NO_ROOT_FOUND`. |
| Distinguish annualized and holding-period returns. | `money_weighted_return` remains the primary annualized value and `holding_period_return` is emitted separately. |
| Net same-day cash flows deterministically. | Cash flows are normalized and netted by date before solving; tests prove order independence. |
| Make support behavior operationally usable. | The MWR support playbook maps reason codes to support actions and client-safe explanations. |

## Areas Where Lotus Is Stronger

- Lotus treats MWR as a governed data mesh product capability, not a standalone calculation utility.
- OpenAPI, API vocabulary, monetary-float allowlist, and no-alias governance are part of the contract.
- Stateful mode provides integration lineage to upstream `lotus-core` evidence.
- `lotus-gateway` preserves supportability metadata instead of flattening the calculation result into
  a single return percentage.
- Response-attribute certification checks business fields, supportability fields, diagnostics, and
  audit evidence together.

## Intentional Current Boundaries

The following are not represented as supported Lotus behavior until implementation, tests, OpenAPI,
consumer propagation, and documentation are completed:

- true Modified Dietz as a separate independently certified method;
- multi-currency per-flow FX conversion inside MWR;
- component or attribution-level MWR decomposition;
- private-market since-inception IRR workflows with capital-call/distribution schedules;
- operational SLO dashboards for MWR reason-code frequency and fallback rate.

## Backlog Candidates

Candidate enhancements should be implemented as governed slices:

1. Add an independently certified Modified Dietz method if business reporting requires it separately
   from the current labeled fallback path.
2. Add MWR operational metrics for fallback rate, no-root rate, multiple-root rate, and stateful
   source-data rejection rate.
3. Add FX-aware MWR only after the cross-repository currency contract is explicit and consumer
   surfaces can show currency provenance.
4. Extend demo/wiki material when front-office surfaces expose reason-code drill-downs directly.

## Proof Points

Implementation-backed proof currently lives in:

- `engine/mwr.py` for solver behavior and supportability metadata;
- `app/models/mwr_responses.py` for the response contract;
- `tests/unit/engine/test_mwr.py` and `tests/integration/test_mwr_api.py` for calculation behavior;
- `tests/integration/test_response_attribute_certification.py` for emitted response fields;
- `docs/guides/mwr-lotus-production-controls.md` and
  `docs/operations/mwr-production-support-playbook.md` for product and support documentation.
