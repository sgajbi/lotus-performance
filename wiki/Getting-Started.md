# Getting Started

## Prerequisites

- **GNU Make** — every command below is a make target
- Python environment compatible with the repo toolchain
- local access to any required upstream Lotus services when exercising stateful flows
- optional Docker if you want topology-parity or threshold-overlay runs

### Obtaining GNU Make on Windows

Make is not present by default on Windows. What matters is not which package manager supplies it,
but **whether it lands on the PATH of the shell you run these commands in**.

- winget, Chocolatey and Scoop install onto the system PATH, so make is available from PowerShell.
  Verified on one maintainer workstation only: `winget install ezwinports.make` yields GNU Make
  4.4.1 resolving from PowerShell. The other two are not tested here.
- **MSYS2 is different.** Its `make` package installs inside the MSYS2 prefix and is not normally
  exposed to PowerShell, so the PowerShell flow below still fails at `make install`. Run these
  commands from the MSYS2 shell instead, or add its binary directory to PATH.

### Make also needs a POSIX shell for the coverage targets

Finding make is necessary but not sufficient. GNU Make runs each recipe through
`$(SHELL)`, which on Windows resolves to `SHELL` if set, otherwise `sh.exe` if one is on PATH,
and otherwise `cmd.exe`. Several recipes here begin with a POSIX-only environment assignment
(`COVERAGE_FILE=... python -m pytest ...`), which `cmd.exe` cannot parse. On a machine with make
but no `sh.exe`, those targets fail while `make --version` reports success.

Affected: `test-coverage-shard` (`Makefile:45`), and therefore `test-coverage`, `coverage-gate`
and `ci`; `ci-local` (`Makefile:85`); `branch-coverage-baseline` (`Makefile:52-54`). Not
affected: `lint`, `typecheck` and `test-unit`, which use no leading assignments.

Confirm before continuing, in the shell you intend to use, that make is present **and** that a
POSIX shell backs it:

```powershell
make --version
Get-Command sh.exe
```

If `sh.exe` does not resolve, install Git for Windows (which supplies one at
`C:\Program Files\Git\usr\bin\sh.exe`) and confirm it is on PATH, or set `SHELL` to a POSIX
shell before invoking make. Running the commands from Git Bash or MSYS2 satisfies this too.

This is where the earlier PowerShell verification on a maintainer workstation was misleading:
Git for Windows was already installed there, so make resolved
`SHELL=C:/Program Files/Git/usr/bin/sh.exe` and the assignment prefixes worked. The check
succeeded in an environment where the failure could not occur.

## Install

`make install` runs `pip install` directly rather than into a managed environment, so create and
activate a virtualenv FIRST. PEP 668 distributions (most current Linux packages, and Homebrew
Python on macOS) mark the system interpreter externally managed and refuse a system-wide
`pip install`, so on such a machine this step fails before anything else runs. This has not been
reproduced by the maintainers: it is the specified behaviour of PEP 668, not an observed error.
CI does not need the step because `actions/setup-python` supplies an isolated interpreter, which
is why the requirement stays invisible in a green pipeline.

On Linux or macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
make install
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
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
  --performance-base-url $PERFORMANCE_BASE_URL \
  --core-control-plane-base-url $CORE_CONTROL_PLANE_BASE_URL
```

Use this when you need governed proof that the canonical TWR inspection path is still aligned.
For a local host-port run, set `PERFORMANCE_BASE_URL` to the API service URL and
`CORE_CONTROL_PLANE_BASE_URL` to the lotus-core control-plane URL.

## Where startup details live

- [docs/technical/runtime_topology.md](https://github.com/sgajbi/lotus-performance/blob/main/docs/technical/runtime_topology.md)
- [docs/examples](https://github.com/sgajbi/lotus-performance/tree/main/docs/examples)
- [Troubleshooting](Troubleshooting)
