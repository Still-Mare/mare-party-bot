"""
익명 건의함.
- 유저가 컨트롤 패널에서 버튼 → 모달로 건의 작성
- 관리자 채널(로그 채널)에 익명으로 게시: 작성자 표시 ❌
- '작성자 확인' 버튼은 서버 주인(owner)만 사용 가능
- 다른 관리자는 내용만 보고 처리

* 완전한 익명은 아니다. DB에는 작성자 ID가 저장되며, 서버 주인 1명이 추적 가능.
  이 점은 유저에게 명시적으로 안내된다 (모달 설명에 표시).
"""

import discord
from discord.ext import commands
from discord import ui

import database as db
from cogs import palette


class SuggestionModal(ui.Modal, title="익명 건의 작성"):
    content = ui.TextInput(
        label="건의 내용 (서버 주인만 작성자 확인 가능)",
        placeholder="개선 아이디어, 운영 피드백, 불편 사항 등을 자유롭게 적어주세요.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        settings = await db.get_settings(interaction.guild.id)
        log_channel_id = settings.get("review_log_channel")
        if not log_channel_id:
            await interaction.response.send_message(
                "건의를 전달할 관리자 채널이 설정되지 않았어요. 관리자에게 문의해주세요.",
                ephemeral=True,
            )
            return
        channel = interaction.guild.get_channel(log_channel_id)
        if not channel:
            await interaction.response.send_message(
                "관리자 채널을 찾을 수 없어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return

        text = str(self.content).strip()
        if not text:
            await interaction.response.send_message("내용을 입력해주세요.", ephemeral=True)
            return

        suggestion_id = await db.create_suggestion(
            interaction.guild.id, interaction.user.id, text
        )

        # 익명 임베드: 작성자 정보 없음
        embed = discord.Embed(
            title="📨 새 익명 건의",
            description=text,
            color=palette.INFO,
        )
        embed.set_footer(text=f"건의 #{suggestion_id} · 서버 주인만 작성자를 확인할 수 있어요")

        view = SuggestionAdminView()
        msg = await channel.send(embed=embed, view=view)
        await db.set_suggestion_public_msg(suggestion_id, msg.id)

        await interaction.response.send_message(
            "건의가 전달됐어요. 익명으로 보낸 사람은 서버 주인만 확인할 수 있어요.\n"
            "소중한 의견 감사합니다!",
            ephemeral=True,
        )


class SuggestionAdminView(ui.View):
    """
    건의글에 붙는 영구 View. 서버 주인만 작성자 확인 가능.

    custom_id를 단일 고정값 "suggestion_reveal"로 유지하여
    bot.add_view(SuggestionAdminView()) 한 번으로 모든 건의 버튼을 처리한다.
    건의 ID는 interaction.message.id → DB 조회로 결정한다.
    """
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="작성자 확인", emoji="🔍",
               style=discord.ButtonStyle.secondary, custom_id="suggestion_reveal")
    async def reveal_btn(self, interaction: discord.Interaction, button: ui.Button):
        # 서버 주인(owner)만 가능
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "서버 주인만 작성자를 확인할 수 있어요.", ephemeral=True
            )
            return

        # 메시지 ID로 건의 조회 — 봇 재시작 후에도 동작
        sid = await db.get_suggestion_by_message(interaction.message.id)
        if not sid:
            await interaction.response.send_message(
                "건의를 찾을 수 없어요. (DB에 메시지 ID가 기록되지 않은 구버전 건의일 수 있어요)",
                ephemeral=True,
            )
            return

        author_id = await db.get_suggestion_author(sid)
        if not author_id:
            await interaction.response.send_message("건의를 찾을 수 없어요.", ephemeral=True)
            return
        member = interaction.guild.get_member(author_id)
        name = f"{member.display_name} ({member.mention})" if member else f"<@{author_id}> (서버에 없음)"
        await interaction.response.send_message(
            f"이 건의의 작성자: {name}\n\n"
            f"※ 익명성 보장을 위해 다른 사람과 공유하지 말아주세요.",
            ephemeral=True,
        )


class Suggestions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(Suggestions(bot))
