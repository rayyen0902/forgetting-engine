"""EngineLogger: ring-buffer operation log for the forgetting engine."""

from dataclasses import dataclass, field
from datetime import datetime

from forgetting_engine.snapshot import TraceSnapshot, snapshots_to_csv
from forgetting_engine.time_position import TimePosition


@dataclass
class EngineLog:
    """Single operation log entry covering all data windows."""

    id: str
    time: TimePosition
    wall_clock: datetime
    operation: str  # "ingest" | "decay" | "descend" | "compress" | "retrieve" | "inject" | "gc" | "retain" | "agent"
    trace_ids: list[str]
    detail: str
    metrics: dict = field(default_factory=dict)
    decision: str = ""


class EngineLogger:
    """Ring-buffer logger. Keeps last N entries."""

    def __init__(self, capacity: int = 10000):
        self.buffer: list[EngineLog] = []
        self.capacity = capacity
        self.snapshots: list[TraceSnapshot] = []
        self._snapshot_round: dict[str, int] = {}  # agent_id → current round number

    def snapshot_round_next(self, agent_id: str) -> int:
        """Get next round number for an agent (auto-increment)."""
        r = self._snapshot_round.get(agent_id, 0)
        self._snapshot_round[agent_id] = r + 1
        return r

    def append(self, entry: EngineLog) -> None:
        self.buffer.append(entry)
        if len(self.buffer) > self.capacity:
            self.buffer = self.buffer[-self.capacity :]

    def recent(self, n: int = 50) -> list[EngineLog]:
        return self.buffer[-n:]

    def by_trace(self, trace_id: str) -> list[EngineLog]:
        """Trace the full lifecycle of a trace by ID."""
        return [e for e in self.buffer if trace_id in e.trace_ids]

    def by_operation(self, op: str, n: int = 20) -> list[EngineLog]:
        return [e for e in self.buffer if e.operation == op][-n:]

    def to_csv(self, path: str) -> int:
        """Export all snapshots to CSV. Returns number of rows written."""
        snapshots_to_csv(self.snapshots, path)
        return len(self.snapshots)

    def __len__(self) -> int:
        return len(self.buffer)
