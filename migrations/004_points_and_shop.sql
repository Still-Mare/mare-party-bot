-- 004_points_and_shop.sql
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 누르세요.
-- IF NOT EXISTS / ADD COLUMN IF NOT EXISTS 로 재실행해도 안전합니다.

-- ─── 유저 포인트 잔액 ───
CREATE TABLE IF NOT EXISTS user_points (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    points   BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

-- ─── 상점 역할 아이템 ───
CREATE TABLE IF NOT EXISTS shop_roles (
    id        BIGSERIAL PRIMARY KEY,
    guild_id  BIGINT   NOT NULL,
    role_id   BIGINT   NOT NULL,
    cost      INTEGER  NOT NULL CHECK (cost > 0),
    label     TEXT,
    UNIQUE (guild_id, role_id)
);

-- ─── guild_settings: 시간당 포인트 설정 ───
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS points_per_hour INTEGER NOT NULL DEFAULT 10;

-- ─── 인덱스 ───
CREATE INDEX IF NOT EXISTS idx_user_points_guild
    ON user_points (guild_id);

CREATE INDEX IF NOT EXISTS idx_shop_roles_guild
    ON shop_roles (guild_id, cost);
