"""DomainAdapter interface and default implementation."""

from abc import ABC, abstractmethod

from forgetting_engine.models import (
    Cue,
    FactField,
    Layer,
    MemoryTrace,
    RetainCondition,
    RetrievalContext,
)
from forgetting_engine.time_position import TimePosition


class DomainAdapter(ABC):
    """Plugin interface for domain-specific behavior.

    Each domain (skincare, coding, etc.) implements this to teach the engine
    what matters in that domain.
    """

    @abstractmethod
    def action_types(self) -> list[str]:
        """Return the list of action types for this domain."""
        ...

    @abstractmethod
    def similarity(self, a: object, b: object) -> float:
        """Compute domain-specific similarity between two content objects."""
        ...

    @abstractmethod
    def fact_schema(self) -> dict[str, FactField]:
        """Return the L3 fact schema for this domain."""
        ...

    @abstractmethod
    def danger_signals(self) -> list[str]:
        """Return danger signal keywords for this domain."""
        ...

    @abstractmethod
    def extra_retain_conditions(self) -> list[RetainCondition]:
        """Return domain-specific retain conditions."""
        ...

    @abstractmethod
    def relevance(self, trace: MemoryTrace, context: RetrievalContext) -> float:
        """Compute relevance of a trace to a retrieval context."""
        ...

    @abstractmethod
    def activation_threshold(self, layer: Layer) -> float:
        """Return the activation threshold for latent trace wake-up."""
        ...

    def is_danger_signal(self, text: str) -> bool:
        return any(s in text for s in self.danger_signals())


class DefaultAdapter(DomainAdapter):
    """Minimal default adapter for generic domains."""

    def action_types(self) -> list[str]:
        return ["general", "question", "answer", "command"]

    def similarity(self, a: object, b: object) -> float:
        from forgetting_engine.embedding import get_embedding
        from forgetting_engine.utils import _extract_text

        emb = get_embedding()
        return emb.similarity(
            emb.embed(_extract_text(a)),
            emb.embed(_extract_text(b)),
        )

    def fact_schema(self) -> dict[str, FactField]:
        return {
            "topic": FactField(type="string"),
            "summary": FactField(type="string"),
        }

    def danger_signals(self) -> list[str]:
        return []

    def extra_retain_conditions(self) -> list[RetainCondition]:
        return []

    def relevance(self, trace: MemoryTrace, context: RetrievalContext) -> float:
        if trace.layer == Layer.L0:
            return 1.0
        from forgetting_engine.embedding import get_embedding
        from forgetting_engine.utils import _extract_text

        emb = get_embedding()
        trace_text = _extract_text(trace.content)
        cue_text = " ".join(c.value for c in context.cues)
        if not cue_text:
            return 0.3
        return emb.similarity(emb.embed(trace_text), emb.embed(cue_text))

    def activation_threshold(self, layer: Layer) -> float:
        return {
            Layer.L2: 0.5,
            Layer.L3: 0.5,
        }.get(layer, 0.5)
