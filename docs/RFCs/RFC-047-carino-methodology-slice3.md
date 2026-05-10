# RFC-047 Slice 3 - Carino Methodology Correction and Deterministic Engine Proof

| Field | Value |
| --- | --- |
| RFC | RFC-047 - Contribution Carino Methodology Alignment and Evidence Contract |
| Slice | 3 - Carino Methodology Correction and Deterministic Engine Proof |
| Status | Complete for Slice 3 implementation |
| Date | 2026-05-10 |
| Branch | `docs/rfc-contribution-carino-alignment` |

## Purpose

Slice 3 corrects the contribution smoothing formula to the supplied Carino methodology and proves
the deterministic cases before any response-evidence expansion is added.

## Implemented Correction

| Area | Before Slice 3 | Slice 3 implementation |
| --- | --- | --- |
| Carino factor direction | Daily smoothed contribution used a residual-style adjustment based on `K / k_t`. | Daily smoothed contribution now applies `F_t = k_t / K` directly to raw daily contribution. |
| Logarithm calculation | Used `log(1 + r)` and exact zero comparison. | Uses `log1p(r)` and near-zero tolerance. |
| Raw-vs-linked proof | Existing tests covered current behavior but did not prove the source-doc `+10%/-10%` example. | Added deterministic factor and contribution tests for the source-doc example. |
| Zero linked return | Only zero daily return was covered. | Added zero-linked-return smoothing proof. |
| Invalid domain | Existing invalid-domain fallback remained intact. | Carino still falls back to raw contribution when a daily linked gross return factor is `<= 0`. |
| Documentation | Methodology docs still described the old adjustment. | Methodology, guide, technical notes, and request-field OpenAPI description now describe `F_t = k_t / K`. |
| Monetary-float governance | Slice 2 moved approved Carino float usage from `engine/contribution.py` to `engine/contribution_smoothing.py`, which caused CI to fail until the allowlist was realigned. | Updated `docs/standards/monetary-float-allowlist.json` to preserve the existing approved Carino float treatment at the new file path and line references. |

## Formula

For a valid linked return path:

1. `k_t = log1p(R_P,t) / R_P,t`, with `k_t = 1` for near-zero `R_P,t`.
2. `R_P = product_t(1 + R_P,t) - 1`.
3. `K = log1p(R_P) / R_P`, with `K = 1` for near-zero `R_P`.
4. `F_t = k_t / K`.
5. `smoothed_contribution_i,t = raw_contribution_i,t * F_t`.

If any daily linked gross return factor is non-positive, Carino is not mathematically valid for the
slice and Lotus falls back to raw daily contribution arithmetic.

## Deterministic Proof

The supplied industry example is now encoded in `tests/unit/engine/test_contribution.py`:

| Day | Portfolio return | `k_t` | Linked `K` | `F_t = k_t / K` |
| --- | ---: | ---: | ---: | ---: |
| 1 | `+10%` | `0.9531017980` | `1.0050335854` | `0.9483283066` |
| 2 | `-10%` | `1.0536051566` | `1.0050335854` | `1.0483283066` |

The same test pack proves:

1. raw arithmetic contribution sums to `0.0` for `+10%/-10%`;
2. linked portfolio return is `-1.0%`;
3. Carino-smoothed contribution sums to `-1.0%`;
4. zero daily return uses neutral factor `1.0`;
5. near-zero return uses neutral factor `1.0`;
6. zero linked return uses neutral total factor `1.0`;
7. invalid `-100%` or worse daily return falls back to raw contribution.

## Documentation and Contract Updates

Updated implementation-backed wording in:

1. `docs/methodologies/metrics/metric-contribution-total.md`
2. `docs/guides/contribution.md`
3. `docs/technical/formula-mapping-review-notes.md`
4. `app/models/contribution_requests.py`

The broader response evidence contract remains Slice 4 scope. Slice 3 deliberately corrects and
proves the core formula before adding new public evidence fields.

## Validation Evidence

Local validation completed on 2026-05-10:

1. `python -m ruff check engine/contribution.py engine/contribution_smoothing.py tests/unit/engine/test_contribution.py app/models/contribution_requests.py` - passed
2. `python -m ruff format --check engine/contribution.py engine/contribution_smoothing.py tests/unit/engine/test_contribution.py app/models/contribution_requests.py` - passed
3. `python -m pytest tests/unit/engine/test_contribution.py -q` - `17 passed`
4. `python -m pytest tests/integration/test_contribution_api.py -q` - `34 passed, 1 warning`
5. `python -m pytest tests/unit/docs/test_public_docs_contract.py tests/unit/docs/test_metric_methodology_docs.py -q` - `49 passed`
6. `python scripts/check_monetary_float_usage.py` - passed, `Findings=135, allowlisted=135`
7. `make lint` - passed
8. `make typecheck` - passed

The integration warning is the pre-existing FastAPI 422 deprecation observed in Slice 2.

## Slice 3 Review

Slice 3 is complete:

1. the factor direction is corrected to `k_t / K`;
2. the source-doc example is encoded as deterministic proof;
3. raw arithmetic mismatch before smoothing is visible in tests;
4. zero daily, zero linked, near-zero, and invalid-domain cases are covered;
5. docs and OpenAPI request-field wording no longer describe the old adjustment formula.

Remaining work moves to Slice 4: expose raw/smoothed contribution evidence, residual posture,
status, and reason codes in the public response contract.
