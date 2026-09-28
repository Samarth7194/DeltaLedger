"""Token-aware batch planning for resumable AI stages.

A *batch* is a bounded, durable unit of work: the items in it are sent to the
provider together (one multi-item request) and their results are persisted
together, so a stopped/failed run resumes from the first incomplete batch.

Sizing is driven only by configuration (`AI_BATCH_MAX_ITEMS`,
`AI_BATCH_INPUT_TOKEN_BUDGET`, `AI_BATCH_TOKEN_SAFETY_MARGIN`); no model
context size is hard-coded here.

Token estimation
----------------
The project has no tokenizer for the Gemini models it calls (the only
tokenizer in the dependency tree is the local BGE embedding model's, which
counts differently), and adding one would be a large new dependency for what
is only a sizing guard. So tokens are *estimated* from character length with
a deliberately conservative ratio (`CHARS_PER_TOKEN`): SEC filing prose runs
about 4 characters per token, but numeric/tabular text tokenizes closer to
2-3, and over-estimating only makes batches slightly smaller. The safety
margin is applied on top of that estimate.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.core.config import Settings

# Conservative (over-counting) characters-per-token ratio; see module docstring.
CHARS_PER_TOKEN = 3.0
# JSON framing per item (keys, quotes, ids) that the character count of the
# item's text does not include.
PER_ITEM_OVERHEAD_TOKENS = 40


def estimate_tokens(text: str | None) -> int:
    """Conservative token estimate for `text` (0 for empty/None)."""
    if not text:
        return 0
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def estimate_payload_tokens(payload: object) -> int:
    """Estimate tokens for any JSON-serializable payload, as it would be sent."""
    return estimate_tokens(json.dumps(payload, sort_keys=True, default=str))


@dataclass(frozen=True)
class BatchingConfig:
    max_items: int
    input_token_budget: int
    safety_margin: float

    @classmethod
    def from_settings(cls, settings: Settings) -> BatchingConfig:
        return cls(
            max_items=settings.ai_batch_max_items,
            input_token_budget=settings.ai_batch_input_token_budget,
            safety_margin=settings.ai_batch_token_safety_margin,
        )

    @property
    def effective_token_budget(self) -> int:
        """Token budget actually planned against: the configured budget minus
        the safety margin (the token counts are estimates, not exact)."""
        return max(1, int(self.input_token_budget * (1.0 - self.safety_margin)))


@dataclass(frozen=True)
class BatchItem:
    """One unit of work to place in a batch.

    `identity` must be stable across runs (e.g. built from persisted
    passage ids and a content hash) - it is what makes a batch's identity
    reproducible. `estimated_tokens` is the item's own input cost.
    """

    identity: str
    estimated_tokens: int


@dataclass(frozen=True)
class PlannedBatch:
    index: int  # 1-based, for "part 3 of 18" style progress
    total: int
    items: tuple[BatchItem, ...]
    estimated_input_tokens: int
    # True when a single item alone exceeds the effective budget. It still
    # gets its own batch (an item can never be split), and callers can log it.
    oversized: bool = False

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def identities(self) -> list[str]:
        return [item.identity for item in self.items]


def plan_batches(
    items: Sequence[BatchItem],
    config: BatchingConfig,
    *,
    fixed_overhead_tokens: int = 0,
) -> list[PlannedBatch]:
    """Pack `items`, in order, into batches bounded by `config`.

    Order is preserved and packing is greedy/deterministic, so the same input
    always yields the same plan - which is what lets a resumed run line up
    with the batches a previous attempt already completed.

    `fixed_overhead_tokens` is the per-request cost that does not depend on the
    items (system prompt, shared metadata) and counts against every batch.
    """
    budget = config.effective_token_budget
    groups: list[list[BatchItem]] = []
    current: list[BatchItem] = []
    current_tokens = fixed_overhead_tokens
    for item in items:
        cost = item.estimated_tokens + PER_ITEM_OVERHEAD_TOKENS
        if current and (
            len(current) >= config.max_items or current_tokens + cost > budget
        ):
            groups.append(current)
            current = []
            current_tokens = fixed_overhead_tokens
        current.append(item)
        current_tokens += cost
    if current:
        groups.append(current)

    total = len(groups)
    return [
        PlannedBatch(
            index=position,
            total=total,
            items=tuple(group),
            estimated_input_tokens=fixed_overhead_tokens
            + sum(item.estimated_tokens + PER_ITEM_OVERHEAD_TOKENS for item in group),
            oversized=(
                len(group) == 1
                and fixed_overhead_tokens
                + group[0].estimated_tokens
                + PER_ITEM_OVERHEAD_TOKENS
                > budget
            ),
        )
        for position, group in enumerate(groups, start=1)
    ]


def canonical_hash(payload: object) -> str:
    """SHA-256 of a JSON-serializable payload in canonical form (sorted keys,
    no incidental whitespace). Used to fingerprint input *content* without
    storing it."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def batch_identity_hash(
    *,
    stage: str,
    model_name: str | None,
    prompt_version: str | None,
    item_identities: Iterable[str],
    context_hash: str = "",
) -> str:
    """Stable identity of a batch: what stage, which model/prompt produced it,
    the shared request context, and exactly which items (in order) it covers.

    Every item identity must already embed a hash of that item's canonical
    input content (not just its ids), and `context_hash` fingerprints request
    content shared by all items (e.g. allowed labels/metrics). So:

    * same ids + same content + same model/prompt/context => same hash (reusable)
    * changed content, model, prompt version, or context    => different hash
    """
    digest = hashlib.sha256()
    for part in (stage, model_name or "", prompt_version or "", context_hash):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    for identity in item_identities:
        digest.update(identity.encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()


def item_request_id(identity: str) -> str:
    """Short, stable, provider-safe id to put on an item inside a multi-item
    request (persisted identities are long; models garble long ids)."""
    return "i_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]


# Per-item outcomes recorded durably with a batch. "success": analysed and
# produced a result. "zero_result": analysed and legitimately produced nothing
# (e.g. a passage with no financial claims). "requires_review": could NOT be
# analysed after repair/retry - a distinct, analyst-visible state, never
# conflated with a genuine empty result.
OUTCOME_SUCCESS = "success"
OUTCOME_ZERO_RESULT = "zero_result"
OUTCOME_REQUIRES_REVIEW = "requires_review"
