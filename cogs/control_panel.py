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


class RecruitPanelView(ui.View):
    """패널 1: 파티 모집 (영구)."""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="파티 모집하기", emoji="📢",
               style=discord.ButtonStyle.success, custom_id="panel:recruit")
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


class RolesPanelView(ui.View):
    """패널 2: 게임 역할 (영구)."""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="게임 역할 받기", emoji="🎮",
               style=discord.ButtonStyle.primary, custom_id="panel:roles")
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


class ActivityPanelView(ui.View):
    """패널 3: 내 활동 & 커뮤니티 (영구)."""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="내 음성시간", emoji="🔊",
               style=discord.ButtonStyle.secondary, custom_id="panel:mytime")
    async def mytime(self, interaction: discord.Interaction, button: ui.Button):
        embed = await build_my_stats_embed(interaction.guild.id, interaction.user)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="음성 랭킹", emoji="📊",
               style=discord.ButtonStyle.secondary, custom_id="panel:ranking")
    async def ranking(self, interaction: discord.Interaction, button: ui.Button):
        embed = await build_ranking_embed(
            interaction.client, interaction.guild, period="week"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="익명 건의", emoji="📨",
               style=discord.ButtonStyle.secondary, custom_id="panel:suggest")
    async def suggest(self, interaction: discord.Interaction, button: ui.Button):
        from cogs.suggestions import SuggestionModal
        await interaction.response.send_modal(SuggestionModal())

    @ui.button(label="잠수 신고", emoji="🕊️",
               style=discord.ButtonStyle.secondary, custom_id="panel:leave")
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


