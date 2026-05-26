"""Shared test fixtures."""

import pytest

from forgetting_engine import (
    Cue,
    DefaultAdapter,
    ForgettingEngine,
    L0_RawMessage,
    RetrievalContext,
    TimePosition,
)
from forgetting_engine.utils import generate_id, now


@pytest.fixture
def fresh_engine():
    """An engine with no agents."""
    return ForgettingEngine()


@pytest.fixture
def engine_with_default_agent(fresh_engine):
    """An engine with one default agent ready to use."""
    fresh_engine.create_agent("agent_1", "default")
    return fresh_engine


@pytest.fixture
def sample_message():
    """A sample user message."""
    return L0_RawMessage(
        role="user",
        text="你好，我最近皮肤很油，应该用什么产品？",
        time=TimePosition(),
        wall_clock=now(),
        session_id="s1",
    )


@pytest.fixture
def sample_context():
    """A sample retrieval context."""
    return RetrievalContext(
        current_session_id="s1",
        recent_messages=["皮肤很油"],
        cues=[Cue(type="entity", value="油性皮肤", weight=0.8)],
        domain_hints={},
    )


@pytest.fixture
def agent_with_messages(engine_with_default_agent):
    """Agent with 5 messages ingested."""
    engine = engine_with_default_agent
    for i in range(5):
        engine.ingest(
            "agent_1",
            L0_RawMessage(
                role="user" if i % 2 == 0 else "agent",
                text=f"消息 {i}：护肤咨询",
                time=TimePosition(),
                wall_clock=now(),
                session_id="s1",
            ),
        )
    return engine
