-- 016: 음성 랭킹 조회용 인덱스
-- voice_ranking()이 guild_id 필터 + week/total_seconds 내림차순 정렬을 쓰는데
-- 지원 인덱스가 없어 데이터가 쌓이면 풀스캔·정렬 비용이 커진다.
-- (Supabase SQL Editor에서 수동 실행)

CREATE INDEX IF NOT EXISTS idx_voice_totals_week
    ON voice_totals (guild_id, week_seconds DESC);

CREATE INDEX IF NOT EXISTS idx_voice_totals_total
    ON voice_totals (guild_id, total_seconds DESC);
