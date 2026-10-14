"""Verify retained authority and replay portfolio source without any upstream calls."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from app.services.returns_series_source.replay import replay_retained_portfolio_source

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--storage-path", required=True)
    parser.add_argument("--calculation-id", required=True, type=UUID)
    parser.add_argument("--tenant-id", required=True)
    options = parser.parse_args()
    print(json.dumps(replay_retained_portfolio_source(**vars(options)), sort_keys=True))


if __name__ == "__main__":
    main()
