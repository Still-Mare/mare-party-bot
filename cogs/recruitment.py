"""
파티 모집 기능.
- 모집글 작성: 게임 선택 → 모달(시간/인원/메모) → 게시 + 역할 멘션
- 참가 / 참가취소 / 마감 버튼 (영구 View)
- 참가자 명단 실시간 갱신
"""

import discord
from discord.ext import commands
from discord import ui

import database as db


def build_recruit_embed(recruit: dict, participant_members: list, host_member) -> discord.Embed:
    """모집글 임베드를 만든다. 참가자 명단 포함."""
    is_closed = recruit["status"] == "closed"
    color = 0x4E5058 if is_closed else 0x248046
    title = ("🔒 [마감] " if is_closed else "📢 ") + f"{recruit['game_name']} 파티 모집"

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="🎮 게임", value=recruit["game_name"], inline=True)
    embed.add_field(name="🕐 시간", value=recruit["play_time"], inline=True)
    embed.add_field(
        name="👥 인원",
        value=f"{len(participant_members)}/{recruit['max_players']}명",
        inline=True,
    )
    if recruit["note"]:
        embed.add_field(name="📝 메모", value=recruit["note"], inline=False)

    if participant_members:
        lines = []
        for i, m in enumerate(participant_members, 1):
            tag = " (모집자)" if m.id == recruit["host_id"] else ""
            lines.append(f"{i}. {m.display_name}{tag}")
        roster = "\n".join(lines)
    else:
        roster = "아직 참가자가 없어요."
    embed.add_field(name="참가자", value=roster, inline=False)

    if host_member:
        embed.set_footer(text=f"모집자: {host_member.display_name}")
    return embed


async def ensure_temp_role(guild, recruit):
    """모집의 임시 역할을 반환. 없으면 생성해서 DB에 저장."""
    import discord as _d
    if recruit["temp_role_id"]:
        role = guild.get_role(recruit["temp_role_id"])
        if role:
            return role
    # 생성
    try:
        role = await guild.create_role(
            name=f"파티-{recruit['game_name']}-{recruit['id']}",
            mentionable=True,
            reason=f"모집 #{recruit['id']} 임시 역할",
        )
    except _d.Forbidden:
        return None
    await db.set_recruit_temp_role(recruit["id"], role.id)
    return role


async def grant_temp_role(guild, recruit, member):
    """참가자에게 임시 역할 부여."""
    role = await ensure_temp_role(guild, recruit)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason="파티 참가")
        except Exception:
            pass


async def revoke_temp_role(guild, recruit, member):
    """참가 취소자에게서 임시 역할 회수."""
    if not recruit["temp_role_id"]:
        return
    role = guild.get_role(recruit["temp_role_id"])
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason="파티 참가 취소")
        except Exception:
            pass


async def delete_temp_role(guild, recruit):
    """모집 종료 시 임시 역할 자체를 삭제 (모든 보유자에게서 자동 제거됨)."""
    if not recruit["temp_role_id"]:
        return
    role = guild.get_role(recruit["temp_role_id"])
    if role:
        try:
            await role.delete(reason="파티 모집 종료")
        except Exception:
            pass
    await db.set_recruit_temp_role(recruit["id"], None)


async def refresh_recruit_message(bot, recruit_id: int):
    """DB 기준으로 모집글 메시지를 다시 그린다."""
    recruit = await db.get_recruit(recruit_id)
    if not recruit or not recruit["message_id"]:
        return
    guild = bot.get_guild(recruit["guild_id"])
    if not guild:
        return
    channel = guild.get_channel(recruit["channel_id"])
    if not channel:
        return
    try:
        msg = await channel.fetch_message(recruit["message_id"])
    except discord.NotFound:
        return

    user_ids = await db.list_participants(recruit_id)
    members = []
    for uid in user_ids:
        m = guild.get_member(uid)
        if m:
            members.append(m)
    host = guild.get_member(recruit["host_id"])

    embed = build_recruit_embed(recruit, members, host)
    view = None if recruit["status"] == "closed" else RecruitView(recruit_id)
    await msg.edit(embed=embed, view=view)


