## 工单：千问第二轮审查 — P0×3 + P1×1

> 审查模型：qwen3.6-plus｜第二轮（增量审查）｜发现时间：2026-05-27
> 第一轮 6 个 Bug 已修复，本轮为新发现

---

### P0-1：`decay_cycle` 遍历停用 agent 时崩溃

**位置**：`engine.py:decay_cycle` → `_rt()`

**触发路径**：

```python
# 1. 业务侧停用 agent
engine.delete_agent("agent_1")

# 2. 下次全局 decay_cycle 崩溃
engine.decay_cycle()  # agent_id=None → 遍历所有 agent
```

**根因**：`decay_cycle` 对 `self.agents.keys()` 逐一调 `self._rt(aid)`，而 `_rt` 对 `is_active=False` 的 agent 直接 `raise ValueError`。任何一个 agent 被停用后，全局遗忘循环直接炸。

**修复方案**：跳过停用 agent，不抛异常。

```python
# 改前（engine.py decay_cycle 内）
for aid in targets:
    rt = self._rt(aid)       # 如果 is_active=False → 崩溃

# 改后
for aid in targets:
    rt = self.agents.get(aid)
    if rt is None or not rt.is_active:
        continue
```

---

### P0-2：`_batch_descend` L1→L2 子 ID 重复注入

**位置**：`engine.py:_batch_descend` L1→L2 分支

**触发路径**：多个 L1 episode → 聚类出 3 个 L2 pattern → 每个 pattern 循环内向父 trace 追加 child ID：

```python
for pattern in patterns:          # 假设 3 个 pattern
    child = self._create_child_trace(...)
    for t in traces:              # 内层再次遍历父 traces
        t.child_trace_ids.append(child.id)   # 每个父 trace 被 append 3 次同一个 ID
```

**根因**：嵌套循环 `for pattern:` 内 `for t in traces:` 导致每个父 trace 的 `child_trace_ids` 重复追加。

**修复方案**：先收集所有 child ID，再统一写入父 traces。

```python
child_ids = []
for pattern in patterns:
    child = self._create_child_trace(...)
    rt.traces[child.id] = child
    child_ids.append(child.id)

for t in traces:
    t.child_trace_ids.extend(child_ids)  # extend 替代嵌套 append
```

---

### P0-3：`_stitch_L1_episodes` prompt 未要求 JSON，叙事注入恒为空

**位置**：`engine.py:_stitch_L1_episodes`

**触发路径**：prompt 只写"整合为2-3句连贯的背景描述"，没要求输出 JSON → 模型返回纯文本 → `_safe_llm_json` 转 `json.loads()` 失败 → 返回 `{}` → `result.get("description", "")` 恒为空。

**根因**：prompt 只管输入格式，没管输出格式。`_safe_llm_json` 能处理 JSON 字符串，但处理不了不是 JSON 的纯文本。

**修复方案 A（推荐）**：prompt 末尾加 JSON 约束。

```python
prompt = (
    "将以下关于用户的记忆片段整合为2-3句连贯的背景描述。"
    "保留关键信息，去掉重复。不要添加不存在的信息。"
    "情绪标签仅作为语境的提示，不需要在输出中提及。\n\n"
    + "\n".join(items)
    + '\n\n返回 JSON: {"description": "整合后的文本"}'
)
```

**修复方案 B**：`_safe_llm_json` 对非 JSON 纯文本做 fallback。

```python
def _safe_llm_json(self, prompt: str) -> dict:
    result = self._llm.call(prompt)
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        text = result.strip()
        # 先尝试 json.loads
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 非 JSON 纯文本 → 包装为 {"description": text}
        return {"description": text}
    return {}
```

**两者都做最安全。**

---

### P1：`_descend` L2→L3 父 trace 未软删除

**位置**：`engine.py:_descend` L2→L3 分支

**问题**：L2→L3 生成子 L3_Fact 后，父 trace 的 `layer` 被改为 L3，但 `content` 仍是 `L2_Pattern`。类型不一致。且 L0→L1、L1→L2 的父 trace 都已改为软删除，L2→L3 没跟上。

**修复方案**：生成子 trace 后对父 trace 执行软删除，与 L0→L1、L1→L2 行为对齐。

```python
# _descend 的 L2→L3 分支末尾
for fact in facts:
    child = self._create_child_trace(...)
    rt.traces[child.id] = child
    trace.child_trace_ids.append(child.id)

self._soft_delete(rt, trace)  # 加这一行
```

---

### 验证方式

```bash
cd /Users/caopinggege/Desktop/forgetting-engine
.venv/bin/python -m pytest tests/ -v
```

修复后 77+ 测试应全绿。
