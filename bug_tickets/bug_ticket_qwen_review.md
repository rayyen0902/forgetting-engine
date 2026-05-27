## 工单：千问代码审查发现（P0×3 + P1×5）

> 审查模型：qwen3.6-plus | 审查范围：主引擎全部 9 个文件 | 发现时间：2026-05-27

---

### P0-1：`_batch_descend` 原地修改父 trace 的 layer，破坏类型契约

**位置**：`engine.py` `_batch_descend` 方法内

**现象**：将 L0 trace 的 `trace.layer` 直接改为 L1。父 trace 的 `content` 仍是 `L0_RawMessage`，但 layer 标记是 L1，类型不一致。导致：
- `render_for_injection` 靠 `t.layer == Layer.L0` 过滤「当前对话」，被改 layer 的 trace 永久丢失
- 下一轮 `decay_cycle` 按 L1 重新扫描，可能重复压缩

**修复方案**：不修改父 trace 的 layer。父 trace 调用 `_soft_delete` 归档，只让新建的 child 承载新层级数据。

```python
# 不要
for t in traces:
    t.layer = to_layer

# 改为
for t in traces:
    self._soft_delete(rt, t)
```

---

### P0-2：`_compress_L2_to_L3` 返回值类型与调用方不匹配

**位置**：`engine.py` `_descend` + `_compress_L2_to_L3`

**现象**：`_compress_L2_to_L3` 返回 `list[L3_Fact]`，但 `_descend` 当单对象传给 `_create_child_trace`。导致 child 的 content 是 `list` 而不是 `L3_Fact`，后续 `render_for_injection` 中 `isinstance(fact, L3_Fact)` 永远 False，L3 事实记忆无法注入。

**修复方案 A（一对一）**：`_compress_L2_to_L3` 改为返回单个 `L3_Fact`，取置信度最高或第一个。

**修复方案 B（一对多）**：对返回的 list 循环创建多个 child trace：

```python
facts = self._compress_L2_to_L3(rt, pattern_list)
for fact in facts:
    child = self._create_child_trace(rt, trace, Layer.L3, fact)
    children.append(child)
```

---

### P0-3：容量触发调用了不存在的 `trace.m_since_born()` 方法

**位置**：`engine.py:_maybe_trigger_capacity_check`

**现象**：`active.sort(key=lambda t: t.m_since_born(current) ...)` — `MemoryTrace` 虽然定义了 `m_since_born(self, now)` 但实际上这个方法名是 `m_since_born` 且接受 now 参数，而这里传入的是 `current`。检查确认 `MemoryTrace` 类上确实有 `m_since_born` 方法（接受 `now` 参数），这里调用 `t.m_since_born(current)` 实际上是合法的。校验确认：此方法存在且签名匹配，**此条为千问误判，撤销**。

**复核结果**：`models.py:81` 定义了 `def m_since_born(self, now: TimePosition) -> int:`，调用 `t.m_since_born(current)` 合法。此条关闭。

---

### P1-1：显式记忆指令未做内容提取，"记住/别忘了" 判定可能失效

**位置**：`engine.py:_init_retain_conditions` 中 RetainCondition "显式记忆指令"

**问题**：`evaluate=lambda t, ctx: _text_contains_any(t.content, ["记住",...])` — `t.content` 是各层结构化对象（`L0_RawMessage` 等），直接传给 `_text_contains_any`。检查 `_text_contains_any` 内部：它调用 `_extract_text(content)` 提取字符串再检查。而 `_extract_text` 对 `L0_RawMessage` 返回 `.text`、对 `L1_Episode` 返回 `predicate` + `outcome`，等等。所以这条路径实际是安全的，因为 `_text_contains_any` 内部已做提取。

**复核结果**：`utils.py` 中 `_text_contains_any` 内部调用了 `_extract_text`，实际不会出错。此条关闭。

---

### P1-2：GC 硬删除使用 `wall_clock_born < cutoff`，近期遗忘无法回收

**位置**：`engine.py:gc` 方法

**问题**：当前双条件是 `deleted_at >= 1v` **且** `wall_clock_born < 90天前`。这意味着如果一条 trace 1 天内产生并被遗忘，要等 90 天才能被 GC 物理删除，造成 trace 积压。

