"""'Wake Agent' cron delivery target (deliver=wake_agent): a job's output becomes a wake.

The gateway connects this adapter only in the live gateway process, so connect() is also where the
delivery loop starts, and disconnect() where it stops."""
from __future__ import annotations

from typing import Any, Callable

from gateway.config import Platform
from gateway.platforms.base import BasePlatformAdapter, SendResult

NAME = "wake_agent"  # the cron "Send to" label derives from this: "Wake Agent"


def register(ctx: Any, on_connect: Callable[[], None], on_disconnect: Callable[[], None],
             queue: Callable[[str], str]) -> None:

    class WakeAgentAdapter(BasePlatformAdapter):
        def __init__(self, config, **kwargs):
            super().__init__(config=config, platform=Platform(NAME))

        async def connect(self, *, is_reconnect=False):
            self._running = True
            on_connect()
            return True

        async def disconnect(self):
            self._running = False
            on_disconnect()

        async def send(self, chat_id, content, reply_to=None, metadata=None):
            try:
                return SendResult(success=True, message_id="wake:" + queue(content or ""))
            except Exception as exc:
                return SendResult(success=False, error=f"wake queue failed: {exc}")

        async def get_chat_info(self, chat_id):
            return {"name": "Wake Agent", "type": "dm"}

    async def standalone_send(pconfig, chat_id, message, *, thread_id=None, media_files=None,
                              force_document=False):
        """Cron worker processes (no live gateway adapter) land here; the gateway's loop delivers."""
        try:
            return {"success": True, "platform": NAME, "chat_id": chat_id, "message_id": "wake:" + queue(message or "")}
        except Exception as exc:
            return {"error": f"wake queue failed: {exc}"}

    ctx.register_platform(
        name=NAME, label="Wake Agent", adapter_factory=WakeAgentAdapter, check_fn=lambda: True,
        env_enablement_fn=lambda: {"home_channel": {"chat_id": "wake", "name": "Wake Agent"}},
        cron_deliver_env_var="WAKE_AGENT_HOME_CHANNEL", standalone_sender_fn=standalone_send,
        emoji="⏰", allow_update_command=False)
