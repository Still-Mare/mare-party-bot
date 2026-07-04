"""
게임 역할 관리 기능.
- 관리자: 게임 추가/삭제 (역할 자동 생성)
- 유저  : 게임 역할 토글 (버튼)
"""

import discord
from discord.ext import commands
from discord import ui

import database as db
from cogs import palette


def _is_valid_emoji(s: str | None) -> bool:
    """
    Discord 버튼에 사용 가능한 이모지인지 확인.
    - 유니코드 이모지: 비-ASCII 문자 포함 (예: 🎯)
    - 커스텀 이모지: <:name:id> 또는 <a:name:id> 형식
    일반 알파벳·숫자 문자열(예: "valorant")은 False.
    """
    if not s:
        return False
    s = s.strip()
    if not s:
        return False
    if s.startswith("<") and s.endswith(">") and ":" in s:
        return True
    return any(ord(c) > 127 for c in s)


# ───────── 게임 추가 모달 ─────────
class AddGameModal(ui.Modal, title="게임 추가 (여러 개 가능)"):
    games_input = ui.TextInput(
        label="이모지 + 게임 이름 (한 줄에 하나씩, 최대 10개)",
        placeholder="🎯 발로란트\n🔫 오버워치\n🏔️ 에이펙스\n⚔️ 롤",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        lines = [ln.strip() for ln in str(self.games_input).splitlines() if ln.strip()]
        if not lines:
            await interaction.response.send_message("입력이 비어있어요.", ephemeral=True)
            return
        if len(lines) > 10:
            await interaction.response.send_message(
                "한 번에 최대 10개까지만 추가할 수 있어요. 나눠서 등록해주세요.",
                ephemeral=True,
            )
            return

        # 권한 부족 시 첫 시도에서 알 수 있도록 미리 응답 defer
        await interaction.response.defer(ephemeral=True)

        added = []
        skipped = []
        failed = []

        for line in lines:
            # 첫 토큰을 이모지로, 나머지를 게임 이름으로 분리
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                failed.append(f"`{line}` (형식 오류 — 이모지와 이름 모두 필요)")
                continue
            emoji, name = parts[0], parts[1].strip()

            # 이모지 유효성 검사 — 알파벳 문자열은 Discord 버튼 이모지로 사용 불가
            if not _is_valid_emoji(emoji):
                failed.append(
                    f"`{line}` (이모지 오류 — '{emoji}'은 유효한 이모지가 아니에요. "
                    f"🎯처럼 실제 이모지 문자를 첫 번째에 입력해주세요)"
                )
                continue

            existing = await db.get_game(guild.id, name)
            if existing:
                skipped.append(f"{emoji} {name} (이미 등록됨)")
                continue

            # 같은 이름 역할이 이미 있으면 재사용, 없으면 생성
            role = discord.utils.get(guild.roles, name=name)
            if role is None:
                try:
                    role = await guild.create_role(
                        name=name, mentionable=True,
                        reason=f"{interaction.user}가 게임 추가",
                    )
                except discord.Forbidden:
                    failed.append(f"{emoji} {name} (역할 생성 권한 부족)")
                    continue
                except discord.HTTPException as e:
                    failed.append(f"{emoji} {name} (오류: {e})")
                    continue

            await db.add_game(guild.id, name, emoji, role.id)
            added.append(f"{emoji} {name}")

        # 결과 메시지
        parts_msg = []
        if added:
            parts_msg.append(f"✅ 추가됨 ({len(added)}개)\n" + "\n".join(f"  • {x}" for x in added))
        if skipped:
            parts_msg.append(f"⏭️ 건너뜀\n" + "\n".join(f"  • {x}" for x in skipped))
        if failed:
            parts_msg.append(f"❌ 실패\n" + "\n".join(f"  • {x}" for x in failed))

        await interaction.followup.send(
            "\n\n".join(parts_msg) or "처리할 게임이 없어요.", ephemeral=True
        )


# ───────── 게임 삭제 선택 ─────────
class RemoveGameSelect(ui.Select):
    def __init__(self, games):
        options = [
            discord.SelectOption(
                label=g["name"],
                emoji=g["emoji"] if _is_valid_emoji(g["emoji"]) else None,
            )
            for g in games
        ]
        super().__init__(placeholder="삭제할 게임 선택", options=options, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]
        game = await db.get_game(interaction.guild.id, name)
        await db.remove_game(interaction.guild.id, name)
        # 역할도 삭제 (선택)
        if game:
            role = interaction.guild.get_role(game["role_id"])
            if role:
                try:
                    await role.delete(reason="게임 삭제")
                except discord.Forbidden:
                    pass
        await interaction.response.send_message(f"'{name}' 게임을 삭제했어요.", ephemeral=True)
        await refresh_role_panel(interaction)


class RemoveGameView(ui.View):
    def __init__(self, games):
        super().__init__(timeout=60)
        self.add_item(RemoveGameSelect(games))


# ───────── 커스텀 이모지 게임 추가 ─────────

class CustomEmojiAddView(ui.View):
    """
    서버 커스텀 이모지 드롭다운 + 유니코드 이모지 버튼.
    게임 추가 시 이모지 방식 선택 화면.
    """
    def __init__(self, emojis: list):
        super().__init__(timeout=60)
        if emojis:
            sorted_emojis = sorted(emojis, key=lambda e: e.name.lower())[:25]
            self.add_item(CustomEmojiSelect(sorted_emojis))
        self.add_item(UseUnicodeEmojiButton())


class CustomEmojiSelect(ui.Select):
    def __init__(self, emojis: list):
        options = [
            discord.SelectOption(
                label=e.name[:100],
                value=f"<{'a' if e.animated else ''}:{e.name}:{e.id}>",
                emoji=e,
            )
            for e in emojis
        ]
        super().__init__(placeholder="서버 커스텀 이모지 선택", options=options)

    async def callback(self, interaction: discord.Interaction):
        emoji_str = self.values[0]  # "<:name:id>" 또는 "<a:name:id>" 형식
        await interaction.response.send_modal(CustomEmojiGameNameModal(emoji_str))


class UseUnicodeEmojiButton(ui.Button):
    def __init__(self):
        super().__init__(label="유니코드 이모지로 추가", emoji="🔤",
                         style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddGameModal())


class CustomEmojiGameNameModal(ui.Modal):
    """커스텀 이모지 선택 후 게임 이름을 입력받는 모달."""
    game_name = ui.TextInput(
        label="게임 이름",
        placeholder="예: 발로란트",
        max_length=50,
    )

    def __init__(self, emoji_str: str):
        super().__init__(title="게임 이름 입력")
        self.emoji_str = emoji_str

    async def on_submit(self, interaction: discord.Interaction):
        name = str(self.game_name).strip()
        if not name:
            await interaction.response.send_message("게임 이름을 입력해주세요.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        existing = await db.get_game(guild.id, name)
        if existing:
            await interaction.followup.send(f"**{name}**은 이미 등록된 게임이에요.", ephemeral=True)
            return

        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            try:
                role = await guild.create_role(
                    name=name, mentionable=True,
                    reason=f"{interaction.user} 게임 추가",
                )
            except discord.Forbidden:
                await interaction.followup.send("역할 생성 권한이 없어요.", ephemeral=True)
                return
            except discord.HTTPException as e:
                await interaction.followup.send(f"역할 생성 오류: {e}", ephemeral=True)
                return

        await db.add_game(guild.id, name, self.emoji_str, role.id)
        await interaction.followup.send(
            f"✅ {self.emoji_str} **{name}** 게임을 추가했어요!", ephemeral=True
        )


# ───────── 역할 토글 버튼 (영구 View) ─────────
class RoleToggleButton(ui.Button):
    def __init__(self, game):
        # DB에 잘못된 이모지가 저장된 경우 None으로 대체 (Invalid emoji 방지)
        emoji = game["emoji"] if _is_valid_emoji(game["emoji"]) else None
        super().__init__(
            label=game["name"],
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            custom_id=f"roletoggle:{game['role_id']}",
        )
        self.role_id = game["role_id"]

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message(
                "역할을 찾을 수 없어요. 관리자가 게임을 다시 등록해야 할 수 있어요.",
                ephemeral=True,
            )
            return
        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.response.send_message(
                    f"{role.name} 역할을 뺐어요.", ephemeral=True
                )
            else:
                await member.add_roles(role)
                await interaction.response.send_message(
                    f"{role.name} 역할을 받았어요!", ephemeral=True
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "역할을 변경할 권한이 없어요. "
                "봇 역할이 해당 게임 역할보다 위에 있는지 관리자에게 확인 요청해주세요.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"역할 변경 중 오류가 발생했어요: {e}", ephemeral=True
            )


class RolePanelView(ui.View):
    """게임 역할 토글 버튼들을 담는 영구 View."""
    def __init__(self, games):
        super().__init__(timeout=None)
        for g in games[:25]:  # 버튼은 최대 25개
            self.add_item(RoleToggleButton(g))


async def refresh_role_panel(interaction: discord.Interaction):
    """역할 선택 메시지를 새로고침해서 최신 게임 목록을 반영."""
    games = await db.list_games(interaction.guild.id)
    if not games:
        return
    view = RolePanelView(games)
    embed = discord.Embed(
        title="🎮 게임 역할 선택",
        description="아래 버튼을 눌러 게임 역할을 받거나 뺄 수 있어요.\n"
                    "역할을 받으면 해당 게임 모집글에 알림이 가요.",
        color=palette.INFO,
    )
    # 채널에 새 패널 전송 (followup)
    await interaction.followup.send(embed=embed, view=view)


class GameRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(GameRoles(bot))
