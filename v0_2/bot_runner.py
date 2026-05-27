"""Bot runner — 从 bot_configs.json 读取角色，跟自己的 Agent 持续聊天。

用法：
    QWEN_API_KEY=sk-xxx BOT_ID=bot_01 python v0_2/bot_runner.py

角色定义在 bot_configs.json，5 个 Bot 各跑一个终端窗口。
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import grpc
import requests
from proto import forgetting_engine_pb2 as pb
from proto import forgetting_engine_pb2_grpc as pb_grpc

BOT_ID = os.getenv("BOT_ID", "bot_01")
QWEN_KEY = os.getenv("QWEN_API_KEY")
ENGINE = os.getenv("FE_ADDR", "knownot.cc:50052")

# 加载配置
cfg = json.loads(Path(__file__).with_name("bot_configs.json").read_text())[BOT_ID]
AGENT_ID = cfg["agent_id"]
API_KEY = cfg["api_key"]
ROLE = cfg["role"]
CUE = cfg["cue"]

# 接引擎
ch = grpc.insecure_channel(ENGINE)
stub = pb_grpc.ForgettingEngineStub(ch)
md = [("x-api-key", API_KEY)]
try:
    stub.CreateAgent(pb.CreateAgentRequest(agent_id=AGENT_ID, domain="default"), metadata=md)
except Exception:
    pass  # agent 已存在，跳过

session = f"{BOT_ID}-chat"


def llm(prompt: str, system: str | None = None) -> str:
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    r = requests.post(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        headers={"Authorization": f"Bearer {QWEN_KEY}", "Content-Type": "application/json"},
        json={"model": "deepseek-v4-flash", "messages": msgs, "max_tokens": 256},
        timeout=60,
    )
    return r.json()["choices"][0]["message"]["content"]


# 首轮：Bot 主动开口
bot_msg = llm("开始一段闲聊，用你自己的语言风格随便聊点什么。别啰嗦。", ROLE)
print(f"[{BOT_ID}] {bot_msg}")

for rnd in range(100):
    # Ingest
    stub.Ingest(pb.IngestRequest(agent_id=AGENT_ID,
        message=pb.RawMessage(role="user", text=bot_msg, session_id=session)), metadata=md)

    # Retrieve + Agent 回复
    ret = stub.RetrieveAndRender(pb.RetrieveAndRenderRequest(
        agent_id=AGENT_ID, current_session_id=session,
        recent_messages=[bot_msg],
        cues=[pb.Cue(type="topic", value=CUE, weight=0.5)],
    ), metadata=md)
    agent_reply = llm(f"{ret.injection_text}\n\n对方说：{bot_msg}\n\n简短回复。")

    # Ingest
    stub.Ingest(pb.IngestRequest(agent_id=AGENT_ID,
        message=pb.RawMessage(role="agent", text=agent_reply, session_id=session)), metadata=md)

    # Decay
    rep = stub.DecayCycle(pb.DecayCycleRequest(agent_id=AGENT_ID), metadata=md)
    r = rep.reports[AGENT_ID]
    print(f"[{BOT_ID} r{rnd}] retain={r.retained} del={r.deleted}")

    # Bot 接话
    bot_msg = llm(f"对方说：{agent_reply}\n\n用你的人物风格接话，别太长。", ROLE)
    print(f"[{BOT_ID}] {bot_msg}")
    time.sleep(0.3)

ch.close()
