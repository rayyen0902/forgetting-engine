## 部署工单：遗忘引擎 gRPC 服务 v0.1

> 交付日期：2026-05-28 | 分支：main | 接收人：运维

---

### 环境变量（运维需提前配置）

```bash
# ── 必填 ──
export QWEN_API_KEY="sk-your-key-here"           # 千问 API key（LLM + Embedding 共用）

# ── 生产建议 ──
export DATABASE_URL="postgresql://user:pass@host:5432/dbname"  # PostgreSQL 计费存储
export GRPC_TLS_CERT="/etc/ssl/fe/cert.pem"      # TLS 证书
export GRPC_TLS_KEY="/etc/ssl/fe/key.pem"        # TLS 私钥

# ── 可选 ──
export QWEN_MODEL="qwen-plus"                    # LLM 模型（默认 qwen-plus）
export QWEN_EMBED_MODEL="text-embedding-v3"      # Embedding 模型（默认 text-embedding-v3）
```

> 不设 `DATABASE_URL` → 自动降级 SQLite（`data/tenants.db`）
> 不设 `GRPC_TLS_CERT/KEY` → 自动降级 `insecure` 端口

---

### 部署步骤

```bash
# 1. 拉代码
git clone https://github.com/rayyen0902/forgetting-engine.git /opt/forgetting-engine
cd /opt/forgetting-engine

# 2. 环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 编译 proto
python compile_proto.py

# 4. 创建 HuFu 生产租户（替换 API key）
python -c "
from billing import TenantStore, seed_dev_tenant
store = TenantStore('data/tenants.db')
seed_dev_tenant(store, 'hf-prod-REPLACE-ME', 'HuFu-Production', 'pro')
"

# 5. 启动
nohup python grpc_server.py \
  --port 50051 \
  --domain skincare \
  > /var/log/forgetting-engine.log 2>&1 &

# 6. 验证
python -c "
import grpc
from proto import forgetting_engine_pb2 as pb, forgetting_engine_pb2_grpc as pb_grpc
ch = grpc.insecure_channel('localhost:50051')
stub = pb_grpc.ForgettingEngineStub(ch)
md = [('x-api-key', 'hf-prod-REPLACE-ME')]
r = stub.CreateAgent(pb.CreateAgentRequest(agent_id='test_1', domain='skincare'), metadata=md)
print(f'Agent: {r.agent_id}')
r = stub.GetUsage(pb.GetUsageRequest(), metadata=md)
print(f'Tier: {r.tier}  Calls: {r.calls_used}/{r.calls_limit}')
print('OK')
"
```

---

### 进程守护（systemd）

```ini
# /etc/systemd/system/forgetting-engine.service
[Unit]
Description=Forgetting Engine gRPC
After=network.target

[Service]
Type=simple
User=fe
WorkingDirectory=/opt/forgetting-engine
EnvironmentFile=/opt/forgetting-engine/.env
ExecStart=/opt/forgetting-engine/.venv/bin/python grpc_server.py --port 50051 --domain skincare
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now forgetting-engine
```

---

### HuFu 接入（Go 侧）

| 时机 | 调用 | 说明 |
|------|------|------|
| 用户注册 | `CreateAgent(userID, "skincare")` | 创建独立记忆空间 |
| 收到消息 | `Ingest(userID, msg)` | 摄入用户消息 + AI 回复（各一次） |
| 拼 prompt 前 | `RetrieveAndRender(userID, ctx)` | 返回 `injection_text` 直接拼入 LLM prompt |
| 定时任务 | `DecayCycle(userID)` | 触发遗忘循环 |

每个请求 gRPC metadata 必须带 `x-api-key`。
