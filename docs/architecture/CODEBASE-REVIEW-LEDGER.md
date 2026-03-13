# Codebase Review Ledger

This ledger tracks systematic review work across `lotus-performance`.

Companion process document:

- [CODEBASE-REVIEW-PLAYBOOK.md](./CODEBASE-REVIEW-PLAYBOOK.md)

## Review entries

| Review ID | Date | Scope / Pattern | Status | Findings | Actions Taken | Follow-up | Evidence / Sign-off |
|---|---|---|---|---|---|---|---|
| LP-CR-001 | 2026-03-13 | Async orchestration, compute-job leasing, and worker fencing | Hardened | Initial review found a correctness risk in `analytics_compute_job` claiming: `lease_pending_jobs(...)` and stale-job reconciliation both selected rows and then mutated them without a row-level claim fence. On PostgreSQL, competing compute workers could observe the same pending or stale row before either transaction committed. | Added explicit PostgreSQL `FOR UPDATE SKIP LOCKED` statement builders for pending-job leasing and stale-job reconciliation in `ComputeJobStore`, and added lower-level unit proofs for both statement shapes while retaining existing lifecycle tests. | Continue this pattern review with worker quiescence, queue observability, and documentation drift around the old background-task runtime description. | Branch `review-ledger-async-orchestration`; files: `app/services/compute_job_store.py`, `tests/unit/services/test_compute_job_store.py`; validation: `python -m pytest tests/unit/services/test_compute_job_store.py -q`, `python -m pytest tests/unit/services/test_compute_executor_worker.py -q`, `python -m ruff check app/services/compute_job_store.py tests/unit/services/test_compute_job_store.py`, `python -m mypy --config-file mypy.ini app/services/compute_job_store.py`. |
