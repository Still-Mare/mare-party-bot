"""
컨트롤 패널.
한 채널에 고정해두는 메인 버튼 묶음.
유저는 여기서 버튼만 눌러 모든 기능을 시작한다.
"""

import discord
from discord.ext import commands
from discord import ui, app_commands

import database as db
from cogs.game_roles import (
    AddGameModal, RemoveGameView, RolePanelView,
)
from cogs.recruitment import GamePickView
from cogs.voice_stats import build_my_stats_embed, build_ranking_embed


class ControlPanelView(ui.View):
    """영구 컨트롤 패널 View."""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="파티 모집하기", emoji="📢",
               style=discord.ButtonStyle.success, custom_id="panel:recruit", row=0)
    async def recruit(self, interaction: discord.Interaction, button: ui.Button):
        games = await db.list_games(interaction.guild.id)
        if not games:
            await interaction.response.send_message(
                "등록된 게임이 없어요. 관리자가 먼저 '게임 추가'로 게임을 등록해야 해요.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "모집할 게임을 선택하세요.", view=GamePickView(games), ephemeral=True
        )

    @ui.button(label="게임 역할 받기", emoji="🎮",
               style=discord.ButtonStyle.primary, custom_id="panel:roles", row=0)
    async def roles(self, interaction: discord.Interaction, button: ui.Button):
        games = await db.list_games(interaction.guild.id)
        if not games:
            await interaction.response.send_message("등록된 게임이 없어요.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🎮 게임 역할 선택",
            description="버튼을 눌러 역할을 받거나 뺄 수 있어요.",
            color=0x5865F2,
        )
        await interaction.response.send_message(
            embed=embed, view=RolePanelView(games), ephemeral=True
        )

    @ui.button(label="내 음성시간", emoji="🔊",
               style=discord.ButtonStyle.secondary, custom_id="panel:mytime", row=1)
    async def mytime(self, interaction: discord.Interaction, button: ui.Button):
        embed = await build_my_stats_embed(interaction.guild.id, interaction.user)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="음성 랭킹", emoji="📊",
               style=discord.ButtonStyle.secondary, custom_id="panel:ranking", row=1)
    async def ranking(self, interaction: discord.Interaction, button: ui.Button):
        embed = await build_ranking_embed(
            interaction.client, interaction.guild, period="week"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="익명 건의", emoji="📨",
               style=discord.ButtonStyle.secondary, custom_id="panel:suggest", row=2)
    async def suggest(self, interaction: discord.Interaction, button: ui.Button):
        from cogs.suggestions import SuggestionModal
        await interaction.response.send_modal(SuggestionModal())

    @ui.button(label="잠수 신고", emoji="🕊️",
               style=discord.ButtonStyle.secondary, custom_id="panel:leave", row=2)
    async def leave_notice(self, interaction: discord.Interaction, button: ui.Button):
        from cogs.leave_notices import LeaveStartView
        embed = discord.Embed(
            title="🕊️ 잠수 신고",
            description=(
                "활동검토에서 일정 기간 제외받을 수 있어요.\n\n"
                "**기간을 선택**하거나 **직접 날짜를 입력**해주세요. "
                "관리자 승인 후 적용돼요."
            ),
            color=0xBA7517,
        )
        await interaction.response.send_message(
            embed=embed, view=LeaveStartView(), ephemeral=True
        )


