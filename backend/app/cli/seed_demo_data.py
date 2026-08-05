from __future__ import annotations

import argparse
import asyncio

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.filing_ingestion_service import FilingIngestionService

DEFAULT_DEMO_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]


async def run(quarters: int) -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        service = FilingIngestionService(session, settings)
        results = []
        for ticker in DEFAULT_DEMO_TICKERS:
            results.append(await service.ingest_company(ticker=ticker, quarters=quarters))
        print({"seeded": results})


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed MVP demo companies from official SEC data.")
    parser.add_argument("--quarters", type=int, default=4)
    args = parser.parse_args()
    asyncio.run(run(args.quarters))


if __name__ == "__main__":
    main()

