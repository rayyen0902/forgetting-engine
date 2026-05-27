## 工单：护肤插件审计 — P0×2 + P1×2

> 审查模型：qwen3.6-plus｜首轮覆盖插件｜发现时间：2026-05-28
> 范围：`adapters/skincare.py`、`adapters/__init__.py`

---

### P0-1：`relevance()` 关键词匹配永远为 0

**位置**：`skincare.py:relevance` 关键词计分段

**根因**：`_extract_skincare_entities()` 返回格式为 `"category:term"`（如 `"ingredient:烟酰胺"`），但关键词匹配直接用这个带前缀的字符串去 original text 做 `in` 判断：

```python
"ingredient:烟酰胺" in "我最近在用烟酰胺精华"  # → False
```

结果 `keyword_score` 永远为 0.0，相关性评分的 0.2 权重彻底失效。

**修复方案**：

```python
# 改前
for entity in trace_entities:
    if entity.lower() in all_cue_text.lower():
        keyword_score += 0.3

# 改后：剥离前缀
for entity in trace_entities:
    term = entity.split(":", 1)[-1]  # "ingredient:烟酰胺" → "烟酰胺"
    if term.lower() in all_cue_text.lower():
        keyword_score += 0.3
```

---

### P0-2：`ConflictDetector` 约束冲突检测同样失效

**位置**：`skincare.py:ConflictDetector.check_fact_vs_new_claim`

**根因**：同 P0-1。`val.lower() in e` 用原始值匹配带前缀的实体串：

```python
"水杨酸" in "ingredient:水杨酸"  # 这个其实匹配得到
```

但反过来检查时：

```python
for val in (value if isinstance(value, list) else [value]):
    if not any(val.lower() in e for e in new_entities):
```

如果 `value` 是 `["水杨酸"]` 而 `new_entities` 是 `{"ingredient:水杨酸"}`，`"水杨酸" in "ingredient:水杨酸"` 能匹配。这个方向没问题。

但如果 `value` 是英文别名（如 `"salicylic acid"`）或缩写（如 `"A醇"` vs `"视黄醇"`），则直接漏报。

**修复方案**：统一清洗两边再匹配。

```python
# 改前
if not any(val.lower() in e for e in new_entities):

# 改后：清洗实体，去掉前缀
clean_entities = {e.split(":", 1)[-1].lower() for e in new_entities}
if not any(val.lower() in clean_entities for val in vals):
```

---

### P1-1：`L2InductionStrategy` 溯源字段用实体名代替 ID

**位置**：`skincare.py:L2InductionStrategy` 三个方法

**根因**：

```python
source_episode_ids=[e.subject_entity for e in eps]  # "B5修复霜" 不是 ID
```

`subject_entity` 是实体名称字符串，不是 episode 的全局唯一标识。导致记忆图谱溯源断裂，同名实体会被错误合并。

**修复方案**：`L1_Episode` 没有独立 `id` 字段，但它的父 `MemoryTrace` 有。需在调用方传入 trace ID 列表，或给 `L1_Episode` 加 `id` 字段。

如果调用方能传入 trace ID：

```python
# 在 L2InductionStrategy 的调用处传入 trace_id
source_episode_ids=[ep_id for ep_id in episode_ids]  # 而非 subject_entity
```

如果暂时拿不到 trace ID，在源头上给 L1_Episode 加 `episode_id` 字段（`domain_tags` 兜底）。

---

### P1-2：`similarity`/`relevance` 热路径重复获取 Embedding

**位置**：`skincare.py:similarity` + `relevance`

**问题**：每次调用都执行 `emb = get_embedding()`，在检索热路径上重复加载模型实例，造成延迟累积。

**修复方案**：加模块级缓存。

```python
_EMBEDDER = None

def _get_cached_embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = get_embedding()
    return _EMBEDDER
```

然后在 `similarity` 和 `relevance` 中：

```python
# 改前
emb = get_embedding()

# 改后
emb = _get_cached_embedder()
```

---

### 验证

```bash
cd /Users/caopinggege/Desktop/forgetting-engine
.venv/bin/python -m pytest tests/test_skincare_adapter.py -v
```

修复后 60 个插件测试应全绿。
