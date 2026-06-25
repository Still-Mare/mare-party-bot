-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 007: 셀프 닉네임 변경 + 변경 이력
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 하세요. (재실행 안전)
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- 닉네임 변경 이력 (old → new, 누가·언제)
CREATE TABLE IF NOT EXISTS nickname_history (
    id          BIGSERIAL   PRIMARY KEY,
    guild_id    BIGINT      NOT NULL,
    user_id     BIGINT      NOT NULL,
    old_nick    TEXT,
    new_nick    TEXT,
    changed_by  BIGINT      NOT NULL,        -- 변경을 실행한 유저 (셀프=user_id, 관리자 대행 시 다름)
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nickname_history_guild_user
    ON nickname_history (guild_id, user_id, changed_at DESC);

-- 닉네임 변경 로그를 게시할 관리자 채널 (선택)
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS nickname_log_channel_id BIGINT;
