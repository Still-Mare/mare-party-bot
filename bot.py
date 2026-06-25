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
from cogs.point_shop import ShopUserPanelView, ShopAdminPanelView

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("party-bot")

TOKEN = os.environ.get("DISCORD_TOKEN")
# Railway 재배포마다 sync하면 일일 2회 글로벌 레이트 리밋에 걸릴 수 있다.
# 명령어 변경 시에만 SYNC_COMMANDS=true 환경변수를 설정하고 1회 배포 후 다시 false로.
SYNC_COMMANDS = os.environ.get("SYNC_COMMANDS", "false").lower() == "true"

intents = discord.Intents.default()
intents.members = True        # 멤버 정보 (역할 부여, 닉네임)
intents.voice_states = True   # 음성 상태 추적
intents.message_content = False  # 메시지 내용은 안 봐도 됨 (버튼 기반)


class PartyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await db.init_db()

        # 입장 경로 추적용 초대코드 사용횟수 캐시 (entry_tracking 이 채움)
        self.invite_cache = {}

        # Cog 로드
        await self.load_extension("cogs.control_panel")
        await self.load_extension("cogs.recruitment")
        await self.load_extension("cogs.game_roles")
        await self.load_extension("cogs.voice_stats")
        await self.load_extension("cogs.activity_review")
        await self.load_extension("cogs.verification")
        await self.load_extension("cogs.suggestions")
        await self.load_extension("cogs.leave_notices")
        await self.load_extension("cogs.point_shop")
        await self.load_extension("cogs.nicknames")       # 셀프 닉네임 변경
        await self.load_extension("cogs.blacklist")        # 블랙리스트 (on_member_join 차단)
        await self.load_extension("cogs.entry_tracking")   # 입장 경로 구분 + 오픈채팅 게이트 설정
        await self.load_extension("cogs.sticky")           # 스티키 공지

        # 영구 View 재등록 (봇 재시작 후에도 버튼이 동작하도록)
        from cogs.control_panel import (
            RecruitPanelView, RolesPanelView, ActivityPanelView,
        )
        self.add_view(RecruitPanelView())
        self.add_view(RolesPanelView())
        self.add_view(ActivityPanelView())
        self.add_view(ControlPanelView())  # 하위 호환 (기존 메시지가 있다면)
        self.add_view(AdminPanelView())
        self.add_view(ShopUserPanelView())
        self.add_view(ShopAdminPanelView())
        from cogs.verification import VerifyView
        self.add_view(VerifyView())
        from cogs.suggestions import SuggestionAdminView
        self.add_view(SuggestionAdminView())

        # 기존 모집글 / 역할 버튼 복원
        await self._restore_persistent_views()

        # 명령어 동기화는 on_ready에서 길드별로만 처리한다.
        # (글로벌 sync는 Discord 전파에 최대 1시간 + 길드 sync와 중복 시 두 개로 표시됨)
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

        if SYNC_COMMANDS:
            # 1. 현재 트리(글로벌 등록된 명령어)를 각 길드에 복사
            for guild in self.guilds:
                self.tree.copy_global_to(guild=guild)

            # 2. 글로벌 명령어 Discord에서 삭제 (이전 배포 잔여물 + 중복 방지)
            self.tree.clear_commands(guild=None)
            await self.tree.sync()

            # 3. 길드별 즉시 동기화 (구버전 "유저용"/"관리자용" 등 stale 명령어 교체)
            for guild in self.guilds:
                await self.tree.sync(guild=guild)

            log.info(f"길드별 슬래시 명령어 즉시 동기화 완료 ({len(self.guilds)}개 길드) — 글로벌 명령어 정리됨")

    async def close(self):
        """봇 종료 시 DB 커넥션 풀을 정리한다."""
        await db.close_db()
        await super().close()


def main():
    if not TOKEN:
        raise SystemExit("환경변수 DISCORD_TOKEN 이 설정되지 않았어요.")
    bot = PartyBot()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
