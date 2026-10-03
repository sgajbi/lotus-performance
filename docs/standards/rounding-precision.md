# Rounding and Precision Standard

This repository adopts the platform-wide mandatory standard defined in `lotus-platform/Financial Rounding and Precision Standard.md` and RFC-0063.

## Local Enforcement

- Monetary/financial calculations use `Decimal`.
- Intermediate calculations do not round.
- Output boundaries apply canonical scale + `ROUND_HALF_EVEN` via `precision_policy` helpers.
- Runtime policy metadata is exposed as `ROUNDING_POLICY_VERSION = "1.1.0"`.
- Compatibility policy_version for this repository is `1.1.0`.
- API/import normalization should call `normalize_input(value, semantic_type)` before domain execution.
- Any change to rules requires RFC approval in PPD.

## Enforcement Points

- Boundary validation: `precision_policy.py` (`normalize_input`) rejects malformed and over-scale inputs.
- Output boundary quantization: `quantize_*` helpers apply final rounding for response shaping.
- Intermediate precision preservation: domain logic keeps unquantized `Decimal` until output-edge serialization.
- `DECIMAL_STRICT` contribution keeps weights, returns, Carino factors, residual allocation, and
  emitted daily/position reconciliation in one Decimal domain. `FLOAT64` remains the compatibility
  return mode; strict requests are not silently downgraded. Both modes retain Decimal valuation
  money, cash-flow cancellation and fees before derived dimensionless return/weight projection.
- The shared TWR hot path may use exact `int64` arithmetic for whole monetary amounts in
  `FLOAT64`, with eightfold overflow headroom and no scaling. Original Decimal evidence is
  restored before reporting. Fractional, oversized and strict-mode amounts remain Decimal;
  this optimization changes neither financial rules nor rounding policy.

## Monetary Float Guard

- CI runs python scripts/check_monetary_float_usage.py.
- Baseline allowlist: docs/standards/monetary-float-allowlist.json.
- New findings fail CI until explicitly approved and allowlisted in dedicated PR.
- Each allowlist entry requires `justification`, `owner`, and `review_by` metadata.
- Stale allowlist entries (past `review_by`) fail CI.

### What the guard is about: amounts, not ratios

The rule governs **monetary amounts and the rates that multiply them**. It does not govern
dimensionless quantities.

| kind | examples | `float` acceptable? |
| --- | --- | --- |
| Monetary amount | cash-flow amount, market value, cost, notional | **No** — use `Decimal` |
| Rate that multiplies money | FX rate, price | **No** — representation error propagates into money |
| Dimensionless ratio | period return, weight, allocation percentage | Yes |
| Count or divisor | periods per year, day count, iteration bounds | Yes |

The guard matches on keyword substrings, so `rate` and `return` also match dimensionless
quantities. A match on a ratio or a divisor is a **false positive**, not deferred debt.

### Dispositioning a finding

Exactly one of two, chosen by what the value *is*:

1. **False positive** — a ratio, count, or divisor. Mark it at the code site with a
   `# monetary-float-allow` comment that says *why* it is outside the rule. It gets **no
   allowlist entry and no expiry**, because there is nothing to come back for. Recording it as a
   time-bounded allowance would assert debt that does not exist, and would return in 180 days to
   be re-derived by whoever picks it up.
2. **Real deferred debt** — a monetary amount or a rate that multiplies money. It keeps a dated
   allowlist entry whose `justification` says what this specific value is and links the issue
   that sizes the migration. A justification true of every entry explains none of them.

An allowlist entry the scan no longer produces must be **removed**, not carried. The guard only
computes findings-minus-allowlist, so a resolved finding keeps its approval unless somebody takes
it away; `tests/unit/scripts/test_monetary_float_usage.py` fails when an orphaned entry appears.

The 2026-09-22 review of expired cohort #472 retired 35 dimensionless-ratio or docstring matches.
#530 then migrated its reviewed market-value, benchmark-price, and FX-conversion boundaries to
Decimal and removed their dated allowances. Compatibility serializers may emit JSON numbers only
at the response edge; benchmark returns remain dimensionless float outputs. The guard still blocks
stale and newly introduced unapproved monetary floats. MWR retains admitted Decimal market values
and cash flows through date aggregation and Dietz capital arithmetic. XIRR projects same-date net
economics at an explicit finite float64 solver boundary; its root search is not an arbitrary-precision
money engine.

## Monetary Request Admission

