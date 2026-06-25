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


def build_entry_settings_embed() -> discord.Embed:
    """입장/오픈채팅 설정 화면 — 각 버튼이 무엇을 하는지 쉬운 말로 안내."""
    embed = discord.Embed(
        title="🔐 입장 보안 & 오픈채팅 설정",
        description=(
            "들어온 사람을 **카카오 오픈채팅 주소로부터 안전하게** 안내하고, "
            "누가 어느 경로로 들어왔는지 구분해요.\n"
            "아래 버튼으로 설정하세요. (⭐ = 꼭 필요 · 나머지는 선택)"
        ),
        color=0x5865F2,
    )
    embed.add_field(
        name="⭐ 💬 오픈채팅 주소",
        value=(
            "카톡 오픈채팅 링크를 등록해요. 이 링크는 **어떤 채널에도 올라가지 않아요.**\n"
            "규칙 인증을 마친 사람이 인증패널의 `[오픈채팅 입장하기]` 버튼을 눌렀을 때만 "
            "**그 사람 화면에만** 잠깐 보여요 → 그래서 디스코드 초대코드가 정지되지 않아요."
        ),
        inline=False,
    )
    embed.add_field(
        name="🟡 카카오 유입 코드  ·  선택(통계용)",
        value=(
            "카톡에 올릴 **디스코드 초대링크 1개**를 등록하면, 그 링크로 들어온 사람은 "
            "'카카오', 나머지는 '디스코드'로 자동 구분돼요."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔓 오픈채팅 인증 역할  ·  선택",
        value="`[오픈채팅 입장하기]` 버튼을 통과한 사람에게 **자동으로 줄 역할**이에요.",
        inline=False,
    )
    embed.add_field(
        name="🏷️ 카톡 유입 표시 역할  ·  선택",
        value="'카카오 유입 코드'로 들어온 사람에게 **자동으로 줄 역할**이에요.",
        inline=False,
    )
    embed.add_field(
        name="📊 유입 통계",
        value="카카오 vs 디스코드로 각각 몇 명이 들어왔는지 확인해요.",
        inline=False,
    )
    embed.set_footer(text="⭐ 오픈채팅 주소만 등록해도 보안 기능은 바로 작동해요.")
    return embed


# ───────── 관리자 설정 UI ─────────
class OpenChatUrlModal(ui.Modal, title="오픈채팅 주소 설정"):
    url_input = ui.TextInput(
        label="카카오 오픈채팅 링크 (비우면 삭제)",
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
                "✅ 오픈채팅 주소를 저장했어요.\n"
                "이 링크는 **어떤 채널에도 올라가지 않고**, 규칙 인증을 마친 사람이 "
                "`[오픈채팅 입장하기]` 버튼을 누를 때 **그 사람에게만** 보여요. "
                "그래서 디스코드 초대코드가 정지될 걱정이 없어요.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message("오픈채팅 주소를 삭제했어요.", ephemeral=True)


class KakaoCodeModal(ui.Modal, title="카카오 유입 코드 등록"):
    code_input = ui.TextInput(
        label="카톡에 올릴 디스코드 초대링크 (비우면 삭제)",
        placeholder="https://discord.gg/xxxx  또는  xxxx",
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
                f"✅ 카카오 유입 코드를 `{code}` 로 등록했어요.\n"
                "이제 이 링크로 들어온 사람은 **카카오**, 다른 링크로 들어온 사람은 "
                "**디스코드**로 자동 구분돼요. (이 링크를 카톡 채팅방에 공유하세요.)",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message("카카오 유입 코드를 삭제했어요.", ephemeral=True)


class GateRoleSelect(ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="오픈채팅 인증 역할 선택")

    async def callback(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        role = self.values[0]
        await db.set_openchat_gate_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"✅ 오픈채팅 인증 역할을 {role.mention}(으)로 정했어요.\n"
            "`[오픈채팅 입장하기]` 버튼을 통과하면 이 역할이 자동으로 부여돼요.",
            ephemeral=True,
        )


class GateRoleSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(GateRoleSelect())


class MarkerRoleSelect(ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="카톡 유입 표시 역할 선택")

    async def callback(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        role = self.values[0]
        await db.set_entry_marker_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"✅ 카톡 유입 코드로 들어온 사람에게 줄 역할을 {role.mention}(으)로 정했어요.",
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

    @ui.button(label="오픈채팅 주소", emoji="💬", style=discord.ButtonStyle.primary, row=0)
    async def set_url(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_modal(OpenChatUrlModal())

    @ui.button(label="카카오 유입 코드", emoji="🟡", style=discord.ButtonStyle.secondary, row=0)
    async def set_kakao(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_modal(KakaoCodeModal())

    @ui.button(label="오픈채팅 인증 역할", emoji="🔓", style=discord.ButtonStyle.secondary, row=1)
    async def set_gate_role(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_message(
            "`[오픈채팅 입장하기]` 버튼을 통과한 사람에게 자동으로 줄 역할을 선택하세요. (선택)",
            view=GateRoleSelectView(), ephemeral=True,
        )

    @ui.button(label="카톡 유입 표시 역할", emoji="🏷️", style=discord.ButtonStyle.secondary, row=1)
    async def set_marker_role(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_message(
            "'카카오 유입 코드'로 들어온 사람에게 자동으로 줄 역할을 선택하세요. (선택)",
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
        embed = discord.Embed(title="📊 입장 경로별 인원", color=0x5865F2)
        embed.description = (
            f"🟡 카카오 오픈채팅으로 들어옴: **{kakao}명**\n"
            f"🔷 디스코드 초대로 들어옴: **{discord_n}명**\n"
            f"🌐 서버 맞춤 URL(vanity)로 들어옴: **{vanity}명**\n"
            f"❓ 구분 못 함(동시 입장 등): **{unknown}명**"
        )
        if not track_ok:
            embed.add_field(
                name="⚠️ 지금은 경로 추적이 꺼져 있어요",
                value="봇에 '서버 관리하기(Manage Server)' 권한이 없어요. "
                      "이 권한을 켜야 누가 어느 경로로 들어왔는지 기록돼요.",
                inline=False,
            )
        elif not settings.get("kakao_invite_code"):
            embed.add_field(
                name="ℹ️ 아직 카카오 유입 코드를 등록 안 했어요",
                value="카카오 유입 코드를 등록하기 전까지는 모두 '디스코드'로 분류돼요.",
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
