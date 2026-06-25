"""
입장 경로 구분 + 오픈채팅 게이트 관리.

경로 구분(카카오 vs 디스코드):
- 봇이 각 길드의 초대코드 사용 횟수를 메모리에 캐시(bot.invite_cache)해두고,
  on_member_join 때 다시 읽어 +1 늘어난 코드를 찾아 '이 사람이 쓴 초대코드'를 판정한다.
- 관리자가 등록한 '카카오 유입용 초대코드'면 route='kakao', 그 외엔 'discord'.
- 모호(동시 입장)하면 'unknown', 아무 코드도 안 늘면 vanity 추정.
- guild.invites() 는 봇에 '서버 관리하기(Manage Guild)' 권한이 필요. 없으면 추적만 비활성.

오픈채팅 게이트:
- 실제 게이트 버튼은 verification.py 의 VerifyView 에 있다([인증하기] → [오픈채팅 입장하기]).
- 여기서는 관리자 설정 UI(오픈채팅 URL·카카오 코드·게이트 역할·마커 역할·유입 통계)만 제공한다.

블랙리스트와 on_member_join 을 공유하므로, 맨 앞에서 is_blacklisted 를 확인해
차단 대상이면 경로 태깅을 건너뛴다(중복 처리 방지).
"""

import logging

import discord
from discord.ext import commands
from discord import ui

import database as db

log = logging.getLogger("party-bot")


