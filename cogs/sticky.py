"""
운영자 공지 스티키 (채널 하단 고정).

- 설정된 채널에 새 메시지가 올라오면, 이전 스티키를 지우고 다시 보내 항상 맨 아래에 둔다.
- on_message 로 감지하며 message_content 인텐트는 불필요(채널/작성자/메시지ID만 사용).
- 메시지 폭주 시 깜빡임·레이트리밋을 막으려고 채널별 3초 debounce + '이미 맨 아래면 스킵'
  + 채널별 Lock 으로 재게시를 직렬화한다.
- 채널당 1개 스티키. 상태는 전부 DB(sticky_messages)에 있어 재시작 후에도 복구된다.
- 관리자 UI 는 관리자 패널의 '📺 채널 설정' 드롭다운 → '📌 스티키 공지 설정' 에서 진입.
"""

import asyncio
import logging

import discord
from discord.ext import commands
from discord import ui

import database as db
from cogs.checks import ensure_manage_guild

log = logging.getLogger("party-bot")

_DEBOUNCE_SECS = 3  # 버스트를 1회 재게시로 흡수


def build_sticky_embed(sticky: dict) -> discord.Embed:
    embed = discord.Embed(
        title=sticky.get("title") or None,
        description=sticky["content"],
        color=0x5865F2,
    )
    if sticky.get("image_url"):
        embed.set_image(url=sticky["image_url"])
    embed.set_footer(text="📌 고정 공지")
    return embed


def _missing_perms(channel, me) -> list:
    # 봇은 자기 자신의 스티키 메시지만 삭제하므로 Manage Messages 는 필요 없다.
    # (자기 메시지 삭제는 권한 불필요) → send/embed 만 하드 요구.
    perms = channel.permissions_for(me)
    missing = []
    if not perms.send_messages:
        missing.append("메시지 보내기 (Send Messages)")
    if not perms.embed_links:
        missing.append("임베드 링크 (Embed Links)")
    return missing


