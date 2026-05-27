# 遗忘引擎 v0.1 · 客户交付文档

> 客户：HuFu（肤小护）  
> 交付日期：2026-05-28  
> 交付方：Forgetting Engine Team

---

## 1. 产品概述

遗忘引擎是一个 Agent 通用记忆中间件。为你的 AI 顾问提供**长期记忆能力**——自动记住用户偏好、禁忌、历史反馈，并在每次对话中注入到 LLM prompt。

HuFu 只需要调用 2 个 gRPC 接口，其余全部由引擎托管。

---

## 2. 交付清单

| 交付物 | 位置 | 说明 |
|--------|------|------|
| gRPC 服务地址 | `engine-host:50051` | 已部署，运维提供具体 IP/域名 |
| API Key | **（已单独发送）** | gRPC metadata 中携带，用于身份识别和配额管理 |
| Proto 文件 | `proto/forgetting_engine.proto` | 编译后生成 Go client stub |
| 配额 | Pro tier | 10,000 agent / 1,000,000 调用/月 |

---

## 3. 接入步骤

### 3.1 生成 Go client

```bash
git clone https://github.com/rayyen0902/forgetting-engine.git
cd forgetting-engine

# 安装 protoc（如已安装跳过）
brew install protobuf  # macOS
# 或 apt install protobuf-compiler  # Linux

# 安装 Go 插件
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

# 生成 Go stub
protoc --go_out=. --go-grpc_out=. proto/forgetting_engine.proto
```

### 3.2 初始化 client

```go
import (
    "google.golang.org/grpc"
    "google.golang.org/grpc/credentials/insecure"
    "google.golang.org/grpc/metadata"
    pb "your-project/proto"
)

conn, _ := grpc.Dial("engine-host:50051",
    grpc.WithTransportCredentials(insecure.NewCredentials()))
client := pb.NewForgettingEngineClient(conn)

// 每个请求带上 API key
md := metadata.Pairs("x-api-key", "your-api-key-here")
```

### 3.3 用户接入（一次性）

```go
// 用户注册时调用一次，创建独立记忆空间
ctx := metadata.NewOutgoingContext(context.Background(), md)
client.CreateAgent(ctx, &pb.CreateAgentRequest{
    AgentId: userID,    // HuFu 用户 ID，如 "hf_user_123"
    Domain:  "skincare",
})
```

### 3.4 对话接入（每次对话调用）

```go
ctx := metadata.NewOutgoingContext(context.Background(), md)

// 每条消息写入引擎
client.Ingest(ctx, &pb.IngestRequest{
    AgentId: userID,
    Message: &pb.RawMessage{
        Role:      "user",          // "user" 或 "agent"
        Text:      userMessage,
        SessionId: sessionID,
        CreatedAt: time.Now().UnixMilli(),
    },
})

// AI 回复后也同样 Ingest 一条 role="agent" 的消息
```

### 3.5 Prompt 增强（发 LLM 前调用）

```go
resp, err := client.RetrieveAndRender(ctx, &pb.RetrieveAndRenderRequest{
    AgentId:          userID,
    CurrentSessionId: sessionID,
    RecentMessages:   []string{userMessage},
    Cues: []*pb.Cue{
        {Type: "entity", Value: "烟酰胺", Weight: 0.8},
    },
})

// resp.InjectionText 直接拼入 LLM prompt：
finalPrompt := resp.InjectionText + "\n\n" + systemPrompt + "\n\n用户：" + userMessage
```

`InjectionText` 示例输出：
```
[当前对话]
[user] 我想买个提亮肤色的精华

[背景]
肤质档案：混合性肤质 · 敏感
⚠ 禁忌：烟酰胺不耐受
[L1 -2c] 理肤泉B5修复霜：泛红改善 [积极]
```

### 3.6 定期维护（可选）

```go
// 建议每小时或每天调用一次，触发遗忘循环
client.DecayCycle(ctx, &pb.DecayCycleRequest{AgentId: userID})
```

---

## 4. 接口速查

| RPC | 参数 | 返回 | 频率 |
|-----|------|------|------|
| `CreateAgent` | agentId, domain | agentId | 用户注册时 1 次 |
| `Ingest` | agentId, RawMessage | traceId | 每条消息 1 次 |
| `RetrieveAndRender` | agentId, sessionId, cues | injectionText | 每次发 LLM 前 1 次 |
| `GetUsage` | - | tier, calls_used/limit | 查配额 |
| `DecayCycle` | agentId(可选) | DecayReport | 定期维护 |

完整 proto 定义见：`proto/forgetting_engine.proto`

---

## 5. 错误处理

| HTTP/gRPC Status | 含义 | 处理方式 |
|------------------|------|----------|
| `OK` | 正常 | - |
| `RESOURCE_EXHAUSTED` | 配额用尽 | 联系我们升级 tier |
| `UNAUTHENTICATED` | 未带 x-api-key | 检查 metadata |
| `INTERNAL` | 引擎内部异常 | 重试 + 联系我们 |

---

## 6. 技术支持

- Proto 定义 & Go stub 生成：参考本文档第 3 节
- API key 变更 / 配额升级：联系 FE Team
- 引擎故障 / 异常：联系 FE Team

---

**HuFu 签收：** ________________  

**FE Team 签收：** ________________
