"""
파티 모집 기능.
- 모집글 작성: 게임 선택 → 모달(시간/인원/메모) → 게시 + 역할 멘션
- 참가 / 참가취소 / 마감 버튼 (영구 View)
- 참가자 명단 실시간 갱신
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks
from discord import ui

import database as db
from cogs import nick_util

log = logging.getLogger("party-bot")

# 모집별 임시 역할 생성 잠금 — 동시 참가 시에도 역할 1개만 생성되게 보장 (단일 프로세스용)
_temp_role_locks: dict[int, asyncio.Lock] = {}

# 전역 관전 모드 진입/해제 직렬화 (동시 클릭 시 호스트 위임·닉 중복 처리 방지)
_spectator_locks: dict[tuple[int, int], asyncio.Lock] = {}


def _spectator_lock(guild_id: int, user_id: int) -> asyncio.Lock:
    key = (guild_id, user_id)
    if key not in _spectator_locks:
        _spectator_locks[key] = asyncio.Lock()
    return _spectator_locks[key]


def build_recruit_embed(
    recruit: dict,
    participant_members: list,
    host_member,
    total_count: int | None = None,
    spectator_members: list | None = None,
) -> discord.Embed:
    """
    모집글 임베드를 만든다. 참가자 명단 포함.
    total_count: DB 기준 실제 참가자 수 (서버를 떠난 멤버 포함).
                 None이면 participant_members 길이를 사용한다.
    """
    is_closed = recruit["status"] == "closed"
    color = 0x4E5058 if is_closed else 0x248046
    title = ("🔒 [마감] " if is_closed else "📢 ") + f"{recruit['game_name']} 파티 모집"

    count = total_count if total_count is not None else len(participant_members)
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="🎮 게임", value=recruit["game_name"], inline=True)
    embed.add_field(name="🕐 시간", value=recruit["play_time"], inline=True)
    embed.add_field(
        name="👥 인원",
        value=f"{count}/{recruit['max_players']}명",
        inline=True,
    )
    if recruit["note"]:
        embed.add_field(name="📝 메모", value=recruit["note"], inline=False)

    if participant_members:
        lines = []
        for i, m in enumerate(participant_members, 1):
            tag = " (모집자)" if m.id == recruit["host_id"] else ""
            lines.append(f"{i}. {m.display_name}{tag}")
        roster = "\n".join(lines)
    else:
        roster = "아직 참가자가 없어요."
    embed.add_field(name="참가자", value=roster, inline=False)

    if spectator_members:
        spec_lines = [
            f"{i}. {nick_util.strip_prefix(m.display_name)}"
            for i, m in enumerate(spectator_members, 1)
        ]
        embed.add_field(name="👀 관전자", value="\n".join(spec_lines), inline=False)

    if host_member:
        embed.set_footer(text=f"모집자: {host_member.display_name}")
    return embed


async def ensure_temp_role(guild, recruit):
    """
    모집의 임시 역할을 반환. 없으면 생성해서 DB에 저장.
    asyncio.Lock으로 동시 참가 시 고아 역할 생성을 방지한다.
    """
    rid = recruit["id"]
    if rid not in _temp_role_locks:
        _temp_role_locks[rid] = asyncio.Lock()

    async with _temp_role_locks[rid]:
        # 잠금 후 DB를 다시 읽어 최신 상태 확인
        fresh = await db.get_recruit(rid)
        if fresh and fresh["temp_role_id"]:
            role = guild.get_role(fresh["temp_role_id"])
            if role:
                return role
        # 새 역할 생성
        try:
            role = await guild.create_role(
                name=f"파티-{recruit['game_name']}-{rid}",
                mentionable=True,
                reason=f"모집 #{rid} 임시 역할",
            )
        except discord.Forbidden:
            log.warning(f"임시 역할 생성 실패 (권한 부족) — 모집 #{rid}")
            return None
        except discord.HTTPException as e:
            log.warning(f"임시 역할 생성 실패 — 모집 #{rid}: {e}")
            return None
        await db.set_recruit_temp_role(rid, role.id)
        return role


async def grant_temp_role(guild, recruit, member):
    """참가자에게 임시 역할 부여."""
    role = await ensure_temp_role(guild, recruit)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason="파티 참가")
        except Exception as e:
            log.warning(f"임시 역할 부여 실패 — 모집 #{recruit['id']} {member} ({member.id}): {e!r}")


async def revoke_temp_role(guild, recruit, member):
    """참가 취소자에게서 임시 역할 회수."""
    if not recruit["temp_role_id"]:
        return
    role = guild.get_role(recruit["temp_role_id"])
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason="파티 참가 취소")
        except Exception as e:
            log.warning(f"임시 역할 회수 실패 — 모집 #{recruit['id']} {member} ({member.id}): {e!r}")


async def grant_voice_access(guild, recruit, member):
    """
    이미 열린 파티 음성방에 개별 입장 권한을 직접 부여.
    임시 역할에 걸린 connect 권한이 있으면 원래 불필요하지만,
    이 코드 배포 이전에 만들어진 음성방(역할 권한이 없는 구버전 채널)도
    즉시 정상 동작하도록 보강한다.
    """
    if not recruit["voice_channel_id"]:
        return
    vc = guild.get_channel(recruit["voice_channel_id"])
    if not vc:
        log.warning(
            f"grant_voice_access: 음성채널을 찾을 수 없음 — 모집 #{recruit['id']} "
            f"voice_channel_id={recruit['voice_channel_id']} {member} ({member.id})"
        )
        return
    if vc.overwrites_for(member).connect is True:
        return  # 이미 정상 — 참가 버튼 반복 클릭 시 불필요한 API 호출 방지
    try:
        await vc.set_permissions(member, connect=True, reason="파티 참가")
    except Exception as e:
        log.warning(
            f"음성방 개별 입장 권한 부여 실패 — 모집 #{recruit['id']} 채널 #{vc.id} "
            f"{member} ({member.id}): {e!r}"
        )


async def revoke_voice_access(guild, recruit, member):
    """참가 취소자의 파티 음성방 개별 입장 권한(있다면) 회수."""
    if not recruit["voice_channel_id"]:
        return
    vc = guild.get_channel(recruit["voice_channel_id"])
    if not vc:
        return
    try:
        await vc.set_permissions(member, overwrite=None, reason="파티 참가 취소")
    except Exception:
        pass


async def delete_temp_role(guild, recruit):
    """모집 종료 시 임시 역할 자체를 삭제 (모든 보유자에게서 자동 제거됨)."""
    if not recruit["temp_role_id"]:
        return
    role = guild.get_role(recruit["temp_role_id"])
    if role:
        try:
            await role.delete(reason="파티 모집 종료")
        except Exception:
            pass
    await db.set_recruit_temp_role(recruit["id"], None)


async def refresh_recruit_message(bot, recruit_id: int):
    """DB 기준으로 모집글 메시지를 다시 그린다."""
    recruit = await db.get_recruit(recruit_id)
    if not recruit or not recruit["message_id"]:
        return
    guild = bot.get_guild(recruit["guild_id"])
    if not guild:
        return
    channel = guild.get_channel(recruit["channel_id"])
    if not channel:
        return
    try:
        msg = await channel.fetch_message(recruit["message_id"])
    except discord.NotFound:
        return

    user_ids = await db.list_participants(recruit_id)
    members = [m for uid in user_ids if (m := guild.get_member(uid))]
    host = guild.get_member(recruit["host_id"])

    # 관전자 = 이 파티 음성방에 현재 있는 '관전자 역할' 보유자 (참가자 제외)
    spectators = []
    if recruit["voice_channel_id"]:
        s = await db.get_settings(guild.id)
        srole_id = s.get("spectator_role_id")
        vc = guild.get_channel(recruit["voice_channel_id"])
        if srole_id and vc:
            srole = guild.get_role(srole_id)
            if srole:
                spectators = [
                    m for m in vc.members
                    if srole in m.roles and m.id not in user_ids
                ]

    embed = build_recruit_embed(
        recruit, members, host,
        total_count=len(user_ids), spectator_members=spectators,
    )
    view = None if recruit["status"] == "closed" else RecruitView(recruit_id)
    await msg.edit(embed=embed, view=view)


# ───────── 전역 관전 모드 ─────────
async def ensure_spectator_role(guild):
    """길드 '관전자' 역할 반환. 없으면 생성해 저장. 실패 시 None."""
    settings = await db.get_settings(guild.id)
    rid = settings.get("spectator_role_id")
    if rid:
        role = guild.get_role(rid)
        if role:
            return role
    try:
        role = await guild.create_role(name="👀 관전", reason="관전 모드용 역할", mentionable=False)
    except discord.HTTPException:
        return None
    await db.set_spectator_role(guild.id, role.id)
    return role


async def _handoff_host(bot, guild, recruit, host) -> str:
    """호스트가 관전 전환 시: 서버에 남아있는 가장 오래된 참가자에게 위임, 없으면 마감. 안내문 반환."""
    rid = recruit["id"]
    participants = await db.list_participants(rid)  # joined_at 순
    # 서버에 아직 있는 가장 오래된 비-호스트 참가자 (이미 나간 유저에게 위임 방지)
    new_host_id = next(
        (uid for uid in participants if uid != host.id and guild.get_member(uid) is not None),
        None,
    )
    if new_host_id is not None:
        await db.set_recruit_host(rid, new_host_id)
        await db.remove_participant(rid, host.id)
        await revoke_temp_role(guild, recruit, host)
        await revoke_voice_access(guild, recruit, host)
        new_host = guild.get_member(new_host_id)
        try:
            await new_host.send(
                f"**{guild.name}**: 모집자가 관전으로 전환해서 회원님이 새 모집자가 됐어요. "
                f"('{recruit['game_name']}' 파티) 다 끝나면 모집글의 '모집 마감'을 눌러주세요."
            )
        except discord.HTTPException:
            pass
        await refresh_recruit_message(bot, rid)
        return f"'{recruit['game_name']}' 파티 모집자를 {new_host.display_name} 님에게 넘겼어요."
    # 남아있는 참가자가 없음 → 마감 (호스트 임시역할도 회수)
    await revoke_temp_role(guild, recruit, host)
    await revoke_voice_access(guild, recruit, host)
    if recruit["voice_channel_id"]:
        await db.close_recruit(rid)
        await refresh_recruit_message(bot, rid)
    else:
        await archive_recruit_to_channel(bot, rid, reason="모집자가 관전 전환(남은 인원 없어 마감)")
    return f"'{recruit['game_name']}' 파티는 남은 인원이 없어 마감했어요."


async def enter_spectator_mode_flow(bot, guild, member) -> tuple[bool, str]:
    """전역 관전 모드 ON. 참가 중인 파티 정리(호스트는 위임/마감) + 관전자 역할 + 닉 접두사."""
    async with _spectator_lock(guild.id, member.id):
        if await db.is_in_spectator_mode(guild.id, member.id):
            return (False, "이미 관전 모드예요.")

        # 원본 닉을 어떤 편집보다 먼저 스냅샷 (이후 접두사 적용/동시 편집으로 오염 방지)
        base = nick_util.strip_prefix(member.nick)

        # 역할을 먼저 확보 — 실패하면 아무것도 바꾸지 않고 종료 (DB/닉/파티 상태 불일치 방지)
        srole = await ensure_spectator_role(guild)
        if srole is None:
            return (False, "관전자 역할을 만들 수 없어요. 봇에 '역할 관리(Manage Roles)' 권한이 있는지 확인해주세요.")
        try:
            await member.add_roles(srole, reason="관전 모드 ON")
        except discord.HTTPException:
            return (False, "관전자 역할을 부여하지 못했어요. 봇 역할을 더 위로 올리고 '역할 관리' 권한을 확인해주세요.")

        # 여기서부터 커밋 — 참가 중인 파티 정리
        notes = []
        for rid in await db.list_user_open_recruits(guild.id, member.id):
            recruit = await db.get_recruit(rid)
            if not recruit:
                continue
            if recruit["host_id"] == member.id:
                notes.append(await _handoff_host(bot, guild, recruit, member))
            else:
                await db.remove_participant(rid, member.id)
                await revoke_temp_role(guild, recruit, member)
                await revoke_voice_access(guild, recruit, member)
                await refresh_recruit_message(bot, rid)
                notes.append(f"'{recruit['game_name']}' 파티 참가를 취소했어요.")

        await db.enter_spectator_mode(guild.id, member.id, base)

        nick_note = ""
        if nick_util.can_edit_nick(member):
            ok, _ = await nick_util.set_nick(
                member, nick_util.with_prefix(base, member), reason="관전 모드"
            )
            if not ok:
                nick_note = " (닉네임 표시는 못 바꿨어요)"
        else:
            nick_note = " (닉네임 표시는 못 바꿨어요)"

        msg = "👀 관전 모드를 켰어요! 이제 아무 파티 음성방이나 들어가서 관전할 수 있어요." + nick_note
        if notes:
            msg += "\n- " + "\n- ".join(notes)
        return (True, msg)


async def exit_spectator_mode_flow(guild, member) -> bool:
    """전역 관전 모드 OFF. 역할 회수 + 닉 복원. 관전 모드가 아니었으면 False."""
    async with _spectator_lock(guild.id, member.id):
        existed, original = await db.exit_spectator_mode(guild.id, member.id)
        if not existed:
            return False
        settings = await db.get_settings(guild.id)
        srole_id = settings.get("spectator_role_id")
        if srole_id:
            srole = guild.get_role(srole_id)
            if srole and srole in member.roles:
                try:
                    await member.remove_roles(srole, reason="관전 모드 OFF")
                except discord.HTTPException:
                    pass
        if member.nick and member.nick.startswith(nick_util.SPECTATOR_PREFIX):
            if nick_util.can_edit_nick(member):
                await nick_util.set_nick(member, original, reason="관전 모드 종료")
        return True


# ───────── 관전 모드 전용 패널 (영구) ─────────
class SpectatorPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="관전 모드 켜기", emoji="👀",
               style=discord.ButtonStyle.success, custom_id="spectator:on")
    async def on(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        _, msg = await enter_spectator_mode_flow(
            interaction.client, interaction.guild, interaction.user
        )
        await interaction.followup.send(msg, ephemeral=True)

    @ui.button(label="관전 모드 끄기", emoji="🚪",
               style=discord.ButtonStyle.secondary, custom_id="spectator:off")
    async def off(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        stopped = await exit_spectator_mode_flow(interaction.guild, interaction.user)
        await interaction.followup.send(
            "관전 모드를 껐어요. 닉네임도 원래대로 돌렸어요." if stopped else "관전 모드가 아니었어요.",
            ephemeral=True,
        )


def build_spectator_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="👀 관전 모드",
        description=(
            "**[관전 모드 켜기]** 를 누르면 닉네임 앞에 '관전'이 붙고, "
            "**아무 파티 음성방이나 자유롭게 들어가서 관전**할 수 있어요 (정원 상관없이). "
            "파티마다 따로 신청할 필요 없어요.\n\n"
            "• 파티에 참가 중이었다면 자동으로 빠져요 (모집자라면 다른 참가자에게 자동 위임).\n"
            "• 음성에서 완전히 나가면 자동으로 꺼져요.\n"
            "• **[관전 모드 끄기]** 를 누르면 닉네임이 원래대로 돌아와요."
        ),
        color=0x5865F2,
    )
    return embed


# ───────── 모집 작성 모달 ─────────
class RecruitModal(ui.Modal, title="파티 모집글 작성"):
    def __init__(self, game_name: str):
        super().__init__()
        self.game_name = game_name

    play_time = ui.TextInput(label="플레이 시간", placeholder="예: 오늘 21:00", max_length=50)
    max_players = ui.TextInput(label="모집 인원 (본인 포함)", placeholder="예: 5", max_length=3)
    note = ui.TextInput(
        label="메모 (선택)",
        placeholder="예: 골드 이상, 마이크 필수",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_p = int(str(self.max_players).strip())
            if max_p < 2 or max_p > 99:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "인원은 2~99 사이 숫자로 입력해주세요.", ephemeral=True
            )
            return

        # 모집글 전용 채널 확인
        settings = await db.get_settings(interaction.guild.id)
        post_channel_id = settings.get("recruit_post_channel_id")
        post_channel = (
            interaction.guild.get_channel(post_channel_id)
            if post_channel_id
            else None
        )
        # 전용 채널이 설정됐으면 그곳에, 없으면 현재 채널에 게시
        target_channel = post_channel or interaction.channel

        recruit_id = await db.create_recruit(
            interaction.guild.id,
            target_channel.id,       # 실제 게시 채널 저장
            interaction.user.id,
            self.game_name,
            str(self.play_time).strip(),
            max_p,
            str(self.note).strip() or None,
        )

        recruit = await db.get_recruit(recruit_id)
        host = interaction.user
        embed = build_recruit_embed(recruit, [host], host)
        view = RecruitView(recruit_id)

        # 역할 멘션
        game = await db.get_game(interaction.guild.id, self.game_name)
        mention = ""
        if game:
            role = interaction.guild.get_role(game["role_id"])
            if role:
                mention = role.mention

        if post_channel and post_channel != interaction.channel:
            # 전용 채널에 게시 → 모달 응답은 ephemeral 안내로 처리
            await interaction.response.defer(ephemeral=True)
            sent = await post_channel.send(content=mention or None, embed=embed, view=view)
            await db.set_recruit_message(recruit_id, sent.id)
            await interaction.followup.send(
                f"모집글이 {post_channel.mention}에 게시됐어요!", ephemeral=True
            )
        else:
            # 현재 채널에 게시 (기존 동작)
            await interaction.response.send_message(
                content=mention or None, embed=embed, view=view
            )
            sent = await interaction.original_response()
            await db.set_recruit_message(recruit_id, sent.id)

        # 모집자에게 임시 역할 부여
        recruit = await db.get_recruit(recruit_id)
        await grant_temp_role(interaction.guild, recruit, host)


# ───────── 게임 선택 (모집 시작) ─────────
class GamePickSelect(ui.Select):
    def __init__(self, games):
        from cogs.game_roles import _is_valid_emoji
        options = [
            discord.SelectOption(
                label=g["name"],
                emoji=g["emoji"] if _is_valid_emoji(g["emoji"]) else None,
            )
            for g in games
        ]
        super().__init__(placeholder="모집할 게임 선택", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RecruitModal(self.values[0]))


class GamePickView(ui.View):
    def __init__(self, games):
        super().__init__(timeout=60)
        self.add_item(GamePickSelect(games))


# ───────── 모집글 버튼 (영구 View) ─────────
class RecruitView(ui.View):
    def __init__(self, recruit_id: int):
        super().__init__(timeout=None)
        self.recruit_id = recruit_id
        # custom_id에 recruit_id를 박아서 재시작 후에도 동작
        self.join_btn.custom_id = f"recruit_join:{recruit_id}"
        self.leave_btn.custom_id = f"recruit_leave:{recruit_id}"
        self.voice_btn.custom_id = f"recruit_voice:{recruit_id}"
        self.close_btn.custom_id = f"recruit_close:{recruit_id}"

    @ui.button(label="참가", emoji="✋", style=discord.ButtonStyle.success, row=0)
    async def join_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        result = await db.try_join_recruit(self.recruit_id, interaction.user.id)
        if result == "closed":
            await interaction.followup.send("마감된 모집이에요.", ephemeral=True)
            return
        if result == "full":
            await interaction.followup.send("이미 인원이 다 찼어요.", ephemeral=True)
            return
        if result == "already_joined":
            # 이미 참가 중이지만, 이 수정 이전에 만들어진 방이라면 입장 권한이
            # 아직도 누락돼 있을 수 있으므로 다시 동기화해준다.
            recruit = await db.get_recruit(self.recruit_id)
            if recruit:
                await grant_temp_role(interaction.guild, recruit, interaction.user)
                await grant_voice_access(interaction.guild, recruit, interaction.user)
            await interaction.followup.send(
                "이미 참가 중이에요. (입장 권한을 다시 확인했어요)", ephemeral=True
            )
            return

        # 참가 성공 — 역할 부여 (recruit 재조회로 최신 temp_role_id 반영)
        recruit = await db.get_recruit(self.recruit_id)
        if recruit:
            # 관전 모드였다면 끄고 플레이어로 전환 (플레이와 관전은 동시에 안 됨)
            if await db.is_in_spectator_mode(interaction.guild.id, interaction.user.id):
                await exit_spectator_mode_flow(interaction.guild, interaction.user)
            await grant_temp_role(interaction.guild, recruit, interaction.user)
            await grant_voice_access(interaction.guild, recruit, interaction.user)

        await interaction.followup.send("참가했어요!", ephemeral=True)
        await refresh_recruit_message(interaction.client, self.recruit_id)

    @ui.button(label="참가 취소", emoji="❌", style=discord.ButtonStyle.secondary, row=0)
    async def leave_btn(self, interaction: discord.Interaction, button: ui.Button):
        recruit = await db.get_recruit(self.recruit_id)
        if not recruit:
            return
        current = await db.list_participants(self.recruit_id)
        if interaction.user.id not in current:
            await interaction.response.send_message("참가하지 않은 상태예요.", ephemeral=True)
            return
        if interaction.user.id == recruit["host_id"]:
            await interaction.response.send_message(
                "모집자는 본인을 뺄 수 없어요. 모집을 마감해주세요.", ephemeral=True
            )
            return
        await db.remove_participant(self.recruit_id, interaction.user.id)
        await revoke_temp_role(interaction.guild, recruit, interaction.user)
        await revoke_voice_access(interaction.guild, recruit, interaction.user)
        await interaction.response.send_message("참가를 취소했어요.", ephemeral=True)
        await refresh_recruit_message(interaction.client, self.recruit_id)

    @ui.button(label="음성방 열기", emoji="🔊", style=discord.ButtonStyle.primary, row=1)
    async def voice_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        recruit = await db.get_recruit(self.recruit_id)
        if not recruit or recruit["status"] != "open":
            await interaction.followup.send("마감된 모집이에요.", ephemeral=True)
            return

        # 이미 음성방이 있으면 안내
        if recruit["voice_channel_id"]:
            existing = interaction.guild.get_channel(recruit["voice_channel_id"])
            if existing:
                await interaction.followup.send(
                    f"이미 음성방이 있어요: {existing.mention}", ephemeral=True
                )
                return

        settings = await db.get_settings(interaction.guild.id)
        category = None
        if settings["voice_category_id"]:
            category = interaction.guild.get_channel(settings["voice_category_id"])

        # 참가자 + 관전자 역할만 접근 가능하게 권한 설정
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(connect=False),
            interaction.guild.me: discord.PermissionOverwrite(
                connect=True, manage_channels=True, move_members=True
            ),
        }
        # 파티 전용 임시 역할에 입장 권한 부여.
        # 참가자는 참가 시점(방 개설 이전/이후 모두)에 이 역할을 받으므로,
        # 개별 멤버 대신 역할에 권한을 걸어야 방 개설 이후 참가자도 자동으로 입장할 수 있다.
        temp_role = await ensure_temp_role(interaction.guild, recruit)
        if temp_role:
            overwrites[temp_role] = discord.PermissionOverwrite(connect=True)
        else:
            # 역할 생성 실패 시 폴백: 현재 참가자에게 개별 권한 부여
            user_ids = await db.list_participants(self.recruit_id)
            for uid in user_ids:
                member = interaction.guild.get_member(uid)
                if member:
                    overwrites[member] = discord.PermissionOverwrite(connect=True)
        # 관전자 역할에 입장 권한 → 관전 모드인 사람은 누구나 이 파티 음성방에 입장 가능
        srole = await ensure_spectator_role(interaction.guild)
        if srole:
            overwrites[srole] = discord.PermissionOverwrite(connect=True)

        try:
            vc = await interaction.guild.create_voice_channel(
                name=f"🎮 {recruit['game_name']} 파티",
                category=category,
                # user_limit=0(무제한): 관전자 정원초과 입장 허용.
                # (Discord는 user_limit이 개별 connect 권한보다 우선해 막으므로 0으로 둔다)
                user_limit=0,
                overwrites=overwrites,
                reason=f"모집 #{self.recruit_id} 음성방",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "음성방을 만들 권한이 없어요. 봇에 '채널 관리' 권한을 주세요.", ephemeral=True
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"음성방 생성 중 오류가 발생했어요: {e}", ephemeral=True
            )
            return

        await db.set_recruit_voice(self.recruit_id, vc.id)

        # 누른 사람이 음성방에 있으면 이동
        if interaction.user.voice and interaction.user.voice.channel:
            try:
                await interaction.user.move_to(vc)
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            f"음성방을 만들었어요: {vc.mention}\n참가자 전원이 나가면 자동으로 닫혀요.",
            ephemeral=True,
        )
        await refresh_recruit_message(interaction.client, self.recruit_id)

    @ui.button(label="모집 마감", emoji="🔒", style=discord.ButtonStyle.danger, row=1)
    async def close_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        recruit = await db.get_recruit(self.recruit_id)
        if not recruit:
            await interaction.followup.send("모집 정보를 찾을 수 없어요.", ephemeral=True)
            return

        # 모집자이거나 서버 관리자 / 패널 관리 역할 보유자만 마감 가능
        settings = await db.get_settings(interaction.guild.id)
        pmr = settings.get("panel_manager_role")
        is_admin = (
            interaction.user.guild_permissions.manage_guild
            or (pmr and any(r.id == pmr for r in interaction.user.roles))
        )
        if interaction.user.id != recruit["host_id"] and not is_admin:
            await interaction.followup.send(
                "모집자나 관리자만 마감할 수 있어요.", ephemeral=True
            )
            return

        await db.close_recruit(self.recruit_id)
        await delete_temp_role(interaction.guild, recruit)

        if not recruit["voice_channel_id"]:
            # 음성방이 없으면 즉시 아카이브 (채널에서 메시지 삭제 + 아카이브 채널 이동)
            await interaction.followup.send("모집을 마감하고 정리했어요.", ephemeral=True)
            await archive_recruit_to_channel(
                interaction.client, self.recruit_id, reason="모집자가 마감함"
            )
        else:
            # 음성방이 활성 중이면 마감 상태 표시 유지 → 전원 퇴장 시 자동 아카이브
            await interaction.followup.send(
                "모집을 마감했어요. 음성방에서 전원 퇴장하면 자동으로 정리돼요.",
                ephemeral=True,
            )
            await refresh_recruit_message(interaction.client, self.recruit_id)


class Recruitment(commands.Cog):
    STALE_HOURS = 6  # 음성방 없이 이 시간 넘게 방치된 모집글 자동 정리

    def __init__(self, bot):
        self.bot = bot
        self.cleanup_stale.start()

    def cog_unload(self):
        self.cleanup_stale.cancel()

    @tasks.loop(minutes=30)
    async def cleanup_stale(self):
        """음성방 없이 오래 방치된 열린 모집글을 자동 마감 (호스트가 깜빡해도 정리)."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.STALE_HOURS)
        for r in await db.list_stale_open_recruits(cutoff):
            try:
                await archive_recruit_to_channel(
                    self.bot, r["id"], reason=f"{self.STALE_HOURS}시간 방치되어 자동 정리됨"
                )
            except Exception as e:
                log.warning(f"방치 모집 자동정리 실패 #{r['id']}: {e}")

    @cleanup_stale.before_loop
    async def _before_cleanup(self):
        await self.bot.wait_until_ready()


