"""
매주 음성 활동량을 검토하는 기능.

흐름:
1. 매주 월요일(UTC) 자동 실행 — 또는 관리자 패널에서 수동 실행
2. 면제 역할 보유자 / 가입 1주 미만 신규원 / 잠수 신고 승인자는 제외
3. 기준 시간(min_seconds) 미달자:
   - strike +1 / DM 경고 발송 (실패 시 로그 채널에 기록)
   - 1·2회차: 정중한 안내 DM
   - STRIKE_KICK_THRESHOLD(3)회 이상: '강퇴 후보'로 분류
4. 강퇴 후보는 관리자 채널에 리스트로 게시
   - auto_kick_enabled=1 이어도 실제 kick은 관리자가 버튼 승인해야 실행
   - 기준 충족자는 strike 초기화

* 안전장치: 봇은 절대 자동으로 kick하지 않는다. 항상 관리자 승인을 거친다.
* 멱등성: last_reviewed_at을 DB에 기록해 재배포 시 이중 실행을 방지한다.
"""

import logging
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks
from discord import ui

import database as db
from cogs.voice_stats import fmt_duration

log = logging.getLogger("party-bot")

NEW_MEMBER_GRACE_DAYS = 7
STRIKE_KICK_THRESHOLD = 3   # 이 횟수 이상 미달 시 강퇴 후보로 분류
# review_loop는 weekday()==0 체크로 매주 월요일 1회 실행 (24h 루프 + 요일 필터)


def _is_exempt(member: discord.Member, exempt_role_id, now) -> bool:
    """검토 제외 대상인지 판단."""
    # 봇 제외
    if member.bot:
        return True
    # 면제 역할 보유
    if exempt_role_id:
        if any(r.id == exempt_role_id for r in member.roles):
            return True
    # 가입 1주 미만 신규원
    if member.joined_at:
        joined = member.joined_at
        if joined.tzinfo is None:
            joined = joined.replace(tzinfo=timezone.utc)
        if (now - joined) < timedelta(days=NEW_MEMBER_GRACE_DAYS):
            return True
    return False


async def run_review(bot, guild: discord.Guild) -> dict:
    """
    검토 실행. 결과 딕셔너리 반환.
    실제 강퇴는 하지 않는다 (후보만 추림).
    """
    settings = await db.get_settings(guild.id)
    min_seconds = settings["min_seconds"]
    exempt_role_id = settings["exempt_role_id"]
    now = datetime.now(timezone.utc)

    # 멤버당 개별 쿼리(N+1) 대신 길드 단위 벌크 조회 3건 + 벌크 갱신 2건으로 처리
    on_leave_ids = await db.list_users_on_leave(guild.id)
    week_seconds_map = await db.get_week_seconds_map(guild.id)

    warned = []      # (member, week_seconds, strikes)
    kick_candidates = []  # (member, week_seconds, strikes)
    passed_members = []   # 기준 충족 → strike 초기화 대상
    failed_members = []   # (member, week_seconds) — strike +1 대상
    exempted = 0

    for member in guild.members:
        if _is_exempt(member, exempt_role_id, now):
            exempted += 1
            continue
        # 잠수 신고가 승인된 멤버는 면제
        if member.id in on_leave_ids:
            exempted += 1
            continue
        secs = week_seconds_map.get(member.id, 0)  # 검토 주기(1주) 동안 누적된 시간
        if secs >= min_seconds:
            passed_members.append(member)
        else:
            failed_members.append((member, secs))

    await db.reset_strikes_bulk(guild.id, [m.id for m in passed_members])
    strike_map = await db.add_strikes_bulk(guild.id, [m.id for m, _ in failed_members])

    for member, secs in failed_members:
        strikes = strike_map.get(member.id, 1)
        if strikes >= STRIKE_KICK_THRESHOLD:
            # STRIKE_KICK_THRESHOLD 회째: 강퇴 후보 + 최종 안내 DM
            kick_candidates.append((member, secs, strikes))
            await _send_final_dm(member, guild, secs, min_seconds, settings)
        else:
            # 1·2회: 경고만
            warned.append((member, secs, strikes))
            await _send_warning_dm(member, guild, secs, min_seconds, strikes, settings)
    passed = len(passed_members)

    return {
        "warned": warned,
        "kick_candidates": kick_candidates,
        "passed": passed,
        "exempted": exempted,
        "min_seconds": min_seconds,
    }


