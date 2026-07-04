"""
블랙리스트 (디스코드 고유 user_id 기반).

- 이미 서버를 나간 유저도 숫자 ID 로 등록할 수 있다 (재입장 시 차단).
- on_member_join 에서 차단: 기본은 강퇴(kick), guild_settings.blacklist_ban_on_join=1 이면 밴.
- 'native_ban' 옵션: DB 기록과 함께 Discord 네이티브 밴을 걸어 봇이 꺼져 있어도 차단 유지.
- 관리자 UI 는 관리자 패널의 '🔑 역할·통계' 드롭다운 → '🚫 블랙리스트 관리' 에서 진입.

entry_tracking 과 on_member_join 을 공유하지만, entry_tracking 은 맨 앞에서
db.is_blacklisted() 를 확인해 차단 대상이면 경로 태깅을 건너뛴다(이중 처리 방지).
"""

import logging

import discord
from discord.ext import commands
from discord import ui

import database as db
from cogs import palette
from cogs.checks import ensure_manage_guild

log = logging.getLogger("party-bot")

# 스노우플레이크 범위 검증 (17자리 ~ 디스코드 ID 최댓값 2^63-1, 19자리)
_MIN_SNOWFLAKE = 10 ** 16
_MAX_SNOWFLAKE = 2 ** 63 - 1


def parse_user_id(raw: str) -> int | None:
    """숫자 ID 또는 <@123> 멘션 문자열을 user_id(int)로 파싱. 실패 시 None."""
    raw = (raw or "").strip()
    if raw.startswith("<@") and raw.endswith(">"):
        raw = raw[2:-1].lstrip("!")
    if not raw.isdigit():
        return None
    val = int(raw)
    if val < _MIN_SNOWFLAKE or val > _MAX_SNOWFLAKE:
        return None
    return val


async def enforce_blacklist_action(member: discord.Member) -> None:
    """블랙리스트 대상 멤버를 설정에 따라 강퇴/밴. (안내 DM 옵션은 조치 전에 전송)"""
    guild = member.guild
    settings = await db.get_settings(guild.id)
    ban = bool(settings.get("blacklist_ban_on_join"))
    notify = bool(settings.get("blacklist_notify"))
    entry = await db.get_blacklist_entry(guild.id, member.id)
    reason = (entry or {}).get("reason") or "블랙리스트"

    # 강퇴/밴 후에는 DM 을 못 보내므로 반드시 조치 전에 발송
    if notify:
        try:
            await member.send(
                f"**{guild.name}** 서버는 블랙리스트 정책에 따라 입장이 제한돼요.\n"
                f"사유: {reason}\n자세한 문의는 서버 운영진에게 부탁드려요."
            )
        except discord.HTTPException:
            pass  # DM 차단/닫힘 — 무시하고 조치 진행

    try:
        if ban:
            await guild.ban(
                member, reason=f"블랙리스트 자동 차단: {reason}", delete_message_seconds=0
            )
        else:
            await member.kick(reason=f"블랙리스트 자동 차단: {reason}")
        log.info(f"블랙리스트 차단: user={member.id} guild={guild.id} ({'ban' if ban else 'kick'})")
    except discord.Forbidden:
        log.warning(
            f"블랙리스트 차단 실패(권한 부족 — 멤버 추방/차단 권한 또는 역할 위치 확인): "
            f"user={member.id} guild={guild.id}"
        )
    except discord.HTTPException as e:
        log.warning(f"블랙리스트 차단 실패: user={member.id} guild={guild.id}: {e}")


def build_blacklist_embed(guild, rows: list) -> discord.Embed:
    embed = discord.Embed(title="🚫 블랙리스트", color=palette.DANGER)
    if not rows:
        embed.description = "등록된 블랙리스트가 없어요."
        return embed
    lines = []
    for r in rows:
        when = r["created_at"].strftime("%Y-%m-%d")
        native = " 🔨밴" if r["native_ban"] else ""
        reason = r["reason"] or "_(사유 없음)_"
        lines.append(f"`{r['user_id']}`{native} — {reason} ({when})")
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"최근 {len(rows)}건 · 아래 드롭다운으로 해제")
    return embed


