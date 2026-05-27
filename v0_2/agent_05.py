"""Agent 01 — gRPC 客户端，连遗忘引擎服务端。

引擎在 knownot.cc:50051，Agent 通过 gRPC 远程调用。
环境变量：
    FE_API_KEY_05  Agent 的引擎 API key
    QWEN_API_KEY   千问 flash 模型 key
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grpc
from proto import forgetting_engine_pb2 as pb
from proto import forgetting_engine_pb2_grpc as pb_grpc
import requests as _requests

AGENT_ID = "agent_05"
API_KEY = os.getenv("FE_API_KEY_05", "agent-05-key")
ENGINE_ADDR = os.getenv("FE_ADDR", "knownot.cc:50051")
QWEN_KEY = os.getenv("QWEN_API_KEY")

# TLS 连接

channel = grpc.insecure_channel(ENGINE_ADDR)
stub = pb_grpc.ForgettingEngineStub(channel)
md = [("x-api-key", API_KEY)]

# 注册
stub.CreateAgent(pb.CreateAgentRequest(agent_id=AGENT_ID, domain="default"), metadata=md)

# —— 单轮对话 ——
session = "s1"
bot_text = "你好，今天想聊聊"

# 1. Ingest bot 消息
stub.Ingest(pb.IngestRequest(
    agent_id=AGENT_ID,
    message=pb.RawMessage(role="user", text=bot_text, session_id=session),
), metadata=md)

# 2. Retrieve + Render
ret = stub.RetrieveAndRender(pb.RetrieveAndRenderRequest(
    agent_id=AGENT_ID,
    current_session_id=session,
    recent_messages=[bot_text],
    cues=[pb.Cue(type="topic", value="聊天", weight=0.5)],
), metadata=md)

# 3. Flash 模型生成回复
reply = ""
if QWEN_KEY:
    prompt = f"{ret.injection_text}\n\n用户说：{bot_text}\n\n请简短回复。"
    r = _requests.post(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        headers={"Authorization": f"Bearer {QWEN_KEY}", "Content-Type": "application/json"},
        json={"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": prompt}], "max_tokens": 256},
        timeout=30,
    )
    reply = r.json()["choices"][0]["message"]["content"]

# 4. Ingest agent 回复
if reply:
    stub.Ingest(pb.IngestRequest(
        agent_id=AGENT_ID,
        message=pb.RawMessage(role="agent", text=reply, session_id=session),
    ), metadata=md)

# 5. Decay
rep = stub.DecayCycle(pb.DecayCycleRequest(agent_id=AGENT_ID), metadata=md)
r = rep.reports[AGENT_ID]
print(f"agent_05: retained={r.retained} deleted={r.deleted}")

channel.close()
