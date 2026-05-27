"""PostgreSQL tenant store — production replacement for billing.TenantStore.

Environment variables:
    DATABASE_URL  (required, e.g. postgresql://user:pass@host:5432/dbname)

Uses the same `tenants` table schema from HuFu's 001_initial_schema.up.sql.
Atomically deducts quota via UPDATE ... WHERE ... AND ... RETURNING pattern.
"""

import hashlib
import logging
import os
from datetime import datetime, timezone

import grpc

from billing import QuotaExhaustedError  # shared exception

logger = logging.getLogger("billing_pg")


class PostgresTenantStore:
    """Production tenant store backed by PostgreSQL."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.getenv("DATABASE_URL")
        if not self.dsn:
            raise ValueError("DATABASE_URL environment variable is required")
        self._conn = None

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            import psycopg2
            import psycopg2.extras

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

            # Lazy monthly reset — runs in same tx, safe under concurrent writes
            cur.execute(
                """UPDATE tenants
                   SET message_used = 0
                   WHERE api_key = %s
                     AND period != %s""",
                (api_key, period),
            )

        return self._read_tenant(api_key)

    def check_and_deduct(self, api_key: str, method: str) -> None:
        from billing import AGENT_CREATE_METHOD, BILLABLE_METHODS, TIERS

        tenant = self.ensure_tenant(api_key)
        tier_cfg = TIERS.get(tenant.get("tier", "free"), TIERS["free"])

        if method == AGENT_CREATE_METHOD:
            limit = tier_cfg["agent_limit"]
            if limit != -1:
                with self.conn.cursor() as cur:
                    cur.execute(
                        """UPDATE tenants
                           SET message_quota = message_quota - 1
                           WHERE api_key = %s AND message_quota > 0
                           RETURNING message_quota""",
                        (api_key,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        raise QuotaExhaustedError(
                            grpc.StatusCode.RESOURCE_EXHAUSTED,
                            f"Agent limit reached ({limit}). Upgrade tier.",
                        )
            # enterprise unlimited — skip limit check

        elif method in BILLABLE_METHODS:
            limit = tier_cfg["calls_limit"]
            with self.conn.cursor() as cur:
                cur.execute(
                    """UPDATE tenants
                       SET message_used = message_used + 1
                       WHERE api_key = %s AND message_used < %s
                       RETURNING message_used""",
                    (api_key, limit),
                )
                row = cur.fetchone()
                if row is None:
                    raise QuotaExhaustedError(
                        grpc.StatusCode.RESOURCE_EXHAUSTED,
                        f"Monthly call limit reached ({limit:,}). "
                        f"Resets next billing period.",
                    )

    def get_usage(self, api_key: str) -> dict:
        from billing import TIERS

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
                "api_key": row[0],
                "name": row[1],
                "tier": row[2],
                "agent_count": row[3],
                "calls_used": row[4],
                "period": row[5],
            }
