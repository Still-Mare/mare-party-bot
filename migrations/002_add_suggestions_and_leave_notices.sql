-- 002_add_suggestions_and_leave_notices.sql
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 누르세요.

-- 익명 건의함
CREATE TABLE IF NOT EXISTS suggestions (
    id              BIGSERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    author_id       BIGINT NOT NULL,                -- 서버 주인만 조회 가능
    content         TEXT   NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    public_msg_id   BIGINT                          -- 관리자 채널에 게시된 메시지 ID
);

-- 잠수 신고 (활동검토 면제)
CREATE TABLE IF NOT EXISTS leave_notices (
    id           BIGSERIAL PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    reason       TEXT,
    until_date   DATE   NOT NULL,
    status       TEXT   NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | expired
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by  BIGINT,
    reviewed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_leave_notices_active
  ON leave_notices (guild_id, user_id, status, until_date);
