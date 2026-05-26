## 工单：护肤插件（SkincareAdapter）编码任务

> 规格文件：`forgetting_engine.pseudo:1325-2052`（约 730 行）  
> 接口定义：`forgetting_engine/domain_adapter.py:DomainAdapter`（7 个抽象方法）  
> 基准参考：`forgetting_engine.pseudo:248-269`（DomainAdapter 接口签名）  
> 编码目录：`forgetting_engine/adapters/`

---

### 需要交付的文件

```
forgetting_engine/adapters/
├── __init__.py          # 导出 SkincareAdapter
└── skincare.py          # SkincareAdapter + 4 个辅助类
```

---

### 任务清单

#### 1. 配置常量（三个表）

**文件**：`skincare.py`

对照伪代码行号实现三个模块级常量：

| 常量 | 伪代码行号 | 说明 |
|------|-----------|------|
| `SKINCARE_ACTION_TYPES` | 1408-1449 | 30 种护肤行为类型，含 7 个宪章类型（refuse_medical_request 等） |
| `SKINCARE_DANGER_SIGNALS` | 1454-1489 | 45 个危险信号词，按 A-G 七类分组 |
| `SKINCARE_FACT_SCHEMA` | 1349-1419 | L3 事实 schema，含 identity/preference/constraint/风险档案 四类字段 |

---

#### 2. SkincareAdapter（7 个接口方法）

**文件**：`skincare.py`  
**伪代码**：1473-1648

| 方法 | 伪代码行号 | 要点 |
|------|-----------|------|
| `action_types()` | 1486-1487 | 返回 `SKINCARE_ACTION_TYPES` |
| `danger_signals()` | 1492-1493 | 返回 `SKINCARE_DANGER_SIGNALS` |
| `fact_schema()` | 1489-1490 | 返回 `SKINCARE_FACT_SCHEMA` |
| `activation_threshold()` | 1495-1503 | L2=0.35, L3=0.55, 其他=0.5 |
| `similarity(a, b)` | 1507-1521 | 实体 Jaccard ×0.45 + 语义 cosine ×0.55 |
| `relevance(trace, context)` | 1532-1596 | L0 直接返回 1.0；L1+ 综合实体/关键词/语义匹配；产品反馈类有时间加权 |
| `extra_retain_conditions()` | 1584-1648 | 7 条保留条件，优先级见注释 |

---

#### 3. 实体抽取

**伪代码行号**：1652-1730

```python
_ENTITY_PATTERNS      # 四类实体词典：ingredient/product_category/brand/skin_concern
_init_entities()       # 懒加载扁平化 _FLAT_ENTITIES
_extract_skincare_entities(text) -> set[str]
_jaccard(set_a, set_b) -> float
```

---

#### 4. 四个辅助类

**伪代码行号**：1730-1999

| 类 | 伪代码 | 职责 |
|----|--------|------|
| `SkincareL1Compressor` | 1730-1760 | L0→L1 后处理：标记产品 trial 起点（通过 `domain_tags`） |
| `SkincareL2InductionStrategy` | 1765-1900 | 三种护肤特化归纳：`extract_product_effect_pairs` / `extract_ingredient_reactions` / `extract_cyclical_patterns` |
| `SkincareConflictDetector` | 1906-1960 | L3 禁忌 vs 当前使用的矛盾检测，区分「建立耐受」 |
| `SkincareInjectionFormatter` | 1965-1999 | L3 facts → 用户档案卡片格式化 |

---

### 关键设计决策

1. `L1_Episode.domain_tags`（伪代码 121 行）替代原 `is_trial_start` 字段，用 `{"trial_start": True}` 标记
2. `L2_Pattern.type` 的领域专属值（product_effect、ingredient_reaction、cyclical）是合法扩展，通用引擎不识别但插件可用
3. `relevance()` 中的时间加权：`trace.m_since_born(trace.born_at)` 永远为 0，伪代码已标注为 placeholder，**需改为 `current.distance_m(trace.born_at)`（current 需由调用方传入或从 context 推断）**
4. extra_retain_conditions 中「反馈链保护」condition 的 evaluate 里，`source_episode_ids` 是 `list[str]`（ID 列表），不可迭代取 `.action_type`，伪代码该行有误。**实现时仅检查 `type == "cascade"` + `confidence >= 0.6`** 即可

---

### 测试要求（`tests/test_skincare_adapter.py`）

| 测试类 | 覆盖 |
|--------|------|
| `TestActionTypes` | 返回 30 个类型、含宪章 7 个 |
| `TestDangerSignals` | 返回 45 个信号、A-G 分组有关键词 |
| `TestFactSchema` | schema 含 4 类字段、风险档案 4 个 key 存在 |
| `TestSimilarity` | 同实体高相似、不同实体低相似 |
| `TestRelevance` | L0 始终 1.0、L1 匹配 cue 返回 > 0 |
| `TestActivationThreshold` | L2=0.35、L3=0.55、默认=0.5 |
| `TestExtraRetainConditions` | 7 条全部返回、过敏 condition 正确触发 |
| `TestEntityExtraction` | `_extract_skincare_entities` 识别成分/品牌/问题 |
| `TestSkincareIntegration` | ingest → retrieve → render 全链路（依赖 engine fixture） |
