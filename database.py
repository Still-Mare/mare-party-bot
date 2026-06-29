"""
PostgreSQL(Supabase) 데이터베이스 헬퍼.
asyncpg 커넥션 풀을 사용해 비동기로 동작한다.
"""

import asyncio
import os
from datetime import datetime, timezone

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL")

_pool: asyncpg.Pool | None = None

# ─── 허용된 guild_settings 컬럼 화이트리스트 (SQL 인젝션 방지) ───
_ALLOWED_SETTINGS_COLUMNS = frozenset({
    "voice_category_id", "archive_channel_id", "review_log_channel",
    "exempt_role_id", "min_seconds", "auto_kick_enabled",
    "panel_manager_role", "verified_role_id", "last_reviewed_at",
    "recruit_post_channel_id", "points_per_10min",
    "points_excluded_channel_id",
    # 007 셀프 닉네임
    "nickname_log_channel_id",
    # 009 블랙리스트
    "blacklist_ban_on_join", "blacklist_notify",
    # 010 입장 경로 + 오픈채팅 게이트
    "openchat_url", "openchat_gate_role_id",
    "kakao_invite_code", "entry_marker_role_id",
    # 012 오픈채팅 운영자 승인제
    "openchat_approval_required", "openchat_request_channel_id",
    # 013 전역 관전 모드
    "spectator_role_id",
    # 014 출입로그
    "entry_log_channel_id",
    # 015 뉴비 게이트
    "newbie_role_id", "newbie_gate_enabled", "newbie_gate_channel_id",
})

# ─── 모집별 참가 직렬화 잠금 (단일 프로세스 내 레이스 컨디션 방지) ───
_join_locks: dict[int, asyncio.Lock] = {}

# ─── 포인트 적립 최소 세션 시간 (초) ───────────────────────────────
# 이 시간 미만 체류 시 포인트 미지급 — 빠른 입퇴장 어뷰징 방지
_MIN_POINT_SESSION_SECS = 300  # 5분


def _get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB 풀이 초기화되지 않았어요. init_db()를 먼저 호출하세요.")
    return _pool


async def init_db():
    """봇 시작 시 한 번 호출. 커넥션 풀을 생성한다."""
    global _pool
    if _pool is not None:
        return
    if not DATABASE_URL:
        raise RuntimeError("환경변수 DATABASE_URL 이 설정되지 않았어요.")
    _pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
        command_timeout=30,
        statement_cache_size=0,  # Supabase PgBouncer(transaction mode) 호환 필수
    )


async def close_db():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _now():
    return datetime.now(timezone.utc)


# ───────────────────────── 게임 ─────────────────────────
async def add_game(guild_id, name, emoji, role_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            """INSERT INTO games (guild_id, name, emoji, role_id)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (guild_id, name)
               DO UPDATE SET emoji = $3, role_id = $4""",
            guild_id, name, emoji, role_id,
        )


async def remove_game(guild_id, name):
    async with _get_pool().acquire() as con:
        await con.execute(
            "DELETE FROM games WHERE guild_id = $1 AND name = $2", guild_id, name
        )


async def list_games(guild_id):
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            "SELECT name, emoji, role_id FROM games WHERE guild_id = $1 ORDER BY name",
            guild_id,
        )
    return [{"name": r["name"], "emoji": r["emoji"], "role_id": r["role_id"]} for r in rows]


async def get_game(guild_id, name):
    async with _get_pool().acquire() as con:
        r = await con.fetchrow(
            "SELECT name, emoji, role_id FROM games WHERE guild_id = $1 AND name = $2",
            guild_id, name,
        )
    return {"name": r["name"], "emoji": r["emoji"], "role_id": r["role_id"]} if r else None


