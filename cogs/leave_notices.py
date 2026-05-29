"""
잠수 신고 기능.
- 유저가 컨트롤 패널 버튼 → 기간 선택 (빠른 선택 또는 직접 입력)
- 사유 입력 → 신고 생성 (status=pending)
- 관리자가 패널에서 '잠수 신고 검토' 버튼 → pending 목록 확인 → 승인/거절
- 승인된 신고는 until_date까지 활동검토에서 자동 제외
- 매일 만료 처리(activity_review의 review_loop가 호출)
"""

from datetime import date, datetime, timedelta

import discord
from discord.ext import commands
from discord import ui

import database as db


def _parse_date_korean(text: str) -> date | None:
    """'2026-06-15', '6/15', '6월 15일' 등 간단한 형식 파싱."""
    text = text.strip().replace(" ", "")
    today = date.today()
    # ISO: 2026-06-15
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        pass
    # 6/15 또는 06/15 → 올해 또는 내년
    for fmt in ("%m/%d", "%m-%d"):
        try:
            d = datetime.strptime(text, fmt).date().replace(year=today.year)
            # 이미 지난 날짜면 내년으로
            if d < today:
                d = d.replace(year=today.year + 1)
            return d
        except ValueError:
            continue
    # 6월15일
    if "월" in text and "일" in text:
        try:
            month_str, rest = text.split("월", 1)
            day_str = rest.replace("일", "").strip()
            d = date(today.year, int(month_str), int(day_str))
            if d < today:
                d = d.replace(year=today.year + 1)
            return d
        except (ValueError, IndexError):
            return None
    return None


