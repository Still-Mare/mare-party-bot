"""
게임 역할 관리 기능.
- 관리자: 게임 추가/삭제 (역할 자동 생성)
- 유저  : 게임 역할 토글 (버튼)
"""

import discord
from discord.ext import commands
from discord import ui

import database as db


# ───────── 게임 추가 모달 ─────────
class AddGameModal(ui.Modal, title="게임 추가"):
    game_name = ui.TextInput(label="게임 이름", placeholder="예: 발로란트", max_length=40)
    emoji = ui.TextInput(label="이모지", placeholder="예: 🎯", max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        name = str(self.game_name).strip()
        emoji = str(self.emoji).strip()
        guild = interaction.guild

        existing = await db.get_game(guild.id, name)
        if existing:
            await interaction.response.send_message(
                f"이미 '{name}' 게임이 등록되어 있어요.", ephemeral=True
            )
            return

        # 같은 이름의 역할이 이미 있으면 재사용, 없으면 생성
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            try:
                role = await guild.create_role(
                    name=name, mentionable=True, reason=f"{interaction.user}가 게임 추가"
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    "역할을 만들 권한이 없어요. 봇 역할에 '역할 관리' 권한을 주세요.",
                    ephemeral=True,
                )
                return

        await db.add_game(guild.id, name, emoji, role.id)
        await interaction.response.send_message(
            f"{emoji} '{name}' 게임을 추가했어요! 역할 {role.mention} 이 생성됐어요.",
            ephemeral=True,
        )
        # 역할 선택 패널 갱신
        await refresh_role_panel(interaction)


# ───────── 게임 삭제 선택 ─────────
class RemoveGameSelect(ui.Select):
    def __init__(self, games):
        options = [
            discord.SelectOption(label=g["name"], emoji=g["emoji"] or None)
            for g in games
        ]
        super().__init__(placeholder="삭제할 게임 선택", options=options, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]
        game = await db.get_game(interaction.guild.id, name)
        await db.remove_game(interaction.guild.id, name)
        # 역할도 삭제 (선택)
        if game:
            role = interaction.guild.get_role(game["role_id"])
            if role:
                try:
                    await role.delete(reason="게임 삭제")
                except discord.Forbidden:
                    pass
        await interaction.response.send_message(f"'{name}' 게임을 삭제했어요.", ephemeral=True)
        await refresh_role_panel(interaction)


class RemoveGameView(ui.View):
    def __init__(self, games):
        super().__init__(timeout=60)
        self.add_item(RemoveGameSelect(games))


# ───────── 역할 토글 버튼 (영구 View) ─────────
class RoleToggleButton(ui.Button):
    def __init__(self, game):
        super().__init__(
            label=game["name"],
            emoji=game["emoji"] or None,
            style=discord.ButtonStyle.secondary,
            custom_id=f"roletoggle:{game['role_id']}",
        )
        self.role_id = game["role_id"]

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message("역할을 찾을 수 없어요.", ephemeral=True)
            return
        member = interaction.user
        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(f"{role.name} 역할을 뺐어요.", ephemeral=True)
        else:
            await member.add_roles(role)
            await interaction.response.send_message(f"{role.name} 역할을 받았어요!", ephemeral=True)


class RolePanelView(ui.View):
    """게임 역할 토글 버튼들을 담는 영구 View."""
    def __init__(self, games):
        super().__init__(timeout=None)
        for g in games[:25]:  # 버튼은 최대 25개
            self.add_item(RoleToggleButton(g))


async def refresh_role_panel(interaction: discord.Interaction):
    """역할 선택 메시지를 새로고침해서 최신 게임 목록을 반영."""
    games = await db.list_games(interaction.guild.id)
    if not games:
        return
    view = RolePanelView(games)
    embed = discord.Embed(
        title="🎮 게임 역할 선택",
        description="아래 버튼을 눌러 게임 역할을 받거나 뺄 수 있어요.\n"
                    "역할을 받으면 해당 게임 모집글에 알림이 가요.",
        color=0x5865F2,
    )
    # 채널에 새 패널 전송 (followup)
    await interaction.followup.send(embed=embed, view=view)


class GameRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(GameRoles(bot))
