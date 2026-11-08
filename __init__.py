"""Wake: scheduled notes and cron output wake the agent in your chat; it messages you in its own voice,
or stays silent when nothing matters.

Public Hermes surfaces only:
- ctx.inject_message(session_key=...)   delivery into the bound chat (needs allow_gateway_injection)
- ctx.register_platform("wake_agent")   cron target; its connect() starts the delivery loop in the gateway
- pre_llm_call / on_session_end hooks   wait for an idle chat; hand compact wakes their instructions
- /wakes, the `wake` tool, `hermes wake` setup and scheduling for the user, the agent and scripts
- skill wake:setup                      agent-led setup walkthrough
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import engine

log = logging.getLogger("plugins.wake")
HERE = Path(__file__).resolve().parent
_CTX: Any = None
_TASK: Optional[asyncio.Task] = None


# --- state helpers -----------------------------------------------------------------------------------
def store(ctx: Any = None) -> engine.Store:
    return engine.Store((ctx or _CTX).state.data_dir)


def conf(ctx: Any = None) -> dict:
    return engine.settings((ctx or _CTX).get_config)


def _session_env(name: str) -> str:
    """The calling session's identity (documented: gateway.session_context.get_session_env)."""
    try:
        from gateway.session_context import get_session_env
        return get_session_env(name) or ""
    except Exception:
        return ""


def _migrate_legacy(ctx: Any) -> None:
    """Move a 0.x queue ($HERMES_HOME/state/wake/queue.json) into the plugin data dir, once."""
    try:
        data_dir = Path(ctx.state.data_dir)
        legacy = data_dir.parent.parent / "state" / "wake" / "queue.json"
        if not legacy.exists():
            return
        items = json.loads(legacy.read_text() or "[]")
        for i in items:
            i.setdefault("kind", "legacy")
        engine.Store(data_dir).locked("queue.json", lambda q: (None, q + items), [])
        legacy.rename(legacy.with_name("queue.json.migrated"))
        log.info("wake: moved %d queued wake(s) from the 0.x state dir", len(items))
    except Exception:
        log.warning("wake: could not migrate the 0.x queue", exc_info=True)


# --- pre-check: skip a wake before it reaches a chat that would draw it ------------------------------
PRECHECK_INSTRUCTIONS = (
    "wake precheck. An assistant scheduled the wake below for {user}. Decide if it should interrupt "
    "{user} now. Answer notify=true unless the content clearly has nothing {user} would want to hear "
    "(an all-clear or empty report, nothing new, a condition that is not met). Reminders {user} asked "
    "for, anything needing action, and anything you are unsure about: notify=true.")
PRECHECK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["notify", "reason"],
                   "properties": {"notify": {"type": "boolean"}, "reason": {"type": "string"}}}


def precheck(prompt: str) -> Optional[tuple]:
    """One structured call on the user's active model (ctx.llm, no overrides). None = can't tell."""
    try:
        r = _CTX.llm.complete_structured(
            instructions=PRECHECK_INSTRUCTIONS.format(user=conf()["user_name"]),
            input=[{"type": "text", "text": prompt[:8000]}], json_schema=PRECHECK_SCHEMA,
            purpose="wake.precheck", temperature=0.0, max_tokens=120)
        p = getattr(r, "parsed", None)
        if isinstance(p, dict) and isinstance(p.get("notify"), bool):
            return p["notify"], str(p.get("reason") or "")[:200]
    except Exception:
        log.warning("wake: precheck failed; the agent decides instead", exc_info=True)
    return None


# --- delivery loop (runs in the gateway: started by the wake_agent adapter's connect) ------------------
async def _loop(ctx: Any) -> None:
    s = store(ctx)

    def inject(text: str, session_key: str) -> bool:
        return ctx.inject_message(text, session_key=session_key)

    last = None
    while True:
        try:
            res = await asyncio.to_thread(engine.tick, s, conf(ctx), inject, None, precheck)
            if res and res.startswith(("delivered", "retry", "skipped")):
                log.info("wake: %s", res)
            elif res == "no-target" and last != res and s.next_due() is not None:
                log.warning("wake: a wake is due but no chat is bound; run /wakes here in the chat that should get it")
            last = res
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("wake: tick failed", exc_info=True)
        await asyncio.sleep(5)


