from __future__ import annotations

import argparse
import asyncio

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.filing_ingestion_service import FilingIngestionService


async def run(ticker: str, quarters: int) -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        service = FilingIngestionService(session, settings)
        result = await service.ingest_company(ticker=ticker, quarters=quarters)
        print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest recent SEC 10-Q filings for a company.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--quarters", type=int, default=4)
    args = parser.parse_args()
    asyncio.run(run(args.ticker, args.quarters))


if __name__ == "__main__":
    main()

