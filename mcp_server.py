"""MCP server wrapping the ForgettingEngine + billing.

Any MCP client (Claude Desktop, Cursor, etc.) can use this to access
agent long-term memory. Each call requires x_api_key for auth + billing.

Usage:
    python mcp_server.py --transport stdio     # for Claude Desktop etc.
    python mcp_server.py --transport sse       # for remote clients via HTTP
"""

import argparse
import logging
import os
import sys
from functools import wraps

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from billing import QuotaExhaustedError, TenantStore
from forgetting_engine import Cue, ForgettingEngine, L0_RawMessage, RetrievalContext, TimePosition
from forgetting_engine.embedding import QwenEmbeddingProvider, StubEmbeddingProvider
from forgetting_engine.llm import QwenLLMProvider, StubLLMProvider
from forgetting_engine.utils import now

logger = logging.getLogger("mcp_server")


def build_engine() -> ForgettingEngine:
    llm = QwenLLMProvider() if os.getenv("QWEN_API_KEY") else StubLLMProvider()
    embed = QwenEmbeddingProvider() if os.getenv("QWEN_API_KEY") else StubEmbeddingProvider()
    logger.info("LLM: %s  Embed: %s",
        "Qwen" if isinstance(llm, QwenLLMProvider) else "Stub",
        "Qwen" if isinstance(embed, QwenEmbeddingProvider) else "Stub",
    )
    return ForgettingEngine(llm_provider=llm, embedding_provider=embed)


def make_billing_decorator(store: TenantStore):
    """Factory: returns a decorator that checks + deducts quota before tool execution."""

    def billable(tool_name: str):
        """Decorator: first arg must be x_api_key."""
        def decorator(func):
            @wraps(func)
            def wrapper(x_api_key: str, **kwargs):
                try:
                    store.check_and_deduct(x_api_key, tool_name)
                except QuotaExhaustedError as e:
                    return f"ERROR: {e.details}"
                return func(**kwargs)
            return wrapper
        return decorator

    return billable


def register_tools(server: FastMCP, engine: ForgettingEngine, store: TenantStore) -> None:
    bill = make_billing_decorator(store)

    @server.tool(description="Create a new agent memory space. Call once per user. First arg: x_api_key.")
    @bill("CreateAgent")
    def create_agent(agent_id: str) -> str:
        engine.create_agent(agent_id, "default")
        return f"agent {agent_id} created"

    @server.tool(description="Ingest a message into agent memory. First arg: x_api_key.")
    @bill("Ingest")
    def ingest(agent_id: str, role: str, text: str, session_id: str) -> str:
        msg = L0_RawMessage(role=role, text=text, time=TimePosition(), wall_clock=now(), session_id=session_id)
        return engine.ingest(agent_id, msg)

    @server.tool(description="Retrieve agent memories and return injection text. First arg: x_api_key.")
    @bill("RetrieveAndRender")
    def retrieve_and_render(
        agent_id: str,
        session_id: str,
        recent_messages: list[str],
        cues: list[dict],
    ) -> str:
        ctx = RetrievalContext(
            current_session_id=session_id,
            recent_messages=recent_messages,
            cues=[Cue(**c) for c in cues],
            domain_hints={},
        )
        traces = engine.retrieve(agent_id, ctx)
        return engine.render_for_injection(agent_id, traces, ctx)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="Forgetting Engine MCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse"])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    engine = build_engine()
    store = TenantStore("data/tenants.db")
    server = FastMCP("forgetting-engine")
    register_tools(server, engine, store)

    logger.info("Billing: MCP tools — Ingest, RetrieveAndRender billable; CreateAgent checked")
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