def start_loop() -> None:
    global _TASK
    if _CTX is None or (_TASK is not None and not _TASK.done()):
        return
    _migrate_legacy(_CTX)
    _TASK = _CTX.spawn_task(_loop(_CTX), name="plugin:wake:delivery")
    log.info("wake: delivery loop started")


def stop_loop() -> None:
    global _TASK
    if _TASK is not None and not _TASK.done():
        _TASK.cancel()
    _TASK = None


# --- hooks -------------------------------------------------------------------------------------------
def _is_target(t: Optional[dict], key: str, sid: str) -> bool:
    return bool(t) and ((key and key == t.get("session_key")) or (sid and sid == t.get("session_id")))


def on_pre_llm_call(session_id: str = "", user_message: Any = None, **_: Any) -> Optional[dict]:
    try:
        s = store()
        key = _session_env("HERMES_SESSION_KEY")
        if _is_target(s.target(), key, session_id):
            s.turn_started(key, session_id)
        context = s.pop_context(user_message)
        return {"context": context} if context else None
    except Exception:
        log.warning("wake: pre_llm_call failed", exc_info=True)
        return None


def on_session_end(session_id: str = "", **_: Any) -> None:
    try:
        s = store()
        key = _session_env("HERMES_SESSION_KEY")
        if _is_target(s.target(), key, session_id):
            s.turn_ended(key, session_id)
    except Exception:
        log.warning("wake: on_session_end failed", exc_info=True)


# --- shared commands (slash command, tool, CLI) -------------------------------------------------------
def _fmt_time(ts: float) -> str:
    return f"{datetime.fromtimestamp(ts, engine.tz(conf()['timezone'])):%a %d %b %H:%M}"


def describe_target(t: Optional[dict]) -> str:
    if not t:
        return "no chat bound yet (run /wakes here in the chat that should get wakes)"
    where = t.get("label") or t.get("platform") or "chat"
    return f"{where} ({t['session_key']})"


def status_text() -> str:
    s = store()
    q = s.queue()
    lines = [f"Wakes go to: {describe_target(s.target())}", f"Queued: {len(q)}"]
    for i in q[:10]:
        err = f"  [retrying: {i['last_error']}]" if i.get("last_error") else ""
        lines.append(f"  {i['id']}  {_fmt_time(i['at'])}  {i['title']}{err}")
    return "\n".join(lines)


def schedule(when: str, note: str, title: str = "", kind: str = "note") -> dict:
    zone = engine.tz(conf()["timezone"])
    at = engine.parse_when(when or "now", zone)
    item = store().add(note, title, at=at.timestamp(), kind=kind)
    return {"id": item["id"], "at": f"{at:%a %d %b %H:%M %Z}".strip(), "title": item["title"]}


TEST_NOTE = ("This is a test wake from the wake plugin, sent during setup. Tell the user in one short line "
             "that wakes reach this chat, and that a wake with nothing worth saying ends silently.")


def bind_here(session_key: str, platform: str, session_id: str, label: str = "") -> str:
    t = store().bind(session_key, platform, session_id, label)
    return (f"Wakes will arrive in this chat: {describe_target(t)}.\n"
            "If they never show up, set plugins.entries.wake.allow_gateway_injection: true in config.yaml "
            "(`hermes config set plugins.entries.wake.allow_gateway_injection true`). Try `/wakes test`.")


