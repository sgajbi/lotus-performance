# Annual Composite Member Dispersion

## Metric

`ANNUAL_MEMBER_DISPERSION` measures the cross-sectional spread of geometrically linked annual returns of historical members included for the entire calendar year. It is calculated analysis, distinct from time-series composite volatility and official report selection.

## Endpoint and Mode Coverage

`POST /performance/composites/analytics` selects this metric and one named estimator. The operation reads twelve exact retained COMPLETE monthly materialization receipts. It does not submit executions or select latest revisions. Supported fee views are `GROSS` and `NET_ACTUAL`; model-net admission is outside this metric.

## Inputs

Required fields are `composite_id`, `year`, `return_view`, `reporting_currency`, and twelve unique `materialization_ids`. `metric_id` defaults to `ANNUAL_MEMBER_DISPERSION`; `method` defaults to `EQUAL_WEIGHT_SAMPLE_STDDEV`. Extra fields are refused, including client-supplied returns, assets, and member lists.

The source vector must cover every complete month of the selected year, with one composite, currency, actual fee view, definition content hash, and policy version. Monthly membership revisions and source cuts may differ and are retained explicitly. A definition or policy change requires separate reviewed admission; this version refuses that mixed basis.

## Upstream Data Sources

Manage owns definition, membership decisions, and full-universe attestations. Performance's existing materialization store owns immutable monthly receipts and admitted member-return evidence. The read adapter uses tenant-scoped lookup; retained-progress validation checks source digests, complete universe coverage, membership decisions, and verified member facts. COMPLETE receipt reads additionally require the matching completed publication manifest.

The annual member set is the intersection of twelve READY populations. An explicitly excluded partial-year member is outside that set. Missing, pending, blocked, or inconsistent evidence is refused; it is never converted into an exclusion. No current portfolio inventory or survivor filter is consulted. January beginning market value supplies the asset-weighted estimator's asset basis.

## Unit Conventions

Returns are decimal ratios: `0.01` means 1%. `value` is a decimal return ratio quantized to `1e-12`, using the existing composite Decimal quantizer's half-even rounding. Multiply by 100 for display in percentage points. Assets use the selected reporting currency; this operation performs no FX conversion. Decimal computation uses precision 60 with exponent limits -128 and 128; nonzero input adjusted exponents outside that interval are refused. Decimal calculation failures are refused.

## Variable Dictionary

| Symbol | Meaning |
| --- | --- |
| `S_m` | Admitted READY member identities for calendar month `m` |
| `S` | Intersection of `S_1` through `S_12` |
| `n` | Number of full-year members in `S` |
| `r_i,m` | Retained decimal monthly return of member `i` |
| `R_i` | Linked annual decimal return of member `i` |
| `A_i` | January beginning assets of member `i` |
| `R_bar` | Equal-weight arithmetic mean of annual member returns |
| `W` | Sum of positive January beginning assets |
| `R_A` | Asset-weighted annual mean |
| `sigma_s` | Equal-weight sample standard deviation |
| `sigma_A` | Year-begin asset-weighted population standard deviation |

## Methodology and Formulas

`S = intersection(S_1, ..., S_12)` and `R_i = product(1 + r_i,m, m=1..12) - 1`.

`EQUAL_WEIGHT_SAMPLE_STDDEV`: `R_bar = sum(R_i) / n`; `sigma_s = sqrt(sum((R_i - R_bar)^2) / (n - 1))`. The estimator uses `ddof=1` and requires at least two members.

`YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV`: `W = sum(A_i)`; `R_A = sum(A_i * R_i) / W`; `sigma_A = sqrt(sum(A_i * (R_i - R_A)^2) / W)`. Every selected member's assets must be finite and strictly positive. The registered method requires at least two members. No sample correction is applied to this named weighted population estimator.

The [GIPS Standards Handbook for Firms](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/) distinguishes annual full-year-member internal dispersion (4.A.1.i), year-end portfolio count (4.A.1.f), and 36-month annualized time-series standard deviation (4.A.1.j). A full-year population of five or fewer gives `NOT_REQUIRED_SMALL_POPULATION`, independently of numerical computability. The response does not establish GIPS compliance, institutional methodology approval, or official publication eligibility.

## Step-by-Step Computation

1. Require tenant authority and read each exact receipt through the read port.
2. Sort by retained month start and validate twelve complete calendar windows and the shared basis.
3. Revalidate each retained source graph and monthly outcome population.
4. Intersect historical READY identities; sort full-year identities deterministically.
5. Link twelve returns for each full-year member and retain ordered source fingerprints and January assets.
6. Apply the selected estimator and quantize the dispersion.
7. Report the December READY count separately from the full-year count.
8. Fingerprint tenant, method, source vector, member evidence, applicability, and result. Reordered receipt identifiers produce the same result; selecting a correction changes the evidence fingerprint even when the spread happens to be unchanged.