async def _dm_or_log(member, guild, settings, msg):
    """DM 시도, 실패하면 로그 채널에 기록."""
    try:
        await member.send(msg)
        return True
    except (discord.Forbidden, discord.HTTPException):
        if settings["review_log_channel"]:
            ch = guild.get_channel(settings["review_log_channel"])
            if ch:
                try:
                    await ch.send(
                        f"⚠️ {member.mention} 님에게 안내 DM을 보내지 못했어요 (DM 차단)."
                    )
                except discord.HTTPException:
                    pass
        return False


async def _send_warning_dm(member, guild, secs, min_seconds, strikes, settings):
    """1·2회 경고 DM (정중한 안내 톤)."""
    msg = (
        f"안녕하세요, **{guild.name}** 운영진입니다.\n\n"
        f"커뮤니티 활동 현황을 정기적으로 확인하고 있으며, 안내차 메시지를 드립니다. "
        f"지난 한 주간 음성채널 이용 시간이 **{fmt_duration(secs)}**(으)로 "
        f"운영 기준({fmt_duration(min_seconds)})에 다소 못 미치는 것으로 확인되었습니다. "
        f"(현재 누적 안내 {strikes}회)\n\n"
        f"강제성이 있는 것은 아니며, 편하실 때 음성채널에서 함께해 주시면 됩니다. "
        f"다만 안내가 누적될 경우 부득이하게 멤버 정리 대상에 포함될 수 있는 점 양해 부탁드립니다.\n\n"
        f"학업·업무·건강 등 **불가피한 사정으로 참여가 어려우신 경우**, 서버 패널의 "
        f"**'잠수 신고' 버튼**으로 기간을 신고하시거나 운영진에게 직접 알려주시면 예외로 처리해 드립니다. "
        f"편하게 말씀해 주세요. 감사합니다."
    )
    return await _dm_or_log(member, guild, settings, msg)


async def _send_final_dm(member, guild, secs, min_seconds, settings):
    """3회째 강퇴 후보 최종 안내 DM (정중하지만 명확하게)."""
    msg = (
        f"안녕하세요, **{guild.name}** 운영진입니다.\n\n"
        f"앞서 두 차례 활동 관련 안내를 드렸으나, 이번 주에도 음성채널 이용 시간이 "
        f"**{fmt_duration(secs)}**(으)로 기준({fmt_duration(min_seconds)})에 미치지 못해 "
        f"부득이하게 멤버 정리 대상으로 검토되고 있습니다.\n\n"
        f"정리되더라도 **언제든 다시 입장하실 수 있으며**, 초대 링크를 통해 돌아오시면 됩니다. "
        f"그동안 함께해 주셔서 감사했습니다.\n\n"
        f"혹시 **불가피한 사정이 있으셨다면 지금이라도 운영진에게 알려주세요. "
        f"확인되면 정리 대상에서 제외해 드립니다.** 소중한 인연 이어가길 바랍니다."
    )
    return await _dm_or_log(member, guild, settings, msg)


def build_review_embed(result: dict, guild) -> discord.Embed:
    embed = discord.Embed(
        title="📋 주간 활동 검토 결과",
        color=0xBA7517,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="✅ 통과", value=f"{result['passed']}명", inline=True)
    embed.add_field(name="🛡️ 면제", value=f"{result['exempted']}명", inline=True)
    embed.add_field(
        name="⚠️ 1차 경고",
        value=f"{len(result['warned'])}명",
        inline=True,
    )

    if result["warned"]:
        lines = [
            f"• {m.display_name} — {fmt_duration(s)} (경고 {st}회)"
            for m, s, st in result["warned"][:15]
        ]
        embed.add_field(name="경고 발송됨 (DM)", value="\n".join(lines), inline=False)

    if result["kick_candidates"]:
        lines = [
            f"• {m.mention} — {fmt_duration(s)} (연속 미달 {st}회)"
            for m, s, st in result["kick_candidates"][:15]
        ]
        embed.add_field(
            name="🚨 강퇴 후보 (3회 이상 미달)",
            value="\n".join(lines),
            inline=False,
        )
        embed.set_footer(text="아래 버튼으로 관리자가 직접 승인해야 강퇴됩니다. 재입장은 가능합니다.")
    else:
        embed.set_footer(text="강퇴 후보가 없어요.")
    return embed


