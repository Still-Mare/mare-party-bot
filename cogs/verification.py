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

    @ui.button(label="오픈채팅 입장하기", emoji="💬",
               style=discord.ButtonStyle.primary, custom_id="verify:openchat")
    async def openchat(self, interaction: discord.Interaction, button: ui.Button):
        """
        이중보안 2차 게이트: 1차 인증을 마친 사람에게만 카카오 오픈채팅 URL을
        '본인에게만 보이는(ephemeral)' 메시지로 전달한다. URL은 어떤 채널에도 게시되지
        않으므로 외부 채팅 유도 링크로 인한 초대코드 정지 위험이 없다.
        """
        settings = await db.get_settings(interaction.guild.id)
        url = settings.get("openchat_url")
        if not url:
            await interaction.response.send_message(
                "아직 오픈채팅이 설정되지 않았어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return

        # 1차 인증 선검사 (이중보안)
        verified_role_id = settings.get("verified_role_id")
        if verified_role_id:
            vrole = interaction.guild.get_role(verified_role_id)
            if vrole and vrole not in interaction.user.roles:
                await interaction.response.send_message(
                    "먼저 위의 **인증하기** 버튼으로 인증을 완료해주세요. (이중 보안)",
                    ephemeral=True,
                )
                return

        # 2차 게이트 통과 역할 부여 (선택)
        gate_role_id = settings.get("openchat_gate_role_id")
        if gate_role_id:
            grole = interaction.guild.get_role(gate_role_id)
            if grole and grole not in interaction.user.roles:
                try:
                    await interaction.user.add_roles(grole, reason="오픈채팅 게이트 통과")
                except discord.HTTPException:
                    pass

        await interaction.response.send_message(
            f"💬 **오픈채팅 입장 링크**\n{url}\n\n"
            "(이 메시지는 회원님에게만 보여요. 링크는 외부에 공유하지 말아주세요.)",
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

        # DB 조회 전 defer — 3초 타임아웃 방지
        await interaction.response.defer(ephemeral=True)

        settings = await db.get_settings(interaction.guild.id)
        if not settings.get("verified_role_id"):
            await interaction.followup.send(
                "먼저 관리자 패널의 '🔓 인증 역할 지정'으로 인증 역할을 설정해주세요.",
                ephemeral=True,
            )
            return

        # 채널 권한 확인
        perms = interaction.channel.permissions_for(interaction.guild.me)
        missing = []
        if not perms.send_messages:
            missing.append("메시지 보내기 (Send Messages)")
        if not perms.embed_links:
            missing.append("임베드 링크 (Embed Links)")
        if missing:
            await interaction.followup.send(
                f"**{interaction.channel.mention} 채널에 인증 패널을 설치할 수 없어요.**\n\n"
                "봇에게 아래 권한이 부족해요:\n"
                + "\n".join(f"• **{p}**" for p in missing)
                + "\n\n채널 편집 → 권한 탭에서 봇 역할을 직접 추가해 위 항목을 체크해주세요.",
                ephemeral=True,
            )
            return

        desc = 안내문 or (
            "아래 **인증하기** 버튼을 누르면 서버 이용에 필요한 역할을 받아요.\n"
            "규칙을 잘 읽고 동의하셨다면 인증해주세요!"
        )
        embed = discord.Embed(title="✅ 서버 인증", description=desc, color=0x248046)

        try:
            await interaction.channel.send(embed=embed, view=VerifyView())
        except discord.Forbidden as e:
            await interaction.followup.send(
                f"권한 오류 (403 / code {e.code}): {e.text}\n"
                "채널 편집 → 권한 탭에서 봇 역할 권한을 확인해주세요.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Discord API 오류 ({e.status} / code {e.code}): {e.text}",
                ephemeral=True,
            )
            return

        await interaction.followup.send("인증 패널을 설치했어요!", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Verification(bot))
