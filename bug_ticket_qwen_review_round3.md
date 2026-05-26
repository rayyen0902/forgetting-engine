## 工单：千问第三轮审查 — P0×3（新增，前两轮未报过）

> 审查模型：qwen3.6-plus｜第三轮｜发现时间：2026-05-27
> 前两轮已覆盖的重复问题不再列入

---

### P0-1：`_batch_descend` 类型过滤失败时父 trace 未软删除

**位置**：`engine.py:_batch_descend`

**触发条件**：`isinstance(t.content, L0_RawMessage)` 或 `isinstance(t.content, L1_Episode)` 过滤后 `messages`/`episodes` 为空

**现象**：代码跳过整个压缩块，父 trace 的 `_soft_delete` 没有执行。这些 trace 残留在活跃内存，`DecayReport` 已经计了 "descended"，实际没降级。

**修复方案**：把 `_soft_delete` 提到 `for t in traces:` 循环末尾，不管压缩是否成功都归档父节点。

```python
# 改前：_soft_delete 在 if messages: / if episodes: 块内部

# 改后
if from_layer == Layer.L0:
    messages = [t.content for t in traces if isinstance(t.content, L0_RawMessage)]
    if messages:
        episode = self._compress_L0_to_L1(rt, messages)
        child = self._create_child_trace(...)
        rt.traces[child.id] = child
        for t in traces:
            t.child_trace_ids.append(child.id)
    # 不管有没有 messages，都归档父节点
    for t in traces:
        self._soft_delete(rt, t)
```

L1→L2 分支同理。

---

### P0-2：`_stitch_L1_episodes` 时间偏移永远为 0

**位置**：`engine.py:_stitch_L1_episodes`

**现象**：

```python
self._layer_tag(t, t.born_at)
```

`_layer_tag(trace, now)` 内部用 `now.distance_m(trace.born_at)` 算偏移。但这里把 `born_at` 当作 `now` 传进去，导致 `distance_m` 永远为 0，所有 L1 标签渲染成 `[-0m]`。

**修复方案**：

```python
# 改前
self._layer_tag(t, t.born_at)

# 改后
self._layer_tag(t, rt.clock)
```

---

### P0-3：Constraint 事实 L3↔L4 无限震荡

**位置**：`engine.py:_soft_delete` + `decay_cycle`

**现象**：

1. `_soft_delete` 对 `fact_type=="constraint"` 的 L3_Fact 执行 `deleted_at=None` + `layer=Layer.L3`（复活）
2. 下一轮 `decay_cycle` 把它当正常 L3 trace 纳入衰减池
3. 跌破 L3 阈值 → 降级到 L4 → `_soft_delete` 再次复活
4. 无限循环 `L3→L4→L3→L4...`

**修复方案**：在 `decay_cycle` 收集待衰减 L3 trace 时跳过 constraint 类型。

```python
# decay_cycle 中 L3 层的遍历处
traces_in_layer = [
    t for t in rt.traces.values()
    if t.layer == layer and not t.is_deleted()
    # 加一行：
    and not (isinstance(t.content, L3_Fact) and t.content.fact_type == "constraint")
]
```

约束事实应该永久豁免衰减评估。

---

### 验证

```bash
cd /Users/caopinggege/Desktop/forgetting-engine
.venv/bin/python -m pytest tests/ -v
```

修复后 77+ 测试应全绿。
