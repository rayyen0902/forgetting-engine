## 部署工单：遗忘引擎 gRPC 服务

> 交付版本：v0.1 | 代码分支：main | 部署目标：生产服务器

---

### 环境要求

| 项目 | 版本/说明 |
|------|----------|
| Python | ≥3.11 |
| 依赖 | grpcio, grpcio-tools, numpy |
| 端口 | 50051（gRPC，可配置） |
| 存储 | SQLite `data/tenants.db`（开发），PostgreSQL（生产切换） |
| 内存 | ≥512MB（含 protobuf + numpy） |

---

### 部署步骤

#### 1. 拉取代码

```bash
git clone https://github.com/rayyen0902/forgetting-engine.git /opt/forgetting-engine
cd /opt/forgetting-engine
```

#### 2. 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install grpcio grpcio-tools
```

#### 3. 编译 protobuf

```bash
python compile_proto.py
```

#### 4. 创建生产租户

```bash
python -c "
from billing import TenantStore, seed_dev_tenant
store = TenantStore('data/tenants.db')
seed_dev_tenant(store, 'hf-prod-XXXX', 'HuFu-Production', 'pro')
"
```

> ⚠️ `hf-prod-XXXX` 替换为实际 API key。

#### 5. 启动服务

```bash
nohup python grpc_server.py \
  --port 50051 \
  --domain skincare \
  > logs/grpc_server.log 2>&1 &
```

#### 6. 验证

```bash
python -c "
import grpc
from proto import forgetting_engine_pb2 as pb, forgetting_engine_pb2_grpc as pb_grpc

channel = grpc.insecure_channel('localhost:50051')
stub = pb_grpc.ForgettingEngineStub(channel)
md = [('x-api-key', 'hf-prod-XXXX')]

# 创建 agent
resp = stub.CreateAgent(pb.CreateAgentRequest(agent_id='hf_user_1', domain='skincare'), metadata=md)
print(f'CreateAgent: {resp.agent_id}')

# 摄入消息
msg = pb.RawMessage(role='user', text='你好，我最近皮肤很油', session_id='s1')
resp = stub.Ingest(pb.IngestRequest(agent_id='hf_user_1', message=msg), metadata=md)
print(f'Ingest: trace_id={resp.trace_id}')

# 检索+注入
resp = stub.RetrieveAndRender(pb.RetrieveAndRenderRequest(
    agent_id='hf_user_1', current_session_id='s2',
    recent_messages=['皮肤很油'],
    cues=[pb.Cue(type='entity', value='油性皮肤', weight=0.8)],
), metadata=md)
print(f'RetrieveAndRender: {resp.traces_retrieved} traces')

# 查看用量
resp = stub.GetUsage(pb.GetUsageRequest(), metadata=md)
print(f'Usage: tier={resp.tier} agents={resp.agent_count} calls={resp.calls_used}')
print('OK')
"
```

---

### HuFu 接入清单

Go 侧的 gRPC client 调用：

```go
// 1. proto 编译
// protoc --go_out=. --go-grpc_out=. proto/forgetting_engine.proto

// 2. 创建 client
conn, _ := grpc.Dial("engine-host:50051", grpc.WithInsecure())
client := pb.NewForgettingEngineClient(conn)

// 3. 每个请求带 x-api-key
md := metadata.Pairs("x-api-key", "hf-prod-XXXX")
ctx := metadata.NewOutgoingContext(context.Background(), md)

// 4. 用户注册时 → CreateAgent
client.CreateAgent(ctx, &pb.CreateAgentRequest{AgentId: userID, Domain: "skincare"})

// 5. 每次收到用户消息 → Ingest
client.Ingest(ctx, &pb.IngestRequest{
    AgentId: userID,
    Message: &pb.RawMessage{Role: "user", Text: msg, SessionId: sessionID},
})

// 6. 拼 LLM prompt 前 → RetrieveAndRender
resp, _ := client.RetrieveAndRender(ctx, &pb.RetrieveAndRenderRequest{
    AgentId: userID, CurrentSessionId: sessionID,
    RecentMessages: []string{msg},
    Cues: []*pb.Cue{{Type: "entity", Value: entity, Weight: 0.8}},
})
// resp.InjectionText 直接拼入 prompt
```

---

### 生产化待办（部署后）

- [ ] 替换 SQLite → PostgreSQL（共享 `tenants` 表）
- [ ] 替换 StubLLM → 千问 API
- [ ] 替换 StubEmbedding → 千问/其他 embedding 服务
- [ ] gRPC 加 TLS（现为 `insecure`）
- [ ] `requirements.txt` 补 `grpcio grpcio-tools`
- [ ] systemd / supervisor 进程守护
