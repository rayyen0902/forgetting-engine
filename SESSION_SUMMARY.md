# 遗忘引擎（Forgetting Engine）— 会话摘要

> 从肤小护项目迁移出来的独立讨论。2026-05-26。

---

## 背景

肤小护是一个护肤 AI 顾问（Go + Python + Qwen API + PostgreSQL），记忆系统有严重缺陷。

---

## 讨论进展

### 已完成设计

1. **五派方案对比** → 选定分层汇总路线
2. **记忆 vs 遗忘** → 命名反转：遗忘引擎，忘是默认、记住是例外
3. **引擎/领域分层** → 通用遗忘引擎 + DomainAdapter 插件
4. **人脑记忆映射** → 感觉/工作/情景/语义/程序 五层映射

### 维度一：触发条件（已完成）

四个并行通道：
- **时间触发** → 改为 **tick 触发**（交互密度驱动）
- **容量触发** → 工作区 7±2 上限，加权淘汰（age × retention × significance）
- **显著性触发** → 闪光灯效应 + 回溯增强（前 N 个 tick 窗口）
- **检索触发** → reconsolidation，访问时重置 decay

### 维度二：压缩算法（已完成）

四层四种格式转换：
- **L0→L1**：LLM 模板提取叙事（subject + predicate + outcome + negation）
- **L1→L2**：三种归纳策略（频率/对比/级联），领域无关
- **L2→L3**：拍扁为 identity / preference / constraint 三类事实
- **constraint 事实**：拒绝自动删除，只能人工操作

### 维度三：注入格式（待讨论）

（下一个议题）

### 关键设计决策：tick 替代 wall-clock

Agent 的时间尺度 = 交互密度，不是真实时间。
- 全局 `tick` 计数器，每次 ingest() +1
- `retention = e^(-lambda * ticks_idle)`
- 100次/1小时 和 10次/1月 的 decay 速率一致
- 真实时间仅用于：长期弃用检测（90天零交互 → 归档）、GC 双条件兜底

---

## 架构总览

```
ForgettingEngine（通用）
├── tick 计数器（全局心跳）
├── decay_cycle()（遗忘主循环）
├── ingest() / ingest_significant()
├── retrieve()（主动注入 + 被动唤醒）
├── _descend()（层级压缩）
├── _soft_delete() / gc()
└── RetainCondition 引擎（6条内置 + 领域追加）

DomainAdapter（插件接口）
├── action_types()
├── similarity()
├── fact_schema()
├── danger_signals()
├── extra_retain_conditions()
├── relevance()
└── activation_threshold()
```

---

## 文件

```
agent-memory/
├── Holographic/                  # 原始方案（参考）
├── fact_repo.go                  # 肤小护 Go 实现（参考）
├── 001_initial_schema.up.sql     # 肤小护 schema（参考）
├── forgetting_engine.pseudo      # 遗忘引擎伪代码（当前设计）
└── SESSION_SUMMARY.md
```
