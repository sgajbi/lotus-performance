from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.evidence.idea_opportunity_runtime import (  # noqa: E402
    default_output_path,
    generate_idea_opportunity_runtime_evidence,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate source-safe RFC-0002 Idea opportunity evidence from lotus-performance runtime.",
    )
    parser.add_argument("--output", type=Path, default=Path(default_output_path()))
    args = parser.parse_args(argv)

    evidence = asyncio.run(generate_idea_opportunity_runtime_evidence())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote Idea opportunity runtime evidence to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
