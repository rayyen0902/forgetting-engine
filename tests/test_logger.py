"""Tests for EngineLogger."""

import pytest

from forgetting_engine import EngineLog, EngineLogger, TimePosition
from forgetting_engine.utils import generate_id, now


class TestEngineLogger:
    def test_append_and_recent(self):
        logger = EngineLogger(capacity=100)
        for i in range(5):
            logger.append(
                EngineLog(
                    id=generate_id(),
                    time=TimePosition.from_m(i),
                    wall_clock=now(),
                    operation="ingest",
                    trace_ids=[f"t{i}"],
                    detail=f"Ingested message {i}",
                )
            )
        assert len(logger) == 5
        recent = logger.recent(3)
        assert len(recent) == 3
        assert recent[-1].trace_ids == ["t4"]

    def test_capacity_enforcement(self):
        logger = EngineLogger(capacity=3)
        for i in range(5):
            logger.append(
                EngineLog(
                    id=generate_id(),
                    time=TimePosition.from_m(i),
                    wall_clock=now(),
                    operation="ingest",
                    trace_ids=[f"t{i}"],
                    detail=f"msg {i}",
                )
            )
        assert len(logger) == 3
        # Oldest entries should be dropped
        assert logger.buffer[0].trace_ids == ["t2"]

    def test_by_trace(self):
        logger = EngineLogger()
        logger.append(
            EngineLog(
                id="log1",
                time=TimePosition(),
                wall_clock=now(),
                operation="ingest",
                trace_ids=["t1", "t2"],
                detail="two traces",
            )
        )
        logger.append(
            EngineLog(
                id="log2",
                time=TimePosition(),
                wall_clock=now(),
                operation="decay",
                trace_ids=["t1"],
                detail="one trace",
            )
        )
        logger.append(
            EngineLog(
                id="log3",
                time=TimePosition(),
                wall_clock=now(),
                operation="ingest",
                trace_ids=["t3"],
                detail="other trace",
            )
        )

        t1_logs = logger.by_trace("t1")
        assert len(t1_logs) == 2

        t3_logs = logger.by_trace("t3")
        assert len(t3_logs) == 1

        t99_logs = logger.by_trace("t99")
        assert len(t99_logs) == 0

    def test_by_operation(self):
        logger = EngineLogger()
        for i in range(5):
            logger.append(
                EngineLog(
                    id=generate_id(),
                    time=TimePosition(),
                    wall_clock=now(),
                    operation="ingest",
                    trace_ids=[f"t{i}"],
                    detail="ingest",
                )
            )
        for i in range(3):
            logger.append(
                EngineLog(
                    id=generate_id(),
                    time=TimePosition(),
                    wall_clock=now(),
                    operation="decay",
                    trace_ids=[f"d{i}"],
                    detail="decay",
                )
            )

        ingest_logs = logger.by_operation("ingest")
        assert len(ingest_logs) == 5

        decay_logs = logger.by_operation("decay")
        assert len(decay_logs) == 3

        gc_logs = logger.by_operation("gc")
        assert len(gc_logs) == 0

    def test_metrics_stored(self):
        logger = EngineLogger()
        logger.append(
            EngineLog(
                id="log1",
                time=TimePosition(),
                wall_clock=now(),
                operation="ingest",
                trace_ids=["t1"],
                detail="test",
                metrics={"connectivity": 3, "lambda": 0.02},
                decision="retained",
            )
        )
        entry = logger.recent(1)[0]
        assert entry.metrics == {"connectivity": 3, "lambda": 0.02}
        assert entry.decision == "retained"
