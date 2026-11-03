"""'Wake Agent' cron delivery target: deliver=wake_agent turns the job's output into a hidden wake."""
import importlib.util, uuid
from pathlib import Path
from gateway.config import Platform
from gateway.platforms.base import BasePlatformAdapter, SendResult

HERE = Path(__file__).resolve().parent
NAME = "wake_agent"  # dropdown label is derived from this: "Wake Agent"


def _engine():
    spec = importlib.util.spec_from_file_location("wake_engine_dl_" + uuid.uuid4().hex[:6], HERE / "engine.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def _queue(text):
    item = _engine().from_delivery(text or "")
    return item["id"] if item else "silent"


class WakeAgentAdapter(BasePlatformAdapter):
    def __init__(self, config, **kwargs):
        super().__init__(config=config, platform=Platform(NAME))

    async def connect(self, *, is_reconnect=False):
        self._running = True
        return True

    async def disconnect(self):
        self._running = False

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        try:
            return SendResult(success=True, message_id="wake:" + _queue(content))
        except Exception as exc:
            return SendResult(success=False, error=f"wake queue failed: {exc}")

    async def get_chat_info(self, chat_id):
        return {"name": "Wake Agent", "type": "dm"}


async def standalone_send(pconfig, chat_id, message, *, thread_id=None, media_files=None, force_document=False):
    """Cron worker processes (no live gateway adapter) land here."""
    try:
        return {"success": True, "platform": NAME, "chat_id": chat_id, "message_id": "wake:" + _queue(message)}
    except Exception as exc:
        return {"error": f"wake queue failed: {exc}"}


def register(ctx):
    ctx.register_platform(
        name=NAME, label="Wake Agent", adapter_factory=WakeAgentAdapter, check_fn=lambda: True,
        env_enablement_fn=lambda: {"home_channel": {"chat_id": "wake", "name": "Wake Agent"}},
        cron_deliver_env_var="WAKE_AGENT_HOME_CHANNEL", standalone_sender_fn=standalone_send,
        emoji="⏰", allow_update_command=False)
