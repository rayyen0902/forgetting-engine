## 工单：gRPC 接口 + 计费网关审计 — P0×2 + P1×3 + P2×3

> 审查模型：qwen3.6-plus｜发现时间：2026-05-28
> 范围：`grpc_server.py`、`billing.py`、`proto/forgetting_engine.proto`

---

### P0-1：配额扣减 TOCTOU 竞态条件

**位置**：`billing.py:check_and_deduct`

**问题**：`calls_used >= limit` 检查与 `UPDATE calls_used + 1` 分步执行。gRPC 线程池并发下，两个线程同时读到 `calls_used = 999,999`，均通过检查并 +1，配额穿透到 1,000,001。

**修复**：合并为原子 SQL：

```python
limit = tier_cfg["calls_limit"]
cur = self.conn.execute(
    "UPDATE tenants SET calls_used = calls_used + 1 WHERE api_key = ? AND calls_used < ?",
    (api_key, limit)
)
self.conn.commit()
if cur.rowcount == 0:
    raise _quota_exhausted(f"Monthly call limit reached ({limit:,}).")
```

Agent 数量检查同理改为原子 SQL。

---

### P0-2：`grpc.RpcError` 实例化方式错误

**位置**：`billing.py:_quota_exhausted` + `BillingInterceptor.intercept_service`

**问题**：`grpc.RpcError(code=..., details=...)` 不可行——它是抽象基类，不支持关键字参数实例化。拦截器 `return grpc.unary_unary_rpc_method_handler(...)` 的 handler 也会因为没法返回有效响应而崩溃。

**修复**：改为 `context.abort()` 模式。

```python
# 拦截器中，对计费方法返回专用 handler：
def _quota_handler(request, context):
    try:
        self.store.check_and_deduct(api_key, method)
    except QuotaExhaustedError as e:
        context.abort(e.code, e.details)
        return None
    return continuation(handler_call_details).unary_unary(request, context)

return grpc.unary_unary_rpc_method_handler(_quota_handler)

# 定义标准异常替代 grpc.RpcError：
class QuotaExhaustedError(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.details = detail
```

---

### P1-1：SQLite 未开 WAL 模式

**位置**：`billing.py:TenantStore.__init__`

**问题**：默认 `journal_mode=DELETE`，gRPC 线程池并发写必现 `database is locked`。

**修复**：

```python
def __init__(self, db_path: str = "data/tenants.db"):
    ...
    self.conn.execute("PRAGMA journal_mode=WAL;")
    self.conn.execute("PRAGMA synchronous=NORMAL;")
```

---

### P1-2：`lv.value` 假设 Enum key

**位置**：`grpc_server.py:DecayCycle`

**问题**：`lv.value` 假设 dict key 是 Enum，若引擎返回 int key 直接 `AttributeError`。

**修复**：

```python
descended={int(lv) if hasattr(lv, 'value') else int(lv): cnt
           for lv, cnt in rep.descended.items()}
```

---

### P1-3：`ensure_tenant` 每次请求执行跨月重置

**位置**：`billing.py:ensure_tenant`

**问题**：每次计费 RPC 都 `UPDATE ... WHERE period != ?`，高频无意义写入。

**修复**：改为惰性重置——仅在读取到 `period != 当前月份` 时触发，或剥离到定时任务。

---

### P2-1：Enterprise agent_limit 硬编码 999_999

**位置**：`billing.py:TIERS`

**修复**：`"agent_limit": -1` 表示无限，check 方法加 `if limit != -1 and ...`。

---

### P2-2：日志泄露 API key 前缀

**位置**：`billing.py:ensure_tenant`

**修复**：`api_key[:8] + "..."` → `hashlib.sha256(api_key.encode()).hexdigest()[:8] + "..."`

---

### P2-3：RawMessage 无客户端时间戳

**位置**：`proto/forgetting_engine.proto:RawMessage`

**修复**：加 `int64 created_at = 4;`，服务端优先用客户端时间。
