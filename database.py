"""
PostgreSQL(Supabase) 데이터베이스 헬퍼.
asyncpg 커넥션 풀을 사용해 비동기로 동작한다.

SQLite 버전에서 바뀐 점:
- 연결: 파일 → asyncpg 풀 (DATABASE_URL 환경변수)
- placeholder: ?  →  $1, $2 ...
- INSERT OR REPLACE → INSERT ... ON CONFLICT ... DO UPDATE
- 시간: 파이썬 ISO 문자열 대신 DB의 TIMESTAMPTZ 활용

테이블은 Supabase에 이미 생성돼 있다고 가정한다.
"""

import os
from datetime import datetime, timezone

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL")

_pool = None


async def init_db():
    """봇 시작 시 한 번 호출. 커넥션 풀을 생성한다."""
    global _pool
    if _pool is not None:
        return
    if not DATABASE_URL:
        raise RuntimeError("환경변수 DATABASE_URL 이 설정되지 않았어요.")
    _pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=1, max_size=10, command_timeout=30
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
    async with _pool.acquire() as con:
        await con.execute(
            """INSERT INTO games (guild_id, name, emoji, role_id)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (guild_id, name)
               DO UPDATE SET emoji = $3, role_id = $4""",
            guild_id, name, emoji, role_id,
        )


async def remove_game(guild_id, name):
    async with _pool.acquire() as con:
        await con.execute(
            "DELETE FROM games WHERE guild_id = $1 AND name = $2", guild_id, name
        )


async def list_games(guild_id):
    async with _pool.acquire() as con:
        rows = await con.fetch(
            "SELECT name, emoji, role_id FROM games WHERE guild_id = $1 ORDER BY name",
            guild_id,
        )
    return [{"name": r["name"], "emoji": r["emoji"], "role_id": r["role_id"]} for r in rows]


async def get_game(guild_id, name):
    async with _pool.acquire() as con:
        r = await con.fetchrow(
            "SELECT name, emoji, role_id FROM games WHERE guild_id = $1 AND name = $2",
            guild_id, name,
        )
    return {"name": r["name"], "emoji": r["emoji"], "role_id": r["role_id"]} if r else None


# ───────────────────────── 모집 ─────────────────────────
async def create_recruit(guild_id, channel_id, host_id, game_name, play_time, max_players, note):
    async with _pool.acquire() as con:
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
    async with _pool.acquire() as con:
        await con.execute(
            "UPDATE recruits SET message_id = $1 WHERE id = $2", message_id, recruit_id
        )


async def get_recruit(recruit_id):
    async with _pool.acquire() as con:
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
    async with _pool.acquire() as con:
        await con.execute(
            "UPDATE recruits SET temp_role_id = $1 WHERE id = $2", role_id, recruit_id
        )


async def set_recruit_voice(recruit_id, voice_channel_id):
    async with _pool.acquire() as con:
        await con.execute(
            "UPDATE recruits SET voice_channel_id = $1 WHERE id = $2",
            voice_channel_id, recruit_id,
        )


async def archive_recruit(recruit_id):
    async with _pool.acquire() as con:
        await con.execute(
            "UPDATE recruits SET status = 'archived', voice_channel_id = NULL WHERE id = $1",
            recruit_id,
        )


async def find_recruit_by_voice(voice_channel_id):
    async with _pool.acquire() as con:
        return await con.fetchval(
            "SELECT id FROM recruits WHERE voice_channel_id = $1", voice_channel_id
        )


async def close_recruit(recruit_id):
    async with _pool.acquire() as con:
        await con.execute(
            "UPDATE recruits SET status = 'closed' WHERE id = $1", recruit_id
        )


async def open_recruits(guild_id):
    async with _pool.acquire() as con:
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
    async with _pool.acquire() as con:
        result = await con.execute(
            """INSERT INTO participants (recruit_id, user_id) VALUES ($1, $2)
               ON CONFLICT (recruit_id, user_id) DO NOTHING""",
            recruit_id, user_id,
        )
    return result.endswith("1")


async def remove_participant(recruit_id, user_id):
    async with _pool.acquire() as con:
        await con.execute(
            "DELETE FROM participants WHERE recruit_id = $1 AND user_id = $2",
            recruit_id, user_id,
        )


async def list_participants(recruit_id):
    async with _pool.acquire() as con:
        rows = await con.fetch(
            "SELECT user_id FROM participants WHERE recruit_id = $1 ORDER BY joined_at",
            recruit_id,
        )
    return [r["user_id"] for r in rows]


# ─────────────────────── 음성 통계 ───────────────────────
async def voice_join(guild_id, user_id):
    async with _pool.acquire() as con:
        await con.execute(
            """INSERT INTO voice_sessions (guild_id, user_id, joined_at)
               VALUES ($1, $2, $3)
               ON CONFLICT (guild_id, user_id) DO UPDATE SET joined_at = $3""",
            guild_id, user_id, _now(),
        )