def parse_invite_code(raw: str) -> str | None:
    """'https://discord.gg/abc', 'discord.gg/abc', 'abc' → 'abc'. 빈 값이면 None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    raw = raw.split("?")[0].rstrip("/")
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    return raw or None


async def _fetch_invite_uses(guild) -> dict | None:
    """{code: uses} 반환. Manage Guild 권한이 없으면 None(추적 불가)."""
    try:
        invites = await guild.invites()
    except (discord.Forbidden, discord.HTTPException):
        return None
    return {inv.code: (inv.uses or 0) for inv in invites}


def _is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.manage_guild


# ───────── 관리자 설정 UI ─────────
class OpenChatUrlModal(ui.Modal, title="오픈채팅 URL 설정"):
    url_input = ui.TextInput(
        label="카카오 오픈채팅 URL (비우면 해제)",
        placeholder="https://open.kakao.com/o/...",
        required=False,
        max_length=300,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        url = str(self.url_input).strip() or None
        await db.set_openchat_url(interaction.guild.id, url)
        if url:
            await interaction.response.send_message(
                "오픈채팅 URL 을 저장했어요.\n"
                "⚠️ 이 링크는 **어떤 채널에도 게시되지 않고**, 인증을 마친 유저가 "
                "[오픈채팅 입장하기] 버튼을 누를 때 **본인에게만(ephemeral)** 보여요. "
                "그래서 초대코드 정지 위험이 없어요.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message("오픈채팅 URL 을 해제했어요.", ephemeral=True)


class KakaoCodeModal(ui.Modal, title="카카오 유입 초대코드 등록"):
    code_input = ui.TextInput(
        label="카카오 전용 초대코드 또는 링크 (비우면 해제)",
        placeholder="https://discord.gg/xxxx 또는 xxxx",
        required=False,
        max_length=120,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        code = parse_invite_code(str(self.code_input))
        await db.set_kakao_invite_code(interaction.guild.id, code)
        if code:
            await interaction.response.send_message(
                f"카카오 유입용 초대코드를 `{code}` 로 등록했어요.\n"
                "이제 이 코드로 들어온 사람은 'kakao', 그 외 초대는 'discord' 로 구분돼요.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message("카카오 초대코드를 해제했어요.", ephemeral=True)


class GateRoleSelect(ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="오픈채팅 통과 역할 선택")

    async def callback(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        role = self.values[0]
        await db.set_openchat_gate_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"오픈채팅 통과 역할을 {role.mention}(으)로 설정했어요. "
            "게이트를 통과하면 이 역할이 부여돼요.",
            ephemeral=True,
        )


class GateRoleSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(GateRoleSelect())


class MarkerRoleSelect(ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="카카오 유입 마커 역할 선택")

    async def callback(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        role = self.values[0]
        await db.set_entry_marker_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"카카오 유입자에게 부여할 마커 역할을 {role.mention}(으)로 설정했어요.",
            ephemeral=True,
        )


class MarkerRoleSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(MarkerRoleSelect())


class EntrySettingsView(ui.View):
    """관리자: 입장 경로 + 오픈채팅 게이트 설정 (ephemeral)."""
    def __init__(self):
        super().__init__(timeout=180)

    @ui.button(label="오픈채팅 URL", emoji="💬", style=discord.ButtonStyle.primary, row=0)
    async def set_url(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_modal(OpenChatUrlModal())

    @ui.button(label="카카오 초대코드", emoji="🟡", style=discord.ButtonStyle.secondary, row=0)
    async def set_kakao(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_modal(KakaoCodeModal())

    @ui.button(label="게이트 통과 역할", emoji="🔓", style=discord.ButtonStyle.secondary, row=1)
    async def set_gate_role(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_message(
            "오픈채팅 게이트 통과 시 부여할 역할을 선택하세요. (선택 사항)",
            view=GateRoleSelectView(), ephemeral=True,
        )

    @ui.button(label="카카오 마커 역할", emoji="🏷️", style=discord.ButtonStyle.secondary, row=1)
    async def set_marker_role(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_message(
            "카카오 유입자에게 자동 부여할 마커 역할을 선택하세요. (선택 사항)",
            view=MarkerRoleSelectView(), ephemeral=True,
        )

    @ui.button(label="유입 통계", emoji="📊", style=discord.ButtonStyle.success, row=2)
    async def stats(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        stats = await db.get_route_stats(interaction.guild.id)
        settings = await db.get_settings(interaction.guild.id)
        kakao = stats.get("kakao", 0)
        discord_n = stats.get("discord", 0)
        unknown = stats.get("unknown", 0)
        vanity = stats.get("vanity", 0)
        me = interaction.guild.me
        track_ok = me.guild_permissions.manage_guild
        embed = discord.Embed(title="📊 입장 경로 유입 통계", color=0x5865F2)
        embed.description = (
            f"🟡 카카오: **{kakao}**\n"
            f"🔷 디스코드: **{discord_n}**\n"
            f"🌐 vanity: **{vanity}**\n"
            f"❓ 미상(동시입장 등): **{unknown}**"
        )
        if not track_ok:
            embed.add_field(
                name="⚠️ 추적 비활성",
                value="봇에 '서버 관리하기(Manage Guild)' 권한이 없어 초대코드 추적이 꺼져 있어요. "
                      "권한을 켜면 경로가 기록돼요.",
                inline=False,
            )
        elif not settings.get("kakao_invite_code"):
            embed.add_field(
                name="ℹ️ 카카오 코드 미등록",
                value="아직 카카오 전용 초대코드를 등록하지 않아 모든 유입이 'discord' 로 분류돼요.",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


# ───────── 입장 경로 추적 Cog ─────────
class EntryTracking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not hasattr(bot, "invite_cache"):
            bot.invite_cache = {}

    @commands.Cog.listener()
    async def on_ready(self):
        # 봇 시작 시 모든 길드의 초대 사용 횟수를 선적재 (첫 입장 오판 방지)
        for guild in self.bot.guilds:
            uses = await _fetch_invite_uses(guild)
            if uses is not None:
                self.bot.invite_cache[guild.id] = uses

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        if invite.guild is None:
            return
        # 아직 선적재되지 않은 길드는 건드리지 않는다. setdefault 로 부분 캐시를 만들면
        # _detect_route 의 'old is None → unknown' cold-cache 안전장치가 무력화된다.
        cache = self.bot.invite_cache.get(invite.guild.id)
        if cache is not None:
            cache[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        if invite.guild is None:
            return
        cache = self.bot.invite_cache.get(invite.guild.id)
        if cache:
            cache.pop(invite.code, None)

    async def _detect_route(self, guild, kakao_code):
        """(used_code, route_label) 반환."""
        old = self.bot.invite_cache.get(guild.id)
        new = await _fetch_invite_uses(guild)
        if new is None:
            return (None, "unknown")  # 권한 없음
        self.bot.invite_cache[guild.id] = new
        if old is None:
            return (None, "unknown")  # 캐시 공백(시작 직후 등)

        increased = [code for code, uses in new.items() if uses > old.get(code, 0)]
        # 1회용 초대가 소비되면 코드가 사라짐 → old 엔 있고 new 엔 없음
        increased += [code for code in old if code not in new]

        if len(increased) == 1:
            used = increased[0]
            if kakao_code and used == kakao_code:
                return (used, "kakao")
            return (used, "discord")
        if not increased:
            return (None, "vanity")   # 아무 코드도 안 늘음 → vanity 추정
        return (None, "unknown")      # 동시 입장 등 모호

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        # 블랙리스트 대상이면 blacklist cog 가 차단을 처리하므로 경로 태깅은 생략.
        # 단, 이 입장도 초대 사용횟수를 +1 시키므로 캐시를 갱신해두지 않으면
        # 다음 '정상' 입장 판정이 어긋난다(두 코드가 늘어난 것처럼 보여 unknown 처리됨).
        if await db.is_blacklisted(guild.id, member.id):
            fresh = await _fetch_invite_uses(guild)
            if fresh is not None:
                self.bot.invite_cache[guild.id] = fresh
            return

        settings = await db.get_settings(guild.id)
        kakao_code = settings.get("kakao_invite_code")
        marker_role_id = settings.get("entry_marker_role_id")

        used_code, route = await self._detect_route(guild, kakao_code)
        await db.record_member_entry(guild.id, member.id, used_code, route)

        if route == "kakao" and marker_role_id:
            role = guild.get_role(marker_role_id)
            if role:
                try:
                    await member.add_roles(role, reason="카카오 유입 마커")
                except discord.HTTPException:
                    pass


async def setup(bot):
    await bot.add_cog(EntryTracking(bot))
