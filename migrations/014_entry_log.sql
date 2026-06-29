-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 014: 출입로그 (입장/퇴장 이벤트 + 이벤트 시점 닉네임 저장)
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 하세요. (재실행 안전, 추가만 함)
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- 출입로그를 자동 게시할 채널 (선택). 없으면 채널 게시는 생략하고 패널 조회만 가능.
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS entry_log_channel_id BIGINT;

-- 입장/퇴장 이벤트 로그.
-- display_name 을 이벤트 시점에 저장해 두는 이유: 유저가 서버를 나가면
-- user_id 로 더 이상 닉네임을 조회할 수 없으므로, "최근까지 쓰던 별명"을 보존한다.
CREATE TABLE IF NOT EXISTS entry_log (
    id           BIGSERIAL   PRIMARY KEY,
    guild_id     BIGINT      NOT NULL,
    user_id      BIGINT      NOT NULL,
    display_name TEXT        NOT NULL,            -- 이벤트 시점의 별명(관전 접두사 제외)
    action       TEXT        NOT NULL,            -- 'join' | 'leave'
    route_label  TEXT,                            -- 입장 경로 (kakao/discord/vanity/unknown) · 퇴장 시 NULL
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 최근순 조회용
CREATE INDEX IF NOT EXISTS idx_entry_log_guild_time
    ON entry_log (guild_id, created_at DESC);

-- 이름 검색용 (대소문자 무시)
CREATE INDEX IF NOT EXISTS idx_entry_log_name
    ON entry_log (guild_id, lower(display_name));
