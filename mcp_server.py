"""MCP server wrapping the ForgettingEngine.

Any MCP client (Claude Desktop, Cursor, etc.) can use this to access
agent long-term memory through the standard MCP protocol.

Usage:
    python mcp_server.py --transport stdio     # for Claude Desktop etc.
    python mcp_server.py --transport sse       # for remote clients via HTTP
"""

import argparse
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


def register_tools(server: FastMCP, engine: ForgettingEngine) -> None:

    @server.tool(description="Create a new agent memory space. Call once per user.")
    def create_agent(agent_id: str) -> str:
        """Create an agent with the default domain."""
        engine.create_agent(agent_id, "default")
        return f"agent {agent_id} created"

    @server.tool(description="Ingest a message into agent memory. Call for every user message and agent reply.")
    def ingest(agent_id: str, role: str, text: str, session_id: str) -> str:
        """Write a message to agent memory. role = 'user' or 'agent'."""
        msg = L0_RawMessage(role=role, text=text, time=TimePosition(), wall_clock=now(), session_id=session_id)
        tid = engine.ingest(agent_id, msg)
        return tid

    @server.tool(description="Retrieve agent memories and return injection text. Call before sending to LLM.")
    def retrieve_and_render(
        agent_id: str,
        session_id: str,
        recent_messages: list[str],
        cues: list[dict],
    ) -> str:
        """Return formatted memory text to inject into the LLM prompt.

        cues: list of {"type": "entity"|"topic"|"action", "value": "...", "weight": 0.0-1.0}
        """
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
    server = FastMCP("forgetting-engine")
    register_tools(server, engine)

    if args.transport == "sse":
        server.run(transport="sse")
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
