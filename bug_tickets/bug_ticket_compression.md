## 工单：主引擎压缩管线两个阻断性 Bug

> 发现时间：2026-05-27 | 来源：代码验收 | 优先级：P0
> 已排除：原 Bug 2（L3→L4 转层）经复现用例验证，`trace.layer = new_layer` 无条件执行，L4 路径正常。误判已撤销。

---

### Bug 1：`_compress_L1_to_L2` 空实现，L1→L2 压缩不可用

**位置**：`forgetting_engine/engine.py:420-426`

**现象**：方法直接 `return []`，导致 L1→L2 压缩路径完全无输出。引擎无法产生任何 L2 Pattern。

**修复方向**：
- 方法签名应接收 `list[L1_Episode]` 而非单个 `L1_Episode`
- 实现三种 induction 策略：`_cluster_by_similarity` 出 frequency、`_group_by_entity` 出 contrast、`_find_causal_chains` 出 cascade
- 参考伪代码 `forgetting_engine.pseudo:648-688`

**复现用例**（`tests/test_compression_pipeline.py::TestBug1_L1toL2Compression`，当前 FAIL）：

```python
def test_l1_to_l2_produces_patterns(self, fresh_engine):
    engine = fresh_engine
    engine.create_agent("agent_1", "default")
    episodes = [
        L1_Episode(
            participants=["user"], topic="B5修复霜使用反馈",
            action_type="report_result_positive",
            subject_entity="B5修复霜", predicate="每晚薄涂",
            outcome="泛红改善", negation=None, emotional_tone=0.7,
            time=TimePosition(), wall_clock=now(), embedding=[0.1] * 128,
        ),
        L1_Episode(
            participants=["user"], topic="B5修复霜持续反馈",
            action_type="report_result_positive",
            subject_entity="B5修复霜", predicate="继续使用一周",
            outcome="泛红完全消退", negation=None, emotional_tone=0.9,
            time=TimePosition(), wall_clock=now(), embedding=[0.15] * 128,
        ),
    ]
    rt = engine.agents["agent_1"]
    result = engine._compress_L1_to_L2(rt, episodes)
    assert len(result) > 0, f"应为至少 1 个 L2 Pattern，实际返回 {len(result)} 个"
```

---

### Bug 2：`_compress_L0_to_L1` 接收单消息而非批量

**位置**：`engine.py:386-418`

**现象**：方法签名 `_compress_L0_to_L1(self, rt, msg: L0_RawMessage)` 只接收一条消息。spec 设计是批量压缩同窗口的一组消息为一个 episode，保留对话上下文。

**修复方向**：
- 方法签名改为 `_compress_L0_to_L1(self, rt, messages: list[L0_RawMessage])`
- 调整 `_descend()` 调用侧，将同窗口 L0 traces 收集后批量传入
- LLM prompt 中逐条列出消息

**复现用例**（`tests/test_compression_pipeline.py::TestBug2_L0toL1BatchCompression`，当前 FAIL）：

```python
def test_l0_to_l1_accepts_message_list(self, fresh_engine):
    engine = fresh_engine
    engine.create_agent("agent_1", "default")
    rt = engine.agents["agent_1"]
    messages = [
        L0_RawMessage(role="user", text="我T区很油",
            time=TimePosition(), wall_clock=now(), session_id="s1"),
        L0_RawMessage(role="agent", text="你是混合性肤质",
            time=TimePosition(), wall_clock=now(), session_id="s1"),
    ]
    try:
        result = engine._compress_L0_to_L1(rt, messages)
    except TypeError as e:
        pytest.fail(f"应接受 list[L0_RawMessage]，当前签名拒绝：{e}")
    assert isinstance(result, L1_Episode)
    assert result.participants, "应提取出参与者"
```

---

### 验证方式

```bash
cd /Users/caopinggege/Desktop/forgetting-engine
.venv/bin/python -m pytest tests/test_compression_pipeline.py -v
```

**当前预期**：2 FAILED。**修复后预期**：2 PASSED。
