from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.gates import compare_against_baseline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two DeltaLedger evaluation reports.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--tolerance", type=float, default=0.0001)
    args = parser.parse_args(argv)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    results = compare_against_baseline(baseline, candidate, tolerance=args.tolerance)
    print(json.dumps([result.__dict__ for result in results], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
