# 🎮 파티 모집 디스코드 봇

게임 서버용 봇. 버튼만으로 게임 역할 받기 / 파티 모집 / 음성 이용시간 통계 / 포인트 상점을 모두 사용할 수 있어요. 명령어를 외울 필요가 없어요.

## 기능

| 기능 | 설명 |
|------|------|
| 🎮 게임 역할 | 버튼으로 게임 역할을 받거나 뺌. 받으면 해당 게임 모집 알림이 옴 |
| ➕ 게임 추가/삭제 | 관리자가 버튼으로 게임 등록 → 역할 자동 생성. 서버 커스텀 이모지 드롭다운 선택 지원 |
| 📢 파티 모집 | 게임 선택 → 시간/인원/메모 입력 → 모집글 게시 + 역할 멘션 |
| ✋ 참가/취소 | 버튼으로 참가, 본인만 참가 취소 가능, 명단 실시간 갱신 |
| 🔒 마감 | 모집자/관리자가 마감 |
| 🔊 음성방 열기 | 모집글 버튼으로 음성방 자동 생성 (참가자만 입장 가능, 지정 카테고리 아래) |
| 📦 자동 종료 | 음성방 전원 퇴장 시 → 방 삭제 + 모집글을 아카이브 채널로 이동 + 스레드 삭제 |
| 🔊 음성 통계 | 음성채널 이용시간 자동 추적, 내 시간/주간 랭킹 조회 |
| 🪙 포인트 상점 | 음성채널 이용 시 10분당 포인트 자동 적립. 포인트로 역할 구매 |
| 📋 활동 검토 | 매주 음성시간 검토 → 기준 미달 시 DM 경고(2회) → 3회째 강퇴 후보 분류 |
| 🛡️ 안전장치 | 신규원(1주 미만)·면제역할 자동 제외, 강퇴는 관리자 버튼 승인 필수 |
| 🔓 규칙 인증 | 버튼 클릭으로 인증 역할 자동 지급 |
| 📨 익명 건의함 | 버튼 → 모달로 익명 건의 → 관리자 채널 게시. 작성자는 서버 주인만 확인 가능 |
| 🕊️ 잠수 신고 | 활동검토 면제 신청 (3일/1주/2주/1개월 또는 날짜 직접 입력). 관리자 승인식 |
| 🔐 입장 이중보안 | 카카오 오픈채팅 URL을 채널에 안 올리고, 인증 통과자에게만 본인에게만 보이는 메시지로 전달 → 초대코드 정지 회피. 카카오/디스코드 유입 경로 자동 구분. (선택) 운영자 승인제 — 신청 → 운영자가 카톡 입장 확인 후 승인 |
| 🚫 블랙리스트 | 디스코드 고유 ID 기반 차단. 이미 나간 유저도 ID로 등록해 재입장 차단(강퇴/밴 토글, 네이티브 밴 옵션) |
| 👀 관전 | 파티 정원이 차도 관전자는 음성방 입장 가능, 닉네임 앞에 "관전 " 표시 (종료 시 자동 복원) |
| ✏️ 셀프 닉네임 | 서버가 별명 변경을 막아둬도 봇이 대신 변경. old→new 변경 이력 기록·조회 |
| 📌 스티키 공지 | 운영자 공지를 채널 맨 아래에 항상 고정 (새 글이 올라오면 자동 재게시) |

---

## 1. 디스코드 봇 만들기

1. https://discord.com/developers/applications 접속 → **New Application**
2. 왼쪽 **Bot** 탭 → **Reset Token** → 토큰 복사 (이게 `DISCORD_TOKEN`)
3. 같은 화면에서 **Privileged Gateway Intents** 두 개 켜기:
   - ✅ **Server Members Intent**
   - ✅ **Presence Intent** 는 불필요, 끄세요