# ───────── 강퇴 승인 View ─────────
class KickApprovalView(ui.View):
    """강퇴 후보별 개별 승인. 관리자만 사용 가능."""
    def __init__(self, candidates):
        super().__init__(timeout=None)
        # 후보를 드롭다운으로 (최대 25명)
        if candidates:
            self.add_item(KickSelect(candidates))


class KickSelect(ui.Select):
    def __init__(self, candidates):
        options = [
            discord.SelectOption(
                label=m.display_name,
                value=str(m.id),
                description=f"연속 미달 {st}회",
            )
            for m, s, st in candidates[:25]
        ]
        super().__init__(
            placeholder="강퇴할 멤버 선택 (복수 선택 가능)",
            options=options,
            min_values=1,
            max_values=len(options),
            custom_id="kick_select",
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message(
                "멤버 강퇴 권한이 있는 관리자만 사용할 수 있어요.", ephemeral=True
            )
            return

        kicked, failed = [], []
        for uid in self.values:
            member = interaction.guild.get_member(int(uid))
            if not member:
                continue
            # 강퇴 전 안내 DM (초대 안내) — 실패해도 진행
            try:
                await member.send(
                    f"**{interaction.guild.name}** 운영진입니다.\n"
                    f"활동 기준 미충족으로 멤버 정리가 진행되었음을 안내드립니다. "
                    f"그동안 함께해 주셔서 감사했습니다.\n"
                    f"언제든 다시 입장하실 수 있으니, 마음이 생기시면 초대 링크로 돌아와 주세요. 🙏"
                )
            except discord.HTTPException:
                pass
            try:
                await member.kick(reason="주간 활동 기준 미달 (관리자 승인)")
                await db.reset_strike(interaction.guild.id, member.id)
                kicked.append(member.display_name)
            except discord.Forbidden:
                failed.append(f"{member.display_name} (권한 부족)")
            except discord.HTTPException:
                failed.append(f"{member.display_name} (오류)")

        msg = ""
        if kicked:
            msg += f"✅ 강퇴 완료: {', '.join(kicked)}\n"
        if failed:
            msg += f"❌ 실패: {', '.join(failed)}"
        await interaction.response.send_message(msg or "처리할 멤버가 없어요.", ephemeral=True)


class ActivityReview(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.review_loop.start()

    def cog_unload(self):
        self.review_loop.cancel()

    @tasks.loop(hours=24)
    async def review_loop(self):
        """매일 체크해서, 매주 월요일에 검토를 실행한다 (1주 주기)."""
        # 매일 잠수 신고 만료 처리
        await db.expire_old_leave_notices()

        now = datetime.now(timezone.utc)
        # 매주 월요일에만 실행
        if now.weekday() != 0:  # 0 = 월요일
            return

        for guild in self.bot.guilds:
            await self._do_review_and_post(guild)

    @review_loop.before_loop
    async def before_review(self):
        await self.bot.wait_until_ready()

    async def _do_review_and_post(self, guild):
        settings = await db.get_settings(guild.id)
        log_channel_id = settings["review_log_channel"]
        if not log_channel_id:
            return  # 로그 채널 미설정이면 검토 안 함
        channel = guild.get_channel(log_channel_id)
        if not channel:
            return

        # 멱등성 체크: 23시간 이내 이미 실행됐으면 스킵 (재배포 시 이중 실행 방지)
        now = datetime.now(timezone.utc)
        last_reviewed = await db.get_last_reviewed_at(guild.id)
        if last_reviewed is not None:
            elapsed = (now - last_reviewed).total_seconds()
            if elapsed < 23 * 3600:
                log.info(
                    f"[{guild.name}] 활동검토 스킵 — 마지막 실행 후 {elapsed/3600:.1f}h 경과 (23h 미만)"
                )
                return

        result = await run_review(self.bot, guild)
        embed = build_review_embed(result, guild)

        # 강퇴 후보가 있고 auto_kick이 켜져 있으면 승인 버튼 첨부
        view = None
        if result["kick_candidates"] and settings["auto_kick_enabled"]:
            view = KickApprovalView(result["kick_candidates"])
        await channel.send(embed=embed, view=view)
        # 주간 시간 초기화 + 실행 시각 기록
        await db.reset_week(guild.id)
        await db.set_last_reviewed_at(guild.id, now)
        log.info(f"[{guild.name}] 활동검토 완료 — 통과 {result['passed']}명, 경고 {len(result['warned'])}명, 후보 {len(result['kick_candidates'])}명")


async def setup(bot):
    await bot.add_cog(ActivityReview(bot))
