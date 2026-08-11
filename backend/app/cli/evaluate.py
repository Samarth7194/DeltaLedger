from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.runner import default_report_dir, run_benchmark_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run DeltaLedger offline evaluation suites.")
    parser.add_argument("--suite", default="all", help="Suite task name or all.")
    parser.add_argument("--offline", action="store_true", help="Run deterministic offline suites.")
    parser.add_argument("--output-dir", type=Path, default=default_report_dir())
    parser.add_argument("--baseline", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run_benchmark_sync(
        suite=args.suite,
        offline=args.offline or True,
        output_dir=args.output_dir,
        baseline_path=args.baseline,
    )
    print(json.dumps({"run_id": report["run_id"], "status": report["status"]}, sort_keys=True))
    return 0 if report["status"] in {"completed", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
