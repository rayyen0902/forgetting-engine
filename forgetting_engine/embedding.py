"""Embedding provider interface and stub implementation.

The stub uses deterministic random vectors seeded by text hash for
reproducible prototyping. Cosine similarity is real (numpy).
"""

import hashlib
import random
from abc import ABC, abstractmethod

from forgetting_engine.utils import cosine_sim


class EmbeddingProvider(ABC):
    """Abstract interface for text embedding."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Convert text to an embedding vector."""
        ...

    @abstractmethod
    def similarity(self, a: list[float], b: list[float]) -> float:
        """Compute similarity between two embedding vectors."""
        ...


class StubEmbeddingProvider(EmbeddingProvider):
    """Stub that generates deterministic pseudo-random vectors.

    Uses SHA-256 of text as random seed so the same text always
    produces the same vector. Vector dimension = 128.
    """

    DIM = 128

    def embed(self, text: str) -> list[float]:
        if not text:
            return [0.0] * self.DIM
        # Deterministic seed from text hash
        seed = int(hashlib.sha256(text.encode()).hexdigest(), 16) % (2**31)
        rng = random.Random(seed)
        vec = [rng.uniform(-1.0, 1.0) for _ in range(self.DIM)]
        # Normalize to unit vector
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def similarity(self, a: list[float], b: list[float]) -> float:
        return cosine_sim(a, b)


# Default provider
_default_provider: EmbeddingProvider = StubEmbeddingProvider()


def get_embedding() -> EmbeddingProvider:
    return _default_provider


def set_embedding(provider: EmbeddingProvider) -> None:
    global _default_provider
    _default_provider = provider


# ── Qwen (DashScope) embedding provider ──────────────────────


class QwenEmbeddingProvider(EmbeddingProvider):
    """Qwen text-embedding via DashScope compatible API.

    Environment variables:
        QWEN_API_KEY  (required)
        QWEN_MODEL    (default: text-embedding-v3)
        QWEN_API_URL  (default: https://dashscope.aliyuncs.com/compatible-mode/v1)
    """

    def __init__(self):
        import os

        self.api_key = os.getenv("QWEN_API_KEY")
        if not self.api_key:
            raise ValueError("QWEN_API_KEY environment variable is required")

        self.model = os.getenv("QWEN_EMBED_MODEL", "text-embedding-v3")
        self.api_url = os.getenv(
            "QWEN_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

    def embed(self, text: str) -> list[float]:
        import requests

        if not text:
            return []

        resp = requests.post(
            f"{self.api_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": text,
                "encoding_format": "float",
            },
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        return body["data"][0]["embedding"]

    def similarity(self, a: list[float], b: list[float]) -> float:
        return cosine_sim(a, b)