## Validation and Failure Behavior

| Condition | Behavior |
| --- | --- |
| Missing tenant header | HTTP 401 |
| Receipt absent for the tenant | HTTP 404 |
| Not exactly twelve unique UUIDs, unsupported selector/view/method, extra field | HTTP 422 request admission |
| Receipt not COMPLETE or absent pinned source | HTTP 409 `ANNUAL_DISPERSION_MONTH_NOT_COMPLETE` |
| Window, composite, fee, or currency mismatch | HTTP 422 `ANNUAL_DISPERSION_MONTH_SCOPE_MISMATCH` |
| Returned receipt identity differs from selection | HTTP 422 `ANNUAL_DISPERSION_RECEIPT_IDENTITY_MISMATCH` |
| Mixed definition digest or membership policy | HTTP 422 `ANNUAL_DISPERSION_POLICY_BASIS_MISMATCH` |
| Inconsistent retained source or publication evidence | Existing retained-source/store admission error; no partial result |
| Return below -100%, nonfinite input, unsupported magnitude, Decimal error, over 1000 annual members | HTTP 422 `ANNUAL_DISPERSION_NUMERICAL_DOMAIN_REFUSED` |
| Weighted method with zero or negative January assets | HTTP 422 numerical-domain refusal |
| Fewer than two qualified members with valid selected inputs | HTTP 200, `status=UNAVAILABLE`, `value=null`, reason `ANNUAL_DISPERSION_INSUFFICIENT_MEMBERS` |
| Identical annual returns for two or more members | Available numerical zero |

A monthly return exactly -100% links to an annual return of -100%. No interpolation, incomplete-year annualization, inferred zero return, or survivor substitution occurs. Twelve receipts and at most 1000 annual members bound the accepted workload; these limits are not a latency or production-scale acceptance claim.

## Configuration Options

The request selects either named estimator. Precision, quantum, complete-year requirement, supported fee views, and population limits are registered method behavior, not caller options. Original and corrected vectors remain separately selectable by immutable UUID; there is no implicit latest selection.

## Outputs

`value`, `unit=DECIMAL_RETURN`, `status`, and `reason_codes` express numerical computation. `full_year_member_count` and `year_end_member_count` express different populations. `reporting_applicability` signals presentation review. `publication_state=CALCULATED_ANALYSIS` and `qualification=RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED` limit the evidence claim. `months`, `members`, `method_version`, and `result_fingerprint` provide replay provenance.

## Worked Example

Synthetic OR11: six historical full-year members have January returns 1%, 2%, 3%, 4%, 5%, and 6%; each has zero returns in February through December. January assets are positive. Full-year and December counts both equal six.

| Member | January decimal return | Remaining 11 months | Linked `R_i` | `R_i - R_bar` | Squared deviation |
|---|---|---|---|---|---|
| 1 | 0.01 | 0 | 0.01 | -0.025 | 0.000625 |
| 2 | 0.02 | 0 | 0.02 | -0.015 | 0.000225 |
| 3 | 0.03 | 0 | 0.03 | -0.005 | 0.000025 |
| 4 | 0.04 | 0 | 0.04 | 0.005 | 0.000025 |
| 5 | 0.05 | 0 | 0.05 | 0.015 | 0.000225 |
| 6 | 0.06 | 0 | 0.06 | 0.025 | 0.000625 |

Output mapping: `R_bar=0.035`; sum of squared deviations `=0.00175`; sample variance `=0.00175/5=7/20000`; response `value=0.018708286934` (about 1.8708286934 percentage points), `status=AVAILABLE`, `full_year_member_count=6`, `year_end_member_count=6`, and `reporting_applicability=REQUIRES_PROFILE_REVIEW`.

If member 6 has an explicit June exclusion but returns in December, full-year count is five and December count is six. The valid population's `value=0.015811388301`, with `NOT_REQUIRED_SMALL_POPULATION`; the exclusion does not create a source failure.

Weighted example: annual returns `0.01` and `0.06`, January assets `100` and `300`. `W=400`, `R_A=0.0475`; weighted squared-deviation sum `=0.1875`; variance `=0.1875/400=3/6400`; `value=0.021650635095`.

The independent engine expectations are executable in `tests/unit/engine/test_composite_annual_dispersion_engine.py`; historical intersection and correction vectors in `tests/unit/services/test_composite_annual_dispersion_service.py`; persisted reopen replay in `tests/unit/adapters/test_composite_annual_dispersion_adapter.py`; registered HTTP behavior in `tests/integration/test_composite_annual_dispersion_api.py`. OR10 time-series comparison appears only as an independent mathematical distinction in the engine test and does not implement a Risk metric.
