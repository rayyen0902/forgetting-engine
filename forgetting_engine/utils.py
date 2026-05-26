"""Utility functions: ID generation, math helpers, clock."""

import uuid
from datetime import datetime, timezone

import numpy as np


def generate_id() -> str:
    return uuid.uuid4().hex[:16]


def now() -> datetime:
    return datetime.now(timezone.utc)


def exp_val(x: float) -> float:
    return float(np.exp(x))


def mean_vals(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(np.mean(values))


def std_vals(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(np.std(values))


def cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


def _extract_text(content) -> str:
    """Extract text from any content type for text-based matching."""
    from forgetting_engine.models import L0_RawMessage, L1_Episode, L2_Pattern, L3_Fact

    if isinstance(content, L0_RawMessage):
        return content.text
    if isinstance(content, L1_Episode):
        return f"{content.predicate} {content.outcome}"
    if isinstance(content, L2_Pattern):
        return content.description
    if isinstance(content, L3_Fact):
        return content.sentence or f"{content.key}: {content.value}"
    return str(content)


def _text_contains_any(content, keywords: list[str]) -> bool:
    return any(kw in _extract_text(content) for kw in keywords)
