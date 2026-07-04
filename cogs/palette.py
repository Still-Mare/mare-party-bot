"""
임베드 색상 팔레트 (의미 기반).

cog마다 hex 리터럴로 흩어져 있던 임베드 색상을 한 곳으로 모은다.
색은 장식이 아니라 의미로 쓴다 — 새 임베드를 만들 때 아래 의미에 맞춰 고를 것.

- INFO:    안내·일반 패널 (Discord blurple)
- SUCCESS: 진행 중·완료·입장 등 긍정 상태
- NEUTRAL: 마감·아카이브 등 비활성 상태
- DANGER:  차단·퇴장·관리자 위험 조작
- WARNING: 경고·검토·승인 대기
- GOLD:    포인트·경제 (상점)
"""

INFO = 0x5865F2
SUCCESS = 0x248046
NEUTRAL = 0x4E5058
DANGER = 0xED4245
WARNING = 0xBA7517
GOLD = 0xF1C40F