class LeaveStartView(ui.View):
    """잠수 신고 진입점 — 빠른 선택 또는 직접 입력."""
    def __init__(self):
        super().__init__(timeout=120)

    @ui.button(label="3일", style=discord.ButtonStyle.secondary, row=0)
    async def b3d(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(LeaveReasonModal(3))

    @ui.button(label="1주", style=discord.ButtonStyle.secondary, row=0)
    async def b1w(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(LeaveReasonModal(7))

    @ui.button(label="2주", style=discord.ButtonStyle.secondary, row=0)
    async def b2w(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(LeaveReasonModal(14))

    @ui.button(label="1개월", style=discord.ButtonStyle.secondary, row=0)
    async def b1m(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(LeaveReasonModal(30))

    @ui.button(label="직접 날짜 입력", emoji="📅",
               style=discord.ButtonStyle.primary, row=1)
    async def custom(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(LeaveCustomDateModal())


class LeaveReasonModal(ui.Modal, title="잠수 신고"):
    reason = ui.TextInput(
        label="사유 (선택, 운영진에게만 보여요)",
        placeholder="예: 시험기간, 출장, 건강상 이유 등",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=200,
    )

    def __init__(self, days: int):
        super().__init__()
        self.days = days
        self.until = date.today() + timedelta(days=days)
        self.title = f"잠수 신고 — {days}일 ({self.until.isoformat()}까지)"

    async def on_submit(self, interaction: discord.Interaction):
        await _submit_leave(interaction, self.until, str(self.reason).strip() or None)


class LeaveCustomDateModal(ui.Modal, title="잠수 신고 — 날짜 직접 입력"):
    date_input = ui.TextInput(
        label="복귀 예정일",
        placeholder="예: 2026-09-01, 9/1, 9월 1일",
        max_length=20,
    )
    reason = ui.TextInput(
        label="사유 (선택)",
        placeholder="예: 시험기간, 출장 등",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        until = _parse_date_korean(str(self.date_input))
        if not until:
            await interaction.response.send_message(
                "날짜 형식을 인식하지 못했어요. 예: `2026-09-01`, `9/1`, `9월 1일`",
                ephemeral=True,
            )
            return
        if until <= date.today():
            await interaction.response.send_message(
                "오늘 이후 날짜를 입력해주세요.", ephemeral=True
            )
            return
        if (until - date.today()).days > 365:
            await interaction.response.send_message(
                "최대 1년까지 신고할 수 있어요.", ephemeral=True
            )
            return
        await _submit_leave(interaction, until, str(self.reason).strip() or None)


async def _submit_leave(interaction: discord.Interaction, until: date, reason):
    """잠수 신고 생성 + 관리자 채널에 통지 + 본인에게 안내."""
    settings = await db.get_settings(interaction.guild.id)
    notice_id = await db.create_leave_notice(
        interaction.guild.id, interaction.user.id, reason, until
    )
    days = (until - date.today()).days

    # 관리자 채널에 알림
    log_channel_id = settings.get("review_log_channel")
    if log_channel_id:
        ch = interaction.guild.get_channel(log_channel_id)
        if ch:
            embed = discord.Embed(
                title="🕊️ 새 잠수 신고",
                description=(
                    f"**{interaction.user.mention}** 님이 잠수를 신고했어요.\n\n"
                    f"📅 복귀 예정: **{until.isoformat()}** ({days}일 후)\n"
                    f"💬 사유: {reason or '_(미입력)_'}"
                ),
                color=0xBA7517,
            )
            embed.set_footer(text=f"신고 #{notice_id} · 관리자 패널에서 승인/거절")
            try:
                await ch.send(embed=embed)
            except discord.HTTPException:
                pass

    await interaction.response.send_message(
        f"잠수 신고가 접수됐어요.\n\n"
        f"📅 복귀 예정: **{until.isoformat()}** ({days}일 후)\n\n"
        f"관리자가 검토 후 승인하면 활동검토에서 자동 제외돼요. "
        f"승인 전까지는 평소대로 검토 대상이니, 가능하면 미리 신고해주세요.",
        ephemeral=True,
    )


# ───────── 관리자: 잠수 신고 검토 ─────────
class LeaveReviewView(ui.View):
    """pending 신고 목록을 보여주는 패널."""
    def __init__(self, notices, guild):
        super().__init__(timeout=300)
        if not notices:
            return
        # 드롭다운: 최대 25개
        options = []
        for n in notices[:25]:
            m = guild.get_member(n["user_id"])
            name = m.display_name if m else f"<@{n['user_id']}>"
            label = f"{name} → {n['until_date'].isoformat()}"
            desc = (n["reason"] or "사유 미입력")[:90]
            options.append(discord.SelectOption(
                label=label[:100], value=str(n["id"]), description=desc
            ))
        self.add_item(LeaveActionSelect(options, action="approve"))
        self.add_item(LeaveActionSelect(options, action="reject"))


class LeaveActionSelect(ui.Select):
    def __init__(self, options, action: str):
        self.action = action
        emoji = "✅" if action == "approve" else "❌"
        ph = f"{emoji} {'승인할' if action == 'approve' else '거절할'} 신고 선택"
        super().__init__(
            placeholder=ph, options=options,
            min_values=1, max_values=len(options),
            custom_id=f"leave_{action}",
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "관리자만 사용할 수 있어요.", ephemeral=True
            )
            return

        processed = []
        for nid_str in self.values:
            nid = int(nid_str)
            notice = await db.get_leave_notice(nid)
            if not notice or notice["status"] != "pending":
                continue
            if self.action == "approve":
                await db.approve_leave_notice(nid, interaction.user.id)
                verb = "승인"
            else:
                await db.reject_leave_notice(nid, interaction.user.id)
                verb = "거절"

            # 신고자에게 DM 안내
            member = interaction.guild.get_member(notice["user_id"])
            if member:
                try:
                    if self.action == "approve":
                        await member.send(
                            f"**{interaction.guild.name}** 운영진입니다.\n"
                            f"잠수 신고가 **승인**되었어요. "
                            f"{notice['until_date'].isoformat()}까지 활동검토에서 제외돼요. "
                            f"편안한 시간 보내고 돌아와 주세요!"
                        )
                    else:
                        await member.send(
                            f"**{interaction.guild.name}** 운영진입니다.\n"
                            f"잠수 신고를 검토했으나 이번에는 승인이 어려워요. "
                            f"궁금한 점이 있으면 운영진에게 문의해주세요."
                        )
                except discord.HTTPException:
                    pass
            processed.append(f"#{nid} {verb}")

        await interaction.response.send_message(
            f"처리 완료: {', '.join(processed) if processed else '없음'}",
            ephemeral=True,
        )


class LeaveNotices(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(LeaveNotices(bot))