# ───────────────────────── 모집 ─────────────────────────
async def create_recruit(guild_id, channel_id, host_id, game_name, play_time, max_players, note):
    async with _get_pool().acquire() as con:
        async with con.transaction():
            recruit_id = await con.fetchval(
                """INSERT INTO recruits
                   (guild_id, channel_id, host_id, game_name, play_time, max_players, note)
                   VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
                guild_id, channel_id, host_id, game_name, play_time, max_players, note,
            )
            await con.execute(
                "INSERT INTO participants (recruit_id, user_id) VALUES ($1, $2)",
                recruit_id, host_id,
            )
    return recruit_id


async def set_recruit_message(recruit_id, message_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            "UPDATE recruits SET message_id = $1 WHERE id = $2", message_id, recruit_id
        )


async def get_recruit(recruit_id):
    async with _get_pool().acquire() as con:
        r = await con.fetchrow(
            """SELECT id, guild_id, channel_id, message_id, host_id, game_name,
                      play_time, max_players, note, status, voice_channel_id, temp_role_id
               FROM recruits WHERE id = $1""",
            recruit_id,
        )
    if not r:
        return None
    return {
        "id": r["id"], "guild_id": r["guild_id"], "channel_id": r["channel_id"],
        "message_id": r["message_id"], "host_id": r["host_id"],
        "game_name": r["game_name"], "play_time": r["play_time"],
        "max_players": r["max_players"], "note": r["note"], "status": r["status"],
        "voice_channel_id": r["voice_channel_id"], "temp_role_id": r["temp_role_id"],
    }


async def set_recruit_temp_role(recruit_id, role_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            "UPDATE recruits SET temp_role_id = $1 WHERE id = $2", role_id, recruit_id
        )


async def set_recruit_voice(recruit_id, voice_channel_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            "UPDATE recruits SET voice_channel_id = $1 WHERE id = $2",
            voice_channel_id, recruit_id,
        )


async def archive_recruit(recruit_id) -> bool:
    """
    status를 'archived'로 원자적으로 점유. 점유에 성공하면 True, 이미 archived였으면 False.
    중복 아카이브(스테일 정리 루프 vs 마감 버튼 등)를 방지한다.
    """
    async with _get_pool().acquire() as con:
        r = await con.fetchval(
            """UPDATE recruits SET status = 'archived', voice_channel_id = NULL
               WHERE id = $1 AND status <> 'archived' RETURNING id""",
            recruit_id,
        )
    return r is not None


async def find_recruit_by_voice(voice_channel_id):
    async with _get_pool().acquire() as con:
        return await con.fetchval(
            "SELECT id FROM recruits WHERE voice_channel_id = $1", voice_channel_id
        )


async def close_recruit(recruit_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            "UPDATE recruits SET status = 'closed' WHERE id = $1", recruit_id
        )


async def open_recruits(guild_id):
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            """SELECT id, game_name, play_time, max_players FROM recruits
               WHERE guild_id = $1 AND status = 'open' ORDER BY id DESC""",
            guild_id,
        )
    return [
        {"id": r["id"], "game_name": r["game_name"],
         "play_time": r["play_time"], "max_players": r["max_players"]}
        for r in rows
    ]


# ─────────────────────── 참가자 ───────────────────────
async def add_participant(recruit_id, user_id):
    """단순 삽입 (create_recruit 내부 전용). 레이스 방지가 필요하면 try_join_recruit 사용."""
    async with _get_pool().acquire() as con:
        result = await con.execute(
            """INSERT INTO participants (recruit_id, user_id) VALUES ($1, $2)
               ON CONFLICT (recruit_id, user_id) DO NOTHING""",
            recruit_id, user_id,
        )
    return result.endswith("1")


async def try_join_recruit(recruit_id: int, user_id: int) -> str:
    """
    인원 초과 레이스 컨디션을 방지하는 원자적 참가 시도.
    반환값: 'added' | 'already_joined' | 'full' | 'closed'
    asyncio.Lock으로 단일 프로세스 내 직렬화를 보장한다.
    """
    if recruit_id not in _join_locks:
        _join_locks[recruit_id] = asyncio.Lock()

    async with _join_locks[recruit_id]:
        async with _get_pool().acquire() as con:
            recruit = await con.fetchrow(
                "SELECT status, max_players FROM recruits WHERE id = $1",
                recruit_id,
            )
            if not recruit or recruit["status"] != "open":
                return "closed"
            cnt = await con.fetchval(
                "SELECT COUNT(*) FROM participants WHERE recruit_id = $1",
                recruit_id,
            )
            if cnt >= recruit["max_players"]:
                return "full"
            result = await con.execute(
                """INSERT INTO participants (recruit_id, user_id)
                   VALUES ($1, $2) ON CONFLICT (recruit_id, user_id) DO NOTHING""",
                recruit_id, user_id,
            )
            return "already_joined" if result.endswith("0") else "added"


async def remove_participant(recruit_id, user_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            "DELETE FROM participants WHERE recruit_id = $1 AND user_id = $2",
            recruit_id, user_id,
        )


async def list_participants(recruit_id):
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            "SELECT user_id FROM participants WHERE recruit_id = $1 ORDER BY joined_at",
            recruit_id,
        )
    return [r["user_id"] for r in rows]


# ─────────────────────── 음성 통계 ───────────────────────
async def voice_join(guild_id, user_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            """INSERT INTO voice_sessions (guild_id, user_id, joined_at)
               VALUES ($1, $2, $3)
               ON CONFLICT (guild_id, user_id) DO UPDATE SET joined_at = $3""",
            guild_id, user_id, _now(),
        )


async def voice_leave(guild_id, user_id):
    """
    DELETE RETURNING으로 원자적 퇴장 처리.
    동시 호출 시 두 번째는 row가 없으므로 이중 누적이 발생하지 않는다.
    퇴장 시 음성 시간에 비례한 포인트를 같은 트랜잭션에서 적립한다.
    """
    async with _get_pool().acquire() as con:
        async with con.transaction():
            row = await con.fetchrow(
                """DELETE FROM voice_sessions
                   WHERE guild_id = $1 AND user_id = $2
                   RETURNING joined_at""",
                guild_id, user_id,
            )
            if not row:
                return
            elapsed = max(0, int((_now() - row["joined_at"]).total_seconds()))
            await con.execute(
                """INSERT INTO voice_totals (guild_id, user_id, total_seconds, week_seconds)
                   VALUES ($1, $2, $3, $3)
                   ON CONFLICT (guild_id, user_id) DO UPDATE SET
                     total_seconds = voice_totals.total_seconds + $3,
                     week_seconds  = voice_totals.week_seconds  + $3""",
                guild_id, user_id, elapsed,
            )
            # 포인트 적립 (10분당 포인트 비율 × 경과 시간)
            settings_row = await con.fetchrow(
                "SELECT points_per_10min FROM guild_settings WHERE guild_id = $1",
                guild_id,
            )
            p10m = settings_row["points_per_10min"] if settings_row else 2
            if p10m > 0 and elapsed >= _MIN_POINT_SESSION_SECS:
                points_earned = int(elapsed * p10m / 600)
                if points_earned > 0:
                    await con.execute(
                        """INSERT INTO user_points (guild_id, user_id, points)
                           VALUES ($1, $2, $3)
                           ON CONFLICT (guild_id, user_id) DO UPDATE
                           SET points = user_points.points + $3""",
                        guild_id, user_id, points_earned,
                    )


async def get_voice_total(guild_id, user_id):
    async with _get_pool().acquire() as con:
        r = await con.fetchrow(
            "SELECT total_seconds, week_seconds FROM voice_totals WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )
    return {"total": r["total_seconds"], "week": r["week_seconds"]} if r else {"total": 0, "week": 0}


async def voice_ranking(guild_id, period="week", limit=10):
    col = "week_seconds" if period == "week" else "total_seconds"
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            f"""SELECT user_id, {col} AS secs FROM voice_totals
                WHERE guild_id = $1 AND {col} > 0
                ORDER BY {col} DESC LIMIT $2""",
            guild_id, limit,
        )
    return [{"user_id": r["user_id"], "seconds": r["secs"]} for r in rows]


async def reset_week(guild_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            "UPDATE voice_totals SET week_seconds = 0 WHERE guild_id = $1", guild_id
        )


# ─────────────────────── 길드 설정 ───────────────────────
async def get_settings(guild_id):
    async with _get_pool().acquire() as con:
        r = await con.fetchrow(
            """SELECT voice_category_id, archive_channel_id, review_log_channel,
                      exempt_role_id, min_seconds, auto_kick_enabled, panel_manager_role,
                      verified_role_id, recruit_post_channel_id,
                      nickname_log_channel_id,
                      blacklist_ban_on_join, blacklist_notify,
                      openchat_url, openchat_gate_role_id,
                      kakao_invite_code, entry_marker_role_id,
                      openchat_approval_required, openchat_request_channel_id,
                      spectator_role_id,
                      entry_log_channel_id,
                      newbie_role_id, newbie_gate_enabled, newbie_gate_channel_id
               FROM guild_settings WHERE guild_id = $1""",
            guild_id,
        )
    if not r:
        return {
            "voice_category_id": None, "archive_channel_id": None,
            "review_log_channel": None, "exempt_role_id": None,
            "min_seconds": 10800, "auto_kick_enabled": 0,
            "panel_manager_role": None, "verified_role_id": None,
            "recruit_post_channel_id": None,
            "nickname_log_channel_id": None,
            "blacklist_ban_on_join": 0, "blacklist_notify": 1,
            "openchat_url": None, "openchat_gate_role_id": None,
            "kakao_invite_code": None, "entry_marker_role_id": None,
            "openchat_approval_required": 0, "openchat_request_channel_id": None,
            "spectator_role_id": None,
            "entry_log_channel_id": None,
            "newbie_role_id": None, "newbie_gate_enabled": 0,
            "newbie_gate_channel_id": None,
        }
    return {
        "voice_category_id": r["voice_category_id"],
        "archive_channel_id": r["archive_channel_id"],
        "review_log_channel": r["review_log_channel"],
        "exempt_role_id": r["exempt_role_id"],
        "min_seconds": r["min_seconds"],
        "auto_kick_enabled": r["auto_kick_enabled"],
        "panel_manager_role": r["panel_manager_role"],
        "verified_role_id": r["verified_role_id"],
        "recruit_post_channel_id": r["recruit_post_channel_id"],
        "nickname_log_channel_id": r["nickname_log_channel_id"],
        "blacklist_ban_on_join": r["blacklist_ban_on_join"],
        "blacklist_notify": r["blacklist_notify"],
        "openchat_url": r["openchat_url"],
        "openchat_gate_role_id": r["openchat_gate_role_id"],
        "kakao_invite_code": r["kakao_invite_code"],
        "entry_marker_role_id": r["entry_marker_role_id"],
        "openchat_approval_required": r["openchat_approval_required"],
        "openchat_request_channel_id": r["openchat_request_channel_id"],
        "spectator_role_id": r["spectator_role_id"],
        "entry_log_channel_id": r["entry_log_channel_id"],
        "newbie_role_id": r["newbie_role_id"],
        "newbie_gate_enabled": r["newbie_gate_enabled"],
        "newbie_gate_channel_id": r["newbie_gate_channel_id"],
    }


async def _upsert_setting(guild_id, column, value):
    if column not in _ALLOWED_SETTINGS_COLUMNS:
        raise ValueError(f"허용되지 않은 guild_settings 컬럼: {column!r}")
    async with _get_pool().acquire() as con:
        await con.execute(
            f"""INSERT INTO guild_settings (guild_id, {column})
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO UPDATE SET {column} = $2""",
            guild_id, value,
        )


async def set_voice_category(guild_id, category_id):
    await _upsert_setting(guild_id, "voice_category_id", category_id)


async def set_archive_channel(guild_id, channel_id):
    await _upsert_setting(guild_id, "archive_channel_id", channel_id)


async def set_review_log_channel(guild_id, channel_id):
    await _upsert_setting(guild_id, "review_log_channel", channel_id)


async def set_exempt_role(guild_id, role_id):
    await _upsert_setting(guild_id, "exempt_role_id", role_id)


async def set_min_seconds(guild_id, seconds):
    await _upsert_setting(guild_id, "min_seconds", seconds)


async def set_auto_kick(guild_id, enabled):
    await _upsert_setting(guild_id, "auto_kick_enabled", 1 if enabled else 0)


async def set_panel_manager_role(guild_id, role_id):
    await _upsert_setting(guild_id, "panel_manager_role", role_id)


async def set_verified_role(guild_id, role_id):
    await _upsert_setting(guild_id, "verified_role_id", role_id)


async def set_recruit_post_channel(guild_id, channel_id):
    """모집글이 게시될 전용 채널. None이면 모집 버튼을 누른 채널에 게시."""
    await _upsert_setting(guild_id, "recruit_post_channel_id", channel_id)


async def get_last_reviewed_at(guild_id):
    """마지막 활동검토 실행 시각 반환. 미설정 시 None."""
    async with _get_pool().acquire() as con:
        return await con.fetchval(
            "SELECT last_reviewed_at FROM guild_settings WHERE guild_id = $1",
            guild_id,
        )


async def set_last_reviewed_at(guild_id, dt):
    await _upsert_setting(guild_id, "last_reviewed_at", dt)


# ─────────────────────── 활동 경고 추적 ───────────────────────
async def get_strikes(guild_id, user_id):
    async with _get_pool().acquire() as con:
        r = await con.fetchval(
            "SELECT strikes FROM activity_warnings WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )
    return r if r is not None else 0


async def add_strike(guild_id, user_id):
    async with _get_pool().acquire() as con:
        new_val = await con.fetchval(
            """INSERT INTO activity_warnings (guild_id, user_id, strikes, last_review)
               VALUES ($1, $2, 1, $3)
               ON CONFLICT (guild_id, user_id) DO UPDATE SET
                 strikes = activity_warnings.strikes + 1, last_review = $3
               RETURNING strikes""",
            guild_id, user_id, _now(),
        )
    return new_val


async def reset_strike(guild_id, user_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            "DELETE FROM activity_warnings WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )


async def list_open_recruit_ids():
    """봇 재시작 시 영구 View 복원용: 열린 모집글 ID 목록."""
    async with _get_pool().acquire() as con:
        rows = await con.fetch("SELECT id FROM recruits WHERE status = 'open'")
    return [r["id"] for r in rows]


# ─────────────────────── 익명 건의함 ───────────────────────
async def create_suggestion(guild_id, author_id, content):
    """건의 생성 후 id 반환."""
    async with _get_pool().acquire() as con:
        return await con.fetchval(
            """INSERT INTO suggestions (guild_id, author_id, content)
               VALUES ($1, $2, $3) RETURNING id""",
            guild_id, author_id, content,
        )


async def set_suggestion_public_msg(suggestion_id, message_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            "UPDATE suggestions SET public_msg_id = $1 WHERE id = $2",
            message_id, suggestion_id,
        )


async def get_suggestion_author(suggestion_id):
    """서버 주인 전용. 작성자 ID 반환."""
    async with _get_pool().acquire() as con:
        return await con.fetchval(
            "SELECT author_id FROM suggestions WHERE id = $1", suggestion_id
        )


async def get_suggestion_by_message(message_id: int):
    """메시지 ID로 건의 ID를 조회한다 (영구 View에서 재시작 후 복원용)."""
    async with _get_pool().acquire() as con:
        return await con.fetchval(
            "SELECT id FROM suggestions WHERE public_msg_id = $1", message_id
        )


# ─────────────────────── 잠수 신고 ───────────────────────
async def create_leave_notice(guild_id, user_id, reason, until_date):
    """잠수 신고 생성. until_date는 datetime.date."""
    async with _get_pool().acquire() as con:
        return await con.fetchval(
            """INSERT INTO leave_notices (guild_id, user_id, reason, until_date)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            guild_id, user_id, reason, until_date,
        )