Daily portfolio and position `begin_mv`, `end_mv`, `bod_cf`, `eod_cf` and `mgmt_fees`, MWR market
values and cash-flow amounts, and shared `FXRate.rate`, use Decimal admission.
Use JSON decimal strings for exact transport, for example `"123.45"` or `"1.123456789012"`.
Ordinary JSON numbers remain compatibility inputs: their parsed numeric value is converted via
its decimal text, not reconstructed from unavailable original digits. Float inputs with absolute
value at least `2^53` are refused; send a decimal string instead. JSON integers remain exact.

Raw request admission refuses boolean, absent required, non-finite and over-scale inputs. Maximum
raw input scales remain eight fractional digits for money and twelve for positive FX rates.
Core-calculated valuations and converted cash flows are calculated evidence, not raw imports:
internal validation preserves their finite Decimal precision without rounding to eight digits.
Only the internal calculated-evidence path enables this policy; request bodies cannot enable it.
Malformed calculated model evidence refuses with `CALCULATED_FINANCIAL_INPUT_INVALID` (422).
Retained admitted requests use the same internal validation when restored. This does not change
the rounding-policy version or output scales.

Decimal request serialization, MWR `cashflows_used.amount`, TWR bucket/daily monetary evidence,
Workspace economics and inspection monetary artifacts use JSON strings. Numerical returns and
weights remain numbers. Request fingerprints bind the admitted serialized representation;
do not reuse a calculation identifier across changed payloads. Retained previous results are not
rewritten to adopt a new request representation.

Dietz retains Decimal amounts and day-count weights until the dimensionless return boundary.
XIRR first nets same-date economics in Decimal, then explicitly projects finite solver coefficients;
overflow or nonzero underflow refuses rather than fabricating zeros. Arithmetic uses a local context
that preserves admitted significands, with a 4096-digit computation-span limit to refuse unbounded
exponent allocation. Decimal sign reversal uses `copy_negate`, not ambient-context unary negation.
Source cash-flow totals, carry-forward adjustments and position FX products use bounded contexts
before aggregation; large offsetting flows must preserve small residuals independently of order.
Unsupported engine domains return a non-retryable typed input refusal, not HTTP 500 or a zero result.

### Valuation Modes and Consumer Migration

`FLOAT64` projects derived return and weight ratios, not source valuation amounts. `DECIMAL_STRICT`
retains Decimal return arithmetic as well. Both use bounded monetary contexts before cancellation;
neither may invent a zero profit after projecting large opposing cash flows. For opening capital100,
closing value9007199254741093.02 and end-day deposit9007199254740993.01, profit is0.01 and daily
TWR is0.01%. Contribution after-fee closing values retain the existing NET/GROSS fee policy.

Consumers must accept monetary decimal strings before deploying calculation identity v15. Validate
the served schema and financial fixtures; producer CI alone is not consumer acceptance. Keep exact
text through monetary evidence processing and use deliberate presentation rounding at display edges.
Retained old responses keep their original schema and identity; corrections create new calculations.

XIRR `gross_cash_flow_scale` remains an approximate numeric diagnostic of projected solver
coefficients, not an original cash-flow total. Its newly visible annotation allowances share the
existing 2026-11-06 numerical-boundary deadline; #472 owns wider exception review. The scanner now
detects short valuation names, cash-flow and fee fields, and refuses an empty source inventory.
Finite ratios must also remain representable after percentage scaling and compounding. Overflow or
non-real compounded MWR refuses explicitly; currency return validation preserves missing-economics
handling rather than replacing missing returns with zero.
FX conversion retains admitted
rates and monetary products before any `FLOAT64` compatibility projection. `DECIMAL_STRICT`
continues to preserve Decimal calculations; `FLOAT64` is not an exact-money calculation claim.

The two retired monetary request allowances are removed. Two existing MWR/NumPy interoperability
allowances are relocated to `engine/numerical_boundary.py`, with their original 2026-11-06 review
deadline retained. They cover the checked legacy numerical projection, not request monetary storage.

## Deviation and Change Control

- Deviations require RFC/ADR approval linked from repository docs and the platform standard (RFC-0063).
- Compatibility-breaking policy changes require explicit RFC migration notes.

## Cross-Service Regression Link

- Shared golden fixture: `tests/fixtures/rounding-golden-vectors.json`.
- Platform check: `lotus-platform/automation/Validate-Rounding-Consistency.ps1`.
- Automation guide: `lotus-platform/automation/docs/Automation-Guide.md`.
- Evidence artifact: `Rounding Consistency Report`.
