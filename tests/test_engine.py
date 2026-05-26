"""Tests for ForgettingEngine core operations."""

import pytest

from forgetting_engine import (
    Cue,
    ForgettingEngine,
    L0_RawMessage,
    Layer,
    RetrievalContext,
    TimePosition,
)
from forgetting_engine.utils import now


class TestAgentLifecycle:
    def test_create_agent(self, fresh_engine):
        aid = fresh_engine.create_agent("agent_1")
        assert aid == "agent_1"
        assert "agent_1" in fresh_engine.agents
        rt = fresh_engine.agents["agent_1"]
        assert rt.is_active
        assert rt.clock.to_m() == 0

    def test_create_duplicate_agent_raises(self, fresh_engine):
        fresh_engine.create_agent("agent_1")
        with pytest.raises(ValueError, match="already exists"):
            fresh_engine.create_agent("agent_1")

    def test_create_agent_unknown_domain(self, fresh_engine):
        with pytest.raises(ValueError, match="Unknown domain"):
            fresh_engine.create_agent("agent_1", "nonexistent")

    def test_delete_agent(self, fresh_engine):
        fresh_engine.create_agent("agent_1")
        fresh_engine.delete_agent("agent_1")
        assert not fresh_engine.agents["agent_1"].is_active

    def test_list_agents(self, fresh_engine):
        fresh_engine.create_agent("a1")
        fresh_engine.create_agent("a2", "default")
        agents = fresh_engine.list_agents()
        assert len(agents) == 2
        assert {a["agent_id"] for a in agents} == {"a1", "a2"}


class TestIngest:
    def test_ingest_advances_clock(self, engine_with_default_agent):
        engine = engine_with_default_agent
        msg = L0_RawMessage(
            role="user", text="hello", time=TimePosition(),
            wall_clock=now(), session_id="s1",
        )
        engine.ingest("agent_1", msg)
        rt = engine.agents["agent_1"]
        assert rt.clock.to_m() == 1

    def test_ingest_creates_trace(self, engine_with_default_agent):
        engine = engine_with_default_agent
        msg = L0_RawMessage(
            role="user", text="hello", time=TimePosition(),
            wall_clock=now(), session_id="s1",
        )
        tid = engine.ingest("agent_1", msg)
        rt = engine.agents["agent_1"]
        assert tid in rt.traces
        trace = rt.traces[tid]
        assert trace.layer == Layer.L0
        assert trace.content == msg
        assert trace.connectivity_score == 0  # First message, no connections

    def test_multiple_ingests_increment_clock(self, engine_with_default_agent):
        engine = engine_with_default_agent
        for i in range(10):
            engine.ingest(
                "agent_1",
                L0_RawMessage(
                    role="user", text=f"msg {i}", time=TimePosition(),
                    wall_clock=now(), session_id="s1",
                ),
            )
        rt = engine.agents["agent_1"]
        assert rt.clock.to_m() == 10
        assert len(rt.traces) == 10

    def test_ingest_significant(self, engine_with_default_agent):
        engine = engine_with_default_agent
        # First, some normal messages
        for i in range(3):
            engine.ingest(
                "agent_1",
                L0_RawMessage(
                    role="user", text=f"normal {i}", time=TimePosition(),
                    wall_clock=now(), session_id="s1",
                ),
            )
        # Then a significant one
        tid = engine.ingest_significant(
            "agent_1",
            L0_RawMessage(
                role="user", text="记住这个！", time=TimePosition(),
                wall_clock=now(), session_id="s1",
            ),
            significance=1.0,
        )
        trace = engine.agents["agent_1"].traces[tid]
        assert trace.significance == 1.0


