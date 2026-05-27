## 回执：bug_ticket_skincare_adapter.md

> 实现日期：2026-05-27
> 规格依据：`forgetting_engine.pseudo:1325-2052`

---

### 交付文件

```
forgetting_engine/adapters/
├── __init__.py          # 导出 SkincareAdapter
└── skincare.py          # SkincareAdapter + 4 辅助类（~530 行）

tests/
└── test_skincare_adapter.py  # 9 测试类 / 60 用例
```

### 改动现有文件（2 处）

| 文件 | 改动 | 原因 |
|------|------|------|
| `forgetting_engine/models.py:190` | `RetrievalContext` 新增 `current_m: int = 0` | 设计决策 #3：修复 relevance() 时间计算 placeholder bug |
| `forgetting_engine/engine.py:710` | `retrieve()` 新增 `context.current_m = current.to_m()` | 为 adapter 提供当前引擎时钟 |

---

### 任务清单对照

| 任务 | 状态 | 说明 |
|------|------|------|
| SKINCARE_ACTION_TYPES | done | 30 种，含 7 个宪章类型 |
| SKINCARE_DANGER_SIGNALS | done | **54 个**（非工单写的 45，伪代码实际条目 54） |
| SKINCARE_FACT_SCHEMA | done | identity/preference/constraint/风险档案 四类 |
| SkincareAdapter (7 方法) | done | action_types / fact_schema / danger_signals / activation_threshold / similarity / relevance / extra_retain_conditions |
| 实体抽取 | done | `_ENTITY_PATTERNS` + `_extract_skincare_entities` + `_jaccard` |
| SkincareL1Compressor | done | `post_process()` → `domain_tags{"trial_start", "entities"}` |
| SkincareL2InductionStrategy | done | `extract_product_effect_pairs` / `extract_ingredient_reactions` / `extract_cyclical_patterns` |
| SkincareConflictDetector | done | `check_fact_vs_new_claim()` — 区分矛盾 vs 建立耐受 |
| SkincareInjectionFormatter | done | `format_skin_profile()` — 身份/禁忌/偏好三段式 |

---

### 4 条设计决策处理情况

| # | 决策 | 处理 |
|---|------|------|
| 1 | `L1_Episode.domain_tags` 替代 `is_trial_start` | `SkincareL1Compressor.post_process()` 写入 `domain_tags["trial_start"]` |
| 2 | `L2_Pattern.type` 领域专属值（product_effect/ingredient_reaction/cyclical） | 辅助类直接使用，注释标注为合法扩展 |
| 3 | `relevance()` 时间计算 bug（`trace.m_since_born(trace.born_at)` 永远为 0） | 修复：`RetrievalContext` 加 `current_m`，引擎 `retrieve()` 设值，adapter 用 `context.current_m - trace.born_at.to_m()` |
| 4 | 反馈链 condition 的 `source_episode_ids` 类型错误 | 实现时仅检查 `type == "cascade"` + `confidence >= 0.6`，不迭代 ID 列表 |

---

### 测试结果

```
tests/test_skincare_adapter.py — 60 passed
tests/test_engine.py            — 20 passed (回归)
tests/test_models.py            — 13 passed (回归)
tests/test_time_position.py     — 15 passed (回归)
tests/test_logger.py            —  5 passed (回归)
tests/test_compression_pipeline —  2 passed (回归)
---
总计 115 passed, 0 failed
```

---

### 已知偏差

**danger_signals 数量**：工单写 45 个，伪代码实际 54 个。实现按伪代码（54），测试断言 `== 54`。建议工单更新此数字。