4. 왼쪽 **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Manage Roles`, `Manage Channels`, `Move Members`, `Kick Members`, `Send Messages`, `Embed Links`, `Read Message History`, `Use Slash Commands`, `Manage Nicknames`, `Manage Server`, `Manage Messages`, `Ban Members`
   - 생성된 URL로 봇을 서버에 초대

> ⚠️ 봇 역할이 게임 역할·관리 대상 멤버보다 **위에** 있어야 역할/닉네임 부여가 동작해요.
> ⚠️ `Manage Channels` + `Move Members` 권한이 있어야 음성방 자동 생성/삭제가 동작해요.
> ⚠️ `Kick Members` 권한은 활동검토 강퇴·블랙리스트 강퇴에 필요해요.
> ⚠️ `Manage Nicknames` = 관전 표시·셀프 닉네임 변경, `Manage Server` = 입장 경로(초대코드) 추적, `Manage Messages` = 스티키 재게시, `Ban Members` = 블랙리스트 네이티브 밴 옵션. **권한이 없어도 봇은 죽지 않고 안내만 띄워요(graceful).**
> ✅ 이번 기능들은 모두 버튼/패널로 동작해 **새 슬래시 명령이 없어요 → `SYNC_COMMANDS` 재배포 불필요**.

---

## 2. 데이터베이스 (Supabase)

이 봇은 **Supabase(PostgreSQL)** 에 데이터를 저장해요. Railway 재배포 시에도 데이터가 보존돼요.

### 2-1. Supabase 프로젝트 만들기

1. https://supabase.com → 로그인 → **New Project**
2. 프로젝트 이름·DB 비밀번호 설정 후 생성 (1~2분 소요)

### 2-2. 연결 문자열 얻기

1. Supabase 대시보드 → 프로젝트 선택 → **Project Settings → Database**
2. **Connection string → Transaction pooler** 의 URI 복사
   - 형식: `postgresql://postgres.PROJECT_REF:비밀번호@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres`
   - `[YOUR-PASSWORD]` 부분을 DB 생성 시 정한 비밀번호로 교체
   - 비밀번호를 잊었으면 **Reset database password** 로 재설정
3. 이 문자열 전체를 환경변수 `DATABASE_URL` 에 넣어요

> ⚠️ 포트 `6543` (Transaction pooler) 를 사용해야 해요. Direct connection(5432)은 봇 재시작 시 연결이 끊길 수 있어요.

### 2-3. 테이블 생성 (처음 설치)

**Supabase 대시보드 → SQL Editor** 에 아래 SQL 전체를 붙여넣고 **Run** 하세요.
`IF NOT EXISTS` 구문이라 이미 테이블이 있어도 안전하게 재실행할 수 있어요.

