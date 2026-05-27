"""Billing — per-tenant quota enforcement. PostgreSQL only.

Tiered model (hybrid):
    free:      1,000 agents | 100,000 calls/month
    pro:      10,000 agents | 1,000,000 calls/month
    enterprise: unlimited agents | 10,000,000 calls/month

Billable:  Ingest, RetrieveAndRender
Checked:   CreateAgent (agent limit check)
"""

import hashlib
import logging
import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

logger = logging.getLogger("billing")


# ── Tier config ────────────────────────────────────────────────


TIERS = {
    "free":       {"agent_limit": 1_000,   "calls_limit": 100_000},
    "pro":        {"agent_limit": 10_000,  "calls_limit": 1_000_000},
    "enterprise": {"agent_limit": -1,      "calls_limit": 10_000_000},
}

# gRPC method paths
GRPC_BILLABLE = {
    "/forgetting_engine.ForgettingEngine/Ingest",
    "/forgetting_engine.ForgettingEngine/RetrieveAndRender",
}
GRPC_AGENT_CHECK = "/forgetting_engine.ForgettingEngine/CreateAgent"

# MCP tool names (shorter, used by mcp_server.py decorator)
MCP_BILLABLE = {"Ingest", "RetrieveAndRender"}
MCP_AGENT_CHECK = "CreateAgent"


class QuotaExhaustedError(Exception):
    """Raised when a tenant exceeds quota. Carries gRPC status code + details."""
    def __init__(self, code, details):
        self.code = code
        self.details = details


# ── Tenant store (PostgreSQL) ──────────────────────────────────


class TenantStore:
    """Production tenant store backed by PostgreSQL.

    Environment: DATABASE_URL (required).
    Schema: reuses HuFu's tenants table (001_initial_schema.up.sql).
    Atomically deducts via UPDATE ... WHERE ... RETURNING.
    """

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.getenv("DATABASE_URL")
        if not self.dsn:
            raise ValueError("DATABASE_URL environment variable is required")
        self._conn = None

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)
            self._conn.autocommit = True
            psycopg2.extras.register_default_jsonb(self._conn)
        return self._conn

    def ensure_tenant(self, api_key: str, name: str = "", tier: str = "free") -> dict:
        period = datetime.now(timezone.utc).strftime("%Y-%m")

        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO tenants (api_key, name, status)
                   VALUES (%s, %s, 1)
                   ON CONFLICT (api_key) DO NOTHING""",
                (api_key, name),
            )
            if cur.rowcount > 0:
                key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:8] + "..."
                logger.info("Tenant created: api_key=%s tier=%s", key_hash, tier)

            cur.execute(
                """UPDATE tenants
                   SET message_used = 0
                   WHERE api_key = %s AND period != %s""",
                (api_key, period),
            )

        return self._read_tenant(api_key)

    def check_and_deduct(self, api_key: str, method: str) -> None:
        """Raise QuotaExhaustedError if quota exhausted, otherwise deduct atomically.

        method: gRPC full path or MCP short name.
        """
        is_agent_create = method == GRPC_AGENT_CHECK or method == MCP_AGENT_CHECK
        is_billable = method in GRPC_BILLABLE or method in MCP_BILLABLE

        tenant = self.ensure_tenant(api_key)
        tier_cfg = TIERS.get(tenant.get("tier", "free"), TIERS["free"])

        if is_agent_create:
            limit = tier_cfg["agent_limit"]
            if limit != -1:
                with self.conn.cursor() as cur:
                    cur.execute(
                        """UPDATE tenants
                           SET agent_count = agent_count + 1
                           WHERE api_key = %s AND agent_count < %s
                           RETURNING agent_count""",
                        (api_key, limit),
                    )
                    if cur.fetchone() is None:
                        raise QuotaExhaustedError(
                            None,
                            f"Agent limit reached ({limit}). Upgrade tier.",
                        )

        elif is_billable:
            limit = tier_cfg["calls_limit"]
            with self.conn.cursor() as cur:
                cur.execute(
                    """UPDATE tenants
                       SET calls_used = calls_used + 1
                       WHERE api_key = %s AND calls_used < %s
                       RETURNING calls_used""",
                    (api_key, limit),
                )
                if cur.fetchone() is None:
                    raise QuotaExhaustedError(
                        None,
                        f"Monthly call limit reached ({limit:,}). "
                        f"Resets next billing period.",
                    )

    def get_usage(self, api_key: str) -> dict:
        tenant = self._read_tenant(api_key)
        tier_cfg = TIERS.get(tenant.get("tier", "free"), TIERS["free"])
        return {
            "tenant_name": tenant.get("name", ""),
            "agent_count": tenant.get("agent_count", 0),
            "agent_limit": tier_cfg["agent_limit"],
            "calls_used": tenant.get("calls_used", 0),
            "calls_limit": tier_cfg["calls_limit"],
            "current_period": tenant.get("period", ""),
            "tier": tenant.get("tier", "free"),
        }

    def register(self, name: str = "") -> str:
        """Generate a new API key, create tenant, return the key."""
        import secrets
        api_key = "fe-" + secrets.token_hex(12)
        self.ensure_tenant(api_key, name, "free")
        return api_key

    def list_agents(self, api_key: str) -> list[str]:
        """Return agent IDs owned by this tenant."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT agent_id FROM agents WHERE api_key = %s ORDER BY created_at""",
                (api_key,),
            )
            return [r[0] for r in cur.fetchall()]

    def add_agent(self, api_key: str, agent_id: str) -> None:
        """Record a new agent under this tenant."""
        with self.conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS agents (
                       agent_id TEXT PRIMARY KEY,
                       api_key TEXT NOT NULL REFERENCES tenants(api_key),
                       created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                   )"""
            )
            cur.execute(
                "INSERT INTO agents (agent_id, api_key) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (agent_id, api_key),
            )

    def _read_tenant(self, api_key: str) -> dict:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT api_key, name, tier,
                          agent_count, calls_used, period
                   FROM tenants WHERE api_key = %s""",
                (api_key,),
            )
            row = cur.fetchone()
            if row is None:
                return {}
            return {
                "api_key": row[0], "name": row[1], "tier": row[2],
                "agent_count": row[3], "calls_used": row[4], "period": row[5],
            }