SLASH_HELP = ("/wakes here            send wakes to this chat\n"
              "/wakes test            send a test wake to the bound chat now\n"
              "/wakes add <when> <note>   when: now, +30m, +2h, +1d, 18:00, 'YYYY-MM-DD HH:MM'\n"
              "/wakes list | status   show the bound chat and queued wakes\n"
              "/wakes cancel <id>     drop a queued wake\n"
              "/wakes off             stop delivering (wakes stay queued)")


def on_slash(raw_args: str, *, session_id: str = "", session_key: str = "", platform: str = "",
             source: Any = None) -> str:
    try:
        args = shlex.split(raw_args or "")
    except ValueError:
        args = (raw_args or "").split()
    cmd = args[0].lower() if args else "status"
    try:
        if cmd == "here":
            label = getattr(source, "chat_name", "") or ("Bot Chat" if platform in engine.COMPACT_PLATFORMS else platform)
            return bind_here(session_key, platform, session_id, label)
        if cmd == "off":
            store().unbind()
            return "Wake delivery is off. Queued wakes wait until you run /wakes here again."
        if cmd == "test":
            if store().target() is None:
                bind_here(session_key, platform, session_id)
            item = store().add(TEST_NOTE, "Test wake", kind="test")
            return f"Test wake {item['id']} queued; it should arrive within a few seconds."
        if cmd == "add" and len(args) >= 3:
            r = schedule(args[1], " ".join(args[2:]))
            return f"Wake {r['id']} at {r['at']}: {r['title']}"
        if cmd == "cancel" and len(args) == 2:
            return "Cancelled." if store().cancel(args[1]) else "No such wake."
        if cmd in ("status", "list"):
            return status_text()
        return SLASH_HELP
    except ValueError as exc:
        return f"wake: {exc}"


WAKE_TOOL_SCHEMA = {
    "name": "wake",
    "description": (
        "Schedule a note to yourself that wakes you in the user's chat later, and manage where wakes go. "
        "When a wake arrives you message the user in your own voice, or reply exactly [SILENT] if it no "
        "longer matters. Cron jobs reach you the same way with deliver=wake_agent. "
        "Actions: schedule (when + note), list, cancel (id), bind_here (send wakes to the current chat), "
        "configure (user_name, timezone), test (send a test wake now), status. "
        "First-time setup or wakes not arriving: load skill wake:setup and follow it."),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["schedule", "list", "cancel", "bind_here", "configure", "test", "status"]},
            "when": {"type": "string", "description": "now, +30m, +2h, +1d, HH:MM (next one) or 'YYYY-MM-DD HH:MM' in the configured timezone"},
            "note": {"type": "string", "description": "What future-you should do or tell the user. Self-contained."},
            "title": {"type": "string", "description": "Short label for listings (optional)."},
            "id": {"type": "string", "description": "Wake id for cancel."},
            "user_name": {"type": "string", "description": "configure: the user's name, used in wake prompts."},
            "timezone": {"type": "string", "description": "configure: IANA timezone, e.g. Europe/London."},
        },
        "required": ["action"],
    },
}


def on_tool(args: dict, session_id: str = "", **_: Any) -> str:
    try:
        a = args or {}
        action = a.get("action") or "status"
        key, plat = _session_env("HERMES_SESSION_KEY"), _session_env("HERMES_SESSION_PLATFORM")
        sid = session_id or _session_env("HERMES_SESSION_ID")
        if action == "bind_here":
            return json.dumps({"ok": True, "message": bind_here(key, plat, sid)})
        if action == "configure":
            changed = {}
            if a.get("timezone"):
                engine.tz(a["timezone"])  # raises on a bad name
                _CTX.set_config("timezone", a["timezone"]); changed["timezone"] = a["timezone"]
            if a.get("user_name"):
                _CTX.set_config("user_name", a["user_name"]); changed["user_name"] = a["user_name"]
            return json.dumps({"ok": True, "changed": changed, "settings": conf()})
        if action in ("schedule", "test"):
            auto_bound = False
            if store().target() is None and key:
                store().bind(key, plat, sid); auto_bound = True  # zero config: wakes come back here
            if action == "test":
                r = schedule("now", TEST_NOTE, "Test wake", kind="test")
            else:
                if not (a.get("note") or "").strip():
                    return json.dumps({"ok": False, "error": "note is required"})
                r = schedule(a.get("when") or "now", a["note"], a.get("title") or "")
            return json.dumps({"ok": True, **r, "target": describe_target(store().target()),
                               **({"auto_bound_to_this_chat": True} if auto_bound else {})})
        if action == "cancel":
            return json.dumps({"ok": store().cancel(a.get("id") or "")})
        if action in ("list", "status"):
            s = store()
            return json.dumps({"ok": True, "target": s.target(), "settings": conf(), "queue": [
                {k: i.get(k) for k in ("id", "title", "kind", "last_error")} | {"at": _fmt_time(i["at"])}
                for i in s.queue()]})
        return json.dumps({"ok": False, "error": f"unknown action {action!r}"})
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


