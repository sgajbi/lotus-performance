# Monitoring Pack

## Purpose

This pack contains deployable or platform-consumable monitoring artifacts for `lotus-performance`.

## Audience

- operations teams adopting alerts and dashboards,
- platform engineers integrating Prometheus and Grafana assets,
- agents validating observability evidence.

## Artifacts

| Artifact | Use | Validation |
| --- | --- | --- |
| `prometheus/lotus-performance-alerts.prometheusrule.json` | PrometheusRule-compatible runtime, MWR, and returns-series alert rules. | `make quality-observability-readiness-gate` |
| `grafana/lotus-performance-operability-dashboard.json` | Runtime breach, MWR solver/source-data, and returns-series supportability dashboard panels. | `make quality-observability-readiness-gate` |

## Maintenance Notes

- Keep alert expressions pointed at service-owned bounded-label metrics.
- Keep alert-backed product supportability surfaces represented in the dashboard with the same key
  metric and bounded operation selector.
- Do not introduce portfolio, client, tenant, account, calculation, correlation, trace, request, or
  response identifiers as alert or dashboard labels.
- Keep explanatory prose in `docs/operations/`; keep deployable adoption truth here.