async def archive_recruit_to_channel(
    bot, recruit_id: int, reason: str = "음성방이 닫혀 자동 종료됨"
):
    """
    모집글을 아카이브 채널에 복제하고 원본을 삭제한다.
    - 음성방 전원 퇴장 시: voice_stats.py에서 호출 (기본 reason)
    - 마감 버튼(음성방 없음): close_btn에서 직접 호출 (reason="모집자가 마감함")
    Discord는 메시지 이동이 불가능하므로 재게시 방식으로 구현한다.
    """
    recruit = await db.get_recruit(recruit_id)
    if not recruit:
        return
    # 원자적으로 아카이브 점유 — 중복 아카이브(스테일 루프 vs 마감 버튼 등) 방지
    if not await db.archive_recruit(recruit_id):
        return  # 이미 다른 경로가 아카이브함
    guild = bot.get_guild(recruit["guild_id"])
    if not guild:
        return  # 이미 점유(archived)했으니 스테일 루프가 다시 잡지 않음

    settings = await db.get_settings(guild.id)
    archive_channel = None
    if settings["archive_channel_id"]:
        archive_channel = guild.get_channel(settings["archive_channel_id"])

    # 참가자 명단 수집
    user_ids = await db.list_participants(recruit_id)
    members = [m for uid in user_ids if (m := guild.get_member(uid))]
    host = guild.get_member(recruit["host_id"])

    # 아카이브 채널에 종료된 모집글 재게시
    if archive_channel:
        embed = build_recruit_embed(recruit, members, host, total_count=len(user_ids))
        embed.color = 0x4E5058
        embed.title = "📦 [종료] " + recruit["game_name"] + " 파티"
        embed.add_field(name="종료 사유", value=reason, inline=False)
        try:
            await archive_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # 원본 모집글 + 스레드 삭제
    channel = guild.get_channel(recruit["channel_id"])
    if channel and recruit["message_id"]:
        try:
            msg = await channel.fetch_message(recruit["message_id"])
            if msg.thread:
                try:
                    await msg.thread.delete()
                except discord.HTTPException:
                    pass
            await msg.delete()
        except discord.NotFound:
            pass

    # 임시 역할 삭제 (모든 보유자에게서 자동 제거됨)
    await delete_temp_role(guild, recruit)
    # status='archived' 점유는 함수 시작에서 이미 처리됨


async def setup(bot):
    await bot.add_cog(Recruitment(bot))
