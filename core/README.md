# Core Pack

## Purpose

This pack contains shared domain foundations used across API services and engines, including
period resolution, envelope helpers, errors, and calculation support utilities.

## Audience

- engineers changing cross-cutting domain semantics,
- agents looking for canonical helpers before adding local branching,
- reviewers checking vocabulary and error-model consistency.

## Maintenance Notes

- Prefer shared helpers here when the same rule applies across multiple analytics surfaces.
- Keep this pack framework-neutral; HTTP adapters belong in `app/`.
- Changes here usually require broader focused tests because the blast radius spans multiple
  endpoints.
