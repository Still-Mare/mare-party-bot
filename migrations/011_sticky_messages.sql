-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 011: 운영자 공지 스티키 (채널 하단 고정)
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 하세요. (재실행 안전)
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- 채널당 1개 스티키. guild_settings 가 아니라 별도 테이블 (채널당 1행)
CREATE TABLE IF NOT EXISTS sticky_messages (
    guild_id        BIGINT      NOT NULL,
    channel_id      BIGINT      NOT NULL,
    title           TEXT,
    content         TEXT        NOT NULL,
    image_url       TEXT,                           -- 선택: 임베드 이미지 URL
    last_message_id BIGINT,                          -- 현재 게시된 스티키 메시지 ID (재시작 후 삭제용)
    enabled         BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by      BIGINT,                          -- 설정한 관리자 ID
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_sticky_messages_enabled
    ON sticky_messages (guild_id)
    WHERE enabled = TRUE;
