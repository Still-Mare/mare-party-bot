"""
포인트 상점 시스템.

/포인트상점      유저용  - 포인트 확인 및 역할 구매 패널 설치
/포인트상점설정  관리자용 - 시간당 포인트·역할 가격 설정 패널 설치

음성채널 이용 시간에 비례해 포인트가 자동 적립되며,
모인 포인트로 상점에 등록된 역할을 구매할 수 있다.
"""

import discord
from discord.ext import commands
from discord import ui, app_commands

import database as db
from cogs.checks import can_manage_panel, ensure_manage_guild, ensure_manage_roles


# ═══════════════════════════════════════════════════════════════
#  유저용 상점 패널 (영구 View)
# ═══════════════════════════════════════════════════════════════

class ShopUserPanelView(ui.View):
    """포인트 상점 유저 패널 — 봇 재시작 후에도 동작하는 영구 View."""

    def __init__(self):
        super().__init__(timeout=None)

    # ── 내 포인트 ──────────────────────────────────────────────
    @ui.button(
        label="내 포인트", emoji="💰",
        style=discord.ButtonStyle.secondary,
        custom_id="shop:mypoints",
    )
    async def my_points(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        points = await db.get_user_points(interaction.guild.id, interaction.user.id)
        p10m   = await db.get_points_per_10min(interaction.guild.id)

        embed = discord.Embed(title="💰 내 포인트 현황", color=0xF1C40F)
        embed.add_field(name="현재 잔액",  value=f"**{points:,}** 포인트", inline=True)
        embed.add_field(name="적립 비율",  value=f"10분 = **{p10m}** 포인트", inline=True)
        embed.set_footer(text=f"{interaction.user.display_name} · 음성채널에 있을수록 포인트가 쌓여요")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── 역할 구매 ──────────────────────────────────────────────
    @ui.button(
        label="역할 구매", emoji="🛒",
        style=discord.ButtonStyle.success,
        custom_id="shop:buy",
    )
    async def buy_role(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        items = await db.list_shop_roles(interaction.guild.id)
        if not items:
            await interaction.followup.send(
                "현재 판매 중인 역할이 없어요. 관리자에게 문의해주세요.", ephemeral=True
            )
            return

        points        = await db.get_user_points(interaction.guild.id, interaction.user.id)
        user_role_ids = {r.id for r in interaction.user.roles}

        embed = discord.Embed(title="🛒 역할 구매", color=0x57F287)
        embed.description = (
            f"💰 내 포인트: **{points:,}** 포인트\n\n"
            "아래 드롭다운에서 구매할 역할을 선택하세요."
        )

        lines = []
        for item in items:
            role = interaction.guild.get_role(item["role_id"])
            if not role:
                continue
            affordable = "✅" if points >= item["cost"] else "❌"
            owned      = "  *(보유 중)*" if role.id in user_role_ids else ""
            lines.append(f"{affordable} **{role.name}**{owned}\n　└ {item['cost']:,} 포인트")

        if lines:
            embed.add_field(name="판매 목록", value="\n".join(lines), inline=False)
        embed.set_footer(text="✅ 구매 가능  ❌ 포인트 부족")

        view = BuyRoleView(items, points, interaction.guild)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


# ═══════════════════════════════════════════════════════════════
#  관리자용 상점 설정 패널 (영구 View)
# ═══════════════════════════════════════════════════════════════

class ShopAdminPanelView(ui.View):
    """포인트 상점 관리자 패널 — 봇 재시작 후에도 동작하는 영구 View."""

    def __init__(self):
        super().__init__(timeout=None)

    # ── 10분당 포인트 설정 ────────────────────────────────────
    @ui.button(
        label="10분당 포인트", emoji="🪙",
        style=discord.ButtonStyle.secondary,
        custom_id="shopadmin:setpph",
        row=0,
    )
    async def set_pph(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_guild(interaction):
            return
        await interaction.response.send_modal(SetPointsPer10MinModal())

    # ── 역할 추가 ──────────────────────────────────────────────
    @ui.button(
        label="역할 추가", emoji="➕",
        style=discord.ButtonStyle.success,
        custom_id="shopadmin:addrole",
        row=0,
    )
    async def add_role(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_roles(interaction):
            return
        await interaction.response.send_message(
            "상점에 추가할 역할을 선택하세요.",
            view=AddShopRoleView(),
            ephemeral=True,
        )

    # ── 역할 제거 ──────────────────────────────────────────────
    @ui.button(
        label="역할 제거", emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id="shopadmin:delrole",
        row=0,
    )
    async def del_role(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_roles(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        items = await db.list_shop_roles(interaction.guild.id)
        if not items:
            await interaction.followup.send("상점에 등록된 역할이 없어요.", ephemeral=True)
            return
        await interaction.followup.send(
            "제거할 역할을 선택하세요.",
            view=RemoveShopRoleView(items, interaction.guild),
            ephemeral=True,
        )

    # ── 현황 보기 ──────────────────────────────────────────────
    @ui.button(
        label="현황 보기", emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="shopadmin:list",
        row=1,
    )
    async def list_items(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_roles(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        items       = await db.list_shop_roles(interaction.guild.id)
        p10m        = await db.get_points_per_10min(interaction.guild.id)
        excluded_id = await db.get_points_excluded_channel(interaction.guild.id)
        afk_id      = interaction.guild.afk_channel.id if interaction.guild.afk_channel else None

        embed = discord.Embed(title="📋 포인트 상점 현황", color=0x5865F2)
        embed.add_field(
            name="🪙 적립 비율",
            value=f"음성 10분 = **{p10m}** 포인트  (5분 미만 세션 제외)",
            inline=False,
        )

        # 잠수채널 현황
        afk_lines = []
        if afk_id:
            afk_ch = interaction.guild.get_channel(afk_id)
            afk_lines.append(f"• Discord AFK 채널: {afk_ch.mention if afk_ch else f'`{afk_id}`'} (자동)")
        if excluded_id:
            ex_ch = interaction.guild.get_channel(excluded_id)
            afk_lines.append(f"• 지정 잠수채널: {ex_ch.mention if ex_ch else f'`{excluded_id}`'}")
        embed.add_field(
            name="🔇 포인트 제외 채널",
            value="\n".join(afk_lines) if afk_lines else "없음 (Discord AFK 채널도 미설정)",
            inline=False,
        )

        if items:
            lines = []
            for item in items:
                role    = interaction.guild.get_role(item["role_id"])
                mention = role.mention if role else f"삭제된 역할 (`{item['role_id']}`)"
                lines.append(f"• {mention} — **{item['cost']:,}** 포인트")
            embed.add_field(
                name=f"🛍️ 판매 중인 역할 ({len(items)}개)",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="🛍️ 판매 중인 역할", value="등록된 역할이 없어요.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── 잠수채널 설정 ─────────────────────────────────────────
    @ui.button(
        label="잠수채널 설정", emoji="🔇",
        style=discord.ButtonStyle.secondary,
        custom_id="shopadmin:setafk",
        row=1,
    )
    async def set_afk_channel(self, interaction: discord.Interaction, button: ui.Button):
        if not await ensure_manage_guild(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        excluded_id = await db.get_points_excluded_channel(interaction.guild.id)
        afk_id      = interaction.guild.afk_channel.id if interaction.guild.afk_channel else None

        lines = ["포인트가 지급되지 않을 채널을 설정해요.\n"]
        if afk_id:
            ch = interaction.guild.get_channel(afk_id)
            lines.append(f"• Discord AFK 채널 {ch.mention if ch else f'`{afk_id}`'}: **자동 제외** (별도 설정 불필요)")
        if excluded_id:
            ch = interaction.guild.get_channel(excluded_id)
            lines.append(f"• 현재 지정 잠수채널: {ch.mention if ch else f'`{excluded_id}`'}")
        else:
            lines.append("• 현재 지정 잠수채널: **미설정**")

        await interaction.followup.send(
            "\n".join(lines),
            view=ExcludedChannelView(excluded_id),
            ephemeral=True,
        )


# ═══════════════════════════════════════════════════════════════
#  구매 흐름 Views
# ═══════════════════════════════════════════════════════════════

class BuyRoleView(ui.View):
    def __init__(self, shop_items: list, user_points: int, guild: discord.Guild):
        super().__init__(timeout=60)
        self.add_item(BuyRoleSelect(shop_items, user_points, guild))


class BuyRoleSelect(ui.Select):
    def __init__(self, shop_items: list, user_points: int, guild: discord.Guild):
        options = []
        for item in shop_items[:25]:
            role = guild.get_role(item["role_id"])
            if not role:
                continue
            can_afford = user_points >= item["cost"]
            options.append(discord.SelectOption(
                label=role.name[:100],
                value=str(item["role_id"]),
                description=f"{item['cost']:,} 포인트 · {'구매 가능' if can_afford else '포인트 부족'}",
                emoji="✅" if can_afford else "❌",
            ))
        if not options:
            options = [discord.SelectOption(label="(구매 가능한 역할 없음)", value="__none__")]
        super().__init__(placeholder="구매할 역할을 선택하세요", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__none__":
            await interaction.response.send_message("구매 가능한 역할이 없어요.", ephemeral=True)
            return

        role_id   = int(self.values[0])
        shop_item = await db.get_shop_role(interaction.guild.id, role_id)
        if not shop_item:
            await interaction.response.send_message("해당 역할이 상점에서 제거되었어요.", ephemeral=True)
            return

        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message("역할을 찾을 수 없어요.", ephemeral=True)
            return

        if any(r.id == role_id for r in interaction.user.roles):
            await interaction.response.send_message(
                f"이미 **{role.name}** 역할을 보유하고 있어요.", ephemeral=True
            )
            return

        # 포인트 원자적 차감
        success = await db.spend_user_points(
            interaction.guild.id, interaction.user.id, shop_item["cost"]
        )
        if not success:
            current = await db.get_user_points(interaction.guild.id, interaction.user.id)
            await interaction.response.send_message(
                f"포인트가 부족해요!\n"
                f"현재: **{current:,}** 포인트  /  필요: **{shop_item['cost']:,}** 포인트",
                ephemeral=True,
            )
            return

        # 역할 지급
        try:
            await interaction.user.add_roles(role, reason="포인트 상점 구매")
        except discord.Forbidden:
            # 포인트 환불
            await db.add_user_points(
                interaction.guild.id, interaction.user.id, shop_item["cost"]
            )
            await interaction.response.send_message(
                "역할 지급에 실패했어요 (봇 권한 부족).\n포인트는 자동으로 환불되었어요.",
                ephemeral=True,
            )
            return

        remaining = await db.get_user_points(interaction.guild.id, interaction.user.id)
        embed = discord.Embed(
            title="✅ 구매 완료!",
            description=f"{role.mention} 역할을 획득했어요!",
            color=0x57F287,
        )
        embed.add_field(name="사용한 포인트", value=f"{shop_item['cost']:,}", inline=True)
        embed.add_field(name="남은 포인트",   value=f"{remaining:,}",         inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════════════════════════
#  관리자 설정 Views & Modals
# ═══════════════════════════════════════════════════════════════

class SetPointsPer10MinModal(ui.Modal, title="10분당 포인트 설정"):
    p10m_input = ui.TextInput(
        label="음성채널 10분당 지급 포인트",
        placeholder="예: 2  (0이면 포인트 지급 안 함)",
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            p10m = int(str(self.p10m_input).strip())
            if p10m < 0 or p10m > 10_000:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "0~10,000 사이의 정수를 입력해주세요.", ephemeral=True
            )
            return
        await db.set_points_per_10min(interaction.guild.id, p10m)
        state = f"**{p10m}** 포인트" if p10m > 0 else "**0** (지급 비활성화)"
        await interaction.response.send_message(
            f"10분당 포인트를 {state}(으)로 설정했어요.\n"
            f"음성채널 10분 이용 시 {p10m} 포인트가 적립돼요.",
            ephemeral=True,
        )


class AddShopRoleView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(AddShopRoleSelect())


class AddShopRoleSelect(ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="상점에 추가할 역할을 선택하세요")

    async def callback(self, interaction: discord.Interaction):
        role     = self.values[0]
        existing = await db.get_shop_role(interaction.guild.id, role.id)
        if existing:
            await interaction.response.send_message(
                f"**{role.name}**은 이미 **{existing['cost']:,}** 포인트에 등록되어 있어요.\n"
                "가격을 바꾸려면 '역할 제거' 후 다시 추가해주세요.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(AddShopRolePriceModal(role.id, role.name))


class AddShopRolePriceModal(ui.Modal):
    price_input = ui.TextInput(
        label="구매에 필요한 포인트",
        placeholder="예: 500",
        max_length=7,
    )

    def __init__(self, role_id: int, role_name: str):
        # Modal title 최대 45자
        super().__init__(title=f"가격 설정: {role_name[:38]}")
        self.role_id = role_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cost = int(str(self.price_input).strip())
            if cost <= 0 or cost > 1_000_000:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "1~1,000,000 사이의 양의 정수를 입력해주세요.", ephemeral=True
            )
            return

        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("역할을 찾을 수 없어요.", ephemeral=True)
            return

        await db.add_shop_role(interaction.guild.id, self.role_id, cost, role.name)
        await interaction.response.send_message(
            f"✅ {role.mention}을 **{cost:,}** 포인트에 상점에 추가했어요!",
            ephemeral=True,
        )


class ExcludedChannelView(ui.View):
    """잠수채널 설정 View (채널 선택 + 해제 버튼)."""
    def __init__(self, current_excluded_id: int | None):
        super().__init__(timeout=60)
        self.add_item(ExcludedChannelSelect())
        if current_excluded_id:
            self.add_item(ClearExcludedChannelButton())


class ExcludedChannelSelect(ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="포인트 제외할 잠수채널 선택",
            channel_types=[discord.ChannelType.voice],
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        await db.set_points_excluded_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"✅ {channel.mention}을 잠수채널로 설정했어요.\n"
            "이 채널에 있는 동안은 포인트가 지급되지 않아요.",
            ephemeral=True,
        )


class ClearExcludedChannelButton(ui.Button):
    def __init__(self):
        super().__init__(label="잠수채널 해제", emoji="✖️", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        await db.set_points_excluded_channel(interaction.guild.id, None)
        await interaction.response.send_message(
            "잠수채널 설정을 해제했어요.\n"
            "(Discord AFK 채널은 항상 자동으로 제외돼요)",
            ephemeral=True,
        )


class RemoveShopRoleView(ui.View):
    def __init__(self, items: list, guild: discord.Guild):
        super().__init__(timeout=60)
        self.add_item(RemoveShopRoleSelect(items, guild))


class RemoveShopRoleSelect(ui.Select):
    def __init__(self, items: list, guild: discord.Guild):
        options = []
        for item in items[:25]:
            role = guild.get_role(item["role_id"])
            name = (role.name if role else f"삭제된 역할 #{item['role_id']}")[:100]
            options.append(discord.SelectOption(
                label=name,
                value=str(item["role_id"]),
                description=f"{item['cost']:,} 포인트",
                emoji="🗑️",
            ))
        super().__init__(placeholder="제거할 역할을 선택하세요", options=options)

    async def callback(self, interaction: discord.Interaction):
        role_id = int(self.values[0])
        await db.remove_shop_role(interaction.guild.id, role_id)
        role    = interaction.guild.get_role(role_id)
        mention = role.mention if role else f"역할 `{role_id}`"
        await interaction.response.send_message(
            f"✅ {mention}을 상점에서 제거했어요.", ephemeral=True
        )


# ═══════════════════════════════════════════════════════════════
#  패널 임베드 빌더
# ═══════════════════════════════════════════════════════════════

def build_shop_user_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🛒 포인트 상점",
        description=(
            "음성채널에서 활동하면 포인트가 자동으로 쌓여요.\n"
            "모은 포인트로 서버의 특별한 역할을 구매해보세요!\n\n"
            "**💰 내 포인트** — 현재 잔액과 적립 비율 확인\n"
            "**🛒 역할 구매** — 판매 중인 역할 목록 조회 및 구매"
        ),
        color=0xF1C40F,
    )
    embed.set_footer(text="음성채널에 있는 시간이 길수록 더 많은 포인트가 쌓여요")
    return embed


def build_shop_admin_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ 포인트 상점 설정",
        description=(
            "음성채널 포인트 시스템과 역할 상점을 관리해요.\n\n"
            "**🪙 10분당 포인트** — 음성채널 10분당 지급 포인트 비율 설정\n"
            "**➕ 역할 추가** — 판매할 역할과 가격 등록\n"
            "**🗑️ 역할 제거** — 상점에서 역할 삭제\n"
            "**📋 현황 보기** — 현재 설정 및 등록 역할 전체 조회\n"
            "**🔇 잠수채널 설정** — 포인트가 지급되지 않을 채널 지정"
        ),
        color=0x5865F2,
    )
    embed.set_footer(text="5분 미만 세션 포인트 미지급 · Discord AFK 채널 자동 제외")
    return embed


# ═══════════════════════════════════════════════════════════════
#  Cog & 슬래시 명령어
# ═══════════════════════════════════════════════════════════════

class PointShop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="포인트상점",
        description="포인트 상점 패널을 이 채널에 설치합니다",
    )
    async def setup_shop_panel(self, interaction: discord.Interaction):
        if not await can_manage_panel(interaction):
            await interaction.response.send_message(
                "이 명령어는 서버 관리자 또는 지정된 패널 관리 역할만 쓸 수 있어요.",
                ephemeral=True,
            )
            return

        perms = interaction.channel.permissions_for(interaction.guild.me)
        missing = []
        if not perms.send_messages:
            missing.append("메시지 보내기")
        if not perms.embed_links:
            missing.append("임베드 링크")
        if missing:
            await interaction.response.send_message(
                f"봇에게 다음 권한이 필요해요: {', '.join(missing)}", ephemeral=True
            )
            return

        await interaction.channel.send(
            embed=build_shop_user_panel_embed(),
            view=ShopUserPanelView(),
        )
        await interaction.response.send_message("🛒 포인트 상점 패널을 설치했어요!", ephemeral=True)

    @app_commands.command(
        name="포인트상점설정",
        description="포인트 상점 관리자 패널을 이 채널에 설치합니다 (관리자 전용)",
    )
    async def setup_shop_admin_panel(self, interaction: discord.Interaction):
        if not await ensure_manage_guild(interaction, "이 명령어는 서버 관리자만 사용할 수 있어요."):
            return

        perms = interaction.channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message(
                "이 채널에 패널을 설치할 권한이 없어요.\n"
                "봇에게 **메시지 보내기** · **임베드 링크** 권한이 필요해요.",
                ephemeral=True,
            )
            return

        await interaction.channel.send(
            embed=build_shop_admin_panel_embed(),
            view=ShopAdminPanelView(),
        )
        await interaction.response.send_message(
            "🛠️ 포인트 상점 설정 패널을 설치했어요!\n"
            "이 채널은 관리자만 볼 수 있게 권한을 설정하는 것을 권장해요.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PointShop(bot))
