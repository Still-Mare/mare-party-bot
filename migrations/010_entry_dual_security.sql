-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 010: 입장 경로 구분 + 오픈채팅 이중보안 게이트
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 하세요. (재실행 안전)
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- guild_settings: 오픈채팅 게이트 + 카카오 유입 초대코드
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS openchat_url          TEXT;     -- 카카오 오픈채팅 URL (채널엔 절대 안 올림, ephemeral 전용)
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS openchat_gate_role_id BIGINT;   -- 2차(오픈채팅) 통과 표시 역할 (선택)
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS kakao_invite_code     TEXT;     -- 카카오 유입용 초대코드 (route=kakao 판정 기준)
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS entry_marker_role_id  BIGINT;   -- 카카오 유입자에게 부여할 마커 역할 (선택)

-- 멤버 입장 경로 기록 (재입장 시 ON CONFLICT 로 갱신)
CREATE TABLE IF NOT EXISTS member_entry (
    guild_id     BIGINT      NOT NULL,
    user_id      BIGINT      NOT NULL,
    invite_code  TEXT,                              -- 판정된 초대코드 (모호 시 NULL)
    route_label  TEXT        NOT NULL DEFAULT 'unknown', -- 'discord' | 'kakao' | 'vanity' | 'unknown'
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_member_entry_route
    ON member_entry (guild_id, route_label);
