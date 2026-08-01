# License Compliance Inventory

Mode: generated first-party and third-party dependency license evidence.

## Policy

- First-party license: `MIT`
- Policy source: `contracts/license-compliance-policy.v1.json`
- Gate command: `make license-compliance-gate`

## Summary

| Metric | Value |
| --- | ---: |
| Packages inventoried | 45 |
| Allowed packages | 43 |
| Review-required packages with active exception | 2 |
| Blocked packages | 0 |
| Review-required packages missing exception | 0 |

## Packages

| Package | Requirement source | Requirement spec | Installed metadata version | License | License source | Review status | Exception owner | Exception expires |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `annotated-types` | runtime | `annotated-types==0.7.0` | `0.7.0` | MIT License | Classifier | allowed | - | - |
| `anyio` | runtime | `anyio==4.10.0` | `4.12.1` | MIT | License-Expression | allowed | - | - |
| `bandit` | development | `bandit>=1.9.4,<2.0.0` | `1.9.4` | Apache-2.0 | License | allowed | - | - |
| `certifi` | runtime | `certifi==2026.2.25` | `2026.2.25` | MPL-2.0 | License | review_required_exception | platform-security | 2027-01-31 |
| `click` | runtime | `click==8.3.3` | `8.4.2` | BSD-3-Clause | License-Expression | allowed | - | - |
| `colorama` | runtime | `colorama==0.4.6` | `0.4.6` | BSD License | Classifier | allowed | - | - |
| `coverage` | development | `coverage>=7.6.0,<8.0.0` | `7.15.1` | Apache-2.0 | License | allowed | - | - |
| `deptry` | development | `deptry>=0.25,<1.0.0` | `0.25.1` | MIT | License-Expression | allowed | - | - |
| `fastapi` | runtime | `fastapi==0.136.3` | `0.136.3` | MIT | License-Expression | allowed | - | - |
| `h11` | runtime | `h11==0.16.0` | `0.16.0` | MIT | License | allowed | - | - |
| `httpcore` | runtime | `httpcore==1.0.9` | `1.0.9` | BSD-3-Clause | License-Expression | allowed | - | - |
| `httpx` | development, runtime | `httpx==0.28.1; httpx>=0.25.0,<1.0.0` | `0.28.1` | BSD-3-Clause | License | allowed | - | - |
| `httpx2` | development | `httpx2>=2.4.0,<3.0.0` | `2.4.0` | BSD-3-Clause | License-Expression | allowed | - | - |
| `idna` | runtime | `idna==3.18` | `3.18` | BSD-3-Clause | License-Expression | allowed | - | - |
| `mypy` | development | `mypy>=1.11.2,<2.0.0` | `2.1.0` | MIT | License-Expression | allowed | - | - |
| `numpy` | runtime | `numpy==2.3.2` | `2.4.6` | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | License-Expression | allowed | - | - |
| `packaging` | runtime | `packaging==25.0` | `26.2` | Apache-2.0 OR BSD-2-Clause | License-Expression | allowed | - | - |
| `pandas` | runtime | `pandas==2.3.2` | `2.3.2` | BSD 3-Clause License Copyright (c) 2008-2011, AQR Capital Management, LLC, Lambda Foundry, Inc. and PyData Development Team All rights reserved. Copyright (c) 2 | License | allowed | - | - |
| `pip-audit` | development | `pip-audit>=2.9.0,<3.0.0` | `2.10.1` | Apache Software License | Classifier | allowed | - | - |
| `pre-commit` | development | `pre-commit>=4.2.0,<5.0.0` | `4.5.1` | MIT | License | allowed | - | - |
| `prometheus-client` | runtime | `prometheus-client==0.25.0` | `0.25.0` | Apache-2.0 AND BSD-2-Clause | License-Expression | allowed | - | - |
| `prometheus-fastapi-instrumentator` | runtime | `prometheus-fastapi-instrumentator==8.0.0` | `8.0.0` | ISC | License | allowed | - | - |
| `psycopg` | development, runtime | `psycopg[binary]==3.2.6; psycopg[binary]>=3.2.0,<4.0.0` | `3.3.4` | LGPL-3.0-only | License-Expression | review_required_exception | platform-security | 2027-01-31 |
| `pydantic` | runtime | `pydantic==2.11.7` | `2.13.4` | MIT | License-Expression | allowed | - | - |
| `pydantic_core` | runtime | `pydantic_core==2.33.2` | `2.46.4` | MIT | License-Expression | allowed | - | - |
| `pydantic-settings` | runtime | `pydantic-settings==2.10.1` | `2.10.1` | MIT | License-Expression | allowed | - | - |
| `pytest` | development | `pytest>=9.0.3,<10.0.0` | `9.1.1` | MIT | License-Expression | allowed | - | - |
| `pytest-asyncio` | development | `pytest-asyncio>=1.3.0,<2.0.0` | `1.4.0` | Apache-2.0 | License-Expression | allowed | - | - |
| `pytest-benchmark` | development | `pytest-benchmark>=4.0.0,<5.0.0` | `4.0.0` | BSD-2-Clause | License | allowed | - | - |
| `pytest-cov` | development | `pytest-cov>=4.0.0,<5.0.0` | `7.1.0` | MIT | License-Expression | allowed | - | - |
| `pytest-mock` | development | `pytest-mock>=3.12.0,<4.0.0` | `3.15.1` | MIT | License | allowed | - | - |
| `python-dateutil` | runtime | `python-dateutil==2.9.0.post0` | `2.9.0.post0` | Apache Software License; BSD License | Classifier | allowed | - | - |
| `python-dotenv` | runtime | `python-dotenv==1.2.2` | `1.2.2` | BSD-3-Clause | License | allowed | - | - |
| `pytz` | runtime | `pytz==2025.2` | `2025.2` | MIT | License | allowed | - | - |
| `radon` | development | `radon>=6.0.1,<7.0.0` | `6.0.1` | MIT | License | allowed | - | - |
| `ruff` | development | `ruff>=0.6.9,<0.7.0` | `0.15.18` | MIT | License-Expression | allowed | - | - |
| `six` | runtime | `six==1.17.0` | `1.17.0` | MIT | License | allowed | - | - |
| `sniffio` | runtime | `sniffio==1.3.1` | `1.3.1` | MIT OR Apache-2.0 | License | allowed | - | - |
| `SQLAlchemy` | development, runtime | `SQLAlchemy==2.0.39; SQLAlchemy>=2.0.0,<3.0.0` | `2.0.51` | MIT | License | allowed | - | - |
| `starlette` | runtime | `starlette==1.3.1` | `1.3.1` | BSD-3-Clause | License-Expression | allowed | - | - |
| `typing_extensions` | runtime | `typing_extensions==4.15.0` | `4.15.0` | PSF-2.0 | License-Expression | allowed | - | - |
| `typing-inspection` | runtime | `typing-inspection==0.4.2` | `0.4.2` | MIT | License-Expression | allowed | - | - |
| `tzdata` | runtime | `tzdata==2025.3` | `2026.3` | Apache-2.0 | License | allowed | - | - |
| `uvicorn` | runtime | `uvicorn==0.35.0` | `0.49.0` | BSD-3-Clause | License-Expression | allowed | - | - |
| `vulture` | development | `vulture>=2.16,<3.0.0` | `2.16` | The MIT License (MIT) Copyright (c) 2012-2020 Jendrik Seipp (jendrikseipp@gmail.com) Permission is hereby granted, free of charge, to any person obtaining a cop | License | allowed | - | - |

## Review Rules

- `allowed` dependencies match the approved license token set in the policy.
- `review_required_exception` dependencies require a policy exception with owner, rationale, and expiry.
- `blocked` or `review_required_missing_exception` dependencies fail the gate.
- Regenerate with `python scripts/license_compliance_inventory.py --write` after dependency changes.
