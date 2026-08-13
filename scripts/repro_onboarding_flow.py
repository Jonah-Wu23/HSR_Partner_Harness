"""复现「跳过跳过→开始使用→回到创建第一个项目」的完整事件链路。

模拟前端 desktopStore 的序号逻辑（hydrate/applyEvents 的精简版），
按真实协议回放：bootstrap → account.register → account.onboarding_complete。
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand


def command(request_id: str, method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


class FrontendStore:
    """复刻 desktop/src/stores/desktopStore.ts 的序号与账号状态逻辑。"""

    def __init__(self) -> None:
        self.last_sequence = -1
        self.needs_bootstrap = False
        self.current_account = None
        self.onboarding_complete: bool | None = None

    def hydrate(self, snapshot: dict) -> None:
        seq = snapshot.get("sequence", -1)
        self.last_sequence = seq
        self.needs_bootstrap = False
        account = snapshot.get("current_account")
        self.current_account = account
        self.onboarding_complete = bool(account and account.get("onboarding_complete"))

    def apply_event(self, event: dict) -> None:
        seq = event["sequence"]
        if seq <= self.last_sequence:
            print(f"  [store] 丢弃事件 seq={seq}（<= lastSequence={self.last_sequence}）")
            return
        if self.last_sequence >= 0 and seq != self.last_sequence + 1:
            print(
                f"  [store] ★缺口★ seq={seq} != lastSequence+1={self.last_sequence + 1} "
                "→ 事件被丢弃，needsBootstrap=true"
            )
            self.last_sequence = seq
            self.needs_bootstrap = True
            return
        self.last_sequence = seq
        kind = event["event"]
        payload = event["payload"]
        if kind == "account.changed":
            account = payload.get("account")
            if account:
                self.current_account = account
                self.onboarding_complete = bool(account.get("onboarding_complete"))
        elif kind == "state.snapshot":
            self.hydrate(payload)

    def line(self) -> str:
        gate = "账号门(default)" if not self.current_account or self.current_account.get("username") == "default" else "无账号门"
        onboarding = (
            "引导中(onboarding_complete=false)"
            if self.current_account
            and self.current_account.get("username") != "default"
            and self.onboarding_complete is False
            else "不显示引导"
        )
        return (
            f"lastSequence={self.last_sequence} needsBootstrap={self.needs_bootstrap} "
            f"| {gate} | {onboarding}"
        )


async def main() -> None:
    events: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        service = build_demo_service(
            database=Path(tmp) / "data" / "pair_harness.db",
            project_root=Path(tmp),
            event_sink=events.append,
        )
        try:
            store = FrontendStore()
            consumed = 0

            def drain_events(tag: str) -> None:
                nonlocal consumed
                new_events = events[consumed:]
                consumed = len(events)
                print(f"--- 事件流（{tag}）：{[(e['event'], e['sequence']) for e in new_events]}")
                for e in new_events:
                    store.apply_event(e)
                print(f"    [store] {store.line()}")

            # 1. 启动 bootstrap（响应路径）
            print("== 1. app.bootstrap（启动，响应快照）==")
            snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
            store.hydrate(snapshot)
            print(f"    响应快照 sequence={snapshot['sequence']} → {store.line()}")

            # 2. 注册新账号（_switch_account → account.changed + state.snapshot 事件）
            print("== 2. account.register（注册新账号）==")
            resp = await service.handle_command(
                command(
                    "r-1",
                    "account.register",
                    username="alice",
                    display_name="Alice",
                    password="secret123",
                )
            )
            print(f"    响应 account.onboarding_complete={resp['account']['onboarding_complete']}")
            drain_events("注册后")

            # 3. 用户点「开始使用」
            print("== 3. account.onboarding_complete（点开始使用）==")
            resp = await service.handle_command(command("c-1", "account.onboarding_complete"))
            print(f"    响应 account.onboarding_complete={resp['account']['onboarding_complete']}")
            drain_events("完成引导后")

            # 4. 再 bootstrap 确认持久化
            print("== 4. app.bootstrap（确认持久化）==")
            snapshot = await service.handle_command(command("b-2", "app.bootstrap"))
            store.hydrate(snapshot)
            print(f"    响应快照 sequence={snapshot['sequence']} "
                  f"flag={snapshot['current_account']['onboarding_complete']} → {store.line()}")

            if store.needs_bootstrap:
                print("\n★ 结论：序号出现缺口 → 前端会重新 bootstrap → Onboarding 重挂载回 step 0")
            elif store.onboarding_complete is True:
                print("\n★ 结论：序号连续，flag=true → 前端应进入主页（无重挂载）")
            else:
                print("\n★ 结论：flag 未翻转")
        finally:
            await service.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
