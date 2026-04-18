# Getting Started

## Prerequisites

- Python environment compatible with the repo toolchain
- local access to any required upstream Lotus services when exercising stateful flows
- optional Docker if you want topology-parity or threshold-overlay runs

## Install

```bash
make install
```

## Run locally

```bash
make run
```

Then verify the service at:

- `/health`
- `/health/ready`
- `/docs`

## Quick validation loop

```bash
make check
```

## Stateful inspection proof

```bash
python scripts/validate_canonical_twr_inspection.py \
  --performance-base-url http://127.0.0.1:8002 \
  --core-control-plane-base-url http://127.0.0.1:8202
```

Use this when you need governed proof that the canonical TWR inspection path is still aligned.

## Where startup details live

- [docs/technical/runtime_topology.md](../docs/technical/runtime_topology.md)
- [docs/examples](../docs/examples)
- [Troubleshooting](Troubleshooting)
