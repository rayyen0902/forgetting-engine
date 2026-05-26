"""Forgetting Engine — Agent memory middleware.

Forget by default, remember as exception.
Multi-agent shared engine, independent M-Clock, domain-pluggable.
"""

from forgetting_engine.domain_adapter import DefaultAdapter, DomainAdapter
from forgetting_engine.embedding import (
    EmbeddingProvider,
    StubEmbeddingProvider,
    get_embedding,
    set_embedding,
)
from forgetting_engine.engine import ForgettingEngine
from forgetting_engine.llm import (
    LLMProvider,
    StubLLMProvider,
    get_llm,
    set_llm,
)
from forgetting_engine.logger import EngineLog, EngineLogger
from forgetting_engine.models import (
    Cue,
    DecayCurve,
    DecayReport,
    EngineContext,
    FactField,
    L0_RawMessage,
    L1_Episode,
    L2_Pattern,
    L3_Fact,
    Layer,
    MemoryTrace,
    RetainCondition,
    RetrievalContext,
)
from forgetting_engine.time_position import TimePosition

__all__ = [
    # Engine
    "ForgettingEngine",
    # Domain
    "DomainAdapter",
    "DefaultAdapter",
    # Models
    "TimePosition",
    "MemoryTrace",
    "DecayCurve",
    "Layer",
    "L0_RawMessage",
    "L1_Episode",
    "L2_Pattern",
    "L3_Fact",
    "RetainCondition",
    "EngineContext",
    "Cue",
    "RetrievalContext",
    "DecayReport",
    "FactField",
    # Logger
    "EngineLog",
    "EngineLogger",
    # Providers
    "LLMProvider",
    "StubLLMProvider",
    "get_llm",
    "set_llm",
    "EmbeddingProvider",
    "StubEmbeddingProvider",
    "get_embedding",
    "set_embedding",
]