async def voice_leave(guild_id, user_id):
    async with _pool.acquire() as con:
        async with con.transaction():
            row = await con.fetchrow(
                "SELECT joined_at FROM voice_sessions WHERE guild_id = $1 AND user_id = $2",
                guild_id, user_id,
            )
            if not row:
                return
            elapsed = int((_now() - row["joined_at"]).total_seconds())
            if elapsed < 0:
                elapsed = 0
            await con.execute(
                "DELETE FROM voice_sessions WHERE guild_id = $1 AND user_id = $2",
                guild_id, user_id,
            )
            await con.execute(
                """INSERT INTO voice_totals (guild_id, user_id, total_seconds, week_seconds)
                   VALUES ($1, $2, $3, $3)
                   ON CONFLICT (guild_id, user_id) DO UPDATE SET
                     total_seconds = voice_totals.total_seconds + $3,
                     week_seconds  = voice_totals.week_seconds  + $3""",
                guild_id, user_id, elapsed,
            )


async def get_voice_total(guild_id, user_id):
    async with _pool.acquire() as con:
        r = await con.fetchrow(
            "SELECT total_seconds, week_seconds FROM voice_totals WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )
    return {"total": r["total_seconds"], "week": r["week_seconds"]} if r else {"total": 0, "week": 0}


async def voice_ranking(guild_id, period="week", limit=10):
    col = "week_seconds" if period == "week" else "total_seconds"
    async with _pool.acquire() as con:
        rows = await con.fetch(
            f"""SELECT user_id, {col} AS secs FROM voice_totals
                WHERE guild_id = $1 AND {col} > 0
                ORDER BY {col} DESC LIMIT $2""",
            guild_id, limit,
        )
    return [{"user_id": r["user_id"], "seconds": r["secs"]} for r in rows]


async def reset_week(guild_id):
    async with _pool.acquire() as con:
        await con.execute(
            "UPDATE voice_totals SET week_seconds = 0 WHERE guild_id = $1", guild_id
        )


# ─────────────────────── 길드 설정 ───────────────────────
async def get_settings(guild_id):
    async with _pool.acquire() as con:
        r = await con.fetchrow(
            """SELECT voice_category_id, archive_channel_id, review_log_channel,
                      exempt_role_id, min_seconds, auto_kick_enabled, panel_manager_role,
                      verified_role_id
               FROM guild_settings WHERE guild_id = $1""",
            guild_id,
        )
    if not r:
        return {
            "voice_category_id": None, "archive_channel_id": None,
            "review_log_channel": None, "exempt_role_id": None,
            "min_seconds": 10800, "auto_kick_enabled": 0,
            "panel_manager_role": None, "verified_role_id": None,
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
    }


async def _upsert_setting(guild_id, column, value):
    async with _pool.acquire() as con:
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


# ─────────────────────── 활동 경고 추적 ───────────────────────
async def get_strikes(guild_id, user_id):
    async with _pool.acquire() as con:
        r = await con.fetchval(
            "SELECT strikes FROM activity_warnings WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )
    return r if r is not None else 0


async def add_strike(guild_id, user_id):
    async with _pool.acquire() as con:
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
    async with _pool.acquire() as con:
        await con.execute(
            "DELETE FROM activity_warnings WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )


async def list_open_recruit_ids():
    """봇 재시작 시 영구 View 복원용: 열린 모집글 ID 목록."""
    async with _pool.acquire() as con:
        rows = await con.fetch("SELECT id FROM recruits WHERE status = 'open'")
    return [r["id"] for r in rows]


# ─────────────────────── 익명 건의함 ───────────────────────
async def create_suggestion(guild_id, author_id, content):
    """건의 생성 후 id 반환."""
    async with _pool.acquire() as con:
        return await con.fetchval(
            """INSERT INTO suggestions (guild_id, author_id, content)
               VALUES ($1, $2, $3) RETURNING id""",
            guild_id, author_id, content,
        )


async def set_suggestion_public_msg(suggestion_id, message_id):
    async with _pool.acquire() as con:
        await con.execute(
            "UPDATE suggestions SET public_msg_id = $1 WHERE id = $2",
            message_id, suggestion_id,
        )


async def get_suggestion_author(suggestion_id):
    """서버 주인 전용. 작성자 ID 반환."""
    async with _pool.acquire() as con:
        return await con.fetchval(
            "SELECT author_id FROM suggestions WHERE id = $1", suggestion_id
        )


# ─────────────────────── 잠수 신고 ───────────────────────
async def create_leave_notice(guild_id, user_id, reason, until_date):
    """잠수 신고 생성. until_date는 datetime.date."""
    async with _pool.acquire() as con:
        return await con.fetchval(
            """INSERT INTO leave_notices (guild_id, user_id, reason, until_date)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            guild_id, user_id, reason, until_date,
        )


async def list_pending_leave_notices(guild_id):
    async with _pool.acquire() as con:
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
    async with _pool.acquire() as con:
        await con.execute(
            """UPDATE leave_notices
               SET status = 'approved', reviewed_by = $1, reviewed_at = now()
               WHERE id = $2""",
            reviewer_id, notice_id,
        )


async def reject_leave_notice(notice_id, reviewer_id):
    async with _pool.acquire() as con:
        await con.execute(
            """UPDATE leave_notices
               SET status = 'rejected', reviewed_by = $1, reviewed_at = now()
               WHERE id = $2""",
            reviewer_id, notice_id,
        )


async def get_leave_notice(notice_id):
    async with _pool.acquire() as con:
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
    async with _pool.acquire() as con:
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
    async with _pool.acquire() as con:
        result = await con.execute(
            """UPDATE leave_notices SET status = 'expired'
               WHERE status = 'approved' AND until_date < CURRENT_DATE"""
        )
    return result
