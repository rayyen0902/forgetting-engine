"""LLM provider interface and stub implementation.

The stub returns placeholder JSON for prototyping. Replace with a real
provider (OpenAI, Anthropic, etc.) by implementing the LLMProvider interface.
"""

import json
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract interface for LLM calls."""

    @abstractmethod
    def call(self, prompt: str) -> dict:
        """Send a prompt to the LLM and return parsed JSON."""
        ...


class StubLLMProvider(LLMProvider):
    """Stub that returns placeholder JSON for prototyping.

    Uses simple keyword heuristics to return vaguely relevant responses
    without calling any external API.
    """

    def call(self, prompt: str) -> dict:
        p = prompt.lower()

        # L0→L1 compression: extract narrative
        if "叙事记录" in p or "固定字段" in p:
            return {
                "topic": "皮肤护理咨询",
                "action_type": "consult_concern",
                "subject_entity": "用户",
                "predicate": "咨询了护肤问题",
                "outcome": "获得了建议",
                "negation": None,
                "emotional_tone": 0.0,
            }

        # L1→L2 frequency pattern summary
        if "总结模式" in p:
            return {"description": "用户多次咨询同类型的护肤问题，关注皮肤改善效果"}

        # L1→L2 contrast pattern summary
        if "总结对比模式" in p:
            return {"description": "用户对不同产品的效果反馈存在差异，偏好温和型产品"}

        # L2→L3 fact extraction
        if "映射到 schema" in p or "schema=" in p:
            return {
                "key": "skin_type",
                "value": "combination",
                "sentence": "用户为混合性肤质",
            }

        # L1 stitching
        if "整合为2-3句" in p or "连贯的背景描述" in p:
            return {"description": "用户关注护肤效果，偏好温和不刺激的产品，对成分安全性有要求"}

        # Conflict detection
        if "存在矛盾" in p:
            return {"conflict": False, "detail": ""}

        # Generic fallback
        return {"description": "无法解析的 LLM 请求", "key": "", "value": "", "sentence": ""}


# ── Qwen (DashScope) provider ─────────────────────────────────


class QwenLLMProvider(LLMProvider):
    """Qwen LLM via DashScope compatible API.

    Environment variables:
        QWEN_API_KEY  (required)
        QWEN_MODEL    (default: qwen-plus)
        QWEN_API_URL  (default: https://dashscope.aliyuncs.com/compatible-mode/v1)
    """

    def __init__(self):
        import os

        self.api_key = os.getenv("QWEN_API_KEY")
        if not self.api_key:
            raise ValueError("QWEN_API_KEY environment variable is required")

        self.model = os.getenv("QWEN_MODEL", "qwen-plus")
        self.api_url = os.getenv(
            "QWEN_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

    def call(self, prompt: str) -> dict:
        import json as _json

        import requests as _requests

        resp = _requests.post(
            f"{self.api_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个 JSON 提取器。根据用户要求输出标准 JSON，不要输出其他内容。",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        text = body["choices"][0]["message"]["content"].strip()
        return _json.loads(text)


# Default provider (stub — swap for real provider in production)
_default_provider: LLMProvider = StubLLMProvider()


def get_llm() -> LLMProvider:
    return _default_provider


def set_llm(provider: LLMProvider) -> None:
    global _default_provider
    _default_provider = provider
