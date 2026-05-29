"""
파티 모집 디스코드 봇 - 메인 엔트리.

실행: python bot.py
환경변수 DISCORD_TOKEN 에 봇 토큰이 있어야 한다.
"""

import os
import logging

import discord
from discord.ext import commands

import database as db
from cogs.control_panel import ControlPanelView, AdminPanelView
from cogs.recruitment import RecruitView
from cogs.game_roles import RoleToggleButton

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("party-bot")

TOKEN = os.environ.get("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True        # 멤버 정보 (역할 부여, 닉네임)
intents.voice_states = True   # 음성 상태 추적
intents.message_content = False  # 메시지 내용은 안 봐도 됨 (버튼 기반)


class PartyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await db.init_db()

        # Cog 로드
        await self.load_extension("cogs.control_panel")
        await self.load_extension("cogs.recruitment")
        await self.load_extension("cogs.game_roles")
        await self.load_extension("cogs.voice_stats")
        await self.load_extension("cogs.activity_review")
        await self.load_extension("cogs.verification")
        await self.load_extension("cogs.suggestions")
        await self.load_extension("cogs.leave_notices")

        # 영구 View 재등록 (봇 재시작 후에도 버튼이 동작하도록)
        self.add_view(ControlPanelView())
        self.add_view(AdminPanelView())
        from cogs.verification import VerifyView
        self.add_view(VerifyView())
        from cogs.suggestions import SuggestionAdminView
        self.add_view(SuggestionAdminView())

        # 기존 모집글 / 역할 버튼 복원
        await self._restore_persistent_views()

        # 슬래시 명령어 동기화
        await self.tree.sync()
        log.info("setup_hook 완료")

    async def _restore_persistent_views(self):
        """DB에 있는 열린 모집글의 버튼 View를 다시 등록한다."""
        recruit_ids = await db.list_open_recruit_ids()
        for recruit_id in recruit_ids:
            self.add_view(RecruitView(recruit_id))
        log.info(f"열린 모집글 {len(recruit_ids)}개 View 복원")

    async def on_ready(self):
        log.info(f"로그인됨: {self.user} (ID: {self.user.id})")
        log.info(f"서버 {len(self.guilds)}개에 연결됨")


def main():
    if not TOKEN:
        raise SystemExit("환경변수 DISCORD_TOKEN 이 설정되지 않았어요.")
    bot = PartyBot()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
