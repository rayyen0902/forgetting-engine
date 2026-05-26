"""Core data models: MemoryTrace, DecayCurve, layer contents, auxiliary types."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from forgetting_engine.time_position import TimePosition


# ============================================================
# Layer enum
# ============================================================


class Layer(Enum):
    L0 = 0  # Raw messages
    L1 = 1  # Narrative episodes
    L2 = 2  # Behavioral patterns
    L3 = 3  # Structured facts
    L4 = 4  # Soft-deleted


# ============================================================
# DecayCurve
# ============================================================


@dataclass
class DecayCurve:
    """Forgetting curve: retention = initial * e^(-lambda * m_idle)."""

    initial: float  # Initial retention, default 1.0
    lambda_: float  # Decay rate per m
    last_access: TimePosition
    access_count: int

    def evaluate(self, now: TimePosition) -> float:
        m_idle = now.distance_m(self.last_access)
        if m_idle < 0:
            return self.initial
        return self.initial * self._exp(-self.lambda_ * m_idle)

    @staticmethod
    def _exp(x: float) -> float:
        from forgetting_engine.utils import exp_val

        return exp_val(x)


# ============================================================
# MemoryTrace
# ============================================================


@dataclass
class MemoryTrace:
    """Minimum storage unit in the forgetting engine."""

    id: str
    layer: Layer
    content: object  # L0_RawMessage | L1_Episode | L2_Pattern | L3_Fact | None
    born_at: TimePosition
    wall_clock_born: datetime

    decay_curve: DecayCurve

    connectivity_score: int = 0
    significance: float = 0.0
    retained_by: list[str] = field(default_factory=list)

    immunity_until: TimePosition | None = None

    parent_trace_ids: list[str] = field(default_factory=list)
    child_trace_ids: list[str] = field(default_factory=list)

    is_first_of_session: bool = False

    deleted_at: TimePosition | None = None
    deleted_wall_clock: datetime | None = None  # When soft-deleted (wall clock), for GC

    def m_since_born(self, now: TimePosition) -> int:
        return now.distance_m(self.born_at)

    def retention(self, now: TimePosition) -> float:
        return self.decay_curve.evaluate(now)

    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __hash__(self) -> int:
        return hash(self.id)


# ============================================================
# Layer content types
# ============================================================


@dataclass
class L0_RawMessage:
    role: str  # "user" | "agent" | "system"
    text: str
    time: TimePosition
    wall_clock: datetime
    session_id: str


@dataclass
class L1_Episode:
    participants: list[str]
    topic: str
    action_type: str
    subject_entity: str
    predicate: str
    outcome: str
    negation: str | None
    emotional_tone: float  # -1.0 ~ 1.0
    time: TimePosition
    wall_clock: datetime
    embedding: list[float]
    domain_tags: dict = field(default_factory=dict)  # Domain-specific metadata


@dataclass
class L2_Pattern:
    type: str  # "frequency" | "contrast" | "cascade" (extensible by domain adapters)
    description: str
    confidence: float  # 0.0 ~ 1.0
    source_episode_ids: list[str]
    evidence_count: int
    last_observed_at: TimePosition


@dataclass
class L3_Fact:
    key: str
    value: object
    fact_type: str  # "identity" | "preference" | "constraint" | "transient"
    sentence: str  # Natural language description from LLM
    confidence: float
    source_pattern_ids: list[str]
    last_updated_at: TimePosition


# ============================================================
# RetainCondition
# ============================================================


@dataclass
class RetainCondition:
    """Hit → retention reset to 1.0, immune for immunity_m."""

    name: str
    priority: int
    evaluate: object  # Callable[[MemoryTrace, EngineContext], bool]
    immunity_m: int


# ============================================================
# EngineContext
# ============================================================


@dataclass
class EngineContext:
    trace: MemoryTrace
    engine: object  # ForgettingEngine (forward ref)
    now: TimePosition
    agent_id: str


# ============================================================
# RetrievalContext
# ============================================================


@dataclass
class Cue:
    type: str  # "entity" | "topic" | "action" | "emotion"
    value: str
    weight: float  # 0.0 ~ 1.0


@dataclass
class RetrievalContext:
    current_session_id: str
    recent_messages: list[str]
    cues: list[Cue]
    domain_hints: dict
    current_m: int = 0  # Engine clock in m, set by retrieve()


# ============================================================
# DecayReport
# ============================================================


@dataclass
class DecayReport:
    retained: int = 0
    descended: dict[Layer, int] = field(default_factory=lambda: defaultdict(int))
    deleted: int = 0


# ============================================================
# FactField
# ============================================================


@dataclass
class FactField:
    type: str
    values: list | None = None
    element: str | None = None
    key: str | None = None
    unit: str | None = None
    min: int | None = None
    max: int | None = None