# ───────── 블랙리스트 추가 모달 ─────────
class BlacklistAddModal(ui.Modal, title="블랙리스트 추가"):
    user_id_input = ui.TextInput(
        label="유저 ID (숫자)",
        placeholder="예: 123456789012345678  (나간 유저도 ID로 등록 가능)",
        max_length=25,
    )
    reason_input = ui.TextInput(
        label="사유 (선택)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=200,
    )
    native_input = ui.TextInput(
        label="디스코드 영구 밴도 적용? (yes 입력 시)",
        placeholder="yes 입력 시 디스코드 밴까지. 비우면 DB 기록만",
        required=False,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not await ensure_manage_guild(interaction):
            return
        uid = parse_user_id(str(self.user_id_input))
        if uid is None:
            await interaction.response.send_message(
                "올바른 유저 ID(17~19자리 숫자)를 입력해주세요.", ephemeral=True
            )
            return
        if uid == interaction.user.id or uid == interaction.client.user.id:
            await interaction.response.send_message(
                "본인이나 봇은 블랙리스트에 추가할 수 없어요.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        reason = str(self.reason_input).strip() or None
        want_native = str(self.native_input).strip().lower() == "yes"
        settings = await db.get_settings(interaction.guild.id)
        member = interaction.guild.get_member(uid)

        notes = []
        native_applied = 0
        if want_native:
            # 밴 후에는 DM 을 못 보내므로, 현재 서버에 있고 안내가 켜져 있으면 밴 전에 DM
            if member and settings.get("blacklist_notify"):
                try:
                    await member.send(
                        f"**{interaction.guild.name}** 서버는 블랙리스트 정책에 따라 입장이 제한돼요.\n"
                        f"사유: {reason or '블랙리스트'}\n자세한 문의는 서버 운영진에게 부탁드려요."
                    )
                except discord.HTTPException:
                    pass
            try:
                await interaction.guild.ban(
                    discord.Object(id=uid),
                    reason=f"블랙리스트(영구밴): {reason or ''}",
                    delete_message_seconds=0,
                )
                native_applied = 1
                notes.append("디스코드 영구 밴 적용됨")
            except discord.Forbidden:
                notes.append("⚠️ 디스코드 밴 실패: 봇에 '멤버 차단(Ban Members)' 권한이 없어요 (DB 기록은 완료)")
            except discord.HTTPException as e:
                notes.append(f"⚠️ 디스코드 밴 실패: {e}")

        # native_ban 플래그는 실제 밴 성공 여부를 반영 (실패 시 0 → 해제 시 unban 시도 안 함)
        await db.add_blacklist(
            interaction.guild.id, uid, reason, interaction.user.id, native_applied
        )

        if not want_native and member:
            # 네이티브 밴이 아니면, 현재 서버에 있는 멤버는 즉시 강퇴/밴 처리
            await enforce_blacklist_action(member)
            notes.append("현재 서버에 있어 바로 조치했어요")

        msg = f"`{uid}` 를 블랙리스트에 추가했어요."
        if notes:
            msg += "\n- " + "\n- ".join(notes)
        await interaction.followup.send(msg, ephemeral=True)


# ───────── 블랙리스트 해제 드롭다운 ─────────
class BlacklistRemoveSelect(ui.Select):
    def __init__(self, rows: list):
        options = [
            discord.SelectOption(
                label=str(r["user_id"]),
                value=str(r["user_id"]),
                description=(r["reason"] or "사유 없음")[:100],
            )
            for r in rows[:25]
        ]
        super().__init__(placeholder="해제할 유저 선택", options=options)

    async def callback(self, interaction: discord.Interaction):
        if not await ensure_manage_guild(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        uid = int(self.values[0])
        native = await db.remove_blacklist(interaction.guild.id, uid)
        note = ""
        if native:  # native_ban=1 이었으면 디스코드 밴도 해제
            try:
                await interaction.guild.unban(discord.Object(id=uid), reason="블랙리스트 해제")
                note = " (디스코드 밴도 해제했어요)"
            except discord.NotFound:
                note = " (디스코드 밴 기록은 이미 없었어요)"
            except discord.Forbidden:
                note = " (⚠️ 디스코드 밴 해제 실패: 봇 권한 부족)"
            except discord.HTTPException:
                pass
        await interaction.followup.send(
            f"`{uid}` 를 블랙리스트에서 해제했어요.{note}", ephemeral=True
        )


class BlacklistRemoveView(ui.View):
    def __init__(self, rows: list):
        super().__init__(timeout=120)
        self.add_item(BlacklistRemoveSelect(rows))


# ───────── 블랙리스트 관리 메뉴 (ephemeral) ─────────
class BlacklistManageView(ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @ui.button(label="ID로 추가", emoji="➕", style=discord.ButtonStyle.danger, row=0)
    async def add(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_guild(interaction):
            return
        await interaction.response.send_modal(BlacklistAddModal())

    @ui.button(label="목록·해제", emoji="📋", style=discord.ButtonStyle.secondary, row=0)
    async def list_remove(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_guild(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        rows = await db.list_blacklist(interaction.guild.id, limit=25)
        embed = build_blacklist_embed(interaction.guild, rows)
        view = BlacklistRemoveView(rows) if rows else None
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @ui.button(label="차단 모드 전환 (강퇴/밴)", emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_mode(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_guild(interaction):
            return
        settings = await db.get_settings(interaction.guild.id)
        new_val = not bool(settings.get("blacklist_ban_on_join"))
        await db.set_blacklist_ban_on_join(interaction.guild.id, new_val)
        state = "밴 (재시도 불가, '멤버 차단' 권한 필요)" if new_val else "강퇴 (소프트 차단)"
        await interaction.response.send_message(
            f"재입장 차단 기본 동작을 **{state}** (으)로 바꿨어요.", ephemeral=True
        )

    @ui.button(label="차단 안내 DM 켜기/끄기", emoji="✉️", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_notify(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_guild(interaction):
            return
        settings = await db.get_settings(interaction.guild.id)
        new_val = not bool(settings.get("blacklist_notify"))
        await db.set_blacklist_notify(interaction.guild.id, new_val)
        state = "켜짐 (차단 전 DM 안내)" if new_val else "꺼짐 (조용히 차단)"
        await interaction.response.send_message(
            f"차단 안내 DM 을 **{state}** (으)로 바꿨어요.", ephemeral=True
        )


class Blacklist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        if await db.is_blacklisted(member.guild.id, member.id):
            await enforce_blacklist_action(member)


async def setup(bot):
    await bot.add_cog(Blacklist(bot))
