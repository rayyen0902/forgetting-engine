## 工单：Trace 持久化到 PostgreSQL

> 优先级：P0 | 分支：同时修 main（v0.1）和 v0.2-dev
> 背景：当前 trace 全在内存 dict，服务器重启全部丢失。线上 HuFu 同样受影响。

---

### 1. 建表 DDL

追加到 `001_initial_schema.up.sql`：

```sql
CREATE TABLE IF NOT EXISTS traces (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    api_key         TEXT NOT NULL,
    layer           INT NOT NULL DEFAULT 0,
    content         JSONB NOT NULL,
    born_at_m       INT NOT NULL,
    wall_clock_born TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lambda_         REAL NOT NULL DEFAULT 0.02,
    access_count    INT NOT NULL DEFAULT 0,
    significance    REAL NOT NULL DEFAULT 0.0,
    retained_by     TEXT[] DEFAULT '{}',
    deleted         BOOLEAN NOT NULL DEFAULT FALSE,
    parent_ids      TEXT[] DEFAULT '{}',
    child_ids       TEXT[] DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_traces_agent ON traces(api_key, agent_id);
CREATE INDEX IF NOT EXISTS idx_traces_layer ON traces(api_key, agent_id, layer) WHERE NOT deleted;
```

### 2. 新增 TraceRepo（`forgetting_engine/trace_repo.py`）

四个方法，操作 PostgreSQL：

| 方法 | SQL | 调用时机 |
|------|-----|----------|
| `insert(trace, agent_id, api_key)` | INSERT | ingest 后 |
| `update(trace)` | UPDATE layer, significance, retained_by, deleted | decay_cycle 每轮结束后 |
| `load(api_key, agent_id)` → list[dict] | SELECT | 引擎启动恢复 |
| `delete(trace_id)` | DELETE | GC 物理删除 |

content 字段用 JSONB，按 `L0_RawMessage` / `L1_Episode` / `L2_Pattern` / `L3_Fact` 序列化，带 `__type` 标记。

### 3. 引擎改动（`forgetting_engine/engine.py`）

5 处改动：

- `__init__` 加参数 `trace_repo: TraceRepo | None = None`
- `ingest()` 末尾加 `_repo.insert(trace, agent_id, api_key)`
- `decay_cycle()` 每个 agent 循环结束后遍历 `rt.traces`，对变更过的 trace 调 `_repo.update(trace)`
- `gc()` 物理删除时调 `_repo.delete(tid)`
- 新增 `restore_all_agents(repo)` — 从 DB 加载所有 agent 的 traces 回内存（引擎启动时调用）

### 4. gRPC 服务端改动

- `grpc_server.py`：`ForgettingEngine(trace_repo=TraceRepo(DATABASE_URL))`
- 启动时调 `engine.restore_all_agents(trace_repo)`

### 验证

```bash
python -m pytest tests/ -q
```