```sql
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 파티 모집 봇 — 전체 스키마 (처음 설치용)
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- ─── 게임 목록 ───────────────────────────────────
CREATE TABLE IF NOT EXISTS games (
    guild_id BIGINT NOT NULL,
    name     TEXT   NOT NULL,
    emoji    TEXT,
    role_id  BIGINT,
    PRIMARY KEY (guild_id, name)
);

-- ─── 파티 모집글 ─────────────────────────────────
CREATE TABLE IF NOT EXISTS recruits (
    id               BIGSERIAL PRIMARY KEY,
    guild_id         BIGINT  NOT NULL,
    channel_id       BIGINT  NOT NULL,
    message_id       BIGINT,
    host_id          BIGINT  NOT NULL,
    game_name        TEXT,
    play_time        TEXT,
    max_players      INTEGER,
    note             TEXT,
    status           TEXT    NOT NULL DEFAULT 'open',  -- open | closed | archived
    voice_channel_id BIGINT,
    temp_role_id     BIGINT
);

-- ─── 파티 참가자 ─────────────────────────────────
CREATE TABLE IF NOT EXISTS participants (
    recruit_id BIGINT      NOT NULL REFERENCES recruits(id) ON DELETE CASCADE,
    user_id    BIGINT      NOT NULL,
    joined_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (recruit_id, user_id)
);

-- ─── 음성채널 현재 세션 (접속 중 추적용) ──────────
CREATE TABLE IF NOT EXISTS voice_sessions (
    guild_id  BIGINT      NOT NULL,
    user_id   BIGINT      NOT NULL,
    joined_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- ─── 음성채널 누적 통계 ──────────────────────────
CREATE TABLE IF NOT EXISTS voice_totals (
    guild_id      BIGINT NOT NULL,
    user_id       BIGINT NOT NULL,
    total_seconds BIGINT NOT NULL DEFAULT 0,
    week_seconds  BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

-- ─── 길드별 설정 ─────────────────────────────────
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id                    BIGINT  PRIMARY KEY,
    voice_category_id           BIGINT,               -- 음성방 생성 카테고리
    archive_channel_id          BIGINT,               -- 종료된 모집글 보관 채널
    review_log_channel          BIGINT,               -- 활동검토 결과 로그 채널
    exempt_role_id              BIGINT,               -- 활동검토 면제 역할
    min_seconds                 INTEGER NOT NULL DEFAULT 10800,  -- 주간 최소 음성시간(초), 기본 3시간
    auto_kick_enabled           INTEGER NOT NULL DEFAULT 0,      -- 강퇴 승인 모드 on/off
    panel_manager_role          BIGINT,               -- /패널 명령어 허용 역할
    verified_role_id            BIGINT,               -- 규칙 인증 시 지급 역할
    last_reviewed_at            TIMESTAMPTZ,          -- 마지막 활동검토 실행 시각
    recruit_post_channel_id     BIGINT,               -- 모집글 전용 게시 채널
    points_per_10min            INTEGER NOT NULL DEFAULT 2,      -- 10분당 지급 포인트
    points_excluded_channel_id  BIGINT,              -- 포인트 미지급 채널 (잠수채널)
    nickname_log_channel_id     BIGINT,              -- 닉네임 변경 로그 채널 (007)
    blacklist_ban_on_join       SMALLINT NOT NULL DEFAULT 0,  -- 재입장 차단: 0=강퇴 1=밴 (009)
    blacklist_notify            SMALLINT NOT NULL DEFAULT 1,  -- 차단 전 DM 안내 여부 (009)
    openchat_url                TEXT,                -- 카카오 오픈채팅 URL (채널 미게시, ephemeral 전용) (010)
    openchat_gate_role_id       BIGINT,              -- 오픈채팅 게이트 통과 역할 (010)
    kakao_invite_code           TEXT,                -- 카카오 유입용 초대코드 (010)
    entry_marker_role_id        BIGINT,              -- 카카오 유입자 마커 역할 (010)
    openchat_approval_required  SMALLINT NOT NULL DEFAULT 0,  -- 오픈채팅 운영자 승인제 on/off (012)
    openchat_request_channel_id BIGINT               -- 오픈채팅 신청을 받을 운영자 채널 (012)
);

-- ─── 활동 경고 누적 ──────────────────────────────
CREATE TABLE IF NOT EXISTS activity_warnings (
    guild_id    BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    strikes     INTEGER NOT NULL DEFAULT 0,
    last_review TIMESTAMPTZ,
    PRIMARY KEY (guild_id, user_id)
);

-- ─── 익명 건의함 ─────────────────────────────────
CREATE TABLE IF NOT EXISTS suggestions (
    id            BIGSERIAL   PRIMARY KEY,
    guild_id      BIGINT      NOT NULL,
    author_id     BIGINT      NOT NULL,
    content       TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    public_msg_id BIGINT
);

-- ─── 잠수 신고 ───────────────────────────────────
CREATE TABLE IF NOT EXISTS leave_notices (
    id          BIGSERIAL   PRIMARY KEY,
    guild_id    BIGINT      NOT NULL,
    user_id     BIGINT      NOT NULL,
    reason      TEXT,
    until_date  DATE        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | expired
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by BIGINT,
    reviewed_at TIMESTAMPTZ
);

-- ─── 포인트 잔액 ─────────────────────────────────
CREATE TABLE IF NOT EXISTS user_points (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    points   BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

-- ─── 포인트 상점 역할 ─────────────────────────────
CREATE TABLE IF NOT EXISTS shop_roles (
    id        BIGSERIAL PRIMARY KEY,
    guild_id  BIGINT    NOT NULL,
    role_id   BIGINT    NOT NULL,
    cost      INTEGER   NOT NULL CHECK (cost > 0),
    label     TEXT,
    UNIQUE (guild_id, role_id)
);

-- ─── 닉네임 변경 이력 (007) ──────────────────────
CREATE TABLE IF NOT EXISTS nickname_history (
    id          BIGSERIAL   PRIMARY KEY,
    guild_id    BIGINT      NOT NULL,
    user_id     BIGINT      NOT NULL,
    old_nick    TEXT,
    new_nick    TEXT,
    changed_by  BIGINT      NOT NULL,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── 관전자 (008) ────────────────────────────────
CREATE TABLE IF NOT EXISTS spectators (
    recruit_id     BIGINT      NOT NULL REFERENCES recruits(id) ON DELETE CASCADE,
    user_id        BIGINT      NOT NULL,
    original_nick  TEXT,
    joined_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (recruit_id, user_id)
);

-- ─── 블랙리스트 (009) ────────────────────────────
CREATE TABLE IF NOT EXISTS blacklist (
    guild_id    BIGINT      NOT NULL,
    user_id     BIGINT      NOT NULL,
    reason      TEXT,
    added_by    BIGINT,
    native_ban  SMALLINT    NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id)
);

-- ─── 멤버 입장 경로 (010) ────────────────────────
CREATE TABLE IF NOT EXISTS member_entry (
    guild_id     BIGINT      NOT NULL,
    user_id      BIGINT      NOT NULL,
    invite_code  TEXT,
    route_label  TEXT        NOT NULL DEFAULT 'unknown',  -- discord | kakao | vanity | unknown
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id)
);

-- ─── 스티키 공지 (011) ───────────────────────────
CREATE TABLE IF NOT EXISTS sticky_messages (
    guild_id        BIGINT      NOT NULL,
    channel_id      BIGINT      NOT NULL,
    title           TEXT,
    content         TEXT        NOT NULL,
    image_url       TEXT,
    last_message_id BIGINT,
    enabled         BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by      BIGINT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, channel_id)
);

-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 인덱스
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CREATE INDEX IF NOT EXISTS idx_recruits_guild_status
    ON recruits (guild_id, status);

CREATE INDEX IF NOT EXISTS idx_recruits_voice_channel
    ON recruits (voice_channel_id)
    WHERE voice_channel_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_suggestions_public_msg
    ON suggestions (public_msg_id)
    WHERE public_msg_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leave_notices_active
    ON leave_notices (guild_id, user_id, status, until_date);

CREATE INDEX IF NOT EXISTS idx_user_points_guild
    ON user_points (guild_id);

CREATE INDEX IF NOT EXISTS idx_shop_roles_guild
    ON shop_roles (guild_id, cost);

CREATE INDEX IF NOT EXISTS idx_nickname_history_guild_user
    ON nickname_history (guild_id, user_id, changed_at DESC);

CREATE INDEX IF NOT EXISTS idx_spectators_recruit ON spectators (recruit_id);
CREATE INDEX IF NOT EXISTS idx_spectators_user    ON spectators (user_id);

CREATE INDEX IF NOT EXISTS idx_blacklist_guild ON blacklist (guild_id);

CREATE INDEX IF NOT EXISTS idx_member_entry_route
    ON member_entry (guild_id, route_label);

CREATE INDEX IF NOT EXISTS idx_sticky_messages_enabled
    ON sticky_messages (guild_id)
    WHERE enabled = TRUE;

-- ─── 오픈채팅 입장 신청 (012) ───────────────────
CREATE TABLE IF NOT EXISTS openchat_requests (
    id            BIGSERIAL   PRIMARY KEY,
    guild_id      BIGINT      NOT NULL,
    user_id       BIGINT      NOT NULL,
    status        TEXT        NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by   BIGINT,
    reviewed_at   TIMESTAMPTZ,
    review_msg_id BIGINT
);
CREATE INDEX IF NOT EXISTS idx_openchat_requests_pending
    ON openchat_requests (guild_id, status);
```

