# 遗忘引擎 v0.1 · 客户交付手册

> **客户**：HuFu（肤小护）  
> **交付日期**：2026-05-28  
> **交付方**：Forgetting Engine Team  
> **文档密级**：客户内部

---

## 1. 服务信息

| 项目 | 值 |
|------|-----|
| 接入地址 | `knownot.cc:50051` |
| 传输加密 | TLS |
| 鉴权方式 | gRPC Metadata `x-api-key` |
| API Key | `ry-20260527001` |
| 套餐 | Pro（10,000 agent / 1,000,000 调用/月） |

> API Key 请妥善保管，勿提交到公开仓库。如需更换请联络我方。

---

## 2. 接入步骤

### 2.1 获取 Proto 文件

```bash
git clone https://github.com/rayyen0902/forgetting-engine.git
# 接口定义文件：proto/forgetting_engine.proto
```

### 2.2 生成 Go Client Stub

```bash
# 安装工具（一次性）
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

# 生成代码
protoc --go_out=. --go-grpc_out=. proto/forgetting_engine.proto
```

### 2.3 初始化连接

```go
import (
    "google.golang.org/grpc"
    "google.golang.org/grpc/credentials"
    "google.golang.org/grpc/metadata"
    pb "your-module/proto"
)

creds, _ := credentials.NewClientTLSFromFile("path/to/cert.pem", "")
conn, _ := grpc.Dial("knownot.cc:50051",
    grpc.WithTransportCredentials(creds))
client := pb.NewForgettingEngineClient(conn)

md := metadata.Pairs("x-api-key", "ry-20260527001")
```

### 2.4 用户注册时 — 创建记忆空间

```go
ctx := metadata.NewOutgoingContext(context.Background(), md)
client.CreateAgent(ctx, &pb.CreateAgentRequest{
    AgentId: userID,
    Domain:  "skincare",
})
```

每个 HuFu 用户调用一次，引擎为其创建独立记忆空间。

### 2.5 每次对话 — 写入记忆

```go
// 用户发消息后
client.Ingest(ctx, &pb.IngestRequest{
    AgentId: userID,
    Message: &pb.RawMessage{
        Role:      "user",
        Text:      userMessage,
        SessionId: sessionID,
        CreatedAt: time.Now().UnixMilli(),
    },
})

// AI 回复后
client.Ingest(ctx, &pb.IngestRequest{
    AgentId: userID,
    Message: &pb.RawMessage{
        Role:      "agent",
        Text:      aiReply,
        SessionId: sessionID,
        CreatedAt: time.Now().UnixMilli(),
    },
})
```

### 2.6 构建 LLM Prompt 前 — 检索记忆

```go
resp, err := client.RetrieveAndRender(ctx, &pb.RetrieveAndRenderRequest{
    AgentId:          userID,
    CurrentSessionId: sessionID,
    RecentMessages:   []string{userMessage},
    Cues: []*pb.Cue{
        {Type: "entity", Value: "烟酰胺", Weight: 0.8},
        {Type: "topic",  Value: "提亮肤色", Weight: 0.6},
    },
})

// resp.InjectionText 直接拼到 LLM System Prompt 前面
finalPrompt := resp.InjectionText + "\n\n" + originalSystemPrompt
```

### 2.7 定期维护 — 触发遗忘（可选）

```go
// 建议每小时或日终调用一次
client.DecayCycle(ctx, &pb.DecayCycleRequest{AgentId: userID})
```

---

## 3. 接口速查

| RPC | 参数 | 返回 | 调用频率 |
|-----|------|------|----------|
| `CreateAgent` | agentId, domain | agentId | 用户注册时 1 次 |
| `Ingest` | agentId, RawMessage(role, text, sessionId, createdAt) | traceId | 每条消息 1 次 |
| `RetrieveAndRender` | agentId, sessionId, recentMessages, cues | injectionText, tracesRetrieved | 发 LLM 前 1 次 |
| `DecayCycle` | agentId（空=全部） | DecayReport | 定时任务 |
| `GetUsage` | — | tier, callsUsed/limit, agentCount | 按需 |
| `DeleteAgent` | agentId | — | 用户注销时 |

完整定义见：`proto/forgetting_engine.proto`

---

## 4. 错误码

| Status Code | 含义 | 建议处理 |
|-------------|------|----------|
| `OK` | 成功 | — |
| `RESOURCE_EXHAUSTED` | 配额用尽 | 联系我方升级套餐 |
| `UNAUTHENTICATED` | 缺少/无效 x-api-key | 检查 metadata |
| `INTERNAL` | 引擎内部错误 | 重试 1 次，仍失败联系我方 |

---

## 5. 接入检查清单

- [ ] Proto 文件已拉取并编译生成 Go stub
- [ ] gRPC 连接 `knownot.cc:50051` 可达（TLS 握手通过）
- [ ] `x-api-key = ry-20260527001` 已配置
- [ ] 用户注册流程中已加入 `CreateAgent` 调用
- [ ] 消息收发流程中已加入 `Ingest` 调用（user + agent 各一次）
- [ ] LLM 调用前已加入 `RetrieveAndRender` 调用
- [ ] 联调通过（创建 test agent + ingest + retrieve 全链路）

---

## 6. 联系与支持

- API Key 更换 / 配额升级 / 故障报修：联系 Forgetting Engine Team
- Proto 定义与接口疑问：参考本文档及 `proto/forgetting_engine.proto`

---

**HuFu 签收**：________________  

**FE Team 签收**：________________
