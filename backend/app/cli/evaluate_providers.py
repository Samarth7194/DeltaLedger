from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.ai.financial_claims import create_claim_extractor
from app.ai.semantic_change import create_change_classifier
from app.core.config import Settings
from app.evaluation.datasets import EVALUATION_ROOT, load_json
from app.evaluation.live_provider_eval import (
    CHANGE_TASK,
    CLAIM_TASK,
    EvaluationConfigError,
    render_markdown,
    run_live_evaluation,
)
from app.evaluation.providers import provider_manifest
from app.evaluation.runner import default_report_dir, run_benchmark_sync

TASK_ALIASES = {"change": CHANGE_TASK, "claims": CLAIM_TASK}


def default_results_dir() -> Path:
    return EVALUATION_ROOT / "results"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate or compare configured AI providers against existing suites."
    )
    parser.add_argument("--suite", default="all", help="Suite task name or all (offline mode).")
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
    live = parser.add_argument_group("live evaluation (--live)")
    live.add_argument(
        "--tasks",
        default="change,claims",
        help="Comma list of: change (disclosure-change classification), claims "
        "(financial-claim extraction). Default: both.",
    )
    live.add_argument(
        "--mode",
        choices=("auto", "batch", "single"),
        default="auto",
        help="auto mirrors the pipeline (multi-item batch requests when configured).",
    )
    live.add_argument(
        "--results-dir",
        type=Path,
        default=default_results_dir(),
        help="Where the JSON results and Markdown comparison are written.",
    )
    live.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Continue a partial results JSON: items it already answered are not requested again.",
    )
    live.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="Stop after this many provider calls (a quota safety valve).",
    )
    args = parser.parse_args(argv)

    if args.live and not args.confirm_paid_api_calls:
        raise SystemExit(
            "Live provider evaluation may incur API cost. Re-run with "
            "--live --confirm-paid-api-calls after configuring credentials."
        )

    settings = Settings()
    if args.live:
        return _run_live(args, settings)

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


def _run_live(args: argparse.Namespace, settings: Settings) -> int:
    try:
        tasks = tuple(TASK_ALIASES[name.strip()] for name in args.tasks.split(",") if name.strip())
    except KeyError as exc:
        raise SystemExit(f"Unknown task {exc.args[0]!r}; use: change, claims.") from exc
    if not tasks:
        raise SystemExit("No tasks selected.")

    if CHANGE_TASK in tasks and settings.change_classifier_provider != "openai_compatible":
        raise SystemExit(
            "CHANGE_CLASSIFIER_PROVIDER is "
            f"{settings.change_classifier_provider!r}: a live evaluation would only measure the "
            "deterministic fake. Configure a real provider first."
        )
    if CLAIM_TASK in tasks and settings.claim_extractor_provider != "openai_compatible":
        raise SystemExit(
            "CLAIM_EXTRACTOR_PROVIDER is "
            f"{settings.claim_extractor_provider!r}: a live evaluation would only measure the "
            "deterministic fake. Configure a real provider first."
        )
    if args.provider and args.provider != settings.change_classifier_provider:
        raise SystemExit(
            f"--provider {args.provider!r} does not match the configured provider "
            f"{settings.change_classifier_provider!r}; live runs use the configured provider."
        )
    if args.model and args.model not in {
        settings.change_classifier_model,
        settings.claim_extractor_model,
    }:
        raise SystemExit(
            f"--model {args.model!r} does not match the configured models; live runs use "
            "CHANGE_CLASSIFIER_MODEL / CLAIM_EXTRACTOR_MODEL."
        )

    if args.resume is not None:
        output_path = args.resume
        if not output_path.exists():
            raise SystemExit(f"--resume file not found: {output_path}")
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_path = args.results_dir / f"live_provider_eval_{stamp}.json"

    markdown_path = output_path.with_suffix(".md")
    try:
        results = asyncio.run(
            run_live_evaluation(
                settings=settings,
                change_classifier=(
                    create_change_classifier(settings) if CHANGE_TASK in tasks else None
                ),
                claim_extractor=(
                    create_claim_extractor(settings.claim_extractor_provider, settings)
                    if CLAIM_TASK in tasks
                    else None
                ),
                tasks=tasks,
                mode=args.mode,
                output_path=output_path,
                resume=args.resume is not None,
                max_requests=args.max_requests,
            )
        )
    except EvaluationConfigError as exc:
        raise SystemExit(str(exc)) from exc
    except Exception as exc:  # the partial results file was already saved
        print(f"Evaluation crashed ({type(exc).__name__}): {str(exc)[:300]}")
        _write_markdown(output_path, markdown_path)
        print(f"Partial results saved to {output_path}")
        return 1

    _write_markdown(output_path, markdown_path)
    remaining = results.get("remaining_items") or {}
    print(f"status={results['status']} stop_reason={results.get('stop_reason')}")
    print(f"remaining items: {remaining if any(remaining.values()) else 'none'}")
    print(f"results: {output_path}")
    print(f"comparison: {markdown_path}")
    return 0 if results["status"] == "completed" else 2


def _write_markdown(results_path: Path, markdown_path: Path) -> None:
    if results_path.exists():
        markdown_path.write_text(render_markdown(load_json(results_path)), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
