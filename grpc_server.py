"""gRPC server wrapping the ForgettingEngine + billing gateway.

Startup:
    python grpc_server.py --port 50051 --domain skincare --dev-key hufu-dev-001

gRPC metadata required on every request:
    x-api-key: <tenant_api_key>

Billing:
    Free tier:  1,000 agents | 100,000 calls/month
    Pro  tier: 10,000 agents | 1,000,000 calls/month
    Enterprise:    unlimited | 10,000,000 calls/month
"""

import argparse
import logging
from concurrent import futures

import grpc

from billing import BillingInterceptor, TenantStore, seed_dev_tenant
from forgetting_engine import (
    Cue,
    ForgettingEngine,
    L0_RawMessage,
    RetrievalContext,
    TimePosition,
)
from forgetting_engine.adapters.skincare import SkincareAdapter
from forgetting_engine.utils import now

from proto import forgetting_engine_pb2 as pb
from proto import forgetting_engine_pb2_grpc as pb_grpc

logger = logging.getLogger("grpc_server")


# ── Protocol mapping helpers ──────────────────────────────────


def _raw_msg_from_pb(pb_msg: pb.RawMessage) -> L0_RawMessage:
    wall_clock = None
    if pb_msg.created_at:
        from datetime import datetime, timezone
        wall_clock = datetime.fromtimestamp(pb_msg.created_at / 1000.0, tz=timezone.utc)
    return L0_RawMessage(
        role=pb_msg.role,
        text=pb_msg.text,
        time=TimePosition(),
        wall_clock=wall_clock or now(),
        session_id=pb_msg.session_id,
    )


def _cues_from_pb(pb_cues: list[pb.Cue]) -> list[Cue]:
    return [Cue(type=c.type, value=c.value, weight=c.weight) for c in pb_cues]


# ── Service implementation ───────────────────────────────────


class ForgettingEngineServicer(pb_grpc.ForgettingEngineServicer):
    """gRPC servicer wrapping a ForgettingEngine instance."""

    def __init__(self, engine: ForgettingEngine):
        self.engine = engine

    # ── Agent management ──────────────────────────────────

    def CreateAgent(self, request: pb.CreateAgentRequest, context) -> pb.CreateAgentResponse:
        logger.info("CreateAgent: agent_id=%s domain=%s", request.agent_id, request.domain)
        domain = request.domain or "default"
        aid = self.engine.create_agent(request.agent_id, domain)
        return pb.CreateAgentResponse(agent_id=aid)

    def DeleteAgent(self, request: pb.DeleteAgentRequest, context) -> pb.DeleteAgentResponse:
        logger.info("DeleteAgent: agent_id=%s", request.agent_id)
        self.engine.delete_agent(request.agent_id)
        return pb.DeleteAgentResponse()

    def ListAgents(self, request: pb.ListAgentsRequest, context) -> pb.ListAgentsResponse:
        agents = [
            pb.AgentInfo(
                agent_id=a["agent_id"],
                domain=a["domain"],
                trace_count=a["trace_count"],
                is_active=a["is_active"],
                clock=a["clock"],
            )
            for a in self.engine.list_agents()
        ]
        return pb.ListAgentsResponse(agents=agents)

    # ── Ingest ──────────────────────────────────────────

    def Ingest(self, request: pb.IngestRequest, context) -> pb.IngestResponse:
        msg = _raw_msg_from_pb(request.message)
        sig = request.significance

        if sig > 0:
            tid = self.engine.ingest_significant(request.agent_id, msg, sig)
        else:
            tid = self.engine.ingest(request.agent_id, msg)

        rt = self.engine.agents.get(request.agent_id)
        trace_count = len(rt.traces) if rt else 0
        logger.debug("Ingest: agent=%s trace_id=%s", request.agent_id, tid)

        return pb.IngestResponse(trace_id=tid, trace_count=trace_count)

    # ── Retrieve + Render (combined call) ────────────────

    def RetrieveAndRender(
        self, request: pb.RetrieveAndRenderRequest, context
    ) -> pb.RetrieveAndRenderResponse:
        logger.debug(
            "RetrieveAndRender: agent=%s session=%s cues=%d",
            request.agent_id, request.current_session_id, len(request.cues),
        )

        ctx = RetrievalContext(
            current_session_id=request.current_session_id,
            recent_messages=list(request.recent_messages),
            cues=_cues_from_pb(request.cues),
            domain_hints=dict(request.domain_hints),
        )

        traces = self.engine.retrieve(request.agent_id, ctx)
        text = self.engine.render_for_injection(request.agent_id, traces, ctx)

        return pb.RetrieveAndRenderResponse(
            injection_text=text,
            traces_retrieved=len(traces),
        )

    # ── Decay cycle ──────────────────────────────────────

    def DecayCycle(self, request: pb.DecayCycleRequest, context) -> pb.DecayCycleResponse:
        agent_id = request.agent_id or None
        logger.info("DecayCycle: agent_id=%s", agent_id or "ALL")

        reports = self.engine.decay_cycle(agent_id)

        pb_reports = {}
        for aid, rep in reports.items():
            pb_reports[aid] = pb.DecayReport(
                retained=rep.retained,
                deleted=rep.deleted,
                descended={lv.value if hasattr(lv, 'value') else int(lv): cnt
                           for lv, cnt in rep.descended.items()},
            )

        return pb.DecayCycleResponse(reports=pb_reports)

    # ── Billing ──────────────────────────────────────────

    def GetUsage(self, request: pb.GetUsageRequest, context) -> pb.GetUsageResponse:
        """Return current tenant usage. api_key from gRPC metadata."""
        api_key = _get_api_key(context)
        usage = _TENANT_STORE.get_usage(api_key)
        return pb.GetUsageResponse(
            tenant_name=usage["tenant_name"],
            agent_count=usage["agent_count"],
            agent_limit=usage["agent_limit"],
            calls_used=usage["calls_used"],
            calls_limit=usage["calls_limit"],
            current_period=usage["current_period"],
            tier=usage["tier"],
        )


