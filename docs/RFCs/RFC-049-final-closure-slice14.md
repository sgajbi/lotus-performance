# RFC-049 Slice 14 - Final Closure

Status: complete on branch; pending PR merge and post-merge wiki publication.

## Purpose

Slice 14 closes RFC-049 as implementation-backed product truth. It promotes only the delivered
persisted-fact composite TWR capability, records final proof, preserves unsupported advanced
boundaries, and prepares the branch for merge.

## Final Supported Product Boundary

Supported after RFC-049:

- persisted member-return fact based composite TWR;
- `POST /performance/composites/twr`;
- `POST /performance/composites/inspect`;
- asset-weighted composite period returns and geometric linking;
- member weights, member contributions, dispersion, and blocked/degraded supportability;
- source fingerprints, source snapshots, calculation ids, and restatement versions;
- classified inspection artifacts:
  `member_inputs.csv`, `period_weights.csv`, `composite_returns.csv`,
  `lineage_manifest.json`, and `support_brief.md`;
- `CompositePerformanceAnalytics:v1`;
- Gateway route realization and Workbench typed BFF consumption.

Still unsupported:

- composite contribution;
- composite attribution;
- composite MWR;
- sleeves and carve-outs;
- model portfolios and wrap programs;
- pooled fund and private-market composites;
- portability records;
- tax-aware, leveraged, or long/short special composite structures;
- multi-currency composite aggregation beyond the current single reporting-currency guard;
- benchmark active return for composites.

## Closure Updates

Updated durable truth:

| Area | Treatment |
| --- | --- |
| RFC status | Updated RFC-049 to `Implemented - final closure ready` and added the gold-pass assessment. |
| Supported features | Promoted persisted-fact composite TWR and inspection as implementation-backed product material. |
| Product wiki | Updated `wiki/Composite-Performance.md` from branch-level wording to proven supported capability wording. |
| Endpoint certification | Updated composite endpoint certification after live proof and Slice 13 Swagger hardening. |
| Documentation map | Updated final documentation routing and supported-feature boundary. |
| RFC ledgers | Updated RFC index, implementation status, RFC-022 delta backlog, and wiki RFC index. |
| Docs regression tests | Updated docs tests so supported composite TWR is pinned without weakening unsupported advanced-scope gates. |

## Evidence

Implementation proof:

- Slice 12 proof: `docs/RFCs/RFC-049-implementation-proof-slice12.md`;
- direct `lotus-performance` composite TWR and inspector probes;
- Gateway composite TWR and inspector probes;
- Workbench BFF composite TWR and inspector probes;
- canonical Workbench validation for `PB_SG_GLOBAL_BAL_001`;
- operations evidence pack covering readiness, metrics, logs, Prometheus, and Grafana.

Hardening proof:

- Slice 13 review: `docs/RFCs/RFC-049-hardening-review-slice13.md`;
- Swagger error examples added for composite not found, no persisted facts, and invalid window;
- endpoint, OpenAPI, data-product, vocabulary, no-alias, and unit gates passed;
- PR `sgajbi/lotus-performance#162` was green after Slice 13 commit `60bf860`.

## Stranded-Truth Reconciliation

Run on 2026-05-12:

```powershell
git fetch origin --prune
git branch -r --no-merged origin/main
```

Result: no unmerged remote `lotus-performance` branches were listed outside the active RFC-049
branch. No durable RFC, docs, wiki, context, contract, OpenAPI, supported-features, or workflow
truth required merge or cherry-pick before closure.

## Context, Skills, And Guidance Review

Reviewed closure impact against:

- `AGENTS.md`;
- `lotus-backend-delivery-governance`;
- `lotus-readme-wiki-governance`;
- repo-local `REPOSITORY-ENGINEERING-CONTEXT.md`;
- RFC-049 platform automation Slice 1;
- RFC-049 data-product/vocabulary platform Slice 6.

Decision: no AGENTS, central context, repository context, local skill, or platform automation change
is required in Slice 14. RFC-049 used the already-merged platform scaffold-certification and
data-product governance patterns and did not discover a new reusable platform gap during closure.

## Wiki Publication

Repo-local wiki source changed during RFC-049. Required closure steps:

1. run `Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance` before merge;
2. merge PR `sgajbi/lotus-performance#162` only after local and remote checks are green;
3. after merge to `main`, publish with
   `Sync-RepoWikis.ps1 -Publish -Repository lotus-performance`;
4. sync local `main` and confirm the working tree is clean.

Pre-merge check on 2026-05-12 confirmed the expected publication drift:

```text
lotus-performance: published GitHub wiki is not synchronized with repo-authored wiki source.
Drift: _Sidebar.md, API-Surface.md, Composite-Performance.md, Home.md, Integrations.md,
Mesh-Data-Products.md, RFC-Index.md, Roadmap.md, Supported-Features.md
```

Treatment: this is expected before the RFC-049 PR is merged. Do not hand-edit the GitHub wiki;
publish the repo-local `wiki/` source after merge.

## Closure Assessment

RFC-049 reached the intended standard for the approved scope. The RFC did not implement every
composite concept discussed in the source material; it deliberately implemented the bank-buyable
foundation that can be proven today: persisted-fact composite TWR, inspection, lineage/restatement
evidence, data-product posture, downstream integration, live proof, and implementation-backed
documentation. Advanced composite analytics remain explicit unsupported boundaries rather than
aspirational claims.
