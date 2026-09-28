from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from app.ai.openai_compatible import ProviderRequestError
from app.ai.semantic_change import ChangeClassificationResult
from app.core.config import Settings
from app.services.filing_comparison_service import FilingComparisonService


class _TrackedComparison:
    """Stands in for a real ORM object that a session can detach.

    Mutating a field after the `_FakeSession` that most recently issued
    this object has been `close()`d raises loudly, mirroring (in spirit)
    how a real detached SQLAlchemy object silently drops such writes --
    except here it fails fast instead of silently, so a missed re-fetch in
    the code under test shows up immediately instead of as a subtly wrong
    final state.
    """

    def __init__(self, **fields: object) -> None:
        object.__setattr__(self, "_stale", False)
        for key, value in fields.items():
            object.__setattr__(self, key, value)

    def __setattr__(self, name: str, value: object) -> None:
        if name != "_stale" and object.__getattribute__(self, "_stale"):
            raise RuntimeError(
                f"attempted to set {name!r} on a stale/detached comparison - "
                "re-fetch via get_comparison() first"
            )
        object.__setattr__(self, name, value)


class _FakeSession:
    """Records commit/rollback/flush/close ordering without touching a real
    DB, and marks any `_TrackedComparison` it is tracking as stale on
    close() -- exactly like a real AsyncSession.close() detaching objects.
    """

    def __init__(self, *, rollback_raises: bool = False) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0
        self.close_count = 0
        self.events: list[str] = []
        self._rollback_raises = rollback_raises
        self._tracked: list[_TrackedComparison] = []

    def track(self, comparison: _TrackedComparison) -> None:
        self._tracked.append(comparison)

    async def commit(self) -> None:
        self.commit_count += 1
        self.events.append("commit")

    async def close(self) -> None:
        self.close_count += 1
        self.events.append("close")
        for comparison in self._tracked:
            object.__setattr__(comparison, "_stale", True)
        self._tracked.clear()

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.events.append("rollback")
        if self._rollback_raises:
            raise RuntimeError("connection already closed")

    async def flush(self) -> None:
        self.flush_count += 1


@contextlib.asynccontextmanager
async def _fake_held_lock(_lock_key: int) -> AsyncIterator[bool]:
    """Stands in for held_advisory_lock() so tests never touch a real DB."""
    yield True


class _FakeComparisonsRepo:
    def __init__(
        self,
        session: _FakeSession,
        comparison: _TrackedComparison,
        section_matches: list[SimpleNamespace],
        *,
        reusable_seed: list[tuple[str | None, str | None, dict]] | None = None,
    ) -> None:
        self._session = session
        self.comparison = comparison
        self.section_matches = section_matches
        self.persisted_changes: dict[uuid.UUID, list[object]] = {}
        self.status_history: list[str] = []
        self._reusable_seed = reusable_seed or []
        self.list_reusable_change_results_calls: list[dict[str, object]] = []

    async def get_comparison(self, comparison_id: uuid.UUID) -> _TrackedComparison:
        # A real `session.get()`/fresh SELECT always returns a usable,
        # attached object -- reflect that by un-staling and re-tracking it.
        object.__setattr__(self.comparison, "_stale", False)
        self._session.track(self.comparison)
        return self.comparison

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

    async def upsert_change_for_passage_match(self, passage_match_id, change):
        self.persisted_changes.setdefault(passage_match_id, []).append(change)
        return change

    async def list_reusable_change_results(
        self, comparison_id, *, model_name, prompt_version, additional_prompt_versions=()
    ):
        self.list_reusable_change_results_calls.append(
            {
                "comparison_id": comparison_id,
                "model_name": model_name,
                "prompt_version": prompt_version,
                "additional_prompt_versions": tuple(additional_prompt_versions),
            }
        )
        return list(self._reusable_seed)

    async def list_failed_change_placeholders(self, comparison_id, *, model_name):
        return []

    async def list_section_matches(self, comparison_id):
        return []

    async def list_passage_matches(self, comparison_id):
        return []

    async def set_matching_state(
        self, comparison, *, fingerprint, section_match_count=0, passage_match_count=0
    ):
        comparison.processing_metrics = {
            **(getattr(comparison, "processing_metrics", None) or {}),
            "matching_fingerprint": fingerprint,
            "matching_section_match_count": section_match_count,
            "matching_passage_match_count": passage_match_count,
        }


