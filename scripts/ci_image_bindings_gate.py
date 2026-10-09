"""Bind central admission outputs to the fixed files used by hosted consumers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMMUTABLE_IMAGE = re.compile(r"[a-z0-9./_-]+@sha256:[0-9a-f]{64}")


def require_immutable(image: str) -> None:
    if IMMUTABLE_IMAGE.fullmatch(image) is None:
        raise ValueError("Admission output must be a nonempty immutable image reference")


def verify_bindings(runtime_image: str, postgres_image: str | None = None) -> dict[str, str]:
    require_immutable(runtime_image)
    first_line = (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()[0]
    if first_line != f"FROM {runtime_image} AS runtime":
        raise ValueError("Fixed Dockerfile does not consume the admitted runtime image")
    bindings = {"runtime_image": runtime_image, "platform": "linux/amd64"}
    if postgres_image is not None:
        require_immutable(postgres_image)
        result = subprocess.run(
            [
                "docker",
                "--context",
                "default",
                "compose",
                "-f",
                str(ROOT / "docker-compose.yml"),
                "-f",
                str(ROOT / "docker-compose.lineage-recovery.yml"),
                "config",
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        service = json.loads(result.stdout)["services"]["performance-lineage-db"]
        if service.get("image") != postgres_image or service.get("platform") != "linux/amd64":
            raise ValueError("Fixed recovery Compose files do not consume the admitted PostgreSQL image/platform")
        bindings["postgres_image"] = postgres_image
    return bindings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--postgres-image")
    args = parser.parse_args(argv)
    try:
        bindings = verify_bindings(args.runtime_image, args.postgres_image)
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError, IndexError) as error:
        print(f"Image binding refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(bindings, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
