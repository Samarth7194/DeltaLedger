from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.config import get_settings
from app.services.health_checks import (
    check_checkpoint_configuration,
    check_configuration,
    check_database,
    check_pgvector,
    check_redis,
    check_storage_configuration,
)


async def run(target: str) -> int:
    settings = get_settings()
    checks = []
    if target in {"all", "config"}:
        checks.append(check_configuration(settings))
    if target in {"all", "checkpoint"}:
        checks.append(check_checkpoint_configuration(settings))
    if target in {"all", "database"}:
        checks.append(await check_database(settings))
    if target in {"all", "pgvector"}:
        checks.append(await check_pgvector(settings))
    if target in {"all", "redis"}:
        checks.append(await check_redis(settings))
    if target in {"all", "storage"}:
        checks.append(check_storage_configuration(settings))
    payload = {
        "status": "ok" if all(check.status == "ok" for check in checks) else "degraded",
        "checks": [check.as_dict() for check in checks],
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "ok" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="DeltaLedger dependency health checks.")
    parser.add_argument(
        "target",
        choices=["all", "config", "checkpoint", "database", "pgvector", "redis", "storage"],
    )
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args.target)))
    except ValueError as exc:
        print(
            json.dumps({"status": "degraded", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
