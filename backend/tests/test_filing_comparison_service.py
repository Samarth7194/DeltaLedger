from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.ai.openai_compatible import ProviderRequestError
from app.core.config import Settings
from app.services.filing_comparison_service import FilingComparisonService


class _FakeSession:
    """Records commit/rollback/flush ordering without touching a real DB."""

    def __init__(self, *, rollback_raises: bool = False) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0
        self.events: list[str] = []
        self._rollback_raises = rollback_raises

    async def commit(self) -> None:
        self.commit_count += 1
        self.events.append("commit")

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.events.append("rollback")
        if self._rollback_raises:
            raise RuntimeError("connection already closed")

    async def flush(self) -> None:
        self.flush_count += 1


class _FakeComparisonsRepo:
    def __init__(self, comparison: SimpleNamespace, section_matches: list[SimpleNamespace]) -> None:
        self.comparison = comparison
        self.section_matches = section_matches
        self.persisted_changes: dict[uuid.UUID, list[object]] = {}
        self.status_history: list[str] = []

    async def get_comparison(self, comparison_id: uuid.UUID) -> SimpleNamespace:
        return self.comparison

    async def try_acquire_comparison_lock(self, comparison_id: uuid.UUID) -> bool:
        return True

    async def release_comparison_lock(self, comparison_id: uuid.UUID) -> bool:
        return True

    async def set_status(self, comparison, status, **kwargs) -> None:
        comparison.status = status
        comparison.error_code = kwargs.get("error_code")
        comparison.error_message = kwargs.get("error_message")
        if kwargs.get("metrics") is not None:
            comparison.processing_metrics = kwargs["metrics"]
        self.status_history.append(status)

    async def get_or_create_passages(self, section_id, passages, *, segmentation_version):
        return list(passages)

    async def list_passages_for_section(self, section_id, *, segmentation_version=None):
        return []

    async def replace_section_matches(self, comparison_id, matches):
        return list(matches)

    async def replace_passage_matches(self, section_match_id, matches):
        return list(matches)

    async def replace_changes_for_section_match(self, section_match_id, changes):
        stored = list(changes)
        self.persisted_changes[section_match_id] = stored
        return stored


class _FakeSectionsRepo:
    def __init__(self, sections_by_filing: dict[uuid.UUID, list[SimpleNamespace]]) -> None:
        self._sections_by_filing = sections_by_filing

    async def get_sections_with_chunks(self, filing_id: uuid.UUID) -> list[SimpleNamespace]:
        return self._sections_by_filing[filing_id]


class _FakeSegmenter:
    def segment_section(self, section: SimpleNamespace) -> list[object]:
        return []


class _FakeMatcher:
    def __init__(self, section_matches: list[SimpleNamespace]) -> None:
        self._section_matches = section_matches
        self.embeddings = SimpleNamespace(model_name="fake-embedding", model_version="v1")

    async def match_sections(self, *, comparison_id, current_sections, previous_sections):
        return self._section_matches


class _FakeAligner:
    def __init__(self, matches_by_section: dict[uuid.UUID, list[SimpleNamespace]]) -> None:
        self._matches_by_section = matches_by_section

    async def align_passages(self, *, section_match_id, current_passages, previous_passages):
        return self._matches_by_section.get(section_match_id, [])


class _FlakyChangeDetector:
    """Succeeds for every section match except one, which raises like a
    Gemini quota failure would."""

    def __init__(self, fail_on_section_match_id: uuid.UUID) -> None:
        self.classifier = SimpleNamespace(model_name="fake-change-classifier", model_version="v1")
        self._fail_on = fail_on_section_match_id
        self.calls: list[uuid.UUID] = []

    async def detect_change(
        self,
        *,
        comparison_id,
        section_match,
        passage_match,
        current_passage,
        previous_passage,
        current_section,
        previous_section,
    ):
        self.calls.append(section_match.id)
        if section_match.id == self._fail_on:
            raise ProviderRequestError(
                "OpenAI-compatible provider request failed after 5 attempt(s): quota exceeded",
                provider="openai_compatible",
                provider_type="disclosure_change_classifier",
                model="gemini-3.6-flash",
                status_code=429,
                retry_count=5,
                retry_after_seconds=15.69,
                error_category="rate_limited",
            )
        return SimpleNamespace(id=uuid.uuid4(), section_match_id=section_match.id)