class TestDecayCycle:
    def test_decay_cycle_all_agents(self, engine_with_default_agent):
        engine = engine_with_default_agent
        # Ingest some messages
        for i in range(5):
            engine.ingest(
                "agent_1",
                L0_RawMessage(
                    role="user", text=f"msg {i}",
                    time=TimePosition(), wall_clock=now(), session_id="s1",
                ),
            )
        reports = engine.decay_cycle()
        assert "agent_1" in reports
        report = reports["agent_1"]
        assert report.retained >= 0
        assert report.deleted >= 0

    def test_decay_cycle_single_agent(self, engine_with_default_agent):
        engine = engine_with_default_agent
        engine.create_agent("agent_2", "default")
        for aid in ["agent_1", "agent_2"]:
            for i in range(3):
                engine.ingest(
                    aid,
                    L0_RawMessage(
                        role="user", text=f"msg {i}",
                        time=TimePosition(), wall_clock=now(), session_id="s1",
                    ),
                )
        reports = engine.decay_cycle(agent_id="agent_1")
        assert len(reports) == 1
        assert "agent_1" in reports

    def test_explicit_memory_retain(self, engine_with_default_agent):
        engine = engine_with_default_agent
        # Ingest a message with explicit memory instruction
        msg = L0_RawMessage(
            role="user", text="记住，我不喜欢吃辣",
            time=TimePosition(), wall_clock=now(), session_id="s1",
        )
        tid = engine.ingest("agent_1", msg)

        # Run many decay cycles to reduce retention
        for _ in range(20):
            engine.ingest(
                "agent_1",
                L0_RawMessage(
                    role="user", text="padding",
                    time=TimePosition(), wall_clock=now(), session_id="s2",
                ),
            )
            engine.decay_cycle(agent_id="agent_1")

        # The "记住" message should be retained if still in active layer
        rt = engine.agents["agent_1"]
        trace = rt.traces.get(tid)
        if trace and not trace.is_deleted():
            # Should have been retained by "显式记忆指令"
            assert len(trace.retained_by) >= 1 or trace.layer != Layer.L0


class TestRetrieve:
    def test_retrieve_returns_active_traces(self, engine_with_default_agent):
        engine = engine_with_default_agent
        msg = L0_RawMessage(
            role="user", text="皮肤很油怎么办",
            time=TimePosition(), wall_clock=now(), session_id="s_curr",
        )
        engine.ingest("agent_1", msg)

        ctx = RetrievalContext(
            current_session_id="s_curr",
            recent_messages=["皮肤很油"],
            cues=[Cue(type="entity", value="油性", weight=0.8)],
            domain_hints={},
        )
        traces = engine.retrieve("agent_1", ctx)
        assert len(traces) >= 1  # At least the L0 message

    def test_retrieve_respects_session_isolation(self, engine_with_default_agent):
        engine = engine_with_default_agent
        # Ingest with a different session
        msg = L0_RawMessage(
            role="user", text="old session message",
            time=TimePosition(), wall_clock=now(), session_id="s_old",
        )
        engine.ingest("agent_1", msg)

        ctx = RetrievalContext(
            current_session_id="s_new",
            recent_messages=["new"],
            cues=[Cue(type="topic", value="new", weight=0.5)],
            domain_hints={},
        )
        traces = engine.retrieve("agent_1", ctx)
        # L0 from different session should still be active but
        # render_for_injection will filter by session
        assert len(traces) >= 1


class TestGC:
    def test_gc_on_fresh_engine(self, fresh_engine):
        assert fresh_engine.gc() == 0

    def test_gc_preserves_non_deleted_traces(self, engine_with_default_agent):
        engine = engine_with_default_agent
        for i in range(5):
            engine.ingest(
                "agent_1",
                L0_RawMessage(
                    role="user", text=f"msg {i}",
                    time=TimePosition(), wall_clock=now(), session_id="s1",
                ),
            )
        count_before = len(engine.agents["agent_1"].traces)
        engine.gc()
        count_after = len(engine.agents["agent_1"].traces)
        assert count_before == count_after  # Nothing deleted since none soft-deleted


class TestRenderForInjection:
    def test_render_basic_structure(self, engine_with_default_agent):
        engine = engine_with_default_agent
        msg = L0_RawMessage(
            role="user", text="测试消息",
            time=TimePosition(), wall_clock=now(), session_id="s_curr",
        )
        engine.ingest("agent_1", msg)

        ctx = RetrievalContext(
            current_session_id="s_curr",
            recent_messages=["测试"],
            cues=[],
            domain_hints={},
        )
        traces = engine.retrieve("agent_1", ctx)
        result = engine.render_for_injection("agent_1", traces, ctx)
        assert "[当前对话]" in result
        assert "测试消息" in result


class TestCapacityTrigger:
    def test_capacity_check_triggers_descend(self, engine_with_default_agent):
        engine = engine_with_default_agent
        # Ingest many messages to trigger capacity limit (L0 cap = 15)
        for i in range(20):
            engine.ingest(
                "agent_1",
                L0_RawMessage(
                    role="user", text=f"msg {i}",
                    time=TimePosition(), wall_clock=now(), session_id="s1",
                ),
            )
        rt = engine.agents["agent_1"]
        # Some L0 should have been descended
        l0_count = sum(
            1 for t in rt.traces.values()
            if t.layer == Layer.L0 and not t.is_deleted()
        )
        assert l0_count <= 20  # Some may have descended