# ───────── 모집 작성 모달 ─────────
class RecruitModal(ui.Modal, title="파티 모집글 작성"):
    def __init__(self, game_name: str):
        super().__init__()
        self.game_name = game_name

    play_time = ui.TextInput(label="플레이 시간", placeholder="예: 오늘 21:00", max_length=50)
    max_players = ui.TextInput(label="모집 인원 (본인 포함)", placeholder="예: 5", max_length=3)
    note = ui.TextInput(
        label="메모 (선택)",
        placeholder="예: 골드 이상, 마이크 필수",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_p = int(str(self.max_players).strip())
            if max_p < 2 or max_p > 99:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "인원은 2~99 사이 숫자로 입력해주세요.", ephemeral=True
            )
            return

        recruit_id = await db.create_recruit(
            interaction.guild.id,
            interaction.channel.id,
            interaction.user.id,
            self.game_name,
            str(self.play_time).strip(),
            max_p,
            str(self.note).strip() or None,
        )

        recruit = await db.get_recruit(recruit_id)
        host = interaction.user
        embed = build_recruit_embed(recruit, [host], host)
        view = RecruitView(recruit_id)

        # 역할 멘션
        game = await db.get_game(interaction.guild.id, self.game_name)
        mention = ""
        if game:
            role = interaction.guild.get_role(game["role_id"])
            if role:
                mention = role.mention

        await interaction.response.send_message(
            content=mention or None, embed=embed, view=view
        )
        sent = await interaction.original_response()
        await db.set_recruit_message(recruit_id, sent.id)

        # 모집자에게 임시 역할 부여
        recruit = await db.get_recruit(recruit_id)
        await grant_temp_role(interaction.guild, recruit, host)


# ───────── 게임 선택 (모집 시작) ─────────
class GamePickSelect(ui.Select):
    def __init__(self, games):
        options = [
            discord.SelectOption(label=g["name"], emoji=g["emoji"] or None)
            for g in games
        ]
        super().__init__(placeholder="모집할 게임 선택", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RecruitModal(self.values[0]))


class GamePickView(ui.View):
    def __init__(self, games):
        super().__init__(timeout=60)
        self.add_item(GamePickSelect(games))


# ───────── 모집글 버튼 (영구 View) ─────────
class RecruitView(ui.View):
    def __init__(self, recruit_id: int):
        super().__init__(timeout=None)
        self.recruit_id = recruit_id
        # custom_id에 recruit_id를 박아서 재시작 후에도 동작
        self.join_btn.custom_id = f"recruit_join:{recruit_id}"
        self.leave_btn.custom_id = f"recruit_leave:{recruit_id}"
        self.voice_btn.custom_id = f"recruit_voice:{recruit_id}"
        self.close_btn.custom_id = f"recruit_close:{recruit_id}"

    @ui.button(label="참가", emoji="✋", style=discord.ButtonStyle.success, row=0)
    async def join_btn(self, interaction: discord.Interaction, button: ui.Button):
        recruit = await db.get_recruit(self.recruit_id)
        if not recruit or recruit["status"] != "open":
            await interaction.response.send_message("마감된 모집이에요.", ephemeral=True)
            return
        current = await db.list_participants(self.recruit_id)
        if len(current) >= recruit["max_players"]:
            await interaction.response.send_message("이미 인원이 다 찼어요.", ephemeral=True)
            return
        added = await db.add_participant(self.recruit_id, interaction.user.id)
        if not added:
            await interaction.response.send_message("이미 참가 중이에요.", ephemeral=True)
            return
        await grant_temp_role(interaction.guild, recruit, interaction.user)
        await interaction.response.send_message("참가했어요!", ephemeral=True)
        await refresh_recruit_message(interaction.client, self.recruit_id)

    @ui.button(label="참가 취소", emoji="❌", style=discord.ButtonStyle.secondary, row=0)
    async def leave_btn(self, interaction: discord.Interaction, button: ui.Button):
        recruit = await db.get_recruit(self.recruit_id)
        if not recruit:
            return
        current = await db.list_participants(self.recruit_id)
        if interaction.user.id not in current:
            await interaction.response.send_message("참가하지 않은 상태예요.", ephemeral=True)
            return
        if interaction.user.id == recruit["host_id"]:
            await interaction.response.send_message(
                "모집자는 본인을 뺄 수 없어요. 모집을 마감해주세요.", ephemeral=True
            )
            return
        await db.remove_participant(self.recruit_id, interaction.user.id)
        await revoke_temp_role(interaction.guild, recruit, interaction.user)
        await interaction.response.send_message("참가를 취소했어요.", ephemeral=True)
        await refresh_recruit_message(interaction.client, self.recruit_id)

    @ui.button(label="음성방 열기", emoji="🔊", style=discord.ButtonStyle.primary, row=1)
    async def voice_btn(self, interaction: discord.Interaction, button: ui.Button):
        recruit = await db.get_recruit(self.recruit_id)
        if not recruit or recruit["status"] != "open":
            await interaction.response.send_message("마감된 모집이에요.", ephemeral=True)
            return

        # 이미 음성방이 있으면 안내
        if recruit["voice_channel_id"]:
            existing = interaction.guild.get_channel(recruit["voice_channel_id"])
            if existing:
                await interaction.response.send_message(
                    f"이미 음성방이 있어요: {existing.mention}", ephemeral=True
                )
                return

        settings = await db.get_settings(interaction.guild.id)
        category = None
        if settings["voice_category_id"]:
            category = interaction.guild.get_channel(settings["voice_category_id"])

        # 참가자만 접근 가능하게 권한 설정
        user_ids = await db.list_participants(self.recruit_id)
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(connect=False),
            interaction.guild.me: discord.PermissionOverwrite(
                connect=True, manage_channels=True, move_members=True
            ),
        }
        for uid in user_ids:
            member = interaction.guild.get_member(uid)
            if member:
                overwrites[member] = discord.PermissionOverwrite(connect=True)

        try:
            vc = await interaction.guild.create_voice_channel(
                name=f"🎮 {recruit['game_name']} 파티",
                category=category,
                user_limit=recruit["max_players"],
                overwrites=overwrites,
                reason=f"모집 #{self.recruit_id} 음성방",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "음성방을 만들 권한이 없어요. 봇에 '채널 관리' 권한을 주세요.", ephemeral=True
            )
            return

        await db.set_recruit_voice(self.recruit_id, vc.id)

        # 누른 사람이 음성방에 있으면 이동
        if interaction.user.voice and interaction.user.voice.channel:
            try:
                await interaction.user.move_to(vc)
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            f"음성방을 만들었어요: {vc.mention}\n참가자 전원이 나가면 자동으로 닫혀요.",
            ephemeral=True,
        )
        await refresh_recruit_message(interaction.client, self.recruit_id)

    @ui.button(label="모집 마감", emoji="🔒", style=discord.ButtonStyle.danger, row=1)
    async def close_btn(self, interaction: discord.Interaction, button: ui.Button):
        recruit = await db.get_recruit(self.recruit_id)
        if not recruit:
            return
        # 모집자 또는 관리자만 마감 가능
        is_admin = interaction.user.guild_permissions.manage_messages
        if interaction.user.id != recruit["host_id"] and not is_admin:
            await interaction.response.send_message(
                "모집자나 관리자만 마감할 수 있어요.", ephemeral=True
            )
            return
        await db.close_recruit(self.recruit_id)
        await delete_temp_role(interaction.guild, recruit)
        await interaction.response.send_message("모집을 마감했어요.", ephemeral=True)
        await refresh_recruit_message(interaction.client, self.recruit_id)