async def list_pending_leave_notices(guild_id):
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            """SELECT id, user_id, reason, until_date, created_at
               FROM leave_notices
               WHERE guild_id = $1 AND status = 'pending'
               ORDER BY created_at""",
            guild_id,
        )
    return [
        {"id": r["id"], "user_id": r["user_id"], "reason": r["reason"],
         "until_date": r["until_date"], "created_at": r["created_at"]}
        for r in rows
    ]


async def approve_leave_notice(notice_id, reviewer_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            """UPDATE leave_notices
               SET status = 'approved', reviewed_by = $1, reviewed_at = now()
               WHERE id = $2""",
            reviewer_id, notice_id,
        )


async def reject_leave_notice(notice_id, reviewer_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            """UPDATE leave_notices
               SET status = 'rejected', reviewed_by = $1, reviewed_at = now()
               WHERE id = $2""",
            reviewer_id, notice_id,
        )


async def get_leave_notice(notice_id):
    async with _get_pool().acquire() as con:
        r = await con.fetchrow(
            """SELECT id, guild_id, user_id, reason, until_date, status
               FROM leave_notices WHERE id = $1""",
            notice_id,
        )
    if not r:
        return None
    return {"id": r["id"], "guild_id": r["guild_id"], "user_id": r["user_id"],
            "reason": r["reason"], "until_date": r["until_date"], "status": r["status"]}


