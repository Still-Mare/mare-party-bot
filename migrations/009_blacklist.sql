-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 009: 블랙리스트 (디스코드 고유 user_id 기반)
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 하세요. (재실행 안전)
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- 블랙리스트 (이미 서버를 나간 유저도 ID로 등록 가능)
CREATE TABLE IF NOT EXISTS blacklist (
    guild_id    BIGINT      NOT NULL,
    user_id     BIGINT      NOT NULL,
    reason      TEXT,
    added_by    BIGINT,                          -- 등록한 관리자 user_id
    native_ban  SMALLINT    NOT NULL DEFAULT 0,  -- 1이면 Discord 네이티브 밴도 적용됨
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_blacklist_guild ON blacklist (guild_id);

-- 재입장 시 강퇴(0) / 밴(1) 기본 동작 토글
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS blacklist_ban_on_join SMALLINT NOT NULL DEFAULT 0;

-- 차단 직전 대상에게 DM 안내를 보낼지 (0=조치만, 1=DM 안내 후 조치)
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS blacklist_notify SMALLINT NOT NULL DEFAULT 1;