class Recruitment(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def archive_recruit_to_channel(bot, recruit_id: int):
    """
    음성방이 닫힐 때 호출.
    모집글을 아카이브 채널에 복제하고 원본을 삭제한다.
    (디스코드는 메시지 이동이 불가능하므로 재게시 방식)
    """
    recruit = await db.get_recruit(recruit_id)
    if not recruit:
        return
    guild = bot.get_guild(recruit["guild_id"])
    if not guild:
        return

    settings = await db.get_settings(guild.id)
    archive_channel = None
    if settings["archive_channel_id"]:
        archive_channel = guild.get_channel(settings["archive_channel_id"])

    # 참가자 명단 수집
    user_ids = await db.list_participants(recruit_id)
    members = [guild.get_member(uid) for uid in user_ids]
    members = [m for m in members if m]
    host = guild.get_member(recruit["host_id"])

    # 아카이브 채널에 종료된 모집글 재게시
    if archive_channel:
        embed = build_recruit_embed(recruit, members, host)
        embed.color = 0x4E5058
        embed.title = "📦 [종료] " + recruit["game_name"] + " 파티"
        embed.add_field(name="상태", value="음성방이 닫혀 자동 종료됨", inline=False)
        try:
            await archive_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # 원본 모집글 + 스레드 삭제
    channel = guild.get_channel(recruit["channel_id"])
    if channel and recruit["message_id"]:
        try:
            msg = await channel.fetch_message(recruit["message_id"])
            # 딸린 스레드가 있으면 함께 삭제
            if msg.thread:
                try:
                    await msg.thread.delete()
                except discord.HTTPException:
                    pass
            await msg.delete()
        except discord.NotFound:
            pass

    # 임시 역할 삭제 (모든 보유자에게서 자동 제거됨)
    await delete_temp_role(guild, recruit)

    await db.archive_recruit(recruit_id)


async def setup(bot):
    await bot.add_cog(Recruitment(bot))