class _FakeSectionsRepo:
    def __init__(self, sections_by_filing: dict[uuid.UUID, list[SimpleNamespace]]) -> None:
        self._sections_by_filing = sections_by_filing

    async def get_sections_with_chunks(self, filing_id: uuid.UUID) -> list[SimpleNamespace]:
        return self._sections_by_filing[filing_id]


class _FakeSegmenter:
    def segment_section(self, section: SimpleNamespace) -> list[object]:
        return []


class _FakeMatcher:
    def __init__(
        self,
        section_matches: list[SimpleNamespace],
        *,
        session: _FakeSession | None = None,
        commit_log: list[tuple[str, int]] | None = None,
    ) -> None:
        self._section_matches = section_matches
        self.embeddings = SimpleNamespace(model_name="fake-embedding", model_version="v1")
        self._session = session
        self._commit_log = commit_log
        self.calls = 0

    async def match_sections(self, *, comparison_id, current_sections, previous_sections):
        self.calls += 1
        if self._session is not None and self._commit_log is not None:
            self._commit_log.append(("match_sections", self._session.commit_count))
        return self._section_matches


class _FakeAligner:
    def __init__(
        self,
        matches_by_section: dict[uuid.UUID, list[SimpleNamespace]],
        *,
        session: _FakeSession | None = None,
        commit_log: list[tuple[str, int]] | None = None,
    ) -> None:
        self._matches_by_section = matches_by_section
        self._session = session
        self._commit_log = commit_log
        self.calls = 0

    async def align_passages(self, *, section_match_id, current_passages, previous_passages):
        self.calls += 1
        if self._session is not None and self._commit_log is not None:
            self._commit_log.append(("align_passages", self._session.commit_count))
        return self._matches_by_section.get(section_match_id, [])


class _PerCandidateDetector:
    """Adapts a fake per-candidate `detect_change` to the batched interface
    FilingComparisonService drives (prepare_candidate/classify_candidates),
    so these tests keep exercising the service's own orchestration."""

    supports_multi_item_requests = False
    batch_prompt_version = "test-v1"
    reusable_prompt_versions = ("test-v1",)
    batch_fixed_overhead_tokens = 0

    def prepare_candidate(
        self,
        *,
        comparison_id,
        section_match,
        passage_match,
        current_passage,
        previous_passage,
        current_section,
        previous_section,
        stats=None,
    ):
        if stats is not None:
            stats.candidate_pairs += 1
        return SimpleNamespace(
            identity=str(passage_match.id),
            request_id=str(passage_match.id),
            passage_match=passage_match,
            current_section=current_section,
            previous_section=previous_section,
            current_passage=current_passage,
            previous_passage=previous_passage,
            needs_model=True,
            estimated_tokens=100,
            detect_kwargs={
                "comparison_id": comparison_id,
                "section_match": section_match,
                "passage_match": passage_match,
                "current_passage": current_passage,
                "previous_passage": previous_passage,
                "current_section": current_section,
                "previous_section": previous_section,
            },
        )

    async def classify_candidates(
        self, candidates, *, known_results=None, stats=None, frozen_failures=None
    ):
        changes = []
        error = None
        for candidate in candidates:
            try:
                change = await self.detect_change(
                    **candidate.detect_kwargs, known_results=known_results, stats=stats
                )
            except Exception as exc:
                error = exc
                break
            changes.append((candidate, change))
        return SimpleNamespace(changes=changes, error=error, records={})


