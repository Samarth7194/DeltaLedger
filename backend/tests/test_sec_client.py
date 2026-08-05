from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.exceptions import UnsafeSecUrlError
from app.integrations.sec.client import SecClient


def test_rejects_non_sec_urls() -> None:
    client = SecClient(Settings(sec_user_agent="DeltaLedgerAI test@example.com"))

    with pytest.raises(UnsafeSecUrlError):
        client._validate_sec_url("https://example.com/not-sec")

    with pytest.raises(UnsafeSecUrlError):
        client._validate_sec_url("http://www.sec.gov/insecure")


def test_accepts_allowed_sec_https_url() -> None:
    client = SecClient(Settings(sec_user_agent="DeltaLedgerAI test@example.com"))

    client._validate_sec_url("https://data.sec.gov/submissions/CIK0000320193.json")


def test_flatten_company_facts_preserves_taxonomy_concept_label_and_unit() -> None:
    client = SecClient(Settings(sec_user_agent="DeltaLedgerAI test@example.com"))
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "val": 100,
                                "fy": 2024,
                                "fp": "Q1",
                                "form": "10-Q",
                                "accn": "0000000000-24-000001",
                            }
                        ]
                    },
                }
            }
        }
    }

    facts = client.flatten_company_facts(payload)

    assert facts == [
        {
            "val": 100,
            "fy": 2024,
            "fp": "Q1",
            "form": "10-Q",
            "accn": "0000000000-24-000001",
            "taxonomy": "us-gaap",
            "concept": "Revenues",
            "label": "Revenue",
            "unit": "USD",
        }
    ]