async def is_user_on_leave(guild_id, user_id):
    """현재 시점 기준으로 승인된 잠수 신고가 유효한지."""
    async with _get_pool().acquire() as con:
        r = await con.fetchval(
            """SELECT 1 FROM leave_notices
               WHERE guild_id = $1 AND user_id = $2
                 AND status = 'approved'
                 AND until_date >= CURRENT_DATE
               LIMIT 1""",
            guild_id, user_id,
        )
    return r is not None


async def expire_old_leave_notices():
    """잠수 기간이 끝난 신고를 expired로 표시. 정기적으로 호출."""
    async with _get_pool().acquire() as con:
        result = await con.execute(
            """UPDATE leave_notices SET status = 'expired'
               WHERE status = 'approved' AND until_date < CURRENT_DATE"""
        )
    return result


# ─────────────────────── 포인트 시스템 ───────────────────────
async def get_user_points(guild_id: int, user_id: int) -> int:
    async with _get_pool().acquire() as con:
        val = await con.fetchval(
            "SELECT points FROM user_points WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )
    return val if val is not None else 0


async def add_user_points(guild_id: int, user_id: int, delta: int) -> int:
    """포인트를 더하거나 뺀다 (음수 가능). 반환값: 새 잔액 (최소 0)."""
    async with _get_pool().acquire() as con:
        new_val = await con.fetchval(
            """INSERT INTO user_points (guild_id, user_id, points)
               VALUES ($1, $2, GREATEST(0, $3))
               ON CONFLICT (guild_id, user_id) DO UPDATE
               SET points = GREATEST(0, user_points.points + $3)
               RETURNING points""",
            guild_id, user_id, delta,
        )
    return new_val


async def spend_user_points(guild_id: int, user_id: int, amount: int) -> bool:
    """포인트를 원자적으로 차감한다. 잔액 부족이면 False를 반환한다."""
    async with _get_pool().acquire() as con:
        result = await con.fetchval(
            """UPDATE user_points
               SET points = points - $3
               WHERE guild_id = $1 AND user_id = $2 AND points >= $3
               RETURNING points""",
            guild_id, user_id, amount,
        )
    return result is not None


# ─────────────────────── 상점 역할 ───────────────────────
async def list_shop_roles(guild_id: int) -> list:
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            "SELECT role_id, cost, label FROM shop_roles WHERE guild_id = $1 ORDER BY cost",
            guild_id,
        )
    return [{"role_id": r["role_id"], "cost": r["cost"], "label": r["label"]} for r in rows]


