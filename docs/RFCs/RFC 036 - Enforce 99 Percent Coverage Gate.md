# RFC 036 - Enforce 99 Percent Coverage Gate

## Problem Statement
Performance Analytics currently enforces a 95% coverage threshold in local and CI coverage gates, which is below the platform standard target.

## Root Cause
Coverage thresholds in `Makefile` and GitHub Actions pipeline were not updated after the platform-wide move to 99% meaningful coverage.

## Proposed Solution
Raise lotus-performance coverage fail-under from 95% to 99% in:
1. `Makefile` (`test-all` and `ci-local` coverage report step)
2. `.github/workflows/pr-merge-gate.yml` (`coverage-gate` job)

## Architectural Impact
No runtime or API contract change. This is a quality-policy hardening change.

## Risks and Trade-offs
- PRs with insufficient test depth will fail earlier.
- Short-term increase in remediation work for low-coverage code paths.

## High-Level Implementation Approach
1. Update fail-under values to 99 in local and CI paths.
2. Run full lotus-performance coverage locally to validate threshold.
3. Merge and monitor pipeline stability.
