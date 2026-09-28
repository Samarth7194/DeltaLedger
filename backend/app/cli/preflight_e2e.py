"""Safe, read-only readiness check for the final AAPL end-to-end run.

    python -m app.cli.preflight_e2e

Verifies database connectivity/migration state, Redis reachability, workflow
and AI batching configuration, storage configuration, and obvious placeholder
or localhost-in-production misconfiguration - printed as a concise PASS / WARN
/ FAIL summary. It never mutates analysis data, never calls the generative
(Gemini) provider, and never enqueues a Dramatiq job: it only reads
configuration and, for the DATABASE/REDIS checks, opens a short-lived
connection to confirm reachability. Secrets are never printed - see
`production_doctor.mask_url` and `runtime_report.runtime_summary`, both reused
here rather than re-implemented.

Exit code: 0 when every check is PASS or WARN, 1 when any check is FAIL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Any

from app.cli.production_doctor import DoctorCheck, mask_url, run_doctor
from app.core.config import Settings, _is_placeholder_contact, _is_placeholder_secret
from app.core.runtime_report import runtime_notes, runtime_summary

# Case-insensitive substrings that mean "this was never filled in" wherever
# they show up in a configured string - the same idea as the destructive-test
# database guard, applied here to the broader set of values a preflight run
# actually depends on.
_PLACEHOLDER_TOKENS = (
    "<user>",
    "<username>",
    "<password>",
    "<host>",
    "your_",
    "yourkey",
    "actual_",
    "real_test_",
    "paste_",
    "change_me",
    "changeme",
    "replace_me",
    "xxxxxxxx",
)


@dataclass(frozen=True)
class PreflightCheck:
    group: str
    name: str
    status: str  # "PASS" | "WARN" | "FAIL"
    detail: str
    metadata: dict[str, Any] | None = None


def _looks_like_placeholder(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return any(token in lowered for token in _PLACEHOLDER_TOKENS)


def _doctor_status_to_preflight(status: str) -> str:
    if status == "blocked":
        return "FAIL"
    if status in {"warning", "degraded"}:
        return "WARN"
    return "PASS"


def _from_doctor_check(group: str, name: str, check: DoctorCheck) -> PreflightCheck:
    return PreflightCheck(
        group, name, _doctor_status_to_preflight(check.status), check.detail, check.metadata
    )


def _security_checks(settings: Settings) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []

    placeholder_fields = {
        "SEC_USER_AGENT": settings.sec_user_agent,
        "AUTH_SECRET_KEY": settings.auth_secret_key,
        "AI_PROVIDER_API_KEY": settings.ai_provider_api_key,
        "MINIO_ACCESS_KEY": settings.minio_access_key,
        "MINIO_SECRET_KEY": settings.minio_secret_key,
        "HF_TOKEN": settings.hf_token,
    }
    flagged = [name for name, value in placeholder_fields.items() if _looks_like_placeholder(value)]
    if (
        settings.sec_user_agent
        and _is_placeholder_contact(settings.sec_user_agent)
        and "SEC_USER_AGENT" not in flagged
    ):
        flagged.append("SEC_USER_AGENT (no real contact address)")
    if flagged:
        checks.append(
            PreflightCheck(
                "security",
                "placeholder_values",
                "FAIL" if settings.is_production else "WARN",
                f"looks like an unfilled-in placeholder: {', '.join(flagged)}",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                "security", "placeholder_values", "PASS", "no obvious placeholders found"
            )
        )

    if settings.auth_enabled and settings.auth_secret_key and _is_placeholder_secret(
        settings.auth_secret_key
    ):
        checks.append(
            PreflightCheck(
                "security",
                "auth_secret_strength",
                "FAIL" if settings.is_production else "WARN",
                "AUTH_SECRET_KEY is too short/common to be a real secret",
            )
        )
    else:
        checks.append(PreflightCheck("security", "auth_secret_strength", "PASS", "acceptable"))

    localhost_notes = [
        note
        for note in runtime_notes(settings, "worker")
        if "localhost" in note.message
    ]
    if localhost_notes:
        checks.append(
            PreflightCheck(
                "security",
                "no_localhost_in_production",
                "FAIL",
                "; ".join(note.message for note in localhost_notes),
            )
        )
    else:
        checks.append(
            PreflightCheck(
                "security",
                "no_localhost_in_production",
                "PASS",
                "no localhost endpoints under a production profile",
            )
        )
    return checks


def _ai_checks(settings: Settings) -> list[PreflightCheck]:
    summary = runtime_summary(settings, "worker")
    checks = [
        PreflightCheck(
            "ai",
            "embedding_provider",
            "PASS",
            f"{summary['embedding_provider']} / {summary['embedding_model']} "
            f"(dim={summary['embedding_dimension']})",
        ),
        PreflightCheck(
            "ai",
            "generative_model",
            "PASS" if summary["change_classifier"][0] != "fake" else "WARN",
            f"disclosure classifier: {summary['change_classifier'][0]} / "
            f"{summary['change_classifier'][1]}",
        ),
        PreflightCheck(
            "ai",
            "batch_configuration",
            "PASS",
            f"max_items={summary['batch_max_items']} "
            f"configured_budget={summary['batch_input_token_budget']} "
            f"effective_budget={summary['batch_effective_budget']} "
            f"multi_item={summary['batch_multi_item_requests']}",
        ),
        PreflightCheck(
            "ai",
            "chat_pacing",
            "PASS",
            f"chat_delay_seconds={summary['ai_provider_chat_delay_seconds']}",
        ),
    ]
    if summary["change_classifier"][0] == "openai_compatible" and not summary[
        "ai_provider_api_key_configured"
    ]:
        checks.append(
            PreflightCheck(
                "ai",
                "provider_credential",
                "FAIL",
                "a real AI provider is selected but AI_PROVIDER_API_KEY is not set",
            )
        )
    return checks


def _workflow_checks(settings: Settings) -> list[PreflightCheck]:
    return [
        PreflightCheck(
            "workflow",
            "checkpoint_provider",
            "PASS" if settings.workflow_checkpoint_provider == "postgres" else "WARN",
            f"provider={settings.workflow_checkpoint_provider}",
        ),
        PreflightCheck(
            "workflow",
            "analysis_time_limit",
            (
                "PASS"
                if settings.analysis_workflow_time_limit_seconds
                > settings.worker_default_time_limit_seconds
                else "WARN"
            ),
            f"analysis_workflow_time_limit_seconds="
            f"{int(settings.analysis_workflow_time_limit_seconds)}",
        ),
        PreflightCheck(
            "workflow",
            "stage_batch_ledger",
            "PASS",
            "durable batch ledger (analysis_stage_batches) is part of every run; "
            "verified reachable in the DATABASE checks below",
        ),
    ]


def _storage_checks(settings: Settings) -> list[PreflightCheck]:
    bucket_configured = bool(settings.minio_bucket_filings and settings.minio_bucket_reports)
    return [
        PreflightCheck(
            "storage",
            "provider",
            "PASS" if settings.object_storage_provider == "minio" else "WARN",
            f"provider={settings.object_storage_provider}",
        ),
        PreflightCheck(
            "storage",
            "bucket_configuration",
            "PASS" if bucket_configured or settings.object_storage_provider != "minio" else "FAIL",
            f"filings_bucket={settings.minio_bucket_filings!r} "
            f"reports_bucket={settings.minio_bucket_reports!r} "
            f"endpoint={mask_url(settings.minio_endpoint)}",
        ),
    ]


async def run_preflight() -> dict[str, Any]:
    settings = Settings()
    doctor = await run_doctor(initialize_checkpoint=False)
    doctor_checks = {check["name"]: DoctorCheck(**check) for check in doctor["checks"]}

    checks: list[PreflightCheck] = []
    if "database" in doctor_checks:
        checks.append(
            _from_doctor_check("database", "connectivity_and_schema", doctor_checks["database"])
        )
    if "redis" in doctor_checks:
        checks.append(_from_doctor_check("redis", "connectivity", doctor_checks["redis"]))
    checks.extend(_workflow_checks(settings))
    checks.extend(_ai_checks(settings))
    checks.extend(_storage_checks(settings))
    checks.extend(_security_checks(settings))

    overall = (
        "FAIL"
        if any(check.status == "FAIL" for check in checks)
        else "WARN"
        if any(check.status == "WARN" for check in checks)
        else "PASS"
    )
    return {
        "overall": overall,
        "environment": settings.environment,
        "app_profile": settings.app_profile,
        "checks": [
            {
                "group": check.group,
                "name": check.name,
                "status": check.status,
                "detail": check.detail,
                **({"metadata": check.metadata} if check.metadata else {}),
            }
            for check in checks
        ],
    }


def _print_summary(result: dict[str, Any]) -> None:
    print(f"DeltaLedger AI - AAPL E2E preflight ({result['app_profile']}/{result['environment']})")
    print("-" * 72)
    current_group = None
    for check in result["checks"]:
        if check["group"] != current_group:
            current_group = check["group"]
            print(f"\n[{current_group.upper()}]")
        print(f"  {check['status']:<4}  {check['name']:<28} {check['detail']}")
    print("\n" + "-" * 72)
    print(f"OVERALL: {result['overall']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON instead")
    args = parser.parse_args(argv)

    result = asyncio.run(run_preflight())
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        _print_summary(result)
    return 0 if result["overall"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
