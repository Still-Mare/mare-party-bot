-- 006_rename_points_per_hour.sql
-- 포인트 적립 단위를 '시간당'에서 '10분당'으로 변경.
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 누르세요.

-- ─── 컬럼 이름 변경 ───
ALTER TABLE guild_settings
    RENAME COLUMN points_per_hour TO points_per_10min;

-- ─── 기존 값 변환 (시간당 → 10분당: ÷ 6, 최솟값 1) ───
-- 예: 10 포인트/시간 → 2 포인트/10분 (≈ 같은 비율)
UPDATE guild_settings
    SET points_per_10min = GREATEST(1, ROUND(points_per_10min / 6.0))
    WHERE points_per_10min > 0;

-- ─── 신규 길드 기본값 2 포인트/10분 ───
ALTER TABLE guild_settings
    ALTER COLUMN points_per_10min SET DEFAULT 2;
