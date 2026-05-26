"""复现压缩管线两个 P0 Bug。修复前全部 FAIL，修复后全部 PASS。

Bug 1: _compress_L1_to_L2 永远返回空列表
Bug 2: _compress_L0_to_L1 只接受单消息，拒绝批量调用
"""

import pytest
from forgetting_engine import (
    ForgettingEngine,
    L0_RawMessage,
    L1_Episode,
    TimePosition,
)
from forgetting_engine.utils import now


# ============================================================
# Bug 1: _compress_L1_to_L2 空实现
# ============================================================

class TestBug1_L1toL2Compression:
    """Bug 1: _compress_L1_to_L2 永远返回空列表"""

    def test_l1_to_l2_produces_patterns(self, fresh_engine):
        """多个相关 L1 episode 应产出至少一个 L2 Pattern"""
        engine = fresh_engine
        engine.create_agent("agent_1", "default")

        episodes = [
            L1_Episode(
                participants=["user"],
                topic="B5修复霜使用反馈",
                action_type="report_result_positive",
                subject_entity="B5修复霜",
                predicate="每晚薄涂",
                outcome="泛红改善",
                negation=None,
                emotional_tone=0.7,
                time=TimePosition(),
                wall_clock=now(),
                embedding=[0.1] * 128,
            ),
            L1_Episode(
                participants=["user"],
                topic="B5修复霜持续反馈",
                action_type="report_result_positive",
                subject_entity="B5修复霜",
                predicate="继续使用一周",
                outcome="泛红完全消退",
                negation=None,
                emotional_tone=0.9,
                time=TimePosition(),
                wall_clock=now(),
                embedding=[0.15] * 128,
            ),
        ]

        rt = engine.agents["agent_1"]
        result = engine._compress_L1_to_L2(rt, episodes)
        assert isinstance(result, list), (
            f"应为 list[L2_Pattern]，实际返回 {type(result).__name__}"
        )
        assert len(result) > 0, (
            f"应为至少 1 个 L2 Pattern，实际返回 {len(result)} 个"
        )


# ============================================================
# Bug 2: _compress_L0_to_L1 拒绝批量
# ============================================================

class TestBug2_L0toL1BatchCompression:
    """Bug 2: _compress_L0_to_L1 只接受单消息"""

    def test_l0_to_l1_accepts_message_list(self, fresh_engine):
        """_compress_L0_to_L1 应接受 list[L0_RawMessage]"""
        engine = fresh_engine
        engine.create_agent("agent_1", "default")
        rt = engine.agents["agent_1"]

        messages = [
            L0_RawMessage(
                role="user", text="我T区很油",
                time=TimePosition(), wall_clock=now(), session_id="s1",
            ),
            L0_RawMessage(
                role="agent", text="你是混合性肤质",
                time=TimePosition(), wall_clock=now(), session_id="s1",
            ),
        ]

        try:
            result = engine._compress_L0_to_L1(rt, messages)
        except TypeError as e:
            pytest.fail(
                f"_compress_L0_to_L1 应接受 list[L0_RawMessage]，"
                f"当前签名拒绝批量调用：{e}"
            )

        assert isinstance(result, L1_Episode), (
            f"批量压缩应返回 L1_Episode，实际 {type(result).__name__}"
        )
        assert result.participants, "应提取出参与者"