**修复方案**：把 AND 改为 OR。两个条件之一满足即可回收：

```python
# 改前
if (rt.clock.distance_m(t.deleted_at) >= GC_M_WINDOW
        and t.wall_clock_born < cutoff):

# 改后  
if (rt.clock.distance_m(t.deleted_at) >= GC_M_WINDOW
        or t.wall_clock_born < cutoff):
```

但需同步引入 `deleted_wall_clock` 字段防误删：刚产生就被 descend 的 trace 如果纯靠 M-Clock 判定可能误杀。折中方案为 M-Clock ≥ 1v **且**（wall_clock_born < 90天 **或** deleted_wall_clock > 7天）。

---

### P1-3：LLM 调用无 JSON 解析防御

**位置**：`engine.py` 多处 `get_llm().call(prompt).get(...)`

**问题**：假设 LLM 始终返回 `dict`。若模型返回纯文本字符串（含 markdown 包裹的 JSON），`.get()` 直接抛 `AttributeError`。

**修复方案**：封装安全解析函数，替换所有调用点：

```python
import json

def _safe_llm_json(prompt: str) -> dict:
    result = get_llm().call(prompt)
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        # 处理 "```json ... ```" 包裹
        text = result.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)
    raise ValueError(f"LLM 返回未知类型: {type(result)}")
```

---

### P1-4：`embedding.py` / `llm.py` 全局 Provider 单例违背多 Agent 隔离

**位置**：`embedding.py` 的 `set_embedding/get_embedding` 和 `llm.py` 的 `set_llm/get_llm`

**问题**：Provider 是进程级全局单例。如果 Agent A 用 Qwen、Agent B 用 OpenAI，全局 set 会互相覆盖，导致请求路由错乱。

**修复方案**：改为引擎级依赖注入：

```python
class ForgettingEngine:
    def __init__(self, embedding_provider=None, llm_provider=None):
        self._embedding = embedding_provider or StubEmbeddingProvider()
        self._llm = llm_provider or StubLLMProvider()
        ...
    
    def _call_llm(self, prompt: str) -> dict:
        return self._llm.call(prompt)
```

引擎内部所有 `get_embedding()` / `get_llm()` 改为 `self._embedding` / `self._llm`。

---

### P1-5：`__init__.py` 硬编码导入 SkincareAdapter，核心包耦合业务插件

**位置**：`forgetting_engine/__init__.py:L2`

**问题**：`from forgetting_engine.adapters.skincare import SkincareAdapter` 让核心包依赖具体的护肤适配器。这不影响运行，但违背插件化理念——如果护肤插件独立为 pip 包，核心包 import 就炸了。

**修复方案**：移除硬编码导入。插件通过 `ForgettingEngine.register_domain("skincare", SkincareAdapter)` 运行时注册，使用方自行 import 适配器即可。

```python
# 改前
from forgetting_engine.adapters.skincare import SkincareAdapter

# 改后
# 移除。改为在 __init__ 中提示注册方式：
# 使用方自行: from forgetting_engine.adapters.skincare import SkincareAdapter
#              ForgettingEngine.register_domain("skincare", SkincareAdapter)
```

---

### 总结

| 编号 | 级别 | 状态 | 说明 |
|------|------|------|------|
| P0-1 | 阻断 | **待修** | _batch_descend 改父trace layer |
| P0-2 | 阻断 | **待修** | L2→L3 返回值类型不匹配 |
| P0-3 | 阻断 | ~~关闭~~ | m_since_born 方法存在，千问误判 |
| P1-1 | 重要 | ~~关闭~~ | _text_contains_any 内部已做提取，千问误判 |
| P1-2 | 重要 | **待修** | GC AND→OR 避免内存积压 |
| P1-3 | 重要 | **待修** | LLM 返回值 JSON 防御 |
| P1-4 | 重要 | **待修** | Provider 全局单例→依赖注入 |
| P1-5 | 重要 | **待修** | __init__.py 移除硬编码 |

**实际有效：P0×2 + P1×4 = 6 个待修项**
