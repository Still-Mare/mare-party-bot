-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 012: 오픈채팅 운영자 승인제 (신청 → 운영자 승인 후 역할 부여)
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 하세요. (재실행 안전)
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- 오픈채팅 입장 신청
CREATE TABLE IF NOT EXISTS openchat_requests (
    id            BIGSERIAL   PRIMARY KEY,
    guild_id      BIGINT      NOT NULL,
    user_id       BIGINT      NOT NULL,
    status        TEXT        NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by   BIGINT,
    reviewed_at   TIMESTAMPTZ,
    review_msg_id BIGINT                                    -- 운영자 채널에 게시된 신청 메시지 ID
);

CREATE INDEX IF NOT EXISTS idx_openchat_requests_pending
    ON openchat_requests (guild_id, status);

-- 한 유저당 '대기 중' 신청은 1건만 (동시 클릭 중복 신청 방지)
CREATE UNIQUE INDEX IF NOT EXISTS uq_openchat_requests_one_pending
    ON openchat_requests (guild_id, user_id) WHERE status = 'pending';

-- 승인제 on/off + 신청을 받을 운영자 채널
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS openchat_approval_required  SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS openchat_request_channel_id BIGINT;
