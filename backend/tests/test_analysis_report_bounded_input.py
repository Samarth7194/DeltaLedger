"""The final report never feeds raw comparison text into a model.

It is assembled deterministically from already-persisted, structured outputs
(counts and ids), so its size is bounded by the number of findings, not by the
size of the filings - there is no giant prompt to split or summarize
hierarchically.
"""

from __future__ import annotations

import inspect
import json
import uuid
from types import SimpleNamespace

from app.services import analysis_report_service
from app.services.analysis_report_service import _counts_by, _evidence_manifest, _summary

HUGE_TEXT = "Liquidity risk language changed materially. " * 5000  # ~215k characters


def test_report_generation_has_no_model_dependency() -> None:
    source = inspect.getsource(analysis_report_service)

    for marker in ("chat_json", "OpenAICompatibleClient", "classify(", "extract_claims"):
        assert marker not in source
    assert 'generator_name="deterministic-analysis-report"' in source
    assert "prompt_version=None" in source


def test_report_inputs_are_ids_and_counts_never_the_raw_filing_text() -> None:
    changes = [
        SimpleNamespace(
            id=uuid.uuid4(),
            change_type="weakened",
            previous_text=HUGE_TEXT,
            current_text=HUGE_TEXT,
        )
        for _ in range(50)
    ]
    verifications = [
        SimpleNamespace(
            id=uuid.uuid4(),
            financial_claim_id=uuid.uuid4(),
            verification_status="verified",
            current_xbrl_fact_id=uuid.uuid4(),
            comparison_xbrl_fact_id=None,
        )
        for _ in range(20)
    ]

    manifest = _evidence_manifest(changes, verifications, [], [])
    summary_counts = _counts_by(changes, "change_type")
    verification_counts = _counts_by(verifications, "verification_status")
    executive_summary = _summary(summary_counts, verification_counts, {})

    serialized = json.dumps([manifest, summary_counts, executive_summary])
    assert "Liquidity risk language" not in serialized
    assert len(serialized) < 20_000  # ~11 MB of source text in, a few KB out
    assert len(manifest["disclosure_change_ids"]) == 50
    assert summary_counts == {"weakened": 50}


def test_report_size_grows_with_findings_not_with_text_size() -> None:
    def build(text: str) -> int:
        changes = [
            SimpleNamespace(id=uuid.uuid4(), change_type="weakened", previous_text=text)
            for _ in range(10)
        ]
        return len(json.dumps(_evidence_manifest(changes, [], [], [])))

    assert build("x") == build(HUGE_TEXT)
