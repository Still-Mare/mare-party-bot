"""
닉네임 변경 공용 헬퍼 — 단일 진실원본(single source of truth).

관전 기능(SPECTATOR_PREFIX 접두사)과 셀프 닉네임 변경이 모두 이 모듈을 통해 닉을 바꾼다.
접두사 부착/제거, 32자 제한, 안전한 member.edit 호출을 한 곳에서 책임진다.
(DB 의존 없음 — 순수 헬퍼라 순환 import 위험이 없다.)
"""

import discord

SPECTATOR_PREFIX = "【👀관전】"
NICK_MAX = 32  # Discord 닉네임 최대 길이


def strip_prefix(name: str | None) -> str | None:
    """SPECTATOR_PREFIX 접두사를 제거한다. 접두사가 없으면 그대로 반환."""
    if name and name.startswith(SPECTATOR_PREFIX):
        return name[len(SPECTATOR_PREFIX):]
    return name


def current_base_nick(member: discord.Member) -> str:
    """현재 표시 닉에서 관전 접두사를 뗀 베이스. 닉이 없으면 username."""
    return strip_prefix(member.nick) or member.name


def with_prefix(base: str | None, member: discord.Member) -> str:
    """베이스 닉(없으면 username) 앞에 관전 접두사를 붙이고 32자로 자른다."""
    raw = base if base else member.name
    return (SPECTATOR_PREFIX + raw)[:NICK_MAX]


def nick_edit_block_reason(member: discord.Member) -> str | None:
    """봇이 이 멤버의 닉을 못 바꾸는 이유(한국어 설명)를 반환. 바꿀 수 있으면 None."""
    guild = member.guild
    if member.id == guild.owner_id:
        return "서버 주인의 닉네임은 디스코드 정책상 봇이 바꿀 수 없어요."
    me = guild.me
    if not me.guild_permissions.manage_nicknames:
        return "봇에 '별명 관리(Manage Nicknames)' 권한이 없어요."
    if not (me.top_role > member.top_role):
        return "회원님 역할이 봇 역할보다 높거나 같아서 닉네임을 못 바꿔요. 서버 관리자에게 봇 역할을 더 위로 옮겨달라고 요청해주세요."
    return None


def can_edit_nick(member: discord.Member) -> bool:
    """봇이 이 멤버의 닉을 바꿀 수 있는지 (owner 불가, 권한·역할 위치 확인)."""
    return nick_edit_block_reason(member) is None


async def set_nick(member: discord.Member, nick: str | None, *, reason: str) -> tuple[bool, str | None]:
    """
    member.edit(nick=...) 안전 호출. (성공여부, 에러메시지) 반환.
    nick 이 빈 문자열/공백/None 이면 None(= username 으로 초기화)으로 처리한다.
    """
    if member.id == member.guild.owner_id:
        return (False, "서버 주인의 닉네임은 디스코드 정책상 봇이 바꿀 수 없어요.")
    value = (nick or "").strip() or None
    if value:
        value = value[:NICK_MAX]
    try:
        await member.edit(nick=value, reason=reason)
        return (True, None)
    except discord.Forbidden:
        return (
            False,
            "봇 권한이 부족해요. 봇 역할을 대상보다 **위**로 올리고 '별명 관리(Manage Nicknames)' 권한을 켜주세요.",
        )
    except discord.HTTPException as e:
        return (False, f"디스코드 API 오류로 닉네임을 못 바꿨어요: {e}")
