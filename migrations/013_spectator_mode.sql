-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 013: 관전 모드 재설계 (전역 관전 모드 + 호스트 위임 + 방치 모집글 자동정리)
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 Run 하세요. (재실행 안전, 추가만 함)
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- 관전자 역할 (전역 관전 모드 시 부여 / 파티 음성방 입장 권한). 없으면 봇이 자동 생성해 저장
ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS spectator_role_id BIGINT;

-- 모집 생성 시각 (음성방 없이 방치된 모집글 자동정리 기준)
ALTER TABLE recruits
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- 전역 관전 모드 상태 (켠 사람의 원본 닉 보관 → 끌 때 복원)
CREATE TABLE IF NOT EXISTS spectator_mode (
    guild_id      BIGINT      NOT NULL,
    user_id       BIGINT      NOT NULL,
    original_nick TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id)
);

-- 참고: 구버전 per-party `spectators` 테이블은 전역 관전 모드로 대체되어 더 이상 쓰지 않습니다.
--       데이터 보존을 위해 DROP 하지 않고 그대로 둡니다. (새 코드는 참조하지 않음)
