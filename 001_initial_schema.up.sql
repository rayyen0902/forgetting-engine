-- 001_initial_schema.up.sql
-- 护肤Agent 核心表结构

-- 企业租户
CREATE TABLE IF NOT EXISTS tenants (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    api_key VARCHAR(64) NOT NULL UNIQUE,
    webhook_secret VARCHAR(128) NOT NULL DEFAULT '',
    message_quota BIGINT NOT NULL DEFAULT 10000,
    message_used BIGINT NOT NULL DEFAULT 0,
    contact_person VARCHAR(100) NOT NULL DEFAULT '',
    status SMALLINT NOT NULL DEFAULT 1,  -- 1=active 0=inactive
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tenants_api_key ON tenants(api_key);
CREATE INDEX idx_tenants_status ON tenants(status);

-- 顾客（关联租户）
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    external_id VARCHAR(128) NOT NULL,    -- 渠道用户ID
    channel VARCHAR(32) NOT NULL,          -- wecom/douyin/web
    nickname VARCHAR(100) NOT NULL DEFAULT '',
    avatar VARCHAR(500) NOT NULL DEFAULT '',
    phone VARCHAR(20) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, channel, external_id)
);

CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_users_channel ON users(tenant_id, channel);

-- 皮肤档案
CREATE TABLE IF NOT EXISTS skin_profiles (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    skin_type VARCHAR(32) NOT NULL DEFAULT '',       -- oily/dry/combination/normal/sensitive
    skin_concerns TEXT[] DEFAULT '{}',               -- acne,wrinkles,pores,spots,dullness,redness
    oil_level SMALLINT DEFAULT 0,                    -- 1-5
    hydration SMALLINT DEFAULT 0,                    -- 1-5
    sensitivity SMALLINT DEFAULT 0,                  -- 1-5
    pore_visible SMALLINT DEFAULT 0,                 -- 1-5
    wrinkle_level SMALLINT DEFAULT 0,                -- 1-5
    pigment_level SMALLINT DEFAULT 0,                -- 1-5
    photo_urls TEXT[] DEFAULT '{}',
    analysis_report TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_skin_profiles_user ON skin_profiles(user_id);

-- 产品（品牌方产品库）
CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(200) NOT NULL,
    category VARCHAR(50) NOT NULL DEFAULT '',        -- cleanser,toner,serum,moisturizer,sunscreen,mask
    skin_types TEXT[] DEFAULT '{}',
    ingredients TEXT[] DEFAULT '{}',
    usage_instruction TEXT DEFAULT '',
    price DECIMAL(10,2) DEFAULT 0,
    image_url VARCHAR(500) DEFAULT '',
    status SMALLINT NOT NULL DEFAULT 1,              -- 1=active 0=inactive
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_products_tenant ON products(tenant_id);
CREATE INDEX idx_products_category ON products(tenant_id, category);

-- 顾客护肤品库
CREATE TABLE IF NOT EXISTS user_products (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    product_name VARCHAR(200) NOT NULL,
    brand VARCHAR(100) NOT NULL DEFAULT '',
    category VARCHAR(50) NOT NULL DEFAULT '',
    usage_step SMALLINT DEFAULT 0,
    usage_time VARCHAR(10) DEFAULT 'both',           -- am/pm/both
    notes TEXT DEFAULT '',
    is_custom BOOLEAN DEFAULT TRUE,                  -- true=自填 false=品牌产品
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_products_user ON user_products(user_id);

-- 护肤日程
CREATE TABLE IF NOT EXISTS schedules (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    type VARCHAR(4) NOT NULL,                        -- am/pm
    steps JSONB NOT NULL DEFAULT '[]',               -- [{product_id,product_name,action,note}]
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, type)
);

CREATE INDEX idx_schedules_user ON schedules(user_id);

-- 对话记录
CREATE TABLE IF NOT EXISTS conversations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    channel VARCHAR(32) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'active',    -- active/closed
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conversations_user ON conversations(user_id);
CREATE INDEX idx_conversations_tenant ON conversations(tenant_id);

-- 消息记录（计费依据）
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id),
    role VARCHAR(16) NOT NULL,                       -- user/assistant
    content_type VARCHAR(16) NOT NULL DEFAULT 'text',-- text/image
    content TEXT NOT NULL DEFAULT '',
    billed BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_messages_created ON messages(created_at);

-- 计费记录
CREATE TABLE IF NOT EXISTS billing_records (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    period VARCHAR(7) NOT NULL,                      -- 月份，如 2026-05
    message_count BIGINT DEFAULT 0,
    free_used BIGINT DEFAULT 0,
    charged_count BIGINT DEFAULT 0,
    amount DECIMAL(10,2) DEFAULT 0,
    status SMALLINT DEFAULT 0,                       -- 0=unpaid 1=paid
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, period)
);

CREATE INDEX idx_billing_tenant ON billing_records(tenant_id);

-- 用户记忆事实（基于 Holographic 设计，多租户+多用户隔离）
CREATE TABLE IF NOT EXISTS facts (
    fact_id         BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES tenants(id),
    user_id         BIGINT NOT NULL REFERENCES users(id),
    content         TEXT NOT NULL,
    category        VARCHAR(32) DEFAULT 'general',
    trust_score     REAL DEFAULT 0.5,
    retrieval_count INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, user_id, content)
);

CREATE INDEX idx_facts_user ON facts(tenant_id, user_id);
CREATE INDEX idx_facts_trust ON facts(trust_score DESC);

-- 插入默认租户（用于开发测试）
INSERT INTO tenants (name, api_key, contact_person, status)
VALUES ('默认品牌', 'hufu-dev-api-key-001', '管理员', 1)
ON CONFLICT DO NOTHING;