### 2-4. 테이블 설명

| 테이블 | 역할 |
|--------|------|
| `games` | 서버별 게임 목록 (이름·이모지·연결 역할 ID) |
| `recruits` | 파티 모집글 (게임명·인원·시간·상태) |
| `participants` | 모집글별 참가자 목록 |
| `voice_sessions` | 현재 음성채널에 접속 중인 세션 (입장 시각 기록용, 봇 재시작 시 복원) |
| `voice_totals` | 유저별 음성 이용시간 누적 (전체 / 이번 주) |
| `guild_settings` | 서버별 모든 설정값 (채널·역할·검토 기준·포인트 설정 등) |
| `activity_warnings` | 활동검토 경고 누적 횟수 |
| `suggestions` | 익명 건의 내용 (author_id는 서버 주인만 조회 가능) |
| `leave_notices` | 잠수 신고 내역 (기간·사유·승인 상태) |
| `user_points` | 서버별 유저 포인트 잔액 |
| `shop_roles` | 포인트로 구매 가능한 역할과 가격 |
| `nickname_history` | 닉네임 변경 이력 (old→new, 변경자·시각) |
| `spectators` | 모집별 관전자 + 관전 시작 시점의 원본 닉네임 |
| `blacklist` | 디스코드 ID 기반 차단 목록 (사유·등록자·네이티브밴 여부) |
| `member_entry` | 멤버 입장 경로 기록 (kakao/discord/vanity/unknown) |
| `sticky_messages` | 채널별 스티키 공지 (내용·현재 메시지 ID·on/off) |
| `openchat_requests` | 오픈채팅 입장 신청 (승인제 ON일 때 운영자 승인 대기열) |