async def get_shop_role(guild_id: int, role_id: int):
    async with _get_pool().acquire() as con:
        r = await con.fetchrow(
            "SELECT role_id, cost, label FROM shop_roles WHERE guild_id = $1 AND role_id = $2",
            guild_id, role_id,
        )
    return {"role_id": r["role_id"], "cost": r["cost"], "label": r["label"]} if r else None


async def add_shop_role(guild_id: int, role_id: int, cost: int, label: str | None = None):
    async with _get_pool().acquire() as con:
        await con.execute(
            """INSERT INTO shop_roles (guild_id, role_id, cost, label)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (guild_id, role_id) DO UPDATE SET cost = $3, label = $4""",
            guild_id, role_id, cost, label,
        )


async def remove_shop_role(guild_id: int, role_id: int):
    async with _get_pool().acquire() as con:
        await con.execute(
            "DELETE FROM shop_roles WHERE guild_id = $1 AND role_id = $2",
            guild_id, role_id,
        )


async def get_points_per_10min(guild_id: int) -> int:
    async with _get_pool().acquire() as con:
        val = await con.fetchval(
            "SELECT points_per_10min FROM guild_settings WHERE guild_id = $1",
            guild_id,
        )
    return val if val is not None else 2


async def set_points_per_10min(guild_id: int, p10m: int):
    await _upsert_setting(guild_id, "points_per_10min", p10m)


async def get_points_excluded_channel(guild_id: int) -> int | None:
    """포인트 미지급 채널(잠수채널) ID 반환. 미설정 시 None."""
    async with _get_pool().acquire() as con:
        return await con.fetchval(
            "SELECT points_excluded_channel_id FROM guild_settings WHERE guild_id = $1",
            guild_id,
        )


async def set_points_excluded_channel(guild_id: int, channel_id: int | None):
    """포인트 미지급 채널을 설정한다. None이면 해제."""
    await _upsert_setting(guild_id, "points_excluded_channel_id", channel_id)


# ─────────────────────── 007 셀프 닉네임 ───────────────────────
async def set_nickname_log_channel(guild_id: int, channel_id: int | None):
    await _upsert_setting(guild_id, "nickname_log_channel_id", channel_id)


async def log_nickname_change(guild_id: int, user_id: int, old_nick, new_nick, changed_by: int):
    """닉네임 변경 이력 1건 기록."""
    async with _get_pool().acquire() as con:
        await con.execute(
            """INSERT INTO nickname_history (guild_id, user_id, old_nick, new_nick, changed_by)
               VALUES ($1, $2, $3, $4, $5)""",
            guild_id, user_id, old_nick, new_nick, changed_by,
        )


