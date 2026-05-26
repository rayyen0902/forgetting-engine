"""Tests for data models: DecayCurve, MemoryTrace, L3_Fact."""

import math

import pytest

from forgetting_engine import (
    DecayCurve,
    L0_RawMessage,
    L3_Fact,
    Layer,
    MemoryTrace,
    TimePosition,
)
from forgetting_engine.utils import now


class TestDecayCurve:
    def test_retention_at_creation(self):
        tp = TimePosition()
        curve = DecayCurve(
            initial=1.0, lambda_=0.02, last_access=tp, access_count=0
        )
        assert curve.evaluate(tp) == pytest.approx(1.0)

    def test_retention_decays_over_time(self):
        tp = TimePosition()
        curve = DecayCurve(
            initial=1.0, lambda_=0.02, last_access=tp, access_count=0
        )
        future = tp.add_m(50)
        expected = math.exp(-0.02 * 50)
        assert curve.evaluate(future) == pytest.approx(expected, rel=1e-6)

    def test_retention_after_reconsolidation(self):
        tp = TimePosition()
        curve = DecayCurve(
            initial=1.0, lambda_=0.02, last_access=tp, access_count=0
        )
        # After 30m, retention has decayed
        mid = tp.add_m(30)
        mid_ret = curve.evaluate(mid)
        assert mid_ret < 1.0

        # Reset with reconsolidation
        curve.last_access = mid
        curve.initial = 1.0
        assert curve.evaluate(mid) == pytest.approx(1.0)

    def test_different_lambda_rates(self):
        tp = TimePosition()
        fast = DecayCurve(initial=1.0, lambda_=0.1, last_access=tp, access_count=0)
        slow = DecayCurve(initial=1.0, lambda_=0.01, last_access=tp, access_count=0)
        future = tp.add_m(20)

        assert fast.evaluate(future) < slow.evaluate(future)

    def test_negative_idle_returns_initial(self):
        tp = TimePosition.from_m(50)
        curve = DecayCurve(
            initial=1.0, lambda_=0.02, last_access=tp, access_count=0
        )
        past = TimePosition.from_m(40)
        assert curve.evaluate(past) == pytest.approx(1.0)


class TestMemoryTrace:
    def test_new_trace_not_deleted(self):
        tp = TimePosition()
        trace = MemoryTrace(
            id="t1",
            layer=Layer.L0,
            content=None,
            born_at=tp,
            wall_clock_born=now(),
            decay_curve=DecayCurve(
                initial=1.0, lambda_=0.02, last_access=tp, access_count=0
            ),
        )
        assert not trace.is_deleted()
        assert trace.deleted_at is None

    def test_trace_retention_delegates(self):
        tp = TimePosition()
        trace = MemoryTrace(
            id="t1",
            layer=Layer.L0,
            content=None,
            born_at=tp,
            wall_clock_born=now(),
            decay_curve=DecayCurve(
                initial=1.0, lambda_=0.02, last_access=tp, access_count=0
            ),
        )
        future = tp.add_m(50)
        assert trace.retention(future) == pytest.approx(math.exp(-0.02 * 50), rel=1e-6)

    def test_m_since_born(self):
        tp = TimePosition.from_m(0)
        trace = MemoryTrace(
            id="t1",
            layer=Layer.L0,
            content=None,
            born_at=tp,
            wall_clock_born=now(),
            decay_curve=DecayCurve(
                initial=1.0, lambda_=0.02, last_access=tp, access_count=0
            ),
        )
        future = TimePosition.from_m(100)
        assert trace.m_since_born(future) == 100

    def test_soft_delete(self):
        tp = TimePosition()
        trace = MemoryTrace(
            id="t1",
            layer=Layer.L0,
            content=None,
            born_at=tp,
            wall_clock_born=now(),
            decay_curve=DecayCurve(
                initial=1.0, lambda_=0.02, last_access=tp, access_count=0
            ),
        )
        trace.deleted_at = tp.add_m(10)
        assert trace.is_deleted()


class TestL3Fact:
    def test_constraint_fact(self):
        fact = L3_Fact(
            key="intolerances",
            value=["烟酰胺"],
            fact_type="constraint",
            sentence="用户对烟酰胺不耐受",
            confidence=0.95,
            source_pattern_ids=[],
            last_updated_at=TimePosition(),
        )
        assert fact.fact_type == "constraint"
        assert fact.key == "intolerances"

    def test_fact_types(self):
        for ftype in ["identity", "preference", "constraint", "transient"]:
            fact = L3_Fact(
                key="test",
                value="val",
                fact_type=ftype,
                sentence="test fact",
                confidence=0.5,
                source_pattern_ids=[],
                last_updated_at=TimePosition(),
            )
            assert fact.fact_type == ftype


class TestLayerEnum:
    def test_layer_values(self):
        assert Layer.L0.value == 0
        assert Layer.L1.value == 1
        assert Layer.L2.value == 2
        assert Layer.L3.value == 3
        assert Layer.L4.value == 4

    def test_layer_order(self):
        assert Layer.L0.value < Layer.L1.value
        assert Layer.L1.value < Layer.L2.value
        assert Layer.L2.value < Layer.L3.value
        assert Layer.L3.value < Layer.L4.value
