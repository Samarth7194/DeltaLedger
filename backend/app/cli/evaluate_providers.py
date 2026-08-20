from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import Settings
from app.evaluation.providers import provider_manifest
from app.evaluation.runner import default_report_dir, run_benchmark_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate or compare configured AI providers against existing suites."
    )
    parser.add_argument("--suite", default="all", help="Suite task name or all.")
    parser.add_argument("--provider", default=None, help="Provider name to label this run.")
    parser.add_argument("--model", default=None, help="Model name to label this run.")
    parser.add_argument("--output-dir", type=Path, default=default_report_dir())
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run the safe offline provider configuration report.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Permit real external provider calls. May incur API cost.",
    )
    parser.add_argument(
        "--confirm-paid-api-calls",
        action="store_true",
        help="Required with --live to avoid accidental paid provider usage.",
    )
    args = parser.parse_args(argv)

    if args.live and not args.confirm_paid_api_calls:
        raise SystemExit(
            "Live provider evaluation may incur API cost. Re-run with "
            "--live --confirm-paid-api-calls after configuring credentials."
        )

    settings = Settings()
    if args.live:
        raise SystemExit(
            "Live provider benchmark execution is intentionally gated until a reviewer "
            "selects a provider, model, budget, and benchmark suite."
        )

    report = run_benchmark_sync(
        suite=args.suite,
        offline=True,
        output_dir=args.output_dir,
    )
    payload = {
        "run_id": report["run_id"],
        "status": report["status"],
        "suite": args.suite,
        "provider": args.provider,
        "model": args.model,
        "mode": "offline_configuration_report",
        "provider_manifest": provider_manifest(settings),
        "note": "Offline mode does not call paid external providers.",
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if report["status"] in {"completed", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
