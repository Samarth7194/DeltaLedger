from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.core.exceptions import SecClientError, UnsafeSecUrlError

ALLOWED_SEC_HOSTS = {"www.sec.gov", "sec.gov", "data.sec.gov"}


@dataclass(frozen=True)
class SecFilingMetadata:
    accession_number: str
    form_type: str
    filing_date: date
    report_period: date | None
    primary_document: str
    source_url: str
    raw_metadata: dict[str, Any]


class SecClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    @asynccontextmanager
    async def _http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return

        async with httpx.AsyncClient(
            timeout=self.settings.sec_request_timeout_seconds,
            headers={
                "User-Agent": self.settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
        ) as client:
            yield client

    async def _throttle(self) -> None:
        min_interval = 1.0 / self.settings.sec_requests_per_second
        async with self._lock:
            now = asyncio.get_running_loop().time()
            wait_for = self._last_request_at + min_interval - now
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_request_at = asyncio.get_running_loop().time()

    async def _get_json(self, url: str) -> dict[str, Any]:
        self._validate_sec_url(url)
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.settings.sec_max_attempts),
            wait=wait_exponential(
                multiplier=self.settings.sec_min_wait_seconds,
                max=self.settings.sec_max_wait_seconds,
            ),
            retry=retry_if_exception_type((httpx.HTTPError, SecClientError)),
            reraise=True,
        ):
            with attempt:
                await self._throttle()
                async with self._http_client() as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise SecClientError("SEC JSON response was not an object.")
                    return payload
        raise SecClientError("SEC request retry loop exited unexpectedly.")

    async def _get_bytes(self, url: str) -> tuple[bytes, str]:
        self._validate_sec_url(url)
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.settings.sec_max_attempts),
            wait=wait_exponential(
                multiplier=self.settings.sec_min_wait_seconds,
                max=self.settings.sec_max_wait_seconds,
            ),
            retry=retry_if_exception_type((httpx.HTTPError, SecClientError)),
            reraise=True,
        ):
            with attempt:
                await self._throttle()
                async with self._http_client() as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    return response.content, content_type
        raise SecClientError("SEC request retry loop exited unexpectedly.")

    def _validate_sec_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SEC_HOSTS:
            raise UnsafeSecUrlError(f"Unsupported SEC URL: {url}")

    async def get_company_tickers(self) -> dict[str, Any]:
        return await self._get_json(f"{self.settings.sec_base_url}/files/company_tickers.json")

    async def lookup_cik(self, ticker: str) -> tuple[str, str]:
        payload = await self.get_company_tickers()
        normalized_ticker = ticker.upper()
        for row in payload.values():
            if not isinstance(row, dict):
                continue
            if str(row.get("ticker", "")).upper() == normalized_ticker:
                cik = str(row["cik_str"]).zfill(10)
                name = str(row.get("title", normalized_ticker))
                return cik, name
        raise SecClientError(f"Ticker was not found in SEC ticker mapping: {ticker}")

    async def get_submissions(self, cik: str) -> dict[str, Any]:
        normalized_cik = cik.zfill(10)
        url = f"{self.settings.sec_data_url}/submissions/CIK{normalized_cik}.json"
        return await self._get_json(url)

    async def get_company_facts(self, cik: str) -> dict[str, Any]:
        normalized_cik = cik.zfill(10)
        url = f"{self.settings.sec_data_url}/api/xbrl/companyfacts/CIK{normalized_cik}.json"
        return await self._get_json(url)

    async def get_filing_document(self, source_url: str) -> tuple[bytes, str]:
        return await self._get_bytes(source_url)

    async def list_recent_10q_filings(self, cik: str, quarters: int) -> list[SecFilingMetadata]:
        payload = await self.get_submissions(cik)
        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_documents = recent.get("primaryDocument", [])

        normalized_cik = cik.lstrip("0")
        results: list[SecFilingMetadata] = []
        for index, form_type in enumerate(forms):
            if form_type != "10-Q":
                continue
            accession = accession_numbers[index]
            accession_no_dashes = accession.replace("-", "")
            primary_document = primary_documents[index]
            source_url = (
                f"{self.settings.sec_base_url}/Archives/edgar/data/"
                f"{normalized_cik}/{accession_no_dashes}/{primary_document}"
            )
            results.append(
                SecFilingMetadata(
                    accession_number=accession,
                    form_type=form_type,
                    filing_date=date.fromisoformat(filing_dates[index]),
                    report_period=(
                        date.fromisoformat(report_dates[index]) if report_dates[index] else None
                    ),
                    primary_document=primary_document,
                    source_url=source_url,
                    raw_metadata={
                        "accessionNumber": accession,
                        "form": form_type,
                        "filingDate": filing_dates[index],
                        "reportDate": report_dates[index],
                        "primaryDocument": primary_document,
                    },
                )
            )
            if len(results) >= quarters:
                break
        return results

    def flatten_company_facts(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        facts = payload.get("facts", {})
        for taxonomy, concepts in facts.items():
            if not isinstance(concepts, dict):
                continue
            for concept, concept_payload in concepts.items():
                if not isinstance(concept_payload, dict):
                    continue
                label = concept_payload.get("label")
                units = concept_payload.get("units", {})
                for unit, unit_facts in units.items():
                    if not isinstance(unit_facts, list):
                        continue
                    for fact in unit_facts:
                        if not isinstance(fact, dict):
                            continue
                        flattened.append(
                            {
                                **fact,
                                "taxonomy": taxonomy,
                                "concept": concept,
                                "label": label,
                                "unit": unit,
                            }
                        )
        return flattened
