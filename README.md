# 遗忘引擎（Forgetting Engine）

> 忘是默认，记住是例外。

Agent 通用记忆中间件。多 agent 共享引擎、独立 M-Clock、领域插件化。

---

## 核心概念

**不是记忆引擎，是遗忘引擎。** 所有进入的数据默认走向遗忘终点，只有满足 RetainCondition 的信息被拦截在半路。

### M-Clock（叙事时钟）

```
瞬 m (moment)   =  1m            1轮交互
幕 s (scene)    =  8m            一个话题段落
章 c (chapter)  =  64m  (8s)     一次完整会话
卷 v (volume)   =  512m (8c)     一个使用周期
纪 e (era)      = 4096m (8v)     一个关系时代
```

内部标记格式：`e0.v1.c2.s3.m4` | 注入 LLM 格式：`-2c`、`-3s`

### 四层记忆

```
L0 原始消息 → L1 叙事片段 → L2 行为模式 → L3 结构化事实 → L4 删除
```

### 遗忘三阶段

```
暂时性遗忘 → 线索唤醒（被动检索，不加入默认注入）
潜伏态     → 多线索累积激活（如 L3 需 ≥2 个线索）
彻底遗忘   → 硬删除（GC 清理）
```

---

## 架构

```
ForgettingEngine（通用）
├── 多 agent 路由（agent_id 隔离）
├── decay_cycle()（遗忘主循环）
├── ingest / retrieve / render_for_injection
├── 四层压缩（L0→L1→L2→L3）
├── RetainCondition 引擎（6条内置 + 领域追加）
└── EngineLogger（全操作日志）

DomainAdapter（插件接口）
├── action_types / similarity / fact_schema
├── danger_signals / extra_retain_conditions
└── relevance / activation_threshold
```

## 使用

```python
engine = ForgettingEngine()
ForgettingEngine.register_domain("skincare", SkincareAdapter)

agent = engine.create_agent("sk_001", "skincare")
engine.ingest(agent, L0_RawMessage(...))
traces = engine.retrieve(agent, context)
prompt = engine.render_for_injection(agent, traces, context)
```

## 落地形态

- 语言：Python（原型/开源） → Rust（商用）
- 部署：gRPC 服务
- 存储：PostgreSQL + pgvector

---

## 目录

```
forgetting-engine/
├── forgetting_engine.pseudo    # 完整伪代码（当前设计阶段）
├── SESSION_SUMMARY.md          # 会话摘要
├── Holographic/                # Hermes 原始记忆方案（参考）
├── fact_repo.go                # 肤小护 Go 实现（参考）
├── 001_initial_schema.up.sql   # 肤小护 schema（参考）
└── memory/                     # Claude 会话记忆
```

## 许可

MIT