async def get_nickname_history(guild_id: int, user_id: int, limit: int = 15) -> list:
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            """SELECT old_nick, new_nick, changed_by, changed_at
               FROM nickname_history
               WHERE guild_id = $1 AND user_id = $2
               ORDER BY changed_at DESC LIMIT $3""",
            guild_id, user_id, limit,
        )
    return [
        {"old_nick": r["old_nick"], "new_nick": r["new_nick"],
         "changed_by": r["changed_by"], "changed_at": r["changed_at"]}
        for r in rows
    ]


# ─────────────────────── 008/013 전역 관전 모드 ───────────────────────
async def set_spectator_role(guild_id: int, role_id: int | None):
    await _upsert_setting(guild_id, "spectator_role_id", role_id)


async def enter_spectator_mode(guild_id: int, user_id: int, original_nick) -> bool:
    """전역 관전 모드 진입. 신규면 True, 이미 켜져 있으면 False(원본 닉 유지)."""
    async with _get_pool().acquire() as con:
        result = await con.execute(
            """INSERT INTO spectator_mode (guild_id, user_id, original_nick)
               VALUES ($1, $2, $3)
               ON CONFLICT (guild_id, user_id) DO NOTHING""",
            guild_id, user_id, original_nick,
        )
    return result.endswith("1")


async def exit_spectator_mode(guild_id: int, user_id: int):
    """관전 모드 해제. (켜져 있었는지, 보관된 원본 닉) 반환. 아니면 (False, None)."""
    async with _get_pool().acquire() as con:
        row = await con.fetchrow(
            """DELETE FROM spectator_mode
               WHERE guild_id = $1 AND user_id = $2
               RETURNING original_nick""",
            guild_id, user_id,
        )
    return (True, row["original_nick"]) if row else (False, None)


async def is_in_spectator_mode(guild_id: int, user_id: int) -> bool:
    async with _get_pool().acquire() as con:
        r = await con.fetchval(
            "SELECT 1 FROM spectator_mode WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )
    return r is not None


async def update_spectator_mode_nick(guild_id: int, user_id: int, new_base):
    """관전 모드 중 셀프 닉변 시, 복원용 원본 닉을 새 베이스로 갱신."""
    async with _get_pool().acquire() as con:
        await con.execute(
            "UPDATE spectator_mode SET original_nick = $3 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id, new_base,
        )


async def list_user_open_recruits(guild_id: int, user_id: int) -> list:
    """이 유저가 참가자(호스트 포함)로 들어있는 열린 모집 ID 목록."""
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            """SELECT r.id FROM recruits r
               JOIN participants p ON p.recruit_id = r.id
               WHERE r.guild_id = $1 AND r.status = 'open' AND p.user_id = $2""",
            guild_id, user_id,
        )
    return [r["id"] for r in rows]


async def set_recruit_host(recruit_id: int, new_host_id: int):
    """모집 호스트 위임."""
    async with _get_pool().acquire() as con:
        await con.execute(
            "UPDATE recruits SET host_id = $1 WHERE id = $2", new_host_id, recruit_id
        )


async def list_stale_open_recruits(cutoff, limit: int = 50) -> list:
    """음성방 없이 cutoff(datetime) 이전에 생성돼 방치된 열린 모집 (자동정리 대상). 틱당 limit개."""
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            """SELECT id, guild_id FROM recruits
               WHERE status = 'open' AND voice_channel_id IS NULL AND created_at < $1
               ORDER BY created_at LIMIT $2""",
            cutoff, limit,
        )
    return [{"id": r["id"], "guild_id": r["guild_id"]} for r in rows]


# ─────────────────────── 009 블랙리스트 ───────────────────────
async def add_blacklist(guild_id: int, user_id: int, reason, added_by: int, native_ban: int = 0):
    async with _get_pool().acquire() as con:
        await con.execute(
            """INSERT INTO blacklist (guild_id, user_id, reason, added_by, native_ban)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (guild_id, user_id) DO UPDATE
               SET reason = $3, added_by = $4, native_ban = $5, created_at = now()""",
            guild_id, user_id, reason, added_by, native_ban,
        )


async def remove_blacklist(guild_id: int, user_id: int):
    """해제. 등록돼 있었으면 native_ban 값(0/1) 반환, 아니면 None."""
    async with _get_pool().acquire() as con:
        row = await con.fetchrow(
            """DELETE FROM blacklist WHERE guild_id = $1 AND user_id = $2
               RETURNING native_ban""",
            guild_id, user_id,
        )
    return row["native_ban"] if row else None


async def is_blacklisted(guild_id: int, user_id: int) -> bool:
    async with _get_pool().acquire() as con:
        r = await con.fetchval(
            "SELECT 1 FROM blacklist WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )
    return r is not None


async def get_blacklist_entry(guild_id: int, user_id: int):
    async with _get_pool().acquire() as con:
        r = await con.fetchrow(
            """SELECT user_id, reason, added_by, native_ban, created_at
               FROM blacklist WHERE guild_id = $1 AND user_id = $2""",
            guild_id, user_id,
        )
    if not r:
        return None
    return {"user_id": r["user_id"], "reason": r["reason"], "added_by": r["added_by"],
            "native_ban": r["native_ban"], "created_at": r["created_at"]}


async def list_blacklist(guild_id: int, limit: int = 25) -> list:
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            """SELECT user_id, reason, added_by, native_ban, created_at
               FROM blacklist WHERE guild_id = $1
               ORDER BY created_at DESC LIMIT $2""",
            guild_id, limit,
        )
    return [
        {"user_id": r["user_id"], "reason": r["reason"], "added_by": r["added_by"],
         "native_ban": r["native_ban"], "created_at": r["created_at"]}
        for r in rows
    ]


