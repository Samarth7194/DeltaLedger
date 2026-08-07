from __future__ import annotations

import hashlib
import re
from collections import Counter
from difflib import SequenceMatcher

TOKEN_RE = re.compile(r"[a-zA-Z0-9.%$'-]+")
NUMERIC_RE = re.compile(r"(?:[$]?\d+(?:\.\d+)?%?)")
YEAR_RE = re.compile(r"\b20\d{2}\b")
QUARTER_RE = re.compile(r"\b(first|second|third|fourth)\s+quarter\b", re.I)

UNCERTAINTY_TERMS = {"may", "might", "could", "uncertain", "subject", "depends", "depending"}
CERTAINTY_TERMS = {"will", "expect", "expects", "committed", "sufficient", "certain"}
COMMITMENT_TERMS = {"will", "shall", "commit", "committed", "must"}
CONDITIONAL_TERMS = {"if", "subject", "provided", "assuming", "depends", "unless"}
NEGATION_TERMS = {"no", "not", "never", "without", "none"}
RISK_TERMS = {"risk", "adverse", "material", "decline", "default", "covenant", "litigation"}


def normalize_for_comparison(text: str) -> str:
    value = text.lower()
    value = re.sub(r"<[^>]+>", " ", value)
    value = YEAR_RE.sub("<year>", value)
    value = QUARTER_RE.sub("<quarter>", value)
    value = re.sub(r"\bpage\s+\d+\b", " ", value)
    value = re.sub(r"[^\w.%$<> -]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def token_set(text: str) -> set[str]:
    return set(tokens(normalize_for_comparison(text)))


def lexical_similarity(left: str, right: str) -> float:
    left_tokens = token_set(left)
    right_tokens = token_set(right)
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    jaccard = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(
        None,
        normalize_for_comparison(left),
        normalize_for_comparison(right),
    ).ratio()
    return round((jaccard * 0.65) + (sequence * 0.35), 4)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(value * value for value in left) ** 0.5 or 1.0
    right_norm = sum(value * value for value in right) ** 0.5 or 1.0
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))


def deterministic_signals(previous_text: str | None, current_text: str | None) -> dict[str, object]:
    previous = previous_text or ""
    current = current_text or ""
    previous_norm = normalize_for_comparison(previous)
    current_norm = normalize_for_comparison(current)
    previous_tokens = Counter(tokens(previous_norm))
    current_tokens = Counter(tokens(current_norm))
    added = sorted((current_tokens - previous_tokens).elements())
    removed = sorted((previous_tokens - current_tokens).elements())
    previous_set = set(previous_tokens)
    current_set = set(current_tokens)
    return {
        "exact_equal": previous == current,
        "normalized_equal": previous_norm == current_norm,
        "token_additions": added,
        "token_removals": removed,
        "uncertainty_added": sorted(
            (current_set & UNCERTAINTY_TERMS) - (previous_set & UNCERTAINTY_TERMS)
        ),
        "uncertainty_removed": sorted(
            (previous_set & UNCERTAINTY_TERMS) - (current_set & UNCERTAINTY_TERMS)
        ),
        "commitment_added": sorted(
            (current_set & COMMITMENT_TERMS) - (previous_set & COMMITMENT_TERMS)
        ),
        "commitment_removed": sorted(
            (previous_set & COMMITMENT_TERMS) - (current_set & COMMITMENT_TERMS)
        ),
        "conditional_added": sorted(
            (current_set & CONDITIONAL_TERMS) - (previous_set & CONDITIONAL_TERMS)
        ),
        "conditional_removed": sorted(
            (previous_set & CONDITIONAL_TERMS) - (current_set & CONDITIONAL_TERMS)
        ),
        "negation_added": sorted(
            (current_set & NEGATION_TERMS) - (previous_set & NEGATION_TERMS)
        ),
        "negation_removed": sorted(
            (previous_set & NEGATION_TERMS) - (current_set & NEGATION_TERMS)
        ),
        "risk_terms_added": sorted((current_set & RISK_TERMS) - (previous_set & RISK_TERMS)),
        "risk_terms_removed": sorted(
            (previous_set & RISK_TERMS) - (current_set & RISK_TERMS)
        ),
        "numeric_previous": NUMERIC_RE.findall(previous),
        "numeric_current": NUMERIC_RE.findall(current),
        "numeric_changed": NUMERIC_RE.findall(previous) != NUMERIC_RE.findall(current),
    }


def clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)
