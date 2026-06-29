-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 015: 뉴비 게이트 (입장 시 뉴비 역할 부여 → 오픈채팅 승인 시 제거)
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 하세요. (재실행 안전, 추가만 함)
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- 입장하면 자동 부여하는 뉴비 역할 (봇이 자동 생성해 저장). '권한받기' 채널만 보이게 하는 데 사용.
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS newbie_role_id BIGINT;

-- 뉴비 게이트 on/off (켜야 입장 시 뉴비 역할을 부여하고, 게이트 통과 시 제거)
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS newbie_gate_enabled SMALLINT NOT NULL DEFAULT 0;

-- '권한받기' 채널 (뉴비만 보이도록 봇이 오버라이드를 적용한 채널)
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS newbie_gate_channel_id BIGINT;