# ── Entrypoint ───────────────────────────────────────────────


# ── Helpers ───────────────────────────────────────────────────


def _get_api_key(context: grpc.ServicerContext) -> str:
    metadata = dict(context.invocation_metadata() or {})
    return metadata.get("x-api-key", "")


# ── Global billing store (initialized at startup) ─────────────

_TENANT_STORE: TenantStore | None = None


# ── Entrypoint ───────────────────────────────────────────────


def serve(port: int, domain: str, dev_key: str | None) -> None:
    global _TENANT_STORE

    import os

    from forgetting_engine.llm import QwenLLMProvider, StubLLMProvider
    from forgetting_engine.embedding import QwenEmbeddingProvider, StubEmbeddingProvider

    llm = QwenLLMProvider() if os.getenv("QWEN_API_KEY") else StubLLMProvider()
    embedding = QwenEmbeddingProvider() if os.getenv("QWEN_API_KEY") else StubEmbeddingProvider()
    logger.info("LLM: %s  Embed: %s",
        "Qwen" if isinstance(llm, QwenLLMProvider) else "Stub",
        "Qwen" if isinstance(embedding, QwenEmbeddingProvider) else "Stub",
    )

    engine = ForgettingEngine(llm_provider=llm, embedding_provider=embedding)

    if domain == "skincare":
        ForgettingEngine.register_domain("skincare", SkincareAdapter)
        logger.info("Domain registered: skincare")

    # Init billing store
    _TENANT_STORE = TenantStore()
    billing_interceptor = BillingInterceptor(_TENANT_STORE)

    # Seed dev tenant
    if dev_key:
        seed_dev_tenant(_TENANT_STORE, dev_key, name="dev", tier="free")

    servicer = ForgettingEngineServicer(engine)
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[billing_interceptor],
    )
    pb_grpc.add_ForgettingEngineServicer_to_server(servicer, server)

    addr = f"[::]:{port}"

    tls_cert = os.getenv("GRPC_TLS_CERT")
    tls_key = os.getenv("GRPC_TLS_KEY")
    if tls_cert and tls_key:
        with open(tls_cert, "rb") as f:
            cert_pem = f.read()
        with open(tls_key, "rb") as f:
            key_pem = f.read()
        creds = grpc.ssl_server_credentials([(key_pem, cert_pem)])
        server.add_secure_port(addr, creds)
        logger.info("gRPC server (TLS) listening on %s", addr)
    else:
        server.add_insecure_port(addr)
        logger.info("gRPC server (insecure) listening on %s", addr)

    server.start()
    logger.info("Billing: free tier (1K agents, 100K calls/month)")

    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Forgetting Engine gRPC Server")
    parser.add_argument("--port", type=int, default=50051, help="gRPC listen port")
    parser.add_argument("--domain", type=str, default="default", help="Domain to register (e.g., skincare)")
    parser.add_argument("--dev-key", type=str, default=None, help="Dev tenant API key to auto-create")
    args = parser.parse_args()

    serve(args.port, args.domain, args.dev_key)
