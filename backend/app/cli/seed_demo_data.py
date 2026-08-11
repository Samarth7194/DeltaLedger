from __future__ import annotations

import argparse
import asyncio
import json

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.demo.dataset import build_demo_manifest
from app.demo.seed import seed_offline_demo
from app.services.filing_ingestion_service import FilingIngestionService

DEFAULT_DEMO_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]


async def run(quarters: int, *, offline: bool, reset: bool, manifest_only: bool) -> None:
    if manifest_only:
        print(json.dumps(build_demo_manifest(), indent=2, sort_keys=True))
        return
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        if offline:
            result = await seed_offline_demo(session, settings, reset=reset)
            print(json.dumps(result, sort_keys=True))
            return
        service = FilingIngestionService(session, settings)
        results = []
        for ticker in DEFAULT_DEMO_TICKERS:
            results.append(await service.ingest_company(ticker=ticker, quarters=quarters))
        print(json.dumps({"seeded": results}, default=str, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare DeltaLedger demo data.")
    parser.add_argument("--quarters", type=int, default=4)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Create deterministic synthetic/reduced-real demo rows without calling SEC.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset deterministic demo rows first. Refuses to run in production.",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Print the deterministic demo manifest without writing the database.",
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            args.quarters,
            offline=args.offline,
            reset=args.reset,
            manifest_only=args.manifest_only,
        )
    )


if __name__ == "__main__":
    main()