class AdminPanelView(ui.View):
    """관리자 전용 패널."""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="게임 추가", emoji="➕",
               style=discord.ButtonStyle.success, custom_id="admin:addgame", row=0)
    async def add_game(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_modal(AddGameModal())

    @ui.button(label="게임 삭제", emoji="🗑️",
               style=discord.ButtonStyle.danger, custom_id="admin:delgame", row=0)
    async def del_game(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        games = await db.list_games(interaction.guild.id)
        if not games:
            await interaction.response.send_message("등록된 게임이 없어요.", ephemeral=True)
            return
        await interaction.response.send_message(
            "삭제할 게임을 선택하세요.", view=RemoveGameView(games), ephemeral=True
        )

    @ui.button(label="주간 랭킹 초기화", emoji="🔄",
               style=discord.ButtonStyle.secondary, custom_id="admin:resetweek", row=1)
    async def reset_week(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await db.reset_week(interaction.guild.id)
        await interaction.response.send_message("이번 주 음성 랭킹을 초기화했어요.", ephemeral=True)

    @ui.button(label="음성방 카테고리 지정", emoji="📁",
               style=discord.ButtonStyle.secondary, custom_id="admin:setcategory", row=2)
    async def set_category(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        categories = interaction.guild.categories
        if not categories:
            await interaction.response.send_message("서버에 카테고리가 없어요.", ephemeral=True)
            return
        await interaction.response.send_message(
            "음성방을 만들 카테고리를 선택하세요.",
            view=CategorySelectView(categories), ephemeral=True,
        )

    @ui.button(label="아카이브 채널 지정", emoji="📦",
               style=discord.ButtonStyle.secondary, custom_id="admin:setarchive", row=2)
    async def set_archive(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_message(
            "종료된 모집글을 보낼 채널을 선택하세요. (관리자만 보이는 채널 권장)",
            view=ArchiveSelectView(), ephemeral=True,
        )

    @ui.button(label="활동검토 설정", emoji="📋",
               style=discord.ButtonStyle.secondary, custom_id="admin:reviewsettings", row=3)
    async def review_settings(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        settings = await db.get_settings(interaction.guild.id)
        from cogs.voice_stats import fmt_duration
        log_ch = f"<#{settings['review_log_channel']}>" if settings["review_log_channel"] else "미설정"
        exempt = f"<@&{settings['exempt_role_id']}>" if settings["exempt_role_id"] else "없음"
        auto = "켜짐 (승인식 강퇴)" if settings["auto_kick_enabled"] else "꺼짐 (알림만)"
        embed = discord.Embed(
            title="📋 활동검토 설정",
            description=(
                f"**로그 채널**: {log_ch}\n"
                f"**기준 시간**: 주당 {fmt_duration(settings['min_seconds'])}\n"
                f"**면제 역할**: {exempt}\n"
                f"**자동강퇴 모드**: {auto}\n\n"
                "신규 가입 1주 미만 멤버는 항상 자동 제외돼요.\n"
                "아래 버튼으로 항목을 설정하세요."
            ),
            color=0xBA7517,
        )
        await interaction.response.send_message(
            embed=embed, view=ReviewSettingsView(), ephemeral=True
        )

    @ui.button(label="지금 활동검토 실행", emoji="▶️",
               style=discord.ButtonStyle.primary, custom_id="admin:runreview", row=3)
    async def run_review_now(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        settings = await db.get_settings(interaction.guild.id)
        if not settings["review_log_channel"]:
            await interaction.response.send_message(
                "먼저 '활동검토 설정'에서 로그 채널을 지정해주세요.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        from cogs.activity_review import run_review, build_review_embed, KickApprovalView
        result = await run_review(interaction.client, interaction.guild)
        embed = build_review_embed(result, interaction.guild)
        channel = interaction.guild.get_channel(settings["review_log_channel"])

        view = None
        if result["kick_candidates"] and settings["auto_kick_enabled"]:
            view = KickApprovalView(result["kick_candidates"])
        await channel.send(embed=embed, view=view)
        await db.reset_week(interaction.guild.id)
        await interaction.followup.send(
            f"활동검토를 실행했어요. 결과는 <#{settings['review_log_channel']}> 에 있어요.",
            ephemeral=True,
        )

    @ui.button(label="잠수 신고 검토", emoji="🕊️",
               style=discord.ButtonStyle.primary, custom_id="admin:leavereview", row=3)
    async def review_leaves(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        notices = await db.list_pending_leave_notices(interaction.guild.id)
        if not notices:
            await interaction.response.send_message(
                "대기 중인 잠수 신고가 없어요.", ephemeral=True
            )
            return

        lines = []
        for n in notices[:15]:
            m = interaction.guild.get_member(n["user_id"])
            name = m.display_name if m else f"<@{n['user_id']}>"
            reason = n["reason"] or "_(미입력)_"
            lines.append(
                f"• `#{n['id']}` {name} → **{n['until_date'].isoformat()}**\n"
                f"   사유: {reason}"
            )
        embed = discord.Embed(
            title="🕊️ 대기 중인 잠수 신고",
            description="\n\n".join(lines),
            color=0xBA7517,
        )
        embed.set_footer(text=f"총 {len(notices)}건 · 아래 드롭다운으로 일괄 처리")

        from cogs.leave_notices import LeaveReviewView
        view = LeaveReviewView(notices, interaction.guild)
        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=True
        )

    @ui.button(label="패널 관리 역할 지정", emoji="🔑",
               style=discord.ButtonStyle.secondary, custom_id="admin:panelrole", row=4)
    async def set_panel_role(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "서버 관리자만 설정할 수 있어요.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "/패널 명령어를 쓸 수 있는 역할을 선택하세요. (서버 관리자는 항상 사용 가능)",
            view=PanelRoleSelectView(), ephemeral=True,
        )

    @ui.button(label="인증 역할 지정", emoji="🔓",
               style=discord.ButtonStyle.secondary, custom_id="admin:verifyrole", row=4)
    async def set_verify_role(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "서버 관리자만 설정할 수 있어요.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "규칙 인증 시 지급할 역할을 선택하세요. 설치는 `/인증패널` 명령어로 해요.",
            view=VerifyRoleSelectView(), ephemeral=True,
        )


class PanelRoleSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(PanelRoleSelect())


class PanelRoleSelect(ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="패널 관리 역할 선택")

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        await db.set_panel_manager_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"패널 관리 역할을 {role.mention}(으)로 설정했어요.\n"
            f"이제 이 역할 보유자도 `/패널` 명령어를 쓸 수 있어요.",
            ephemeral=True,
        )


class VerifyRoleSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(VerifyRoleSelect())


class VerifyRoleSelect(ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="인증 역할 선택")

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        await db.set_verified_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"인증 역할을 {role.mention}(으)로 설정했어요.\n"
            f"이제 `/인증패널` 명령어로 인증 버튼을 원하는 채널에 설치하세요.",
            ephemeral=True,
        )


class ReviewSettingsView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @ui.button(label="로그 채널", emoji="📑", style=discord.ButtonStyle.secondary, row=0)
    async def log_channel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "활동검토 결과를 올릴 관리자 채널을 선택하세요.",
            view=ReviewLogSelectView(), ephemeral=True,
        )

    @ui.button(label="기준 시간", emoji="🕐", style=discord.ButtonStyle.secondary, row=0)
    async def min_time(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(MinTimeModal())

    @ui.button(label="면제 역할", emoji="🛡️", style=discord.ButtonStyle.secondary, row=0)
    async def exempt_role(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "검토에서 제외할 역할을 선택하세요.",
            view=ExemptRoleSelectView(), ephemeral=True,
        )

    @ui.button(label="자동강퇴 모드 켜기/끄기", emoji="🔁",
               style=discord.ButtonStyle.danger, row=1)
    async def toggle_autokick(self, interaction: discord.Interaction, button: ui.Button):
        settings = await db.get_settings(interaction.guild.id)
        new_val = not bool(settings["auto_kick_enabled"])
        await db.set_auto_kick(interaction.guild.id, new_val)
        state = "켜짐 (강퇴 후보에 승인 버튼 표시)" if new_val else "꺼짐 (알림만, 강퇴 버튼 없음)"
        await interaction.response.send_message(
            f"자동강퇴 모드를 **{state}** (으)로 바꿨어요.\n"
            f"※ 켜져 있어도 실제 강퇴는 관리자가 버튼으로 승인해야 실행돼요.",
            ephemeral=True,
        )


class CategorySelectView(ui.View):
    def __init__(self, categories):
        super().__init__(timeout=60)
        self.add_item(CategorySelect(categories))


class CategorySelect(ui.Select):
    def __init__(self, categories):
        options = [
            discord.SelectOption(label=c.name, value=str(c.id))
            for c in categories[:25]
        ]
        super().__init__(placeholder="카테고리 선택", options=options)

    async def callback(self, interaction: discord.Interaction):
        cat_id = int(self.values[0])
        await db.set_voice_category(interaction.guild.id, cat_id)
        cat = interaction.guild.get_channel(cat_id)
        await interaction.response.send_message(
            f"음성방 카테고리를 '{cat.name}'(으)로 설정했어요.", ephemeral=True
        )


class ArchiveSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(ArchiveChannelSelect())


class ArchiveChannelSelect(ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="아카이브 채널 선택",
            channel_types=[discord.ChannelType.text],
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        await db.set_archive_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"아카이브 채널을 <#{channel.id}>(으)로 설정했어요.", ephemeral=True
        )


# ───────── 활동검토 설정 ─────────
class ReviewLogSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(ReviewLogChannelSelect())


class ReviewLogChannelSelect(ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="활동검토 로그 채널 선택",
            channel_types=[discord.ChannelType.text],
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        await db.set_review_log_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"활동검토 로그 채널을 <#{channel.id}>(으)로 설정했어요.", ephemeral=True
        )


class ExemptRoleSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(ExemptRoleSelect())


class ExemptRoleSelect(ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="검토 면제 역할 선택")

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        await db.set_exempt_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"검토 면제 역할을 {role.mention}(으)로 설정했어요.", ephemeral=True
        )


class MinTimeModal(ui.Modal, title="활동 기준 시간 설정"):
    hours = ui.TextInput(
        label="주간 최소 음성시간 (시간 단위)",
        placeholder="예: 3 (= 3시간)",
        max_length=4,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            h = float(str(self.hours).strip())
            if h < 0 or h > 999:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "0~999 사이 숫자로 입력해주세요.", ephemeral=True
            )
            return
        await db.set_min_seconds(interaction.guild.id, int(h * 3600))
        await interaction.response.send_message(
            f"활동 기준을 주당 {h}시간으로 설정했어요.", ephemeral=True
        )


async def can_manage_panel(interaction: discord.Interaction) -> bool:
    """서버 관리자이거나, 지정된 패널 관리 역할 보유자면 True."""
    if interaction.user.guild_permissions.manage_guild:
        return True
    settings = await db.get_settings(interaction.guild.id)
    role_id = settings.get("panel_manager_role")
    if role_id and any(r.id == role_id for r in interaction.user.roles):
        return True
    return False


def build_user_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="🎮 파티 봇 컨트롤 패널",
        description=(
            "아래 버튼으로 모든 기능을 사용할 수 있어요.\n\n"
            "📢 **파티 모집하기** — 게임을 골라 모집글을 올려요\n"
            "🎮 **게임 역할 받기** — 모집 알림 받을 게임을 선택해요\n"
            "🔊 **내 음성시간** — 내 음성채널 이용시간을 봐요\n"
            "📊 **음성 랭킹** — 이번 주 음성 랭킹을 봐요"
        ),
        color=0x5865F2,
    )


def build_admin_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="🛠️ 관리자 패널",
        description="게임 등록/삭제, 음성방·아카이브 설정, 활동검토를 관리해요.",
        color=0xED4245,
    )


class ControlPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="패널", description="이 채널에 패널을 설치합니다 (관리자/지정 역할만)")
    @app_commands.describe(종류="설치할 패널 종류를 고르세요")
    @app_commands.choices(종류=[
        app_commands.Choice(name="유저용 (모집·역할·음성)", value="user"),
        app_commands.Choice(name="관리자용 (설정·활동검토)", value="admin"),
    ])
    async def setup_panel(
        self,
        interaction: discord.Interaction,
        종류: app_commands.Choice[str] = None,
    ):
        # 권한 게이트: 관리자 또는 지정 역할만
        if not await can_manage_panel(interaction):
            await interaction.response.send_message(
                "이 명령어는 서버 관리자 또는 지정된 패널 관리 역할만 쓸 수 있어요.",
                ephemeral=True,
            )
            return

        kind = 종류.value if 종류 else "user"  # 기본값: 유저용

        if kind == "admin":
            await interaction.channel.send(
                embed=build_admin_panel_embed(), view=AdminPanelView()
            )
            await interaction.response.send_message(
                "관리자 패널을 설치했어요! (이 채널은 관리자만 보이게 권한 설정을 권장해요)",
                ephemeral=True,
            )
        else:
            await interaction.channel.send(
                embed=build_user_panel_embed(), view=ControlPanelView()
            )
            await interaction.response.send_message(
                "유저용 패널을 설치했어요!", ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(ControlPanel(bot))
