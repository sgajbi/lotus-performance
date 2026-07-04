# Engine Pack

## Purpose

This pack contains calculation engines and methodology implementation that should remain independent
from HTTP, persistence, and framework concerns.

## Audience

- methodology engineers,
- backend engineers adding or hardening calculations,
- reviewers checking numerical behavior and edge-case coverage.

## Ownership Boundary

The engine owns deterministic performance methodology. It should not own:

- FastAPI request/response handling,
- durable execution lifecycle,
- source retrieval from `lotus-core`,
- operator runbooks or monitoring artifacts.

## Maintenance Notes

- Use `Decimal` where monetary or precision-sensitive methodology requires it.
- Preserve behavior with focused unit tests before refactoring calculation internals.
- Document intentional methodology changes in `docs/methodologies/` and endpoint certification
  evidence.
