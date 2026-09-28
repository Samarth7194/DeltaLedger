"""Resumable, batched disclosure classification, end to end through
FilingComparisonService with a real DisclosureChangeService and the real
StageBatchRepository (over an in-memory store)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.ai.openai_compatible import ProviderRequestError
from app.ai.semantic_change import ChangeClassificationResult
from app.core.config import Settings
from app.db.models.workflow import BATCH_STAGE_DISCLOSURE_COMPARISON as STAGE
from app.repositories.stage_batch_repository import StageBatchRepository
from app.services.disclosure_change_service import DisclosureChangeService
from app.services.filing_comparison_service import FilingComparisonService
from tests.batch_test_helpers import InMemoryBatchSession, batch_rows
from tests.test_disclosure_batch_classification import (
    _passage,
    _provider_error,
    _result,
    _ScriptedClassifier,
    _section,
)
from tests.test_filing_comparison_service import (
    _fake_held_lock,
    _FakeAligner,
    _FakeMatcher,
    _FakeSectionsRepo,
    _FakeSegmenter,
    _FakeSession,
    _TrackedComparison,
)

RUN_ID = uuid.uuid4()


class _PersistingComparisonsRepo:
    """Comparisons repository whose persisted changes survive between runs
    like database rows - and, like the real `replace_section_matches`, whose
    re-run wipes them first (the cascade the reuse cache exists to survive)."""

    def __init__(self, session, comparison, passages_by_section, database, matches_db) -> None:
        self._session = session
        self.comparison = comparison
        self._passages_by_section = passages_by_section
        # `database` is the persistent store shared by every repository
        # instance, i.e. what survives a process restart.
        self.changes_by_passage_match: dict[uuid.UUID, object] = database
        self._matches = matches_db  # persisted section/passage matches
        self.upsert_calls: list[uuid.UUID] = []
        self.status_history: list[str] = []

    async def get_comparison(self, comparison_id):
        object.__setattr__(self.comparison, "_stale", False)
        self._session.track(self.comparison)
        return self.comparison

    async def set_status(self, comparison, status, **kwargs):
        comparison.status = status
        comparison.error_code = kwargs.get("error_code")
        comparison.error_message = kwargs.get("error_message")
        if kwargs.get("metrics") is not None:
            comparison.processing_metrics = kwargs["metrics"]
        self.status_history.append(status)

    async def get_or_create_passages(self, section_id, passages, *, segmentation_version):
        return list(passages)

    async def list_passages_for_section(self, section_id, *, segmentation_version=None):
        return self._passages_by_section.get(section_id, [])

    async def replace_section_matches(self, comparison_id, matches):
        self.changes_by_passage_match.clear()  # the cascade wipe
        self._matches["section"] = list(matches)
        self._matches["passage"] = []
        return list(matches)

    async def replace_passage_matches(self, section_match_id, matches):
        stored = list(matches)
        self._matches["passage"] = [
            m for m in self._matches["passage"] if m.section_match_id != section_match_id
        ] + stored
        return stored

    async def list_section_matches(self, comparison_id):
        # Database row order is arbitrary: return it reversed on purpose.
        return list(reversed(self._matches["section"]))

    async def list_passage_matches(self, comparison_id):
        return list(reversed(self._matches["passage"]))

    async def set_matching_state(
        self, comparison, *, fingerprint, section_match_count=0, passage_match_count=0
    ):
        comparison.processing_metrics = {
            **(getattr(comparison, "processing_metrics", None) or {}),
            "matching_fingerprint": fingerprint,
            "matching_section_match_count": section_match_count,
            "matching_passage_match_count": passage_match_count,
        }

    async def upsert_change_for_passage_match(self, passage_match_id, change):
        self.upsert_calls.append(passage_match_id)
        self.changes_by_passage_match[passage_match_id] = change  # replace, never append
        return change

    async def list_reusable_change_results(
        self, comparison_id, *, model_name, prompt_version, additional_prompt_versions=()
    ):
        versions = {prompt_version, *additional_prompt_versions}
        return [
            (c.previous_text, c.current_text, c.original_model_output)
            for c in self.changes_by_passage_match.values()
            if c.detection_method in ("hybrid", "hybrid_cached")
            and c.model_name == model_name
            and c.prompt_version in versions
        ]

    async def list_failed_change_placeholders(self, comparison_id, *, model_name):
        return [
            (c.previous_text, c.current_text, c.original_model_output)
            for c in self.changes_by_passage_match.values()
            if c.detection_method == "model_output_failed" and c.model_name == model_name
        ]


class _Scenario:
    def __init__(self, *, model_pairs: int, unchanged_pairs: int = 0, max_items: int = 2) -> None:
        self.max_items = max_items
        filing_ids = (uuid.uuid4(), uuid.uuid4())
        current_section = _section()
        previous_section = _section()
        current_section.id, previous_section.id = uuid.uuid4(), uuid.uuid4()
        current_section.text_hash, previous_section.text_hash = "hash-cur", "hash-prev"
        self.current_section, self.previous_section = current_section, previous_section
        self.settings_overrides: dict[str, object] = {}
        self.comparison = _TrackedComparison(
            id=uuid.uuid4(),
            current_filing_id=filing_ids[0],
            comparison_filing_id=filing_ids[1],
            status="queued",
        )
        self.section_match = SimpleNamespace(
            id=uuid.uuid4(),
            current_section_id=current_section.id,
            previous_section_id=previous_section.id,
            match_type="exact_structural",
        )
        passages_current, passages_previous, passage_matches = [], [], []
        for index in range(model_pairs + unchanged_pairs):
            same = index >= model_pairs
            word = f"term{index}q"
            previous = _passage(f"We expect {word} demand to remain resilient.")
            current = _passage(
                previous.text if same else f"We expect {word} demand may weaken materially."
            )
            passages_previous.append(previous)
            passages_current.append(current)
            passage_matches.append(
                SimpleNamespace(
                    id=uuid.uuid4(),
                    section_match_id=self.section_match.id,
                    current_passage_id=current.id,
                    previous_passage_id=previous.id,
                )
            )
        self.passage_matches = passage_matches
        self._passages = {
            current_section.id: passages_current,
            previous_section.id: passages_previous,
        }
        # The persistent "database": changes and ledger rows. Everything else
        # (sessions, repositories, services) is rebuilt from scratch per run.
        self.database: dict[uuid.UUID, object] = {}
        self.matches_db: dict[str, list] = {"section": [], "passage": []}
        self.session = _FakeSession()
        self.repo = _PersistingComparisonsRepo(
            self.session, self.comparison, self._passages, self.database, self.matches_db
        )
        self.sections = _FakeSectionsRepo(
            {filing_ids[0]: [current_section], filing_ids[1]: [previous_section]}
        )
        self.ledger_rows: list = []
        self.embedding_version = "v1"  # change it to change the matching fingerprint

    def service(
        self, classifier, *, run_id=RUN_ID, aligner=None
    ) -> FilingComparisonService:
        # A brand-new process-equivalent: new session, repositories, matcher,
        # aligner, detector and service. Only `self.database` and the ledger
        # rows (the persisted state) carry over.
        self.session = _FakeSession()
        self.repo = _PersistingComparisonsRepo(
            self.session, self.comparison, self._passages, self.database, self.matches_db
        )
        self.matcher = _FakeMatcher([self.section_match])
        self.matcher.embeddings.model_version = self.embedding_version
        self.aligner = aligner or _FakeAligner({self.section_match.id: self.passage_matches})
        settings = Settings(
            _env_file=None,
            app_profile="local-cloud",
            environment="local",
            ai_batch_max_items=self.max_items,
            **self.settings_overrides,
        )
        # A finished comparison is forced back to a re-run; an interrupted or
        # failed one is left exactly as the crash/failure left it.
        object.__setattr__(self.comparison, "_stale", False)
        if self.comparison.status == "completed":
            self.comparison.status = "queued"
        service = FilingComparisonService(
            self.session,
            settings,
            comparisons=self.repo,
            sections=self.sections,
            segmenter=_FakeSegmenter(),
            matcher=self.matcher,
            aligner=self.aligner,
            change_detector=DisclosureChangeService(settings, classifier),
            session_factory=lambda: InMemoryBatchSession(self.ledger_rows),
            lock_factory=_fake_held_lock,
            batches=StageBatchRepository(InMemoryBatchSession(self.ledger_rows)),
            batches_factory=StageBatchRepository,
        )
        self._run_id = run_id
        return service

    async def run(self, classifier, *, run_id=RUN_ID, aligner=None) -> None:
        await self.service(classifier, run_id=run_id, aligner=aligner).process_comparison(
            self.comparison.id, analysis_run_id=run_id
        )

    def ledger(self):
        return batch_rows(self.ledger_rows, STAGE)


class _FailOnNthBatchClassifier(_ScriptedClassifier):
    """Healthy except that its `fail_on`-th multi-item request (1-based) hits
    an exhausted rate limit."""

    def __init__(self, *, fail_on: int | None) -> None:
        super().__init__()
        self._fail_on = fail_on

    async def classify_batch(self, items):
        attempt = len(self.batch_calls) + 1
        if self._fail_on == attempt:
            self.batch_calls.append([item_id for item_id, _ in items])
            raise _provider_error()
        return await super().classify_batch(items)


@pytest.mark.asyncio
async def test_classification_runs_as_durable_token_bounded_parts() -> None:
    scenario = _Scenario(model_pairs=5, unchanged_pairs=2, max_items=2)
    classifier = _ScriptedClassifier()

    await scenario.run(classifier)

    ledger = scenario.ledger()
    # 5 model items / 2 per batch = 3 parts; the 2 unchanged pairs never enter a batch.
    assert [(row.index, row.total, row.status) for row in ledger] == [
        (1, 3, "completed"),
        (2, 3, "completed"),
        (3, 3, "completed"),
    ]
    assert len(classifier.batch_calls) == 2 and len(classifier.single_calls) == 1
    assert scenario.comparison.status == "completed"
    metrics = scenario.comparison.processing_metrics
    assert metrics["classification_batches_total"] == 3
    assert metrics["classification_deterministic_skips"] == 2
    assert metrics["classification_gemini_calls"] == 3  # not 5 (one per item)
    # Every candidate stored exactly once.
    assert len(scenario.repo.changes_by_passage_match) == 7
    assert sorted(scenario.repo.upsert_calls) == sorted(scenario.repo.changes_by_passage_match)


@pytest.mark.asyncio
async def test_a_failed_batch_is_recorded_and_the_next_run_resumes_at_it() -> None:
    scenario = _Scenario(model_pairs=6, max_items=2)  # 3 parts

    # Run 1: parts 1-2 complete, part 3 hits the exhausted rate limit.
    first = _FailOnNthBatchClassifier(fail_on=3)
    with pytest.raises(ProviderRequestError):
        await scenario.run(first)

    ledger = scenario.ledger()
    assert [row.status for row in ledger] == ["completed", "completed", "failed"]
    assert ledger[2].error_category == "rate_limited"
    assert "quota exceeded" in ledger[2].error_message
    assert scenario.comparison.status == "failed"
    assert len(first.batch_calls) == 3

    # Run 2: the same comparison is retried with a healthy provider.
    second = _FailOnNthBatchClassifier(fail_on=None)
    await scenario.run(second)

    # Only part 3 reached the provider; parts 1-2 were never re-requested.
    assert len(second.batch_calls) == 1
    assert len(second.batch_calls[0]) == 2
    ledger = scenario.ledger()
    assert [row.status for row in ledger] == ["completed", "completed", "completed"]
    assert [row.retry_count for row in ledger] == [0, 0, 1]
    assert scenario.comparison.status == "completed"
    metrics = scenario.comparison.processing_metrics
    assert metrics["classification_batches_skipped"] == 2
    assert metrics["classification_batches_executed"] == 1
    assert metrics["classification_gemini_calls"] == 1
    # All six pairs have their result, each stored once and tied to its own passages.
    assert len(scenario.repo.changes_by_passage_match) == 6
    for passage_match in scenario.passage_matches:
        change = scenario.repo.changes_by_passage_match[passage_match.id]
        assert change.change_summary == f"S:{change.current_text}"
        assert change.supporting_evidence["current"]["passage_id"] == str(
            passage_match.current_passage_id
        )


@pytest.mark.asyncio
async def test_batches_one_to_three_complete_and_batch_four_fails_then_resumes_at_four() -> None:
    scenario = _Scenario(model_pairs=8, max_items=2)  # 4 parts

    with pytest.raises(ProviderRequestError):
        await scenario.run(_FailOnNthBatchClassifier(fail_on=4))
    assert [row.status for row in scenario.ledger()] == [
        "completed",
        "completed",
        "completed",
        "failed",
    ]

    healthy = _FailOnNthBatchClassifier(fail_on=None)
    await scenario.run(healthy)

    assert len(healthy.batch_calls) == 1  # only batch 4
    assert [row.status for row in scenario.ledger()] == ["completed"] * 4


@pytest.mark.asyncio
async def test_a_provider_failure_never_destroys_completed_parts() -> None:
    scenario = _Scenario(model_pairs=6, max_items=2)

    with pytest.raises(ProviderRequestError):
        await scenario.run(_FailOnNthBatchClassifier(fail_on=2))

    ledger = scenario.ledger()
    assert [row.status for row in ledger] == ["completed", "failed", "pending"]
    # Part 1's results were stored before the failure and are still there.
    assert len(scenario.repo.changes_by_passage_match) == 2
    stored_texts = {c.current_text for c in scenario.repo.changes_by_passage_match.values()}
    assert len(stored_texts) == 2


@pytest.mark.asyncio
async def test_rerunning_a_finished_comparison_does_not_duplicate_or_recall() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)
    await scenario.run(_ScriptedClassifier())
    first_ids = {pm: c.change_summary for pm, c in scenario.repo.changes_by_passage_match.items()}

    # Force a full re-run of the comparison (status reset) with the ledger intact.
    classifier = _ScriptedClassifier()
    await scenario.run(classifier)

    assert classifier.batch_calls == [] and classifier.single_calls == []
    assert len(scenario.repo.changes_by_passage_match) == 4  # no duplicates
    assert {
        pm: c.change_summary for pm, c in scenario.repo.changes_by_passage_match.items()
    } == first_ids
    assert scenario.comparison.processing_metrics["classification_batches_skipped"] == 2
    assert [row.status for row in scenario.ledger()] == ["completed", "completed"]


@pytest.mark.asyncio
async def test_a_model_or_prompt_version_change_forces_reclassification() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)
    await scenario.run(_ScriptedClassifier())
    assert [row.status for row in scenario.ledger()] == ["completed", "completed"]

    class _NewPromptClassifier(_ScriptedClassifier):
        prompt_version = "single-v2"
        batch_prompt_version = "batch-v2"

    newer = _NewPromptClassifier()
    await scenario.run(newer)

    # Nothing from the old prompt version is reused: both parts run again.
    assert len(newer.batch_calls) == 2
    assert scenario.comparison.processing_metrics["classification_batches_skipped"] == 0
    assert all(
        change.prompt_version == "batch-v2"
        for change in scenario.repo.changes_by_passage_match.values()
    )

    class _NewModelClassifier(_ScriptedClassifier):
        model_name = "other-model"

    other = _NewModelClassifier()
    await scenario.run(other)
    assert len(other.batch_calls) == 2


@pytest.mark.asyncio
async def test_without_an_analysis_run_it_still_batches_but_persists_no_ledger() -> None:
    scenario = _Scenario(model_pairs=4, max_items=2)
    classifier = _ScriptedClassifier()

    await scenario.service(classifier).process_comparison(scenario.comparison.id)

    assert len(classifier.batch_calls) == 2
    assert scenario.ledger() == []
    assert scenario.comparison.status == "completed"


@pytest.mark.asyncio
async def test_a_completed_part_keeps_its_unclassifiable_items_instead_of_retrying_them() -> None:
    scenario = _Scenario(model_pairs=2, max_items=2)  # a single part
    first = _ScriptedClassifier(bad_texts=("term1q",), hopeless_texts=("term1q",))
    await scenario.run(first)
    placeholders = [
        c
        for c in scenario.repo.changes_by_passage_match.values()
        if c.change_type == "requires_review"
    ]
    assert len(placeholders) == 1

    retry = _ScriptedClassifier()
    await scenario.run(retry)

    # The completed part is final: no request, the placeholder is carried over.
    assert retry.batch_calls == [] and retry.single_calls == []
    assert [row.status for row in scenario.ledger()] == ["completed"]
    assert (
        sum(
            1
            for c in scenario.repo.changes_by_passage_match.values()
            if c.change_type == "requires_review"
        )
        == 1
    )


def test_result_model_used_in_the_cache_round_trips() -> None:
    # The seed cache stores original_model_output and re-validates it on resume.
    stored = _result("x").model_dump()
    assert ChangeClassificationResult.model_validate(stored).summary == "S:x"
