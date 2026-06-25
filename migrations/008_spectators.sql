-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 008: 관전 기능 (정원 초과 입장 + 닉네임 관전 표시)
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 하세요. (재실행 안전)
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- 모집별 관전자 (participants 정원과 완전히 분리)
CREATE TABLE IF NOT EXISTS spectators (
    recruit_id     BIGINT      NOT NULL REFERENCES recruits(id) ON DELETE CASCADE,
    user_id        BIGINT      NOT NULL,
    original_nick  TEXT,                          -- 관전 시작 시점의 원본 닉(접두사 제외). NULL=username
    joined_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (recruit_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_spectators_recruit ON spectators (recruit_id);
CREATE INDEX IF NOT EXISTS idx_spectators_user    ON spectators (user_id);