### 2-5. 마이그레이션 (기존 설치 업데이트)

**처음 설치라면 2-3의 전체 스키마 SQL만 실행하면 돼요.**
이미 운영 중인 봇에 업데이트를 적용할 때는 `migrations/` 폴더의 파일을 순서대로 실행하세요.

| 파일 | 적용 내용 |
|------|-----------|
| `002_add_suggestions_and_leave_notices.sql` | 익명 건의함·잠수 신고 테이블 추가 |
| `003_indexes_and_idempotency.sql` | 성능 인덱스 추가, `last_reviewed_at` 컬럼 추가 |
| `004_points_and_shop.sql` | `user_points`·`shop_roles` 테이블 추가, `points_per_10min` 컬럼 추가 |
| `005_points_afk_channel.sql` | `points_excluded_channel_id` (잠수채널) 컬럼 추가 |
| `006_rename_points_per_hour.sql` | `points_per_hour` → `points_per_10min` rename, 기존 값 단위 변환 |
| `007_self_nickname.sql` | `nickname_history` 테이블 + `nickname_log_channel_id` 컬럼 |
| `008_spectators.sql` | `spectators` 테이블 (관전 기능) |
| `009_blacklist.sql` | `blacklist` 테이블 + `blacklist_ban_on_join`·`blacklist_notify` 컬럼 |
| `010_entry_dual_security.sql` | `member_entry` 테이블 + 오픈채팅/카카오 관련 4개 컬럼 |
| `011_sticky_messages.sql` | `sticky_messages` 테이블 (스티키 공지) |
| `012_openchat_approval.sql` | `openchat_requests` 테이블 + 오픈채팅 운영자 승인제 컬럼 2개 |

> `002~005`, `007~011` 은 `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` 구문이라 **재실행해도 안전**해요.
> ⚠️ 단 `006` 은 값 변환(`÷6`)이 들어 있어 **한 번만 실행**해야 해요. 다시 실행하면 포인트가 또 나눠져요. (각 마이그레이션은 순서대로 1회씩만 실행하면 됩니다.)

---

## 3. 로컬에서 테스트

```bash
pip install -r requirements.txt

export DISCORD_TOKEN="봇_토큰"
export DATABASE_URL="postgresql://postgres.xxx:비밀번호@...pooler.supabase.com:6543/postgres"

python bot.py
```

봇이 켜지면 채널에서 슬래시 명령어로 패널을 설치하세요:

| 명령어 | 설치되는 패널 |
|--------|---------------|
| `/패널 종류:파티모집` | 파티 모집 패널 |
| `/패널 종류:게임역할` | 게임 역할 패널 |
| `/패널 종류:내활동` | 음성시간·익명건의·잠수신고 패널 |
| `/패널 종류:관리자` | 서버 설정 관리자 패널 |
| `/포인트상점` | 포인트 상점 유저 패널 |
| `/포인트상점설정` | 포인트 상점 관리자 패널 |
| `/인증패널` | 규칙 인증 버튼 패널 |

> **슬래시 명령어가 보이지 않을 때**: 환경변수 `SYNC_COMMANDS=true` 설정 후 1회 재시작, 동기화 완료 후 `false` 로 되돌리세요.

초기 설정 순서:
1. **관리자 패널 → ➕ 게임 추가** — 게임 이름 + 이모지 등록
2. **관리자 패널 → 채널 설정** — 음성방 카테고리, 아카이브 채널, 모집글 채널 지정
3. **`/포인트상점설정` → 🪙 10분당 포인트** — 포인트 적립 비율 설정 (기본 2포인트/10분)
4. **`/포인트상점설정` → ➕ 역할 추가** — 구매 가능한 역할과 가격 등록

---

## 4. Railway 배포 (24시간 구동)

1. 이 폴더를 GitHub 저장소로 push
2. https://railway.app → **New Project → Deploy from GitHub repo**
3. 저장소 선택
4. **Variables** 탭에서 환경변수 두 개 추가:
   - `DISCORD_TOKEN` = 봇 토큰
   - `DATABASE_URL` = Supabase 연결 문자열
5. 자동으로 `Procfile` 의 `worker: python bot.py` 가 실행됨

> 데이터는 Supabase에 있으니 재배포해도 게임 목록·포인트·경고·음성기록이 모두 보존돼요.

---

## 파일 구조

