"""Billing interceptor — per-tenant quota enforcement on gRPC requests.

Tiered model (hybrid):
    free:      1,000 agents | 100,000 calls/month
    pro:      10,000 agents | 1,000,000 calls/month
    enterprise: unlimited agents | 10,000,000 calls/month

Billable RPCs:  Ingest, RetrieveAndRender
Free RPCs:      CreateAgent (checked against agent limit), DeleteAgent,
                ListAgents, DecayCycle, GetUsage

Storage: SQLite (swap to PostgreSQL for production).
"""

import hashlib
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import grpc

logger = logging.getLogger("billing")


# ── Tier config ────────────────────────────────────────────────


TIERS = {
    "free":       {"agent_limit": 1_000,   "calls_limit": 100_000},
    "pro":        {"agent_limit": 10_000,  "calls_limit": 1_000_000},
    "enterprise": {"agent_limit": -1,      "calls_limit": 10_000_000},
}

BILLABLE_METHODS = {
    "/forgetting_engine.ForgettingEngine/Ingest",
    "/forgetting_engine.ForgettingEngine/RetrieveAndRender",
}

AGENT_CREATE_METHOD = "/forgetting_engine.ForgettingEngine/CreateAgent"

_METADATA_API_KEY = "x-api-key"


# ── Tenant store (SQLite) ──────────────────────────────────────


class TenantStore:
    """Lightweight tenant registry. Mirrors the HuFu tenants table."""

    def __init__(self, db_path: str = "data/tenants.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS tenants (
                api_key      TEXT PRIMARY KEY,
                name         TEXT NOT NULL DEFAULT '',
                tier         TEXT NOT NULL DEFAULT 'free',
                agent_count  INTEGER NOT NULL DEFAULT 0,
                calls_used   INTEGER NOT NULL DEFAULT 0,
                period       TEXT NOT NULL DEFAULT '',   -- "2026-05"
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        self.conn.commit()

    def ensure_tenant(self, api_key: str, name: str = "", tier: str = "free") -> dict:
        """Idempotent tenant creation. Returns current usage."""
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO tenants (api_key, name, tier, period) VALUES (?, ?, ?, ?)",
            (api_key, name, tier, period),
        )
        if cur.rowcount > 0:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:8] + "..."
            logger.info("Tenant created: api_key=%s tier=%s", key_hash, tier)
            self.conn.commit()

        # Lazy monthly reset: only if the stored period is stale
        if cur.rowcount == 0:
            stored = self.conn.execute(
                "SELECT period FROM tenants WHERE api_key = ?", (api_key,)
            ).fetchone()
            if stored and stored["period"] != period:
                self.conn.execute(
                    "UPDATE tenants SET calls_used = 0, period = ? WHERE api_key = ?",
                    (period, api_key),
                )
                self.conn.commit()

        self.conn.commit()  # Close any pending transaction

        row = self.conn.execute(
            "SELECT * FROM tenants WHERE api_key = ?", (api_key,)
        ).fetchone()
        return dict(row) if row else {}

    def check_and_deduct(self, api_key: str, method: str) -> None:
        """Raise QuotaExhaustedError if quota exhausted, otherwise deduct atomically."""
        tenant = self.ensure_tenant(api_key)
        tier_cfg = TIERS.get(tenant.get("tier", "free"), TIERS["free"])

        if method == AGENT_CREATE_METHOD:
            limit = tier_cfg["agent_limit"]
            if limit != -1:
                cur = self.conn.execute(
                    "UPDATE tenants SET agent_count = agent_count + 1 "
                    "WHERE api_key = ? AND agent_count < ?",
                    (api_key, limit),
                )
                self.conn.commit()
                if cur.rowcount == 0:
                    raise QuotaExhaustedError(
                        grpc.StatusCode.RESOURCE_EXHAUSTED,
                        f"Agent limit reached ({limit}). "
                        f"Upgrade tier.",
                    )
            else:
                self.conn.execute(
                    "UPDATE tenants SET agent_count = agent_count + 1 WHERE api_key = ?",
                    (api_key,),
                )
                self.conn.commit()

        elif method in BILLABLE_METHODS:
            limit = tier_cfg["calls_limit"]
            cur = self.conn.execute(
                "UPDATE tenants SET calls_used = calls_used + 1 "
                "WHERE api_key = ? AND calls_used < ?",
                (api_key, limit),
            )
            self.conn.commit()
            if cur.rowcount == 0:
                raise QuotaExhaustedError(
                    grpc.StatusCode.RESOURCE_EXHAUSTED,
                    f"Monthly call limit reached ({limit:,}). "
                    f"Resets next billing period.",
                )

    def get_usage(self, api_key: str) -> dict:
        tenant = self.ensure_tenant(api_key)
        tier_cfg = TIERS.get(tenant.get("tier", "free"), TIERS["free"])
        return {
            "tenant_name": tenant.get("name", ""),
            "agent_count": tenant["agent_count"],
            "agent_limit": tier_cfg["agent_limit"],
            "calls_used": tenant["calls_used"],
            "calls_limit": tier_cfg["calls_limit"],
            "current_period": tenant.get("period", ""),
            "tier": tenant.get("tier", "free"),
        }


class QuotaExhaustedError(Exception):
    """Raised when a tenant exceeds their quota. Carries gRPC status code + details."""
    def __init__(self, code, details):
        self.code = code
        self.details = details


# ── gRPC interceptor ──────────────────────────────────────────


class BillingInterceptor(grpc.ServerInterceptor):
    """Intercept unary RPCs, validate api_key, enforce quota."""

    def __init__(self, tenant_store):
        self.store = tenant_store  # TenantStore | PostgresTenantStore（duck typing）

    def intercept_service(self, continuation, handler_call_details):
        method = handler_call_details.method
        metadata = dict(handler_call_details.invocation_metadata or ())

        api_key = metadata.get(_METADATA_API_KEY, "")

        if not api_key:
            return grpc.unary_unary_rpc_method_handler(
                lambda req, ctx: _abort(
                    ctx, grpc.StatusCode.UNAUTHENTICATED,
                    "Missing x-api-key in gRPC metadata"
                )
            )

        # Only intercept billable/free-checked methods
        if method in BILLABLE_METHODS or method == AGENT_CREATE_METHOD:
            original_handler = continuation(handler_call_details)

            def _quota_handler(request, context):
                try:
                    self.store.check_and_deduct(api_key, method)
                except QuotaExhaustedError as e:
                    context.abort(e.code, e.details)
                    return None
                return original_handler.unary_unary(request, context)

            return grpc.unary_unary_rpc_method_handler(
                _quota_handler,
                request_deserializer=original_handler.request_deserializer,
                response_serializer=original_handler.response_serializer,
            )

        return continuation(handler_call_details)


def _abort(context, code, detail):
    context.abort(code, detail)
    return None  # unreachable


# ── Seed helper (dev / onboarding) ────────────────────────────


def seed_dev_tenant(store: TenantStore, api_key: str, name: str = "dev", tier: str = "free") -> None:
    store.ensure_tenant(api_key, name, tier)
    logger.info("Dev tenant ready: %s (tier=%s)", name, tier)
