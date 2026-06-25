"""
음성채널 이용시간 추적.
- on_voice_state_update 로 입장/퇴장 감지
- 입장 시각 기록 → 퇴장 시 누적
- 봇 시작 시 이미 음성방에 있던 사람도 세션 시작 처리
"""

import logging

import discord
from discord.ext import commands

import database as db

log = logging.getLogger("party-bot")


def fmt_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}시간 {m}분"
    return f"{m}분"


class VoiceStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _no_points_channel(self, channel, guild_id: int) -> bool:
        """이 채널에 있는 동안 포인트를 지급하지 않아야 하면 True."""
        if channel is None:
            return False
        # Discord 내장 AFK 채널 (afk_channel_id는 2.x에서 비공개 — afk_channel 사용)
        afk_ch = channel.guild.afk_channel
        if afk_ch and channel.id == afk_ch.id:
            return True
        # 관리자가 지정한 잠수채널
        excluded = await db.get_points_excluded_channel(guild_id)
        return bool(excluded and channel.id == excluded)

    @commands.Cog.listener()
    async def on_ready(self):
        # 봇 재시작 시 현재 음성방에 있는 사람들 세션 시작 (잠수채널 제외)
        for guild in self.bot.guilds:
            afk_id      = guild.afk_channel.id if guild.afk_channel else None
            excluded_id = await db.get_points_excluded_channel(guild.id)
            for vc in guild.voice_channels:
                if (afk_id and vc.id == afk_id) or (excluded_id and vc.id == excluded_id):
                    continue  # 잠수채널은 세션 시작 안 함
                for member in vc.members:
                    if not member.bot:
                        await db.voice_join(guild.id, member.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        guild   = member.guild
        was_afk = await self._no_points_channel(before.channel, guild.id)
        now_afk = await self._no_points_channel(after.channel,  guild.id)

        if before.channel is None and after.channel is not None:
            # ── 음성방 최초 진입 ──
            if not now_afk:
                await db.voice_join(guild.id, member.id)
            # 잠수채널 직접 진입 시: 세션 시작 안 함

        elif before.channel is not None and after.channel is None:
            # ── 음성방 퇴장 ──
            if not was_afk:
                await db.voice_leave(guild.id, member.id)
            # 잠수채널에서 나갔을 때: 세션이 없으므로 아무것도 안 함

        elif before.channel is not None and after.channel is not None:
            # ── 채널 이동 ──
            if not was_afk and now_afk:
                # 일반채널 → 잠수채널: 현재까지 누적 시간/포인트 정산 후 세션 종료
                await db.voice_leave(guild.id, member.id)
            elif was_afk and not now_afk:
                # 잠수채널 → 일반채널: 새 세션 시작
                await db.voice_join(guild.id, member.id)
            # 일반→일반 또는 잠수→잠수: 세션 유지 (입장시각 리셋 방지)

        # ── 관전 모드인 사람이 음성에서 완전히 나가면 관전 모드 자동 OFF (깜빡 방지) ──
        # 실패해도 아래의 음성방 비움 정리(_check_empty_recruit_voice)가 끊기지 않게 격리한다.
        if after.channel is None and before.channel is not None:
            try:
                if await db.is_in_spectator_mode(guild.id, member.id):
                    from cogs.recruitment import exit_spectator_mode_flow
                    await exit_spectator_mode_flow(guild, member)
            except Exception as e:
                log.warning(f"관전 모드 자동 OFF 실패 user={member.id}: {e}")

        # ── 모집 음성방 멤버십이 바뀌면 그 모집글의 관전자 목록을 갱신 ──
        if before.channel != after.channel:
            await self._refresh_recruit_for_voice(before.channel)
            await self._refresh_recruit_for_voice(after.channel)

        # ── 모집용 음성방이 비었는지 확인 ──
        if before.channel is not None:
            await self._check_empty_recruit_voice(before.channel)

    async def _refresh_recruit_for_voice(self, channel):
        """음성 채널이 모집 음성방이면 그 모집글을 다시 그려 관전자 목록을 갱신한다."""
        if not isinstance(channel, discord.VoiceChannel):
            return
        recruit_id = await db.find_recruit_by_voice(channel.id)
        if recruit_id is not None:
            from cogs.recruitment import refresh_recruit_message
            await refresh_recruit_message(self.bot, recruit_id)

    async def _check_empty_recruit_voice(self, channel):
        """모집용 음성방이 비었으면 삭제하고 모집글을 아카이브한다."""
        if not isinstance(channel, discord.VoiceChannel):
            return
        # 봇이 아닌 멤버가 남아있으면 유지
        human_members = [m for m in channel.members if not m.bot]
        if human_members:
            return
        # 이 음성방이 모집과 연결돼 있는지 확인
        recruit_id = await db.find_recruit_by_voice(channel.id)
        if recruit_id is None:
            return
        # 음성방 삭제
        try:
            await channel.delete(reason="모집 음성방 전원 퇴장")
        except discord.HTTPException:
            pass
        # 모집글 아카이브 (지연 import로 순환참조 회피)
        from cogs.recruitment import archive_recruit_to_channel
        await archive_recruit_to_channel(self.bot, recruit_id)


async def build_my_stats_embed(guild_id: int, member) -> discord.Embed:
    stats = await db.get_voice_total(guild_id, member.id)
    embed = discord.Embed(title="🔊 내 음성 이용시간", color=0xD85A30)
    embed.add_field(name="이번 주", value=fmt_duration(stats["week"]), inline=True)
    embed.add_field(name="전체 누적", value=fmt_duration(stats["total"]), inline=True)
    embed.set_footer(text=member.display_name)
    return embed


async def build_ranking_embed(bot, guild, period: str = "week") -> discord.Embed:
    rows = await db.voice_ranking(guild.id, period, limit=10)
    label = "이번 주" if period == "week" else "전체"
    embed = discord.Embed(title=f"📊 음성 랭킹 ({label})", color=0xD85A30)
    if not rows:
        embed.description = "아직 기록이 없어요."
        return embed
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, r in enumerate(rows):
        member = guild.get_member(r["user_id"])
        name = member.display_name if member else f"(나간 유저)"
        prefix = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{prefix} {name} — {fmt_duration(r['seconds'])}")
    embed.description = "\n".join(lines)
    return embed


async def setup(bot):
    await bot.add_cog(VoiceStats(bot))
