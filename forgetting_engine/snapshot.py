"""Trace lifecycle snapshot — per-round state capture for data analysis."""

import csv
from dataclasses import dataclass


@dataclass
class TraceSnapshot:
    """Single trace state at a point in time (one decay_cycle round)."""

    round: int            # decay_cycle round number
    agent_id: str         # which agent
    trace_id: str         # which trace
    layer: int            # Layer.value
    retention: float      # current retention at snapshot time
    significance: float   # 0.0 ~ 1.0
    born_at_m: int        # born_at.to_m()
    m_since_born: int     # clock distance from born_at
    deleted: bool         # is_deleted()
    retained_by: str      # condition name(s), empty if none

    CSV_HEADER = [
        "round", "agent_id", "trace_id", "layer", "retention",
        "significance", "born_at_m", "m_since_born", "deleted", "retained_by",
    ]

    def to_row(self) -> list:
        return [
            self.round, self.agent_id, self.trace_id, self.layer,
            f"{self.retention:.6f}", f"{self.significance:.4f}",
            self.born_at_m, self.m_since_born,
            str(self.deleted), self.retained_by,
        ]


def snapshots_to_csv(snapshots: list[TraceSnapshot], path: str) -> None:
    """Write all snapshots to a CSV file."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(TraceSnapshot.CSV_HEADER)
        for s in snapshots:
            w.writerow(s.to_row())