class _FlakyChangeDetector(_PerCandidateDetector):
    """Succeeds for every section match except one, which raises like a
    Gemini quota failure would."""

    def __init__(
        self,
        fail_on_section_match_id: uuid.UUID,
        *,
        session: _FakeSession | None = None,
        commit_log: list[tuple[str, int]] | None = None,
    ) -> None:
        self.classifier = SimpleNamespace(
            model_name="fake-change-classifier",
            model_version="v1",
            prompt_version="test-v1",
        )
        self._fail_on = fail_on_section_match_id
        self.calls: list[uuid.UUID] = []
        self._session = session
        self._commit_log = commit_log

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
        known_results=None,
        stats=None,
    ):
        self.calls.append(section_match.id)
        if self._session is not None and self._commit_log is not None:
            self._commit_log.append(("detect_change", self._session.commit_count))
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
        return SimpleNamespace(
            id=uuid.uuid4(), section_match_id=section_match.id, detection_method="hybrid"
        )


class _KnownResultsCapturingDetector(_PerCandidateDetector):
    """Records exactly what `known_results` dict it received on every call,
    to prove the cache seeded from a prior attempt's persisted results
    (list_reusable_change_results) actually reaches detect_change()."""

    classifier = SimpleNamespace(
        model_name="fake-change-classifier", model_version="v1", prompt_version="test-v1"
    )

    def __init__(self) -> None:
        self.known_results_snapshots: list[dict] = []

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
        known_results=None,
        stats=None,
    ):
        self.known_results_snapshots.append(dict(known_results) if known_results else {})
        return SimpleNamespace(
            id=uuid.uuid4(), section_match_id=section_match.id, detection_method="hybrid"
        )


