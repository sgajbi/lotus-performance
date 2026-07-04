# Adapters Pack

## Purpose

This pack contains integration seams between domain/application logic and external storage,
transport, or infrastructure concerns.

## Audience

- engineers changing persistence or integration implementations,
- agents checking whether a dependency belongs behind an adapter,
- reviewers checking dependency direction and testability.

## Maintenance Notes

- Keep adapters thin and replaceable; business rules belong in services or engines.
- Avoid leaking adapter-specific exceptions or payload shapes into public API contracts.
- Add focused tests around translation, failure behavior, and retry/degradation posture.
