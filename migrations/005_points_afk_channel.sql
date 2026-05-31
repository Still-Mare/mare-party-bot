-- 005_points_afk_channel.sql
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 누르세요.

-- ─── guild_settings: 포인트 제외 채널 (잠수채널) 설정 ───
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS points_excluded_channel_id BIGINT;
