"""
규칙 인증 기능.
- 입장 시에는 역할을 주지 않는다.
- #규칙 채널 등에 설치된 인증 버튼을 누르면 인증 역할을 지급한다.
- 영구 View라서 봇 재시작 후에도 버튼이 동작한다.
"""

import discord
from discord.ext import commands
from discord import ui, app_commands

import database as db


class VerifyView(ui.View):
    """규칙 인증 버튼 (영구)."""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="인증하기", emoji="✅",
               style=discord.ButtonStyle.success, custom_id="verify:confirm")
    async def verify(self, interaction: discord.Interaction, button: ui.Button):
        settings = await db.get_settings(interaction.guild.id)
        role_id = settings.get("verified_role_id")
        if not role_id:
            await interaction.response.send_message(
                "아직 인증 역할이 설정되지 않았어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message(
                "인증 역할을 찾을 수 없어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return
        if role in interaction.user.roles:
            await interaction.response.send_message(
                "이미 인증이 완료된 상태예요!", ephemeral=True
            )
            return
        try:
            await interaction.user.add_roles(role, reason="규칙 인증")
        except discord.Forbidden:
            await interaction.response.send_message(
                "역할을 지급할 권한이 없어요. 봇 역할이 인증 역할보다 위에 있는지 확인해주세요.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"인증이 완료됐어요! {role.mention} 역할을 받았어요. 환영해요! 🎉",
            ephemeral=True,
        )


class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="인증패널", description="이 채널에 규칙 인증 버튼을 설치합니다 (관리자)")
    @app_commands.describe(안내문="인증 버튼 위에 표시할 안내 문구 (선택)")
    async def setup_verify(self, interaction: discord.Interaction, 안내문: str = None):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "서버 관리자만 사용할 수 있어요.", ephemeral=True
            )
            return
        settings = await db.get_settings(interaction.guild.id)
        if not settings.get("verified_role_id"):
            await interaction.response.send_message(
                "먼저 관리자 패널의 '🔓 인증 역할 지정'으로 인증 역할을 설정해주세요.",
                ephemeral=True,
            )
            return

        desc = 안내문 or (
            "아래 **인증하기** 버튼을 누르면 서버 이용에 필요한 역할을 받아요.\n"
            "규칙을 잘 읽고 동의하셨다면 인증해주세요!"
        )
        embed = discord.Embed(
            title="✅ 서버 인증",
            description=desc,
            color=0x248046,
        )
        await interaction.channel.send(embed=embed, view=VerifyView())
        await interaction.response.send_message("인증 패널을 설치했어요!", ephemeral=True)
