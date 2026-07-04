"""
인터랙션 권한 체크 공용 헬퍼.

각 cog에 복붙되어 있던 권한 가드(권한 확인 → 실패 시 ephemeral 안내 → return)를
한 곳으로 모은다. 동작 보존이 원칙 — 요구 권한과 안내 문구는 기존 그대로이며,
문구가 다른 곳은 msg 인자로 재정의한다.

사용 패턴:
    if not await ensure_manage_guild(interaction):
        return
"""

import discord

import database as db

PERM_DENIED_MSG = "관리자만 사용할 수 있어요."


async def _ensure_perm(interaction: discord.Interaction, perm: str, msg: str) -> bool:
    if getattr(interaction.user.guild_permissions, perm):
        return True
    await interaction.response.send_message(msg, ephemeral=True)
    return False


async def ensure_manage_guild(interaction: discord.Interaction, msg: str = PERM_DENIED_MSG) -> bool:
    """manage_guild 가드. 권한 없으면 ephemeral 안내 후 False."""
    return await _ensure_perm(interaction, "manage_guild", msg)


async def ensure_manage_roles(interaction: discord.Interaction, msg: str = PERM_DENIED_MSG) -> bool:
    """manage_roles 가드. 권한 없으면 ephemeral 안내 후 False."""
    return await _ensure_perm(interaction, "manage_roles", msg)


async def ensure_kick_members(interaction: discord.Interaction, msg: str = PERM_DENIED_MSG) -> bool:
    """kick_members 가드. 권한 없으면 ephemeral 안내 후 False."""
    return await _ensure_perm(interaction, "kick_members", msg)


async def can_manage_panel(interaction: discord.Interaction) -> bool:
    """서버 관리자이거나, 지정된 패널 관리 역할 보유자면 True."""
    if interaction.user.guild_permissions.manage_guild:
        return True
    settings = await db.get_settings(interaction.guild.id)
    role_id = settings.get("panel_manager_role")
    return bool(role_id and any(r.id == role_id for r in interaction.user.roles))
