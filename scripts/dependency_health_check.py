from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import venv
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINIMUM_AUDIT_SETUPTOOLS_VERSION = "83.0.0"


@dataclass
class CommandResult:
    command: list[str]
    return_code: int
    stdout: str
    stderr: str


def _run(command: list[str], *, cwd: Path | None = None) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def _print_section(title: str, body: str) -> None:
    print(f"\n=== {title} ===")
    print(body or "(no output)")


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _site_packages_path(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Lib" / "site-packages"
    return next((venv_dir / "lib").glob("python*/site-packages"))


def _install_command(args: argparse.Namespace, venv_python: Path) -> list[str]:
    command = [str(venv_python), "-m", "pip", "install"]
    for requirement in args.requirement:
        command.extend(["-r", str(ROOT / requirement)])
    for editable_spec in args.editable_spec:
        command.append(editable_spec)
    return command


def _bootstrap_command(venv_python: Path) -> list[str]:
    """Return the deterministic installer bootstrap used by the isolated audit."""
    return [
        str(venv_python),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
        f"setuptools>={MINIMUM_AUDIT_SETUPTOOLS_VERSION}",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Project-scoped dependency health and vulnerability audit")
    parser.add_argument(
        "--requirement",
        action="append",
        default=[],
        help="Requirements file relative to the repository root. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--editable-spec",
        action="append",
        default=[],
        help="Editable install target to install into the isolated audit environment.",
    )
    parser.add_argument(
        "--fail-on-outdated",
        action="store_true",
        help="Fail when outdated packages are detected in the isolated audit environment.",
    )
    parser.add_argument(
        "--skip-audit",
        action="store_true",
        help="Skip vulnerability auditing and only verify installability and dependency consistency.",
    )
    parser.add_argument(
        "--skip-outdated",
        action="store_true",
        help="Skip outdated-package reporting.",
    )
    args = parser.parse_args()

    if not args.requirement and not args.editable_spec:
        parser.error("at least one --requirement or --editable-spec is required")

    with tempfile.TemporaryDirectory(prefix="lotus-dependency-audit-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        venv_dir = temp_dir / "audit-venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
        venv_python = _venv_python(venv_dir)

        bootstrap = _run(_bootstrap_command(venv_python), cwd=ROOT)
        if bootstrap.return_code != 0:
            _print_section("dependency audit bootstrap stderr", bootstrap.stderr)
            return bootstrap.return_code

        install = _run(_install_command(args, venv_python), cwd=ROOT)
        if install.return_code != 0:
            _print_section("dependency install stdout", install.stdout)
            _print_section("dependency install stderr", install.stderr)
            return install.return_code

        pip_check = _run([str(venv_python), "-m", "pip", "check"], cwd=ROOT)
        if pip_check.return_code != 0:
            _print_section("pip check stdout", pip_check.stdout)
            _print_section("pip check stderr", pip_check.stderr)
            return pip_check.return_code

        vulnerabilities: list[dict[str, object]] = []
        if not args.skip_audit:
            audit = _run(
                [sys.executable, "-m", "pip_audit", "--path", str(_site_packages_path(venv_dir)), "-f", "json"],
                cwd=ROOT,
            )
            if audit.return_code != 0 and not audit.stdout:
                _print_section("pip-audit stderr", audit.stderr)
                return audit.return_code
            if audit.stdout:
                try:
                    payload = json.loads(audit.stdout)
                except json.JSONDecodeError:
                    _print_section("pip-audit stdout", audit.stdout)
                    _print_section("pip-audit stderr", audit.stderr)
                    return 1
                vulnerabilities = payload.get("dependencies", [])
                vulnerabilities = [item for item in vulnerabilities if item.get("vulns")]

        outdated_rows: list[dict[str, object]] = []
        if not args.skip_outdated:
            outdated = _run([str(venv_python), "-m", "pip", "list", "--outdated", "--format=json"], cwd=ROOT)
            if outdated.return_code != 0:
                _print_section("pip outdated stderr", outdated.stderr)
                return outdated.return_code
            outdated_rows = json.loads(outdated.stdout) if outdated.stdout else []

        _print_section("Vulnerability Summary", f"Known vulnerabilities: {len(vulnerabilities)}")
        if vulnerabilities:
            _print_section("Vulnerabilities", json.dumps(vulnerabilities, indent=2))

        if not args.skip_outdated:
            _print_section("Outdated Summary", f"Outdated packages: {len(outdated_rows)}")
            if outdated_rows:
                _print_section("Outdated Packages", json.dumps(outdated_rows, indent=2))

        if vulnerabilities:
            return 1
        if args.fail_on_outdated and outdated_rows:
            return 2
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
