## Summary

| Metric | Value |
| --- | ---: |
| Operational readiness families | 5 |
| Expected implementation markers | 28 |
| Present implementation markers | 28 |
| Missing implementation markers | 0 |
| Mapped observability/readiness test functions | 443 |
| Deployable monitoring alert rules | 14 |
| Deployable monitoring dashboard panels | 10 |
| Monitoring artifact violations | 0 |

Mapped test functions are counted per readiness family and can overlap when one test proves multiple operational contracts.

## Surface Coverage

| Family | Present markers | Expected markers | Test functions | Missing markers |
| --- | ---: | ---: | ---: | ---: |
| `health_metrics_endpoints` | 4 | 4 | 51 | 0 |
| `correlation_propagation` | 6 | 6 | 168 | 0 |
| `structured_logging` | 6 | 6 | 57 | 0 |
| `metrics` | 6 | 6 | 43 | 0 |
| `health_readiness` | 6 | 6 | 121 | 0 |

## Missing Markers

| Family | Marker |
| --- | --- |
| none | none |

## Monitoring Artifact Violations

| Finding |
| --- |
| none |
