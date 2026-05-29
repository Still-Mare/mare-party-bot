-- 003_indexes_and_idempotency.sql
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 누르세요.
-- IF NOT EXISTS 를 사용해 재실행해도 안전합니다.

-- ─── guild_settings: 활동검토 멱등성용 컬럼 ───
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS last_reviewed_at TIMESTAMPTZ;

-- ─── recruits: 자주 쓰이는 조회에 인덱스 추가 ───
-- list_open_recruit_ids(), open_recruits() 에서 status 필터
CREATE INDEX IF NOT EXISTS idx_recruits_guild_status
    ON recruits (guild_id, status);

-- find_recruit_by_voice() 에서 voice_channel_id 단일 조회
CREATE INDEX IF NOT EXISTS idx_recruits_voice_channel
    ON recruits (voice_channel_id)
    WHERE voice_channel_id IS NOT NULL;

-- ─── suggestions: get_suggestion_by_message() 에서 public_msg_id 조회 ───
CREATE INDEX IF NOT EXISTS idx_suggestions_public_msg
    ON suggestions (public_msg_id)
    WHERE public_msg_id IS NOT NULL;

-- ─── leave_notices: is_user_on_leave() 커버링 인덱스 (이미 있으면 무시) ───
CREATE INDEX IF NOT EXISTS idx_leave_notices_active
    ON leave_notices (guild_id, user_id, status, until_date);