# ───────── 스티키 작성/수정 모달 ─────────
class StickyModal(ui.Modal, title="스티키 공지 설정"):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

    title_input = ui.TextInput(label="제목 (선택)", required=False, max_length=200)
    content_input = ui.TextInput(
        label="내용",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )
    image_input = ui.TextInput(
        label="이미지 URL (선택)",
        required=False,
        placeholder="https://...",
        max_length=400,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not await ensure_manage_guild(interaction):
            return
        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "스티키는 일반 텍스트 채널에만 설정할 수 있어요.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        missing = _missing_perms(channel, interaction.guild.me)
        if missing:
            await interaction.followup.send(
                f"**{channel.mention} 에 스티키를 설정할 수 없어요.** 봇에게 아래 권한이 부족해요:\n"
                + "\n".join(f"• **{p}**" for p in missing)
                + "\n\n채널 편집 → 권한 탭에서 봇 역할에 위 항목을 켜주세요.",
                ephemeral=True,
            )
            return

        title = str(self.title_input).strip() or None
        content = str(self.content_input).strip()
        image_url = str(self.image_input).strip() or None
        if not content:
            await interaction.followup.send("내용을 입력해주세요.", ephemeral=True)
            return
        if image_url and not image_url.lower().startswith(("http://", "https://")):
            await interaction.followup.send(
                "이미지 URL 은 http:// 또는 https:// 로 시작해야 해요. 이미지를 빼려면 비워주세요.",
                ephemeral=True,
            )
            return

        # 기존 스티키 메시지가 있으면 삭제 후 새로 게시
        old = await db.get_sticky(interaction.guild.id, channel.id)
        if old and old.get("last_message_id"):
            try:
                msg = await channel.fetch_message(old["last_message_id"])
                await msg.delete()
            except discord.HTTPException:
                pass

        await db.upsert_sticky(
            interaction.guild.id, channel.id, title, content, image_url, interaction.user.id
        )
        sticky = await db.get_sticky(interaction.guild.id, channel.id)
        try:
            sent = await channel.send(embed=build_sticky_embed(sticky))
        except discord.HTTPException as e:
            await interaction.followup.send(f"스티키 게시 중 오류가 발생했어요: {e}", ephemeral=True)
            return
        await db.set_sticky_message_id(interaction.guild.id, channel.id, sent.id)
        # on_message 빠른 필터용 메모리 셋 갱신
        cog = interaction.client.get_cog("Sticky")
        if cog:
            cog.sticky_channels.add(channel.id)
        await interaction.followup.send(
            f"{channel.mention} 에 스티키 공지를 설정했어요! 새 메시지가 올라와도 항상 맨 아래에 고정돼요.",
            ephemeral=True,
        )


# ───────── 채널 선택 (설정/해제) ─────────
class StickySetChannelSelect(ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="스티키를 둘 채널 선택", channel_types=[discord.ChannelType.text])

    async def callback(self, interaction: discord.Interaction):
        if not await ensure_manage_guild(interaction):
            return
        # 컴포넌트 상호작용 → 모달 응답
        await interaction.response.send_modal(StickyModal(self.values[0].id))


class StickySetChannelView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(StickySetChannelSelect())


class StickyDisableChannelSelect(ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="스티키를 끌 채널 선택", channel_types=[discord.ChannelType.text])

    async def callback(self, interaction: discord.Interaction):
        if not await ensure_manage_guild(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        channel = self.values[0]
        sticky = await db.get_sticky(interaction.guild.id, channel.id)
        if not sticky:
            await interaction.followup.send("그 채널에는 스티키가 없어요.", ephemeral=True)
            return
        # 현재 스티키 메시지 삭제
        if sticky.get("last_message_id"):
            real = interaction.guild.get_channel(channel.id)
            if isinstance(real, discord.TextChannel):
                try:
                    msg = await real.fetch_message(sticky["last_message_id"])
                    await msg.delete()
                except discord.HTTPException:
                    pass
        await db.disable_sticky(interaction.guild.id, channel.id)
        cog = interaction.client.get_cog("Sticky")
        if cog:
            cog.sticky_channels.discard(channel.id)
        await interaction.followup.send(f"{channel.mention} 의 스티키를 껐어요.", ephemeral=True)


class StickyDisableChannelView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(StickyDisableChannelSelect())


# ───────── 스티키 관리 메뉴 (ephemeral) ─────────
class StickyManageView(ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @ui.button(label="스티키 설정/수정", emoji="📌", style=discord.ButtonStyle.success, row=0)
    async def set_sticky(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_guild(interaction):
            return
        await interaction.response.send_message(
            "스티키 공지를 둘 채널을 선택하세요.", view=StickySetChannelView(), ephemeral=True
        )

    @ui.button(label="스티키 끄기", emoji="🗑️", style=discord.ButtonStyle.danger, row=0)
    async def disable_sticky(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_guild(interaction):
            return
        await interaction.response.send_message(
            "스티키를 끌 채널을 선택하세요.", view=StickyDisableChannelView(), ephemeral=True
        )


# ───────── 스티키 재게시 Cog ─────────
class Sticky(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._tasks: dict[int, asyncio.Task] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        # 스티키가 켜진 채널 id 집합 — on_message 에서 DB 조회 전 빠른 1차 필터
        self.sticky_channels: set[int] = set()

    @commands.Cog.listener()
    async def on_ready(self):
        # 활성 스티키 채널을 메모리 셋에 선적재 (재시작 후에도 빠른 필터 동작)
        for guild in self.bot.guilds:
            for s in await db.list_enabled_stickies(guild.id):
                self.sticky_channels.add(s["channel_id"])

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 봇/DM/스레드·비텍스트 채널 무시 (message_content 없이 동작)
        if message.author.bot or message.guild is None:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        # 스티키 없는 채널은 DB 조회 없이 즉시 반환 (메시지마다 DB 히트 방지)
        if message.channel.id not in self.sticky_channels:
            return
        self._schedule_repost(message.channel)

    def _schedule_repost(self, channel):
        cid = channel.id
        existing = self._tasks.get(cid)
        if existing and not existing.done():
            existing.cancel()
        task = asyncio.create_task(self._debounced_repost(channel))
        self._tasks[cid] = task
        # 완료된 task 가 dict 에 쌓이지 않게 정리 (현재 task 일 때만 제거)
        task.add_done_callback(
            lambda t, c=cid: self._tasks.pop(c, None) if self._tasks.get(c) is t else None
        )

    async def _debounced_repost(self, channel):
        try:
            await asyncio.sleep(_DEBOUNCE_SECS)
        except asyncio.CancelledError:
            return
        try:
            await self._repost(channel)
        except Exception as e:  # 백그라운드 task — 예외가 새어나가지 않게
            log.warning(f"스티키 재게시 실패 channel={channel.id}: {e}")

    async def _repost(self, channel):
        lock = self._locks.setdefault(channel.id, asyncio.Lock())
        async with lock:
            sticky = await db.get_sticky(channel.guild.id, channel.id)
            if not sticky or not sticky["enabled"]:
                return
            # 이미 우리 스티키가 맨 아래면 스킵
            if sticky["last_message_id"] and channel.last_message_id == sticky["last_message_id"]:
                return
            # 이전 스티키 삭제 (수동 삭제·만료 시 404 무시)
            if sticky["last_message_id"]:
                try:
                    old = await channel.fetch_message(sticky["last_message_id"])
                    await old.delete()
                except discord.NotFound:
                    pass
                except discord.HTTPException:
                    pass
            # 새로 게시
            try:
                msg = await channel.send(embed=build_sticky_embed(sticky))
            except discord.HTTPException:
                return
            await db.set_sticky_message_id(channel.guild.id, channel.id, msg.id)


async def setup(bot):
    await bot.add_cog(Sticky(bot))