# --- `hermes wake` CLI -------------------------------------------------------------------------------
def _cli_setup(p: Any) -> None:
    sub = p.add_subparsers(dest="wake_cmd")
    a = sub.add_parser("add", help="queue a wake: hermes wake add 18:00 'call the dentist'")
    a.add_argument("when"); a.add_argument("note", nargs="+"); a.add_argument("--title", default="")
    n = sub.add_parser("now", help="wake the agent as soon as the chat is free")
    n.add_argument("note", nargs="+"); n.add_argument("--title", default="")
    sub.add_parser("list", help="show the bound chat and queued wakes")
    c = sub.add_parser("cancel", help="drop a queued wake"); c.add_argument("id")
    sub.add_parser("test", help="send a test wake to the bound chat")
    b = sub.add_parser("bind", help="advanced: bind a chat by session key (normally use /wakes here)")
    b.add_argument("session_key"); b.add_argument("--platform", default="")
    sub.add_parser("unbind", help="stop delivering (wakes stay queued)")


def _cli(ns: Any) -> int:
    cmd = getattr(ns, "wake_cmd", None) or "list"
    try:
        if cmd in ("add", "now"):
            r = schedule("now" if cmd == "now" else ns.when, " ".join(ns.note), ns.title)
            print(f"wake {r['id']} at {r['at']}: {r['title']}")
        elif cmd == "cancel":
            print("cancelled" if store().cancel(ns.id) else "no such wake")
        elif cmd == "test":
            print("test wake", store().add(TEST_NOTE, "Test wake", kind="test")["id"], "queued")
        elif cmd == "bind":
            print(bind_here(ns.session_key, ns.platform, ""))
        elif cmd == "unbind":
            store().unbind(); print("unbound")
        else:
            print(status_text())
        return 0
    except ValueError as exc:
        print(f"wake: {exc}")
        return 2


# --- registration ------------------------------------------------------------------------------------
def register(ctx: Any) -> None:
    global _CTX
    _CTX = ctx
    from . import cron_target
    cron_target.register(ctx, start_loop, stop_loop, lambda text: from_delivery_text(text))
    ctx.register_tool(name="wake", toolset="wake", schema=WAKE_TOOL_SCHEMA, handler=on_tool,
                      description="Schedule wakes into the user's chat", emoji="⏰")
    ctx.register_command("wakes", handler=on_slash, description="Wakes: bind this chat, test, list, schedule",
                         args_hint="here | test | add <when> <note> | list | cancel <id> | off")
    ctx.register_cli_command("wake", help="Queue and inspect wakes for the agent", setup_fn=_cli_setup,
                             handler_fn=_cli, description="Queue notes that wake the agent in your chat")
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("on_session_end", on_session_end)
    skill = HERE / "skills" / "setup" / "SKILL.md"
    if skill.exists():
        ctx.register_skill("setup", skill)
    ctx.on_unload(stop_loop)


def from_delivery_text(text: str) -> str:
    item = engine.from_delivery(store(), text, conf())
    return item["id"] if item else "silent"
