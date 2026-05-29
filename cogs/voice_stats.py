"""
음성채널 이용시간 추적.
- on_voice_state_update 로 입장/퇴장 감지
- 입장 시각 기록 → 퇴장 시 누적
- 봇 시작 시 이미 음성방에 있던 사람도 세션 시작 처리
"""

import discord
from discord.ext import commands

import database as db


def fmt_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}시간 {m}분"
    return f"{m}분"


class VoiceStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # 봇 재시작 시 현재 음성방에 있는 사람들 세션 시작
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if not member.bot:
                        await db.voice_join(guild.id, member.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        # 음성방 진입 (이전엔 없었는데 지금 있음)
        if before.channel is None and after.channel is not None:
            await db.voice_join(member.guild.id, member.id)
        # 음성방 퇴장
        elif before.channel is not None and after.channel is None:
            await db.voice_leave(member.guild.id, member.id)
        # 채널 이동: 세션은 유지되므로 누적시간 계산엔 영향 없음
        # (voice_join을 다시 부르면 입장시각이 리셋되어 시간이 깎이므로 호출하지 않음)

        # ── 모집용 음성방이 비었는지 확인 ──
        # 누군가 채널을 떠났을 때(before.channel이 있을 때) 그 방을 점검
        if before.channel is not None:
            await self._check_empty_recruit_voice(before.channel)

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