```
discord-party-bot/
├── bot.py                  # 메인 엔트리, Cog 로드, 영구 View 복원
├── database.py             # PostgreSQL(Supabase) 헬퍼 — asyncpg 풀
├── cogs/
│   ├── control_panel.py    # 관리자 패널 (채널·역할·활동검토 설정)
│   ├── recruitment.py      # 파티 모집 (모달, 참가/취소/마감 버튼)
│   ├── game_roles.py       # 게임 추가/삭제, 역할 토글, 커스텀 이모지 선택
│   ├── voice_stats.py      # 음성 이용시간 추적 + 랭킹 (잠수채널 제외 처리)
│   ├── point_shop.py       # 포인트 상점 (적립·구매·관리자 설정)
│   ├── activity_review.py  # 주간 활동검토 자동화
│   ├── verification.py     # 규칙 인증 + 오픈채팅 게이트 버튼
│   ├── suggestions.py      # 익명 건의함
│   ├── leave_notices.py    # 잠수 신고
│   ├── nicknames.py        # 셀프 닉네임 변경 + 변경 이력
│   ├── nick_util.py        # 닉네임 접두사·복원 공용 헬퍼 (관전/셀프닉 공유)
│   ├── blacklist.py        # 블랙리스트 (ID 차단, on_member_join)
│   ├── entry_tracking.py   # 입장 경로 구분 + 오픈채팅 게이트 설정
│   └── sticky.py           # 스티키 공지 (채널 하단 고정)
├── migrations/
│   ├── 002_add_suggestions_and_leave_notices.sql
│   ├── 003_indexes_and_idempotency.sql
│   ├── 004_points_and_shop.sql
│   ├── 005_points_afk_channel.sql
│   ├── 006_rename_points_per_hour.sql
│   ├── 007_self_nickname.sql
│   ├── 008_spectators.sql
│   ├── 009_blacklist.sql
│   ├── 010_entry_dual_security.sql
│   ├── 011_sticky_messages.sql
│   └── 012_openchat_approval.sql
├── requirements.txt
├── Procfile                # Railway 실행 설정 (worker: python bot.py)
├── runtime.txt
└── .env.example
```

---

## 채널 권한 설정 (권장)

모집 채널을 봇 전용으로 만들려면 채널 설정 → 권한에서:
- `@everyone` → **메시지 보내기** ❌
- 봇 역할 → **메시지 보내기** ✅

관리자 패널·포인트 상점 설정 패널은 관리자만 보이는 채널에 설치하세요.

---

## 활동 검토 동작 방식

설정 (관리자 패널 → **📋 활동검토 설정**):
- **📑 로그 채널** — 검토 결과를 올릴 관리자 전용 채널 (필수)
- **🕐 기준 시간** — 주간 최소 음성시간 (기본 3시간)
- **🛡️ 면제 역할** — 이 역할 보유자는 검토에서 제외
- **🔁 자동강퇴 모드** — 켜면 강퇴 후보에 승인 버튼이 붙음

동작 흐름:
1. 매주 월요일 자동 실행 (또는 **▶️ 지금 활동검토 실행**)
2. 자동 제외: 봇 / 면제 역할 / 가입 1주 미만 신규원
3. 기준 미달자 → 경고 1회 누적 + DM 발송
4. 연속 3회 미달 → 강퇴 후보 분류 (관리자가 드롭다운으로 직접 승인해야 실행)
5. 강퇴는 kick 방식 (초대 링크로 재입장 가능, 밴 아님)

---

## 포인트 상점 동작 방식

- 음성채널에 **5분 이상** 체류 후 퇴장 시 포인트 자동 적립
- **잠수채널 / Discord AFK 채널** 체류 시간은 포인트 미적립
- 잠수채널로 이동 시 이동 전 일반채널 시간만 정산

| 버튼 | 기능 |
|------|------|
| 🪙 10분당 포인트 | 10분 체류당 지급 포인트 설정 (기본 2) |
| ➕ 역할 추가 | 역할 선택 → 가격 입력 → 상점 등록 |
| 🗑️ 역할 제거 | 상점에서 역할 삭제 |
| 📋 현황 보기 | 설정·등록 역할·잠수채널 전체 조회 |
| 🔇 잠수채널 설정 | 포인트 미지급 채널 지정·해제 |

---

## 주간 랭킹 자동 초기화 (선택)

현재는 관리자가 **🔄 주간 랭킹 초기화** 버튼으로 수동 초기화해요.
매주 자동 초기화를 원하면 `discord.ext.tasks` 로 스케줄러를 추가할 수 있어요.