# ── gRPC interceptor ──────────────────────────────────────────


def _abort(context, code, detail):
    context.abort(code, detail)
    return None


_METADATA_API_KEY = "x-api-key"


def make_billing_interceptor(store: TenantStore):
    """Factory: returns a BillingInterceptor class bound to the given store."""
    import grpc

    class _BillingInterceptor(grpc.ServerInterceptor):
        def intercept_service(self, continuation, handler_call_details):
            method = handler_call_details.method
            metadata = dict(handler_call_details.invocation_metadata or ())
            api_key = metadata.get(_METADATA_API_KEY, "")

            if not api_key:
                return grpc.unary_unary_rpc_method_handler(
                    lambda req, ctx: _abort(ctx, grpc.StatusCode.UNAUTHENTICATED,
                                            "Missing x-api-key in gRPC metadata")
                )

            if method in GRPC_BILLABLE or method == GRPC_AGENT_CHECK:
                original_handler = continuation(handler_call_details)

                def _quota_handler(request, context):
                    try:
                        store.check_and_deduct(api_key, method)
                    except QuotaExhaustedError as e:
                        context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, e.details)
                        return None
                    return original_handler.unary_unary(request, context)

                return grpc.unary_unary_rpc_method_handler(
                    _quota_handler,
                    request_deserializer=original_handler.request_deserializer,
                    response_serializer=original_handler.response_serializer,
                )

            return continuation(handler_call_details)

    return _BillingInterceptor


# ── Seed helper ────────────────────────────────────────────────


def seed_tenant(store: TenantStore, api_key: str, name: str = "dev", tier: str = "free") -> None:
    store.ensure_tenant(api_key, name, tier)
    logger.info("Tenant seeded: %s (tier=%s)", name, tier)