async def set_blacklist_ban_on_join(guild_id: int, enabled: bool):
    await _upsert_setting(guild_id, "blacklist_ban_on_join", 1 if enabled else 0)


async def set_blacklist_notify(guild_id: int, enabled: bool):
    await _upsert_setting(guild_id, "blacklist_notify", 1 if enabled else 0)


# ─────────────────────── 010 입장 경로 + 오픈채팅 ───────────────────────
async def record_member_entry(guild_id: int, user_id: int, invite_code, route_label: str):
    async with _get_pool().acquire() as con:
        await con.execute(
            """INSERT INTO member_entry (guild_id, user_id, invite_code, route_label, joined_at)
               VALUES ($1, $2, $3, $4, now())
               ON CONFLICT (guild_id, user_id) DO UPDATE
               SET invite_code = $3, route_label = $4, joined_at = now()""",
            guild_id, user_id, invite_code, route_label,
        )


async def get_route_stats(guild_id: int) -> dict:
    """경로별 유입 수 집계. {'kakao': n, 'discord': m, ...}"""
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            """SELECT route_label, COUNT(*) AS cnt FROM member_entry
               WHERE guild_id = $1 GROUP BY route_label""",
            guild_id,
        )
    return {r["route_label"]: r["cnt"] for r in rows}


