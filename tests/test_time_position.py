"""Tests for TimePosition M-Clock."""

import pytest

from forgetting_engine import TimePosition


class TestTimePositionBasic:
    def test_default_is_zero(self):
        tp = TimePosition()
        assert tp.to_m() == 0
        assert str(tp) == "e0.v0.c0.s0.m0"

    def test_from_m_simple(self):
        tp = TimePosition.from_m(5)
        assert tp.m == 5
        assert tp.s == 0
        assert tp.to_m() == 5

    def test_from_m_with_carry(self):
        tp = TimePosition.from_m(10)
        assert tp.s == 1
        assert tp.m == 2
        assert tp.to_m() == 10

    def test_from_m_chapter(self):
        tp = TimePosition.from_m(64)
        assert tp.c == 1
        assert tp.s == 0
        assert tp.m == 0
        assert tp.to_m() == 64

    def test_from_m_volume(self):
        tp = TimePosition.from_m(512)
        assert tp.v == 1
        assert tp.c == 0
        assert tp.to_m() == 512

    def test_from_m_era(self):
        tp = TimePosition.from_m(4096)
        assert tp.e == 1
        assert tp.v == 0
        assert tp.to_m() == 4096

    def test_from_m_complex(self):
        # 4096 + 512 + 64 + 8 + 1 = 4681
        tp = TimePosition.from_m(4681)
        assert tp.e == 1
        assert tp.v == 1
        assert tp.c == 1
        assert tp.s == 1
        assert tp.m == 1
        assert tp.to_m() == 4681


class TestTimePositionOperations:
    def test_distance_m(self):
        a = TimePosition.from_m(10)
        b = TimePosition.from_m(5)
        assert a.distance_m(b) == 5
        assert b.distance_m(a) == -5

    def test_add_m(self):
        tp = TimePosition.from_m(5)
        result = tp.add_m(3)
        assert result.to_m() == 8
        assert str(result) == "e0.v0.c0.s1.m0"

    def test_add_m_across_boundaries(self):
        tp = TimePosition.from_m(0)
        result = tp.add_m(100)
        assert result.c == 1
        assert result.s == 4
        assert result.m == 4

    def test_comparison(self):
        a = TimePosition.from_m(5)
        b = TimePosition.from_m(10)
        assert a < b
        assert b > a
        assert a != b
        assert TimePosition.from_m(5) == TimePosition.from_m(5)

    def test_hash(self):
        a = TimePosition.from_m(42)
        b = TimePosition.from_m(42)
        assert hash(a) == hash(b)
        assert len({a, b}) == 1

    def test_str_representation(self):
        tp = TimePosition(e=2, v=3, c=1, s=4, m=5)
        assert str(tp) == "e2.v3.c1.s4.m5"


class TestTimePositionConstants:
    def test_m_per_s(self):
        assert TimePosition.M_PER_S == 8

    def test_m_per_c(self):
        assert TimePosition.M_PER_C == 64

    def test_m_per_v(self):
        assert TimePosition.M_PER_V == 512

    def test_m_per_e(self):
        assert TimePosition.M_PER_E == 4096

    def test_hierarchy_is_8_base(self):
        """Verify 8-base progression."""
        assert TimePosition.M_PER_S == 8
        assert TimePosition.M_PER_C == 8 * TimePosition.M_PER_S
        assert TimePosition.M_PER_V == 8 * TimePosition.M_PER_C
        assert TimePosition.M_PER_E == 8 * TimePosition.M_PER_V
