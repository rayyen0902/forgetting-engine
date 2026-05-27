## 工单：千问第四轮审查 — P0×3

> 审查模型：qwen3.6-plus｜第四轮｜发现时间：2026-05-27
> 3 个 P0：2 个回归 + 1 个元老级隐藏 bug

---

### P0-1：`_stitch_L1_episodes` 使用了未定义的 `rt`

**位置**：`engine.py:_stitch_L1_episodes`

**根因**：上轮修 P0-2 时把 `_layer_tag(t, t.born_at)` 改为 `_layer_tag(t, rt.clock)`，但方法内没有 `rt` 变量。运行时直接 `NameError`。

**修复方案**：方法首行加 `rt = self._rt(agent_id)`。

---

### P0-2：`_descend` L2→L3 先软删除再改 layer，产生僵尸 trace

**位置**：`engine.py:_descend` L2→L3 分支

**根因**：上轮修 P1 时在 L2→L3 末尾加了 `self._soft_delete(rt, trace)`，但之后的 `trace.layer = new_layer` 仍在执行。导致 trace 同时满足 `deleted_at != None` 且 `layer == Layer.L3`，变成 GC 和 decay_cycle 都处理不了的僵尸。

**修复方案**：`_soft_delete` 之后 `return`，不执行后续 `trace.layer = new_layer`。

```python
if old_layer == Layer.L2:
    facts = self._compress_L2_to_L3(rt, [trace.content])
    for fact in facts:
        child = self._create_child_trace(...)
        rt.traces[child.id] = child
        trace.child_trace_ids.append(child.id)
    self._soft_delete(rt, trace)
    return  # ← 不加这行就会执行下面的 trace.layer = new_layer
```

---

### P0-3：容量触发淘汰方向反了——该留的走了，该走的留了

**位置**：`engine.py:_maybe_trigger_capacity_check`

**根因**：

```python
active.sort(key=lambda t:
    t.m_since_born(current)
    * (1.0 - t.retention(current))
    * (1.0 - t.significance),
    reverse=True,   # 高分 = 老 + 忘得多 + 不重要 = 最该淘汰 → 排前面
)
overflow = active[int(limit * 0.7):]  # 却切了后 30% = 最新 + 记得牢 + 最重要 = 最不该淘汰的
```

排序把「最该淘汰」排到最前面，但切片切的是最后面 30%，等于把「最不该淘汰」的干掉了，把「最该淘汰」的留下了。逻辑完全反了。

**修复方案**：

```python
# 改后
active.sort(key=lambda t:
    t.m_since_born(current)
    * (1.0 - t.retention(current))
    * (1.0 - t.significance),
    reverse=True,
)
# 取前 30%（最该淘汰的），不是后 30%
overflow_count = max(1, len(active) - limit)
for v in active[-overflow_count:]:  # 或 active[limit:]
    self._batch_descend(...)
```

或者简化：不排序、不切百分比，直接取超出 limit 的那部分按得分最低的淘汰。核心是在 `reverse=True` 的前提下，淘汰**头部**不是尾部。

---

### 验证

```bash
cd /Users/caopinggege/Desktop/forgetting-engine
.venv/bin/python -m pytest tests/ -v
```