# ─────────────────────── 014 출입로그 ───────────────────────
def _escape_like(text: str) -> str:
    r"""ILIKE 검색어에서 와일드카드(%, _)와 이스케이프 문자(\)를 리터럴로 처리."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def set_entry_log_channel(guild_id: int, channel_id):
    """출입로그를 자동 게시할 채널. None 이면 채널 게시 비활성(패널 조회만)."""
    await _upsert_setting(guild_id, "entry_log_channel_id", channel_id)


async def record_entry_log(guild_id: int, user_id: int, display_name: str,
                           action: str, route_label=None):
    """입장/퇴장 이벤트 1건 기록. display_name 은 이벤트 시점의 별명(나간 뒤 조회 불가 대비)."""
    async with _get_pool().acquire() as con:
        await con.execute(
            """INSERT INTO entry_log (guild_id, user_id, display_name, action, route_label)
               VALUES ($1, $2, $3, $4, $5)""",
            guild_id, user_id, display_name, action, route_label,
        )


def _entry_row(r) -> dict:
    return {
        "id": r["id"], "user_id": r["user_id"], "display_name": r["display_name"],
        "action": r["action"], "route_label": r["route_label"], "created_at": r["created_at"],
    }


async def get_entry_log(guild_id: int, limit: int = 15) -> list:
    """최근 출입 이벤트 목록 (최신순)."""
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            """SELECT id, user_id, display_name, action, route_label, created_at
               FROM entry_log WHERE guild_id = $1
               ORDER BY id DESC LIMIT $2""",
            guild_id, limit,
        )
    return [_entry_row(r) for r in rows]


async def search_entry_log(guild_id: int, query: str, limit: int = 25) -> list:
    """별명으로 출입 이벤트 검색 (대소문자 무시, 부분일치, 최신순)."""
    pattern = f"%{_escape_like(query)}%"
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            r"""SELECT id, user_id, display_name, action, route_label, created_at
                FROM entry_log
                WHERE guild_id = $1 AND display_name ILIKE $2 ESCAPE '\'
                ORDER BY id DESC LIMIT $3""",
            guild_id, pattern, limit,
        )
    return [_entry_row(r) for r in rows]


# ─────────────────────── 015 뉴비 게이트 ───────────────────────
async def set_newbie_role(guild_id: int, role_id):
    await _upsert_setting(guild_id, "newbie_role_id", role_id)


async def set_newbie_gate_enabled(guild_id: int, enabled: bool):
    await _upsert_setting(guild_id, "newbie_gate_enabled", 1 if enabled else 0)


async def set_newbie_gate_channel(guild_id: int, channel_id):
    await _upsert_setting(guild_id, "newbie_gate_channel_id", channel_id)


async def set_openchat_url(guild_id: int, url):
    await _upsert_setting(guild_id, "openchat_url", url)


async def set_openchat_gate_role(guild_id: int, role_id):
    await _upsert_setting(guild_id, "openchat_gate_role_id", role_id)


async def set_kakao_invite_code(guild_id: int, code):
    await _upsert_setting(guild_id, "kakao_invite_code", code)


async def set_entry_marker_role(guild_id: int, role_id):
    await _upsert_setting(guild_id, "entry_marker_role_id", role_id)


# ─────────────────────── 011 스티키 공지 ───────────────────────
async def upsert_sticky(guild_id: int, channel_id: int, title, content, image_url, created_by: int):
    """스티키 설정/수정. enabled=TRUE 로 켜고 last_message_id 는 유지(이전 메시지 삭제용)."""
    async with _get_pool().acquire() as con:
        await con.execute(
            """INSERT INTO sticky_messages
                   (guild_id, channel_id, title, content, image_url, enabled, created_by, updated_at)
               VALUES ($1, $2, $3, $4, $5, TRUE, $6, now())
               ON CONFLICT (guild_id, channel_id) DO UPDATE
               SET title = $3, content = $4, image_url = $5,
                   enabled = TRUE, created_by = $6, updated_at = now()""",
            guild_id, channel_id, title, content, image_url, created_by,
        )


async def get_sticky(guild_id: int, channel_id: int):
    async with _get_pool().acquire() as con:
        r = await con.fetchrow(
            """SELECT guild_id, channel_id, title, content, image_url,
                      last_message_id, enabled
               FROM sticky_messages WHERE guild_id = $1 AND channel_id = $2""",
            guild_id, channel_id,
        )
    if not r:
        return None
    return {"guild_id": r["guild_id"], "channel_id": r["channel_id"],
            "title": r["title"], "content": r["content"], "image_url": r["image_url"],
            "last_message_id": r["last_message_id"], "enabled": r["enabled"]}


async def set_sticky_message_id(guild_id: int, channel_id: int, message_id):
    async with _get_pool().acquire() as con:
        await con.execute(
            """UPDATE sticky_messages SET last_message_id = $3
               WHERE guild_id = $1 AND channel_id = $2""",
            guild_id, channel_id, message_id,
        )


async def disable_sticky(guild_id: int, channel_id: int) -> bool:
    """스티키 끄기. 존재했으면 True."""
    async with _get_pool().acquire() as con:
        result = await con.execute(
            """UPDATE sticky_messages SET enabled = FALSE, updated_at = now()
               WHERE guild_id = $1 AND channel_id = $2""",
            guild_id, channel_id,
        )
    return result.endswith("1")


async def list_enabled_stickies(guild_id: int) -> list:
    async with _get_pool().acquire() as con:
        rows = await con.fetch(
            """SELECT channel_id, title, content, last_message_id
               FROM sticky_messages WHERE guild_id = $1 AND enabled = TRUE""",
            guild_id,
        )
    return [
        {"channel_id": r["channel_id"], "title": r["title"],
         "content": r["content"], "last_message_id": r["last_message_id"]}
        for r in rows
    ]


# ─────────────────────── 012 오픈채팅 운영자 승인제 ───────────────────────
async def set_openchat_approval_required(guild_id: int, enabled: bool):
    await _upsert_setting(guild_id, "openchat_approval_required", 1 if enabled else 0)


async def set_openchat_request_channel(guild_id: int, channel_id: int | None):
    await _upsert_setting(guild_id, "openchat_request_channel_id", channel_id)


async def create_openchat_request(guild_id: int, user_id: int) -> int | None:
    """
    대기 중 신청이 없으면 생성하고 id 반환. 이미 대기 중이면 None.
    WHERE NOT EXISTS 로 1차 방어하고, 동시 클릭 레이스는 부분 유니크 인덱스
    (uq_openchat_requests_one_pending)가 막아 UniqueViolation 시 None 반환.
    """
    async with _get_pool().acquire() as con:
        try:
            return await con.fetchval(
                """INSERT INTO openchat_requests (guild_id, user_id)
                   SELECT $1, $2
                   WHERE NOT EXISTS (
                       SELECT 1 FROM openchat_requests
                       WHERE guild_id = $1 AND user_id = $2 AND status = 'pending'
                   )
                   RETURNING id""",
                guild_id, user_id,
            )
        except asyncpg.UniqueViolationError:
            return None


async def set_openchat_request_msg(request_id: int, message_id: int):
    async with _get_pool().acquire() as con:
        await con.execute(
            "UPDATE openchat_requests SET review_msg_id = $1 WHERE id = $2",
            message_id, request_id,
        )


async def get_openchat_request(request_id: int):
    async with _get_pool().acquire() as con:
        r = await con.fetchrow(
            "SELECT id, guild_id, user_id, status FROM openchat_requests WHERE id = $1",
            request_id,
        )
    if not r:
        return None
    return {"id": r["id"], "guild_id": r["guild_id"], "user_id": r["user_id"], "status": r["status"]}


async def review_openchat_request(request_id: int, reviewer_id: int, approved: bool):
    """
    pending 신청을 승인/거절 처리. 원자적으로 status를 바꾼다.
    처리에 성공하면 신청자 user_id 반환, 이미 처리됐으면 None(중복 처리 방지).
    """
    status = "approved" if approved else "rejected"
    async with _get_pool().acquire() as con:
        r = await con.fetchrow(
            """UPDATE openchat_requests
               SET status = $1, reviewed_by = $2, reviewed_at = now()
               WHERE id = $3 AND status = 'pending'
               RETURNING user_id""",
            status, reviewer_id, request_id,
        )
    return r["user_id"] if r else None


async def list_pending_openchat_request_ids() -> list:
    """봇 재시작 시 영구 View 복원용: 대기 중 신청 ID 목록."""
    async with _get_pool().acquire() as con:
        rows = await con.fetch("SELECT id FROM openchat_requests WHERE status = 'pending'")
    return [r["id"] for r in rows]
