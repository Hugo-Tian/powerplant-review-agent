-- ============================================================
-- 电厂工单智能推送系统 数据库设计
-- PostgreSQL 15+
-- ============================================================

-- 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- 全文模糊搜索

-- ============================================================
-- 1. 基础字典表
-- ============================================================

CREATE TABLE device_types (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50) UNIQUE NOT NULL,   -- e.g. TURBINE
    name        VARCHAR(100) NOT NULL,          -- e.g. 汽轮机
    parent_id   INT REFERENCES device_types(id),
    sort_order  INT DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE manufacturers (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50) UNIQUE NOT NULL,
    name        VARCHAR(100) NOT NULL,
    country     VARCHAR(50),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE device_models (
    id              SERIAL PRIMARY KEY,
    manufacturer_id INT NOT NULL REFERENCES manufacturers(id),
    device_type_id  INT NOT NULL REFERENCES device_types(id),
    model_code      VARCHAR(100) NOT NULL,
    model_name      VARCHAR(200),
    spec_json       JSONB,                      -- 技术参数
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(manufacturer_id, model_code)
);

CREATE TABLE plants (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50) UNIQUE NOT NULL,
    name        VARCHAR(200) NOT NULL,
    location    VARCHAR(200),
    capacity_mw NUMERIC(10,2),
    status      VARCHAR(20) DEFAULT 'operating', -- operating/maintenance/shutdown
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE units (
    id          SERIAL PRIMARY KEY,
    plant_id    INT NOT NULL REFERENCES plants(id),
    unit_no     VARCHAR(20) NOT NULL,           -- #1 #2
    capacity_mw NUMERIC(10,2),
    status      VARCHAR(20) DEFAULT 'operating',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 2. 事件信息表
-- ============================================================

CREATE TABLE events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_no        VARCHAR(50) UNIQUE NOT NULL,  -- EVT-20250115-001
    plant_id        INT NOT NULL REFERENCES plants(id),
    unit_id         INT REFERENCES units(id),
    device_type_id  INT REFERENCES device_types(id),
    manufacturer_id INT REFERENCES manufacturers(id),
    model_id        INT REFERENCES device_models(id),
    kks_code        VARCHAR(100),               -- KKS设备编码
    title           VARCHAR(500) NOT NULL,
    content         TEXT NOT NULL,              -- 原始事件描述
    level           VARCHAR(20) NOT NULL CHECK (level IN ('紧急','重要','一般','建议')),
    event_type      VARCHAR(50),                -- 故障类型
    status          VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open','processing','closed')),
    occurred_at     TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_events_plant ON events(plant_id);
CREATE INDEX idx_events_occurred ON events(occurred_at DESC);
CREATE INDEX idx_events_level ON events(level);
CREATE INDEX idx_events_device_type ON events(device_type_id);
CREATE INDEX idx_events_manufacturer ON events(manufacturer_id);
CREATE INDEX idx_events_content_gin ON events USING gin(to_tsvector('simple', content));

-- 事件附件
CREATE TABLE event_attachments (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id    UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    file_name   VARCHAR(500) NOT NULL,
    file_type   VARCHAR(50),
    file_size   BIGINT,
    storage_url VARCHAR(1000) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 3. NLP 标签表
-- ============================================================

CREATE TABLE tags (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(100) UNIQUE NOT NULL,
    name        VARCHAR(200) NOT NULL,
    category    VARCHAR(50) NOT NULL CHECK (category IN (
                  'device_type','manufacturer','model','fault_type',
                  'keyword','component','action','symptom','kks')),
    weight      NUMERIC(5,4) DEFAULT 1.0,       -- 标签权重
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tags_category ON tags(category);

-- 事件-标签关联（NLP提取结果）
CREATE TABLE event_tags (
    id              BIGSERIAL PRIMARY KEY,
    event_id        UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    tag_id          INT NOT NULL REFERENCES tags(id),
    confidence      NUMERIC(5,4) NOT NULL DEFAULT 1.0,  -- NLP置信度 0~1
    extract_method  VARCHAR(50) DEFAULT 'nlp',           -- nlp/rule/manual
    extracted_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(event_id, tag_id)
);

CREATE INDEX idx_event_tags_event ON event_tags(event_id);
CREATE INDEX idx_event_tags_tag ON event_tags(tag_id);

-- NLP 提取任务记录
CREATE TABLE nlp_extract_jobs (
    id          BIGSERIAL PRIMARY KEY,
    event_id    UUID NOT NULL REFERENCES events(id),
    model_ver   VARCHAR(50) NOT NULL,           -- NLP模型版本
    status      VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending','running','done','failed')),
    raw_result  JSONB,                          -- 模型原始输出
    token_count INT,
    duration_ms INT,
    error_msg   TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

-- ============================================================
-- 4. 用户与权限表
-- ============================================================

CREATE TABLE departments (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    plant_id    INT REFERENCES plants(id),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    emp_no          VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(100) NOT NULL,
    department_id   INT REFERENCES departments(id),
    plant_id        INT REFERENCES plants(id),
    role            VARCHAR(50),                -- 汽轮机专工/运行值长/检修工程师
    shift_group     VARCHAR(20),                -- 班组 A/B/C/D
    responsible_units JSONB,                   -- ["#1","#2"]
    email           VARCHAR(200),
    phone           VARCHAR(50),
    push_enabled    BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ
);

-- ============================================================
-- 5. 用户行为记录表
-- ============================================================

CREATE TABLE user_behaviors (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES users(id),
    session_id          VARCHAR(100),
    page_url            VARCHAR(500),
    module              VARCHAR(100),           -- 事件信息库/状态报告/工单管理
    action_type         VARCHAR(50) NOT NULL CHECK (action_type IN (
                          'query','detail','export','download','share','print')),
    query_content       TEXT,                   -- 查询关键词原文
    query_fields        JSONB,                  -- 结构化查询条件
    selected_event_id   UUID REFERENCES events(id),
    data_type_tags      JSONB,                  -- 命中的数据标签
    result_count        INT,                    -- 查询结果条数
    enter_time          TIMESTAMPTZ NOT NULL,
    leave_time          TIMESTAMPTZ,
    stay_duration_sec   INT GENERATED ALWAYS AS (
                          EXTRACT(EPOCH FROM (leave_time - enter_time))::INT
                        ) STORED,
    mouse_max_stay_sec  INT,                    -- 鼠标最长悬停时长(秒)
    scroll_depth_pct    INT,                    -- 滚动深度 0~100
    click_positions     JSONB,                  -- 点击热力坐标
    ip_address          INET,
    user_agent          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_behaviors_user ON user_behaviors(user_id);
CREATE INDEX idx_behaviors_enter ON user_behaviors(enter_time DESC);
CREATE INDEX idx_behaviors_action ON user_behaviors(action_type);
CREATE INDEX idx_behaviors_event ON user_behaviors(selected_event_id) WHERE selected_event_id IS NOT NULL;

-- ============================================================
-- 6. 用户画像表
-- ============================================================

CREATE TABLE user_profiles (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID UNIQUE NOT NULL REFERENCES users(id),
    -- 设备偏好 (tag_id → weight)
    device_interests    JSONB DEFAULT '{}',
    -- 厂家偏好
    mfr_interests       JSONB DEFAULT '{}',
    -- 故障类型关注
    fault_interests     JSONB DEFAULT '{}',
    -- 关键词兴趣
    keyword_interests   JSONB DEFAULT '{}',
    -- 个性化标签列表
    personal_tags       JSONB DEFAULT '[]',
    -- 画像得分向量（用于余弦相似度匹配）
    profile_vector      JSONB DEFAULT '[]',
    -- 统计摘要
    total_behaviors     INT DEFAULT 0,
    active_days_30      INT DEFAULT 0,
    avg_stay_sec        INT DEFAULT 0,
    last_computed_at    TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 7. 推送结果表
-- ============================================================

CREATE TABLE push_results (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id),
    event_id        UUID NOT NULL REFERENCES events(id),
    push_date       DATE NOT NULL DEFAULT CURRENT_DATE,
    match_score     NUMERIC(5,4) NOT NULL,       -- 0~1
    score_breakdown JSONB,                        -- 各维度得分明细
    push_reasons    JSONB,                        -- 推送原因文本列表
    push_type       VARCHAR(50),                  -- personal/device_group/emergency
    is_read         BOOLEAN DEFAULT FALSE,
    read_at         TIMESTAMPTZ,
    is_clicked      BOOLEAN DEFAULT FALSE,
    clicked_at      TIMESTAMPTZ,
    feedback        VARCHAR(20),                  -- like/dislike/irrelevant
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, event_id, push_date)
);

CREATE INDEX idx_push_user_date ON push_results(user_id, push_date DESC);
CREATE INDEX idx_push_score ON push_results(match_score DESC);

-- ============================================================
-- 8. 推送配置表
-- ============================================================

CREATE TABLE push_configs (
    id                  SERIAL PRIMARY KEY,
    user_id             UUID UNIQUE NOT NULL REFERENCES users(id),
    score_threshold     NUMERIC(5,4) DEFAULT 0.60,
    max_push_per_day    INT DEFAULT 20,
    -- 维度权重
    weight_device_type  NUMERIC(5,4) DEFAULT 0.35,
    weight_behavior     NUMERIC(5,4) DEFAULT 0.30,
    weight_role         NUMERIC(5,4) DEFAULT 0.20,
    weight_manufacturer NUMERIC(5,4) DEFAULT 0.15,
    -- 推送时间窗口
    push_window_start   TIME DEFAULT '07:30',
    push_window_end     TIME DEFAULT '09:00',
    -- 渠道开关
    channel_in_app      BOOLEAN DEFAULT TRUE,
    channel_mobile      BOOLEAN DEFAULT TRUE,
    channel_email       BOOLEAN DEFAULT FALSE,
    channel_sms         BOOLEAN DEFAULT FALSE,
    -- 紧急事件实时推送
    emergency_realtime  BOOLEAN DEFAULT TRUE,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 触发器：更新 updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_events_updated_at       BEFORE UPDATE ON events        FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_user_profiles_updated   BEFORE UPDATE ON user_profiles  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_push_configs_updated    BEFORE UPDATE ON push_configs   FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- 种子数据（示例）
-- ============================================================
INSERT INTO device_types(code,name) VALUES
  ('TURBINE','汽轮机'),('GENERATOR','发电机'),('EXCITER','励磁系统'),
  ('TRANSFORMER','变压器'),('BOILER','锅炉'),('FWP','给水泵'),
  ('CWP','循环水泵'),('CONDENSER','凝汽器'),('ACC','空冷系统'),
  ('SCR','脱硝系统'),('FGD','脱硫系统'),('ESP','除尘器');

INSERT INTO manufacturers(code,name,country) VALUES
  ('DFST','东方汽轮机','CN'),('HARBIN','哈电集团','CN'),
  ('SEC','上海电气','CN'),('NARI','南瑞继保','CN'),
  ('TBEA','特变电工','CN'),('XATR','西安变压器','CN');
