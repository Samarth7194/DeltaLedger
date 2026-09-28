from __future__ import annotations

import pytest

from app.ai.batching import (
    PER_ITEM_OVERHEAD_TOKENS,
    BatchingConfig,
    BatchItem,
    batch_identity_hash,
    estimate_tokens,
    item_request_id,
    plan_batches,
)
from app.core.config import Settings


def _items(count: int, tokens: int) -> list[BatchItem]:
    return [BatchItem(identity=f"item-{index}", estimated_tokens=tokens) for index in range(count)]


def test_estimate_tokens_is_conservative_and_handles_empty() -> None:
    assert estimate_tokens(None) == 0
    assert estimate_tokens("") == 0
    # 3 chars/token, rounded up: never fewer tokens than the common ~4 chars/token rule.
    assert estimate_tokens("a" * 300) == 100
    assert estimate_tokens("a" * 300) >= 300 // 4
    assert estimate_tokens("a") == 1


def test_plan_respects_max_items() -> None:
    config = BatchingConfig(max_items=3, input_token_budget=1_000_000, safety_margin=0.0)

    plan = plan_batches(_items(7, tokens=10), config)

    assert [batch.item_count for batch in plan] == [3, 3, 1]
    assert [batch.index for batch in plan] == [1, 2, 3]
    assert {batch.total for batch in plan} == {3}


def test_plan_is_token_aware_and_applies_the_safety_margin() -> None:
    per_item = 100 + PER_ITEM_OVERHEAD_TOKENS  # 140 planned tokens per item
    # 1000 * (1 - 0.3) = 700 effective budget -> 700 // 140 = 5 items per batch.
    config = BatchingConfig(max_items=50, input_token_budget=1000, safety_margin=0.3)
    assert config.effective_token_budget == 700
    assert per_item * 5 <= 700 < per_item * 6

    plan = plan_batches(_items(12, tokens=100), config)

    assert [batch.item_count for batch in plan] == [5, 5, 2]
    assert all(batch.estimated_input_tokens <= 700 for batch in plan)


def test_fixed_request_overhead_counts_against_every_batch() -> None:
    config = BatchingConfig(max_items=50, input_token_budget=1000, safety_margin=0.0)

    without = plan_batches(_items(6, tokens=100), config)
    with_overhead = plan_batches(_items(6, tokens=100), config, fixed_overhead_tokens=500)

    assert len(with_overhead) > len(without)
    assert all(batch.estimated_input_tokens <= 1000 for batch in with_overhead)


def test_a_single_oversized_item_gets_its_own_flagged_batch() -> None:
    config = BatchingConfig(max_items=8, input_token_budget=500, safety_margin=0.0)
    items = [
        BatchItem("small-1", 50),
        BatchItem("huge", 5000),
        BatchItem("small-2", 50),
    ]

    plan = plan_batches(items, config)

    assert [batch.identities for batch in plan] == [["small-1"], ["huge"], ["small-2"]]
    assert [batch.oversized for batch in plan] == [False, True, False]


def test_plan_preserves_order_and_is_deterministic() -> None:
    config = BatchingConfig(max_items=4, input_token_budget=2000, safety_margin=0.25)
    items = _items(11, tokens=120)

    first = plan_batches(items, config)
    second = plan_batches(items, config)

    assert first == second
    assert [identity for batch in first for identity in batch.identities] == [
        item.identity for item in items
    ]


def test_empty_input_yields_no_batches() -> None:
    config = BatchingConfig(max_items=4, input_token_budget=2000, safety_margin=0.25)

    assert plan_batches([], config) == []


def test_batch_identity_hash_is_stable_and_sensitive_to_every_input() -> None:
    base = {
        "stage": "disclosure_comparison",
        "model_name": "model-a",
        "prompt_version": "prompt-v1",
        "item_identities": ["p1|p2", "p3|p4"],
    }

    assert batch_identity_hash(**base) == batch_identity_hash(**base)
    assert len(batch_identity_hash(**base)) == 64
    # Different model, prompt version, items, item order, or stage -> different batch.
    assert batch_identity_hash(**{**base, "model_name": "model-b"}) != batch_identity_hash(**base)
    assert batch_identity_hash(**{**base, "prompt_version": "prompt-v2"}) != batch_identity_hash(
        **base
    )
    assert batch_identity_hash(**{**base, "item_identities": ["p1|p2"]}) != batch_identity_hash(
        **base
    )
    assert batch_identity_hash(
        **{**base, "item_identities": ["p3|p4", "p1|p2"]}
    ) != batch_identity_hash(**base)
    assert batch_identity_hash(**{**base, "stage": "financial_claims"}) != batch_identity_hash(
        **base
    )
    # Boundaries can't be forged by concatenation.
    merged = {**base, "item_identities": ["p1|p2p3|p4"]}
    assert batch_identity_hash(**merged) != batch_identity_hash(**base)


def test_item_request_id_is_short_stable_and_distinct() -> None:
    first = item_request_id("passage-a|passage-b")

    assert first == item_request_id("passage-a|passage-b")
    assert first != item_request_id("passage-a|passage-c")
    assert first.startswith("i_") and len(first) == 14


def test_batching_config_comes_from_settings_and_is_validated() -> None:
    settings = Settings(
        _env_file=None,
        app_profile="local-cloud",
        environment="local",
        ai_batch_max_items=5,
        ai_batch_input_token_budget=4000,
        ai_batch_token_safety_margin=0.5,
    )

    config = BatchingConfig.from_settings(settings)

    assert (config.max_items, config.input_token_budget, config.safety_margin) == (5, 4000, 0.5)
    assert config.effective_token_budget == 2000

    for bad in (
        {"ai_batch_max_items": 0},
        {"ai_batch_input_token_budget": 0},
        {"ai_batch_token_safety_margin": 0.95},
        {"ai_batch_token_safety_margin": -0.1},
    ):
        with pytest.raises(ValueError):
            Settings(_env_file=None, app_profile="local-cloud", environment="local", **bad)
