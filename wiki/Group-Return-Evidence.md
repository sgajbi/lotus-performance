# Group-Return Evidence

`lotus-performance` publishes `POST /integration/attribution/group-return-evidence/v1` for a Risk
consumer that needs empirical portfolio and benchmark group returns on the same source cut.

The route is stateful-only and requires an admitted tenant, one portfolio, one benchmark context,
one daily grouping, one inclusive business-date window, and one common reporting currency. It
publishes decimal-ratio portfolio/benchmark returns and beginning weights by date and group,
aggregate active-return reconciliation, signed portfolio weights where source capital is negative,
execution-bound source effective dates/fingerprints, and a deterministic economic `source_cut_id`.

Performance owns this source normalization and return evidence. Core retains portfolio, benchmark,
index, FX, classification, and booking authority. Risk owns risk attribution and its consumer
acceptance. Gateway and Workbench may only present a supported downstream result; they must not
reconstruct these economics or tenant authority.

The route refuses incomplete retained source rows, missing classifications, duplicate observations,
calendar gaps, failed, stale or foreign source lineage, conflicting labels, non-reconciling weights
or returns, and currency mismatch. It never fills gaps, renormalizes partial evidence, creates FX,
or claims an upstream revision where Core has not supplied one. `source_cut_id` is the comparison
identity for identical reads and restatements; it includes canonical upstream fingerprints and
effective dates but excludes execution identifiers and serving timestamps.

See the repository certification note for request detail, formula, tolerance, and focused tests:
[Group Return Evidence Endpoint Certification](https://github.com/sgajbi/lotus-performance/blob/main/docs/technical/group-return-evidence-endpoint-certification.md).