# 하위 호환용 (예전 영구 View 등록 코드가 이 이름 참조)
class ControlPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)


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
        await interaction.response.defer(ephemeral=True)
        games = await db.list_games(interaction.guild.id)
        if not games:
            await interaction.followup.send("등록된 게임이 없어요.", ephemeral=True)
            return
        await interaction.followup.send(
            "삭제할 게임을 선택하세요.", view=RemoveGameView(games), ephemeral=True
        )

    @ui.button(label="주간 랭킹 초기화", emoji="🔄",
               style=discord.ButtonStyle.secondary, custom_id="admin:resetweek", row=2)
    async def reset_week(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await db.reset_week(interaction.guild.id)
        await interaction.followup.send("이번 주 음성 랭킹을 초기화했어요.", ephemeral=True)

    @ui.button(label="음성방 카테고리 지정", emoji="📁",
               style=discord.ButtonStyle.secondary, custom_id="admin:setcategory", row=1)
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
               style=discord.ButtonStyle.secondary, custom_id="admin:setarchive", row=1)
    async def set_archive(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_message(
            "종료된 모집글을 보낼 채널을 선택하세요. (관리자만 보이는 채널 권장)",
            view=ArchiveSelectView(), ephemeral=True,
        )

    @ui.button(label="모집글 채널 지정", emoji="📌",
               style=discord.ButtonStyle.primary, custom_id="admin:setrecruitchannel", row=1)
    async def set_recruit_channel(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        settings = await db.get_settings(interaction.guild.id)
        current = (
            f"현재: <#{settings['recruit_post_channel_id']}>\n\n"
            if settings.get("recruit_post_channel_id")
            else "현재: 미설정 (파티 모집 버튼을 누른 채널에 게시됨)\n\n"
        )
        await interaction.followup.send(
            f"{current}모집글이 항상 게시될 전용 채널을 선택하세요.\n"
            "설정하면 파티 모집 버튼이 어느 채널에 있든 모집글은 이 채널에 올라가요.",
            view=RecruitChannelSelectView(), ephemeral=True,
        )

    @ui.button(label="활동검토 설정", emoji="📋",
               style=discord.ButtonStyle.secondary, custom_id="admin:reviewsettings", row=3)
    async def review_settings(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
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
        await interaction.followup.send(
            embed=embed, view=ReviewSettingsView(), ephemeral=True
        )

    @ui.button(label="지금 활동검토 실행", emoji="▶️",
               style=discord.ButtonStyle.primary, custom_id="admin:runreview", row=4)
    async def run_review_now(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        settings = await db.get_settings(interaction.guild.id)
        if not settings["review_log_channel"]:
            await interaction.followup.send(
                "먼저 '활동검토 설정'에서 로그 채널을 지정해주세요.", ephemeral=True
            )
            return

        from cogs.activity_review import run_review, build_review_embed, KickApprovalView
        from datetime import datetime, timezone
        result = await run_review(interaction.client, interaction.guild)
        embed = build_review_embed(result, interaction.guild)
        channel = interaction.guild.get_channel(settings["review_log_channel"])

        view = None
        if result["kick_candidates"] and settings["auto_kick_enabled"]:
            view = KickApprovalView(result["kick_candidates"])
        await channel.send(embed=embed, view=view)
        await db.reset_week(interaction.guild.id)
        await db.set_last_reviewed_at(interaction.guild.id, datetime.now(timezone.utc))
        await interaction.followup.send(
            f"활동검토를 실행했어요. 결과는 <#{settings['review_log_channel']}> 에 있어요.",
            ephemeral=True,
        )

    @ui.button(label="잠수 신고 검토", emoji="🕊️",
               style=discord.ButtonStyle.secondary, custom_id="admin:leavereview", row=3)
    async def review_leaves(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        notices = await db.list_pending_leave_notices(interaction.guild.id)
        if not notices:
            await interaction.followup.send("대기 중인 잠수 신고가 없어요.", ephemeral=True)
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
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @ui.button(label="패널 관리 역할 지정", emoji="🔑",
               style=discord.ButtonStyle.secondary, custom_id="admin:panelrole", row=2)
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
               style=discord.ButtonStyle.secondary, custom_id="admin:verifyrole", row=2)
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


class RecruitChannelSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(RecruitChannelSelect())


class RecruitChannelSelect(ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="모집글 전용 채널 선택",
            channel_types=[discord.ChannelType.text],
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        await db.set_recruit_post_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"모집글 전용 채널을 {channel.mention}(으)로 설정했어요.\n"
            f"이제 '파티 모집하기' 버튼을 어디서 누르든 모집글은 이 채널에 게시돼요.",
            ephemeral=True,
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


def build_recruit_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📢 파티 모집",
        description=(
            "함께 플레이할 파티원을 모집해요.\n\n"
            "버튼을 누르면 게임을 선택하고 모집 정보를 입력할 수 있어요.\n"
            "모집글이 올라가면 해당 게임 역할 보유자에게 자동으로 알림이 가요."
        ),
        color=0x248046,
    )
    embed.set_footer(text="모집 완료 후 '모집 마감' 버튼을 눌러 정리해주세요.")
    return embed


def build_roles_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎮 게임 역할",
        description=(
            "관심 있는 게임의 역할을 받아 파티 모집 알림을 받아요.\n\n"
            "버튼을 누르면 역할이 토글돼요. 이미 있으면 해제, 없으면 추가됩니다."
        ),
        color=0x5865F2,
    )
    embed.set_footer(text="역할이 있으면 해당 게임 파티 모집 시 멘션으로 알림을 받아요.")
    return embed


def build_activity_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📊 내 활동 & 커뮤니티",
        color=0x4E5058,
    )
    embed.add_field(
        name="🔊 음성 통계",
        value="내 이번 주·전체 이용 시간과\n서버 음성 랭킹을 확인해요.",
        inline=True,
    )
    embed.add_field(
        name="💬 커뮤니티",
        value="운영진에게 익명으로 건의하거나\n잠수 기간을 신고해요.",
        inline=True,
    )
    return embed


def build_admin_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ 관리자 패널",
        description="서버 설정 및 운영 기능을 관리해요.",
        color=0xED4245,
    )
    embed.add_field(
        name="🎮 게임 관리",
        value="게임 역할 추가 · 삭제",
        inline=True,
    )
    embed.add_field(
        name="📺 채널 설정",
        value="음성방 · 아카이브 · 모집글 채널",
        inline=True,
    )
    embed.add_field(
        name="🔑 역할 · 통계",
        value="패널 역할 · 인증 역할 · 랭킹 초기화",
        inline=True,
    )
    embed.add_field(
        name="📋 활동검토",
        value="기준 시간 설정 · 잠수 신고 검토 · 수동 실행",
        inline=False,
    )
    return embed


class ControlPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="패널", description="이 채널에 패널을 설치합니다 (관리자/지정 역할만)")
    @app_commands.describe(종류="설치할 패널 종류를 고르세요")
    @app_commands.choices(종류=[
        app_commands.Choice(name="📢 파티 모집", value="recruit"),
        app_commands.Choice(name="🎮 게임 역할", value="roles"),
        app_commands.Choice(name="📊 내 활동 & 커뮤니티", value="activity"),
        app_commands.Choice(name="🛠️ 관리자", value="admin"),
    ])
    async def setup_panel(
        self,
        interaction: discord.Interaction,
        종류: app_commands.Choice[str],
    ):
        # 권한 게이트
        if not await can_manage_panel(interaction):
            await interaction.response.send_message(
                "이 명령어는 서버 관리자 또는 지정된 패널 관리 역할만 쓸 수 있어요.",
                ephemeral=True,
            )
            return

        kind = 종류.value

        if kind == "recruit":
            await interaction.channel.send(
                embed=build_recruit_panel_embed(), view=RecruitPanelView()
            )
            msg = "📢 파티 모집 패널을 설치했어요!"
        elif kind == "roles":
            await interaction.channel.send(
                embed=build_roles_panel_embed(), view=RolesPanelView()
            )
            msg = "🎮 게임 역할 패널을 설치했어요!"
        elif kind == "activity":
            await interaction.channel.send(
                embed=build_activity_panel_embed(), view=ActivityPanelView()
            )
            msg = "📊 내 활동 & 커뮤니티 패널을 설치했어요!"
        elif kind == "admin":
            await interaction.channel.send(
                embed=build_admin_panel_embed(), view=AdminPanelView()
            )
            msg = "🛠️ 관리자 패널을 설치했어요! (이 채널은 관리자만 보이게 권한 설정을 권장해요)"
        else:
            msg = "알 수 없는 패널 종류예요."

        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ControlPanel(bot))