def _build_two_section_fixture() -> tuple[
    _TrackedComparison,
    list[SimpleNamespace],
    dict[uuid.UUID, list[SimpleNamespace]],
    _FakeSectionsRepo,
]:
    current_filing_id = uuid.uuid4()
    comparison_filing_id = uuid.uuid4()
    comparison = _TrackedComparison(
        id=uuid.uuid4(),
        current_filing_id=current_filing_id,
        comparison_filing_id=comparison_filing_id,
        status="queued",
    )

    current_sections = [
        SimpleNamespace(id=uuid.uuid4(), section_order=1),
        SimpleNamespace(id=uuid.uuid4(), section_order=2),
    ]
    previous_sections = [
        SimpleNamespace(id=uuid.uuid4(), section_order=1),
        SimpleNamespace(id=uuid.uuid4(), section_order=2),
    ]
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
    comparison: _TrackedComparison,
    section_matches: list[SimpleNamespace],
    passage_matches_by_section: dict[uuid.UUID, list[SimpleNamespace]],
    sections_repo: _FakeSectionsRepo,
    change_detector: _FlakyChangeDetector,
    commit_log: list[tuple[str, int]] | None = None,
    session_factory=None,
    comparisons_factory=None,
    lock_factory=None,
    reusable_seed=None,
) -> tuple[FilingComparisonService, _FakeComparisonsRepo]:
    comparisons_repo = _FakeComparisonsRepo(
        session, comparison, section_matches, reusable_seed=reusable_seed
    )
    # _env_file=None keeps this test isolated from whatever a developer's
    # local .env happens to be configured for (e.g. a real production-style
    # worker run), so it is deterministic regardless of machine state.
    service = FilingComparisonService(
        session,
        Settings(_env_file=None, app_profile="local-cloud", environment="local"),
        comparisons=comparisons_repo,
        sections=sections_repo,
        segmenter=_FakeSegmenter(),
        matcher=_FakeMatcher(section_matches, session=session, commit_log=commit_log),
        aligner=_FakeAligner(passage_matches_by_section, session=session, commit_log=commit_log),
        change_detector=change_detector,
        session_factory=session_factory,
        comparisons_factory=comparisons_factory,
        lock_factory=lock_factory or _fake_held_lock,
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

    # The passage classified before the failure kept its persisted change...
    passage_0_id = passage_matches_by_section[section_matches[0].id][0].id
    passage_1_id = passage_matches_by_section[section_matches[1].id][0].id
    assert passage_0_id in comparisons_repo.persisted_changes
    assert len(comparisons_repo.persisted_changes[passage_0_id]) == 1
    # ...but the passage that failed never got a chance to persist anything.
    assert passage_1_id not in comparisons_repo.persisted_changes

    # Commits (no single transaction spans more than one stage/AI call):
    # loaded-sections, section-matches-stored, aligning_passages-status,
    # passages+matches for section 0, passages+matches for section 1,
    # detecting_changes-status, the batch plan, the partial results of the
    # failed batch (the item classified before the failure is kept), and
    # finally the "failed" status. None were undone.
    # (+2: the matching-reuse check, and the matching-complete marker written
    # once every section is aligned.)
    assert session.commit_count == 13
    assert session.rollback_count == 1
    assert comparison.status == "failed"
    assert comparison.error_code == "ProviderRequestError"


@pytest.mark.asyncio
async def test_connection_is_closed_before_every_bge_and_gemini_call() -> None:
    """The actual reported bug: a connection sitting open (and idle) across
    BGE/Gemini calls got silently dropped by Neon. Every such call must be
    preceded by a session.close(), not just a commit()."""
    comparison, section_matches, passage_matches_by_section, sections_repo = (
        _build_two_section_fixture()
    )
    session = _FakeSession()
    change_detector = _FlakyChangeDetector(
        fail_on_section_match_id=uuid.uuid4(),  # never matches - full happy path
    )
    service, _comparisons_repo = _build_service(
        session=session,
        comparison=comparison,
        section_matches=section_matches,
        passage_matches_by_section=passage_matches_by_section,
        sections_repo=sections_repo,
        change_detector=change_detector,
    )

    await service.process_comparison(comparison.id)

    # Closes: after loading sections (1), the matching-reuse check (1), before
    # each section's align_passages (2), before the classification loop
    # starts (1), and after the batch results are persisted (2) = 7.
    assert session.close_count == 7
    assert comparison.status == "completed"


@pytest.mark.asyncio
async def test_final_comparison_state_is_fully_persisted_across_repeated_close_cycles() -> None:
    """Regression test for a real bug found during review: comparison.status
    is set multiple times (aligning_passages, detecting_changes, completed)
    across several session.close() calls. Mutating a stale (detached)
    reference instead of re-fetching first would either raise (caught here
    via _TrackedComparison) or, in real SQLAlchemy, silently discard the
    write -- this asserts every stage's write actually lands."""
    comparison, section_matches, passage_matches_by_section, sections_repo = (
        _build_two_section_fixture()
    )
    session = _FakeSession()
    change_detector = _FlakyChangeDetector(fail_on_section_match_id=uuid.uuid4())
    service, comparisons_repo = _build_service(
        session=session,
        comparison=comparison,
        section_matches=section_matches,
        passage_matches_by_section=passage_matches_by_section,
        sections_repo=sections_repo,
        change_detector=change_detector,
    )

    await service.process_comparison(comparison.id)

    assert comparisons_repo.status_history == [
        "matching_sections",
        "aligning_passages",
        "detecting_changes",
        "completed",
    ]
    assert comparison.status == "completed"
    assert comparison.matching_model_name == "fake-embedding"
    assert comparison.matching_model_version == "v1"
    assert comparison.change_model_name == "fake-change-classifier"
    assert comparison.change_model_version == "v1"
    assert comparison.processing_metrics["findings_generated"] == 2


class _FakeRecoverySession:
    """A brand new, independent fake session, as if opened fresh from
    AsyncSessionLocal() after the original session's connection died."""

    def __init__(self) -> None:
        self.commit_count = 0
        self.closed = False

    async def __aenter__(self) -> _FakeRecoverySession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True

    async def commit(self) -> None:
        self.commit_count += 1


class _FakeRecoveryComparisonsRepo:
    """Bound to whatever _FakeRecoverySession it was constructed with -
    proves the recovery path talks to a *different* session than the dead
    original, not the dead one."""

    def __init__(self, session: _FakeRecoverySession, comparison: _TrackedComparison) -> None:
        self.session = session
        self._comparison = comparison

    async def get_comparison(self, comparison_id: uuid.UUID) -> _TrackedComparison:
        object.__setattr__(self._comparison, "_stale", False)
        return self._comparison

    async def set_status(self, comparison, status, **kwargs) -> None:
        comparison.status = status
        comparison.error_code = kwargs.get("error_code")
        comparison.error_message = kwargs.get("error_message")


@pytest.mark.asyncio
async def test_rollback_failure_recovers_via_a_new_session_without_masking_the_error() -> None:
    comparison, section_matches, passage_matches_by_section, sections_repo = (
        _build_two_section_fixture()
    )
    session = _FakeSession(rollback_raises=True)
    change_detector = _FlakyChangeDetector(fail_on_section_match_id=section_matches[1].id)
    recovery_sessions: list[_FakeRecoverySession] = []

    def _session_factory() -> _FakeRecoverySession:
        recovery_session = _FakeRecoverySession()
        recovery_sessions.append(recovery_session)
        return recovery_session

    def _comparisons_factory(
        recovery_session: _FakeRecoverySession,
    ) -> _FakeRecoveryComparisonsRepo:
        return _FakeRecoveryComparisonsRepo(recovery_session, comparison)

    service, comparisons_repo = _build_service(
        session=session,
        comparison=comparison,
        section_matches=section_matches,
        passage_matches_by_section=passage_matches_by_section,
        sections_repo=sections_repo,
        change_detector=change_detector,
        session_factory=_session_factory,
        comparisons_factory=_comparisons_factory,
    )

    with pytest.raises(ProviderRequestError):
        await service.process_comparison(comparison.id)

    assert session.rollback_count == 1
    # The dead session's own commit/rollback machinery was never asked to
    # persist the failure - recovery opened exactly one brand new session...
    assert len(recovery_sessions) == 1
    # ...used it to commit the "failed" status...
    assert recovery_sessions[0].commit_count == 1
    assert recovery_sessions[0].closed is True
    # ...and the original ProviderRequestError is what the caller sees, not
    # some secondary error from the dead session/lock-release cleanup.
    assert comparison.status == "failed"
    assert comparison.error_code == "ProviderRequestError"


@pytest.mark.asyncio
async def test_lock_not_acquired_skips_processing_entirely() -> None:
    """If another worker already holds the comparison lock, process_comparison
    must return immediately without touching the comparison at all."""
    comparison, section_matches, passage_matches_by_section, sections_repo = (
        _build_two_section_fixture()
    )
    session = _FakeSession()
    change_detector = _FlakyChangeDetector(fail_on_section_match_id=uuid.uuid4())

    @contextlib.asynccontextmanager
    async def _lock_already_held(_lock_key: int):
        yield False

    service, comparisons_repo = _build_service(
        session=session,
        comparison=comparison,
        section_matches=section_matches,
        passage_matches_by_section=passage_matches_by_section,
        sections_repo=sections_repo,
        change_detector=change_detector,
        lock_factory=_lock_already_held,
    )

    await service.process_comparison(comparison.id)

    assert comparisons_repo.status_history == []
    assert session.commit_count == 0
    assert comparison.status == "queued"


@pytest.mark.asyncio
async def test_resume_seeds_the_classification_cache_from_prior_persisted_results() -> None:
    """The core resumability fix: a comparison re-entered after an
    interruption must query list_reusable_change_results() (scoped to the
    current model/prompt version) BEFORE the destructive
    replace_section_matches() cascade, and feed the result into
    known_results so detect_change() can reuse it instead of calling
    Gemini again for a pair already classified in the killed attempt."""
    comparison, section_matches, passage_matches_by_section, sections_repo = (
        _build_two_section_fixture()
    )
    session = _FakeSession()
    detector = _KnownResultsCapturingDetector()
    seeded_result = ChangeClassificationResult(
        change_type="weakened",
        summary="Disclosure became more conditional.",
        explanation="Added uncertainty language.",
        confidence=0.82,
        risk_category="liquidity",
        materiality_reason="Liquidity language weakened.",
    )
    seed_key = ("prior previous text", "prior current text")
    service, comparisons_repo = _build_service(
        session=session,
        comparison=comparison,
        section_matches=section_matches,
        passage_matches_by_section=passage_matches_by_section,
        sections_repo=sections_repo,
        change_detector=detector,
        reusable_seed=[(*seed_key, seeded_result.model_dump())],
    )

    await service.process_comparison(comparison.id)

    # Queried for reuse before any classification happened, scoped to the
    # detector's own model/prompt version (never blindly reused across a
    # model/config change).
    assert len(comparisons_repo.list_reusable_change_results_calls) == 1
    seed_call = comparisons_repo.list_reusable_change_results_calls[0]
    assert seed_call["model_name"] == detector.classifier.model_name
    assert seed_call["prompt_version"] == detector.classifier.prompt_version

    # Every detect_change() call received the seeded entry, proving it was
    # loaded into known_results before the classification loop started (not
    # merely accumulated from calls within this same run).
    assert detector.known_results_snapshots
    for snapshot in detector.known_results_snapshots:
        assert seed_key in snapshot
        assert snapshot[seed_key].change_type == "weakened"
        assert snapshot[seed_key].materiality_reason == "Liquidity language weakened."


@pytest.mark.asyncio
async def test_ai_stages_run_without_holding_an_open_db_transaction() -> None:
    """Every matcher/aligner/change_detector call should see a commit_count
    strictly greater than the previous AI call's - proving a commit closed
    the transaction in between, so no AI call ever runs while the previous
    one's DB work (or its own inputs' loading) is still uncommitted."""

    comparison, section_matches, passage_matches_by_section, sections_repo = (
        _build_two_section_fixture()
    )
    session = _FakeSession()
    commit_log: list[tuple[str, int]] = []
    change_detector = _FlakyChangeDetector(
        fail_on_section_match_id=uuid.uuid4(),  # never matches - full happy path
        session=session,
        commit_log=commit_log,
    )
    service, _comparisons_repo = _build_service(
        session=session,
        comparison=comparison,
        section_matches=section_matches,
        passage_matches_by_section=passage_matches_by_section,
        sections_repo=sections_repo,
        change_detector=change_detector,
        commit_log=commit_log,
    )

    await service.process_comparison(comparison.id)

    assert [name for name, _count in commit_log] == [
        "match_sections",
        "align_passages",
        "align_passages",
        "detect_change",
        "detect_change",
    ]
    commit_counts = [count for _name, count in commit_log]
    matcher_and_aligner_counts = commit_counts[:3]
    classifier_counts = commit_counts[3:]
    # Every matcher/aligner call was preceded by a fresh commit since the
    # previous one, so no transaction spans more than one of them...
    assert matcher_and_aligner_counts == sorted(set(matcher_and_aligner_counts))
    assert len(set(matcher_and_aligner_counts)) == 3
    assert matcher_and_aligner_counts[0] >= 1
    # ...and the classification batch started on a fresh commit too. The two
    # items of one batch are classified back-to-back with no database work
    # between them (same commit count), which is the point of a batch.
    assert classifier_counts[0] > matcher_and_aligner_counts[-1]
    assert len(set(classifier_counts)) == 1
