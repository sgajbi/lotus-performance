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
  exposed to PowerShell, so the PowerShell flow below still fails at `make install`. Either add
  its binary directory to PATH, or run everything from the MSYS2 shell using the POSIX commands
  given alongside the PowerShell ones below -- `Get-Command` and `Activate.ps1` are PowerShell
  syntax and will not run there.

### Make also needs a POSIX shell for the coverage targets

Finding make is necessary but not sufficient. GNU Make runs each recipe through
`$(SHELL)`, which on Windows resolves to `SHELL` if set, otherwise `sh.exe` if one is on PATH,
and otherwise `cmd.exe`. Several recipes here begin with a POSIX-only environment assignment
(`COVERAGE_FILE=... python -m pytest ...`), which `cmd.exe` cannot parse. On a machine with make
but no `sh.exe`, those targets fail while `make --version` reports success.

Affected: `test-coverage-shard` (`Makefile:45`), and therefore `test-coverage`, `coverage-gate`
and `ci`; `ci-local` (`Makefile:85`); `branch-coverage-baseline` (`Makefile:52-54`). Not
affected: `lint`, `typecheck` and `test-unit`, which use no leading assignments.

Confirm before continuing, in the shell you intend to use, that make is present and that a
POSIX shell actually backs it:

```
make --version
make shell-check
```

Both commands are shell-neutral and work from PowerShell, Git Bash, MSYS2 and WSL alike.

`make shell-check` prints the `SHELL` make is really using and then runs a recipe line with a
leading `VAR=value` assignment, checking in Python that the variable arrived. That is the
construct the coverage targets depend on, so the check exercises the real thing.

Testing for `sh.exe` on PATH would not be enough: make prefers an explicitly set `SHELL` over
any `sh.exe` it can find, so on a machine with `SHELL` pointing at `cmd.exe` the file exists,
the check passes, and the recipes still fail. A prerequisite check that passes in the failing
case is the same defect this section documents.

If `make shell-check` fails, install Git for Windows (which supplies a POSIX shell at
`C:\Program Files\Git\usr\bin\sh.exe`), ensure it is on PATH, and clear or repoint any
`SHELL` you have set to a non-POSIX shell. Running the commands from Git Bash, MSYS2 or WSL
satisfies the requirement directly.

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
if ((Get-Command python).Source -ne (Resolve-Path .\.venv\Scripts\python.exe).Path) {
    throw "venv is not active - do not run make install, it would install globally"
}
make install
```

On Windows from Git Bash, MSYS2 or WSL, which is the route the POSIX-shell requirement above
recommends. Note `Scripts`, not `bin`: a virtualenv created by Windows Python uses the
Windows layout whatever shell you activate it from, so the Linux block above does not apply.

```bash
python -m venv .venv
. .venv/Scripts/activate && make install
```

The `&&` is deliberate in both Windows blocks. `make install` runs `pip install` directly, so
an activation that failed silently would install into the system interpreter -- the outcome
the paragraph above exists to prevent. Under WSL, use the Linux block instead: a WSL
virtualenv is a Linux one and uses `bin`.

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
