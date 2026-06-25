"""
셀프 닉네임 변경 + 변경 이력 로깅.

- 서버가 @everyone 의 '별명 변경'을 막아둬도, 봇이 '별명 관리' 권한으로 대신 바꿔준다.
- 유저는 '내 활동' 패널의 [✏️ 닉네임 변경] 버튼 → 모달로 변경한다 (버튼/모달 기반, 외우는 명령 없음).
- 변경 시 nickname_history 에 old→new 기록 + (설정 시) 로그 채널에 임베드 게시.
- 관전 중인 유저가 닉을 바꾸면 '관전 ' 접두사를 재적용하고 관전 원본 닉도 갱신한다 (nick_util 단일 경로).
"""

import time
import logging

import discord
from discord.ext import commands
from discord import ui

import database as db
from cogs import nick_util

log = logging.getLogger("party-bot")

# 셀프 닉변 쿨다운 (초) — 연타 어뷰징 방지
_NICK_COOLDOWN_SECS = 60
_nick_cooldown: dict[tuple[int, int], float] = {}


# ───────── 셀프 닉네임 변경 모달 ─────────
class NicknameModal(ui.Modal, title="닉네임 변경"):
    new_nick = ui.TextInput(
        label="새 닉네임",
        placeholder="비우면 원래 이름으로 초기화돼요",
        required=False,
        max_length=nick_util.NICK_MAX,
    )

    async def on_submit(self, interaction: discord.Interaction):
        member = interaction.user
        guild = interaction.guild

        # 서버 주인 / 권한·역할 위치 사전 검사
        if member.id == guild.owner_id:
            await interaction.response.send_message(
                "서버 주인의 닉네임은 디스코드 정책상 봇이 바꿀 수 없어요.", ephemeral=True
            )
            return
        me = guild.me
        if not me.guild_permissions.manage_nicknames:
            await interaction.response.send_message(
                "봇에게 '별명 관리(Manage Nicknames)' 권한이 없어요. 관리자에게 문의해주세요.",
                ephemeral=True,
            )
            return
        if me.top_role <= member.top_role:
            await interaction.response.send_message(
                "봇 역할이 회원님 역할보다 아래에 있어 닉네임을 바꿀 수 없어요. "
                "관리자에게 봇 역할을 위로 올려달라고 요청해주세요.",
                ephemeral=True,
            )
            return

        # 쿨다운
        key = (guild.id, member.id)
        now = time.monotonic()
        last = _nick_cooldown.get(key)
        if last is not None and (now - last) < _NICK_COOLDOWN_SECS:
            remain = int(_NICK_COOLDOWN_SECS - (now - last))
            await interaction.response.send_message(
                f"닉네임은 {_NICK_COOLDOWN_SECS}초에 한 번만 바꿀 수 있어요. {remain}초 후 다시 시도해주세요.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        old_base = nick_util.current_base_nick(member)        # 관전 접두사 제외한 현재 베이스
        new_base = str(self.new_nick).strip() or None

        # 관전 중이면 접두사 재적용 + 관전 원본 닉 갱신
        spectating = await db.get_spectating_recruit_ids(guild.id, member.id)
        if spectating:
            desired = nick_util.with_prefix(new_base, member)
            ok, err = await nick_util.set_nick(member, desired, reason="셀프 닉네임 변경(관전 중)")
            if ok:
                await db.update_spectator_original_nick(guild.id, member.id, new_base)
        else:
            ok, err = await nick_util.set_nick(member, new_base, reason="셀프 닉네임 변경")

        if not ok:
            await interaction.followup.send(err or "닉네임을 바꾸지 못했어요.", ephemeral=True)
            return

        _nick_cooldown[key] = now
        await db.log_nickname_change(guild.id, member.id, old_base, new_base, member.id)

        # 로그 채널 게시 (선택)
        settings = await db.get_settings(guild.id)
        log_ch_id = settings.get("nickname_log_channel_id")
        if log_ch_id:
            ch = guild.get_channel(log_ch_id)
            if ch:
                embed = discord.Embed(title="✏️ 닉네임 변경", color=0x5865F2)
                embed.add_field(name="유저", value=f"{member.mention} (`{member.id}`)", inline=False)
                embed.add_field(name="이전", value=old_base or "_(없음)_", inline=True)
                embed.add_field(name="이후", value=new_base or "_(원래 이름)_", inline=True)
                try:
                    await ch.send(embed=embed)
                except discord.HTTPException:
                    pass

        shown = new_base or "원래 이름(초기화)"
        await interaction.followup.send(f"닉네임을 **{shown}**(으)로 바꿨어요!", ephemeral=True)


# ───────── 닉네임 변경 전용 패널 (영구) ─────────
class NicknamePanelView(ui.View):
    """특정 채널에 설치하는 닉네임 변경 버튼 패널 (영구 View)."""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="닉네임 변경하기", emoji="✏️",
               style=discord.ButtonStyle.primary, custom_id="nickname:open")
    async def open(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(NicknameModal())


def build_nickname_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✏️ 닉네임 변경",
        description=(
            "아래 **닉네임 변경하기** 버튼을 누르면 원하는 닉네임으로 바꿀 수 있어요.\n"
            "비워서 보내면 원래 이름으로 초기화돼요.\n"
            f"(어뷰징 방지를 위해 {_NICK_COOLDOWN_SECS}초에 한 번만 바꿀 수 있어요.)"
        ),
        color=0x5865F2,
    )
    embed.set_footer(text="변경 내역은 운영진이 확인할 수 있어요.")
    return embed


# ───────── 관리자: 닉네임 변경 이력 조회 ─────────
def build_nick_history_embed(guild, target: discord.Member, rows: list) -> discord.Embed:
    embed = discord.Embed(
        title=f"✏️ 닉네임 변경 이력 — {target.display_name}",
        color=0x5865F2,
    )
    if not rows:
        embed.description = "기록이 없어요."
        return embed
    lines = []
    for r in rows:
        old = r["old_nick"] or "_(없음)_"
        new = r["new_nick"] or "_(초기화)_"
        when = r["changed_at"].strftime("%Y-%m-%d %H:%M")
        by = "" if r["changed_by"] == target.id else f" (변경: <@{r['changed_by']}>)"
        lines.append(f"`{when}` {old} → **{new}**{by}")
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"최근 {len(rows)}건")
    return embed


class NickHistoryUserSelect(ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="이력을 볼 유저 선택", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        target = self.values[0]
        rows = await db.get_nickname_history(interaction.guild.id, target.id, limit=15)
        embed = build_nick_history_embed(interaction.guild, target, rows)
        await interaction.followup.send(embed=embed, ephemeral=True)


class NickHistoryUserSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(NickHistoryUserSelect())


class NickLogChannelSelect(ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="닉네임 로그 채널 선택",
            channel_types=[discord.ChannelType.text],
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        channel = self.values[0]
        await db.set_nickname_log_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"닉네임 변경 로그 채널을 <#{channel.id}>(으)로 설정했어요.", ephemeral=True
        )


class NickLogChannelSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(NickLogChannelSelect())


class Nicknames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(Nicknames(bot))