def _build_two_section_fixture() -> tuple[
    SimpleNamespace,
    list[SimpleNamespace],
    dict[uuid.UUID, list[SimpleNamespace]],
    _FakeSectionsRepo,
]:
    current_filing_id = uuid.uuid4()
    comparison_filing_id = uuid.uuid4()
    comparison = SimpleNamespace(
        id=uuid.uuid4(),
        current_filing_id=current_filing_id,
        comparison_filing_id=comparison_filing_id,
        status="queued",
    )

    current_sections = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
    previous_sections = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
    section_matches = [
        SimpleNamespace(
            id=uuid.uuid4(),
            current_section_id=current_sections[0].id,
            previous_section_id=previous_sections[0].id,
            match_type="exact_structural",
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            current_section_id=current_sections[1].id,
            previous_section_id=previous_sections[1].id,
            match_type="exact_structural",
        ),
    ]
    passage_matches_by_section = {
        section_matches[0].id: [
            SimpleNamespace(
                id=uuid.uuid4(),
                section_match_id=section_matches[0].id,
                current_passage_id=uuid.uuid4(),
                previous_passage_id=uuid.uuid4(),
            )
        ],
        section_matches[1].id: [
            SimpleNamespace(
                id=uuid.uuid4(),
                section_match_id=section_matches[1].id,
                current_passage_id=uuid.uuid4(),
                previous_passage_id=uuid.uuid4(),
            )
        ],
    }
    sections_repo = _FakeSectionsRepo(
        {current_filing_id: current_sections, comparison_filing_id: previous_sections}
    )
    return comparison, section_matches, passage_matches_by_section, sections_repo


def _build_service(
    *,
    session: _FakeSession,
    comparison: SimpleNamespace,
    section_matches: list[SimpleNamespace],
    passage_matches_by_section: dict[uuid.UUID, list[SimpleNamespace]],
    sections_repo: _FakeSectionsRepo,
    change_detector: _FlakyChangeDetector,
) -> tuple[FilingComparisonService, _FakeComparisonsRepo]:
    comparisons_repo = _FakeComparisonsRepo(comparison, section_matches)
    # _env_file=None keeps this test isolated from whatever a developer's
    # local .env happens to be configured for (e.g. a real production-style
    # worker run), so it is deterministic regardless of machine state.
    service = FilingComparisonService(
        session,
        Settings(_env_file=None, app_profile="local-cloud", environment="local"),
        comparisons=comparisons_repo,
        sections=sections_repo,
        segmenter=_FakeSegmenter(),
        matcher=_FakeMatcher(section_matches),
        aligner=_FakeAligner(passage_matches_by_section),
        change_detector=change_detector,
    )
    return service, comparisons_repo


@pytest.mark.asyncio
async def test_partial_comparison_persistence_survives_a_mid_loop_provider_failure() -> None:
    comparison, section_matches, passage_matches_by_section, sections_repo = (
        _build_two_section_fixture()
    )
    session = _FakeSession()
    change_detector = _FlakyChangeDetector(fail_on_section_match_id=section_matches[1].id)
    service, comparisons_repo = _build_service(
        session=session,
        comparison=comparison,
        section_matches=section_matches,
        passage_matches_by_section=passage_matches_by_section,
        sections_repo=sections_repo,
        change_detector=change_detector,
    )

    with pytest.raises(ProviderRequestError):
        await service.process_comparison(comparison.id)

    # The section classified before the failure kept its persisted change...
    assert section_matches[0].id in comparisons_repo.persisted_changes
    assert len(comparisons_repo.persisted_changes[section_matches[0].id]) == 1
    # ...but the section that failed never got a chance to persist anything.
    assert section_matches[1].id not in comparisons_repo.persisted_changes

    # Commits: after section matching, after passage alignment, after the
    # first (successful) section's change detection, and finally after
    # recording the "failed" status. None of these commits were undone.
    assert session.commit_count == 4
    assert session.rollback_count == 1
    assert comparison.status == "failed"
    assert comparison.error_code == "ProviderRequestError"


@pytest.mark.asyncio
async def test_rollback_failure_does_not_mask_the_original_provider_error() -> None:
    comparison, section_matches, passage_matches_by_section, sections_repo = (
        _build_two_section_fixture()
    )
    session = _FakeSession(rollback_raises=True)
    change_detector = _FlakyChangeDetector(fail_on_section_match_id=section_matches[1].id)
    service, comparisons_repo = _build_service(
        session=session,
        comparison=comparison,
        section_matches=section_matches,
        passage_matches_by_section=passage_matches_by_section,
        sections_repo=sections_repo,
        change_detector=change_detector,
    )

    with pytest.raises(ProviderRequestError):
        await service.process_comparison(comparison.id)

    assert session.rollback_count == 1
    # Status is never flipped to "failed" because we couldn't safely persist
    # that on a connection rollback() itself couldn't recover.
    assert "failed" not in comparisons_repo.status_history
