"""Engine behaviour: due/late/busy/retry/ordering, the silent path, timezones, cron unwrapping."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_spec = importlib.util.spec_from_file_location("wake_engine", Path(__file__).resolve().parents[1] / "engine.py")
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

S = dict(engine.DEFAULTS, user_name="Sam")
T0 = 1_800_000_000.0
LOCAL = {"session_key": "agent:main:local:dm:bot", "platform": "local", "session_id": "ses_1"}
DISCORD = {"session_key": "agent:main:discord:dm:42", "platform": "discord", "session_id": "ses_2"}


class Inject:
    """Stands in for ctx.inject_message: records calls, answers from a script of results."""

    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, text, session_key):
        self.calls.append((text, session_key))
        r = self.results.pop(0) if self.results else True
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def store(tmp_path):
    return engine.Store(tmp_path)


def bound(store, target=LOCAL):
    store.bind(target["session_key"], target["platform"], target["session_id"])
    return store


# --- due / ordering -------------------------------------------------------------------------------
def test_nothing_due_until_its_time(store):
    bound(store).add("later", at=T0 + 60)
    inj = Inject()
    assert engine.tick(store, S, inj, now=T0) is None
    assert inj.calls == []
    assert engine.tick(store, S, inj, now=T0 + 61).startswith("delivered:")
    assert len(inj.calls) == 1 and store.queue() == []


def test_no_target_keeps_wakes_queued(store):
    store.add("hello", at=T0)
    assert engine.tick(store, S, Inject(), now=T0) == "no-target"
    assert len(store.queue()) == 1


def test_delivers_one_per_tick_in_time_order(store):
    bound(store)
    b = store.add("second", at=T0 + 2)
    a = store.add("first", at=T0 + 1)
    inj = Inject()
    assert engine.tick(store, S, inj, now=T0 + 10) == "delivered:" + a["id"]
    store.turn_ended(LOCAL["session_key"], LOCAL["session_id"])  # the wake's turn ran
    assert engine.tick(store, S, inj, now=T0 + 11) == "delivered:" + b["id"]
    assert [c[0] for c in inj.calls] == ["⏰ first", "⏰ second"]


def test_done_log_records_delivery(store, tmp_path):
    bound(store).add("x", at=T0)
    engine.tick(store, S, Inject(), now=T0)
    rec = json.loads((tmp_path / "done.jsonl").read_text().splitlines()[0])
    assert rec["note"] == "x" and rec["delivered"] == T0


# --- busy: wait for idle, no attempt counted -------------------------------------------------------
def test_busy_chat_holds_wake_without_counting_an_attempt(store):
    bound(store).add("ping", at=T0)
    store.turn_started(LOCAL["session_key"], LOCAL["session_id"], now=T0)
    inj = Inject()
    assert engine.tick(store, S, inj, now=T0 + 1) == "busy"
    assert inj.calls == [] and "attempts" not in store.queue()[0]
    store.turn_ended(LOCAL["session_key"], LOCAL["session_id"])
    assert engine.tick(store, S, inj, now=T0 + 2).startswith("delivered:")


def test_busy_matches_by_session_id_too(store):
    bound(store).add("ping", at=T0)
    store.turn_started("", LOCAL["session_id"], now=T0)
    assert engine.tick(store, S, Inject(), now=T0 + 1) == "busy"


def test_other_chats_turns_do_not_block(store):
    bound(store).add("ping", at=T0)
    store.turn_started("agent:main:local:dm:other", "ses_other", now=T0)
    assert engine.tick(store, S, Inject(), now=T0 + 1).startswith("delivered:")


def test_stale_busy_mark_expires(store):
    bound(store).add("ping", at=T0)
    store.turn_started(LOCAL["session_key"], LOCAL["session_id"], now=T0)
    assert engine.tick(store, S, Inject(), now=T0 + engine.BUSY_TTL + 1).startswith("delivered:")


def test_accepted_wake_holds_the_next_until_its_turn_runs_or_grace_passes(store):
    bound(store)
    store.add("one", at=T0)
    store.add("two", at=T0)
    inj = Inject()
    engine.tick(store, S, inj, now=T0)
    assert engine.tick(store, S, inj, now=T0 + 5) == "busy"
    assert engine.tick(store, S, inj, now=T0 + engine.INJECTED_GRACE + 1).startswith("delivered:")


# --- retry -------------------------------------------------------------------------------------------
def test_refusal_backs_off_and_holds_later_wakes(store):
    bound(store)
    a = store.add("first", at=T0)
    store.add("second", at=T0 + 1)
    inj = Inject(False)
    assert engine.tick(store, S, inj, now=T0 + 2) == "retry:" + a["id"]
    head = store.queue()[0]
    assert head["attempts"] == 1 and head["retry_at"] == T0 + 2 + 15
    assert "allow_gateway_injection" in head["last_error"]
    assert engine.tick(store, S, inj, now=T0 + 3) is None  # head waiting; second must not overtake
    assert len(inj.calls) == 1
    assert engine.tick(store, S, inj, now=T0 + 18) == "delivered:" + a["id"]


def test_backoff_grows_and_caps(store):
    bound(store).add("x", at=T0)
    now = T0
    for _ in range(30):
        engine.tick(store, S, Inject(False), now=now)
        now = store.queue()[0]["retry_at"]
    assert store.queue()[0]["retry_at"] - now <= 300


def test_inject_exception_is_a_retry_not_a_crash(store):
    bound(store).add("x", at=T0)
    assert engine.tick(store, S, Inject(RuntimeError("boom")), now=T0).startswith("retry:")
    assert "RuntimeError: boom" in store.queue()[0]["last_error"]


def test_failed_compact_wake_leaves_no_pending_context(store):
    bound(store).add("x", at=T0)
    engine.tick(store, S, Inject(False), now=T0)
    assert store.read("pending.json", []) == []


# --- rendering: compact on drawn surfaces, full prompt on messaging ----------------------------------
def test_local_chat_gets_short_line_and_hook_context(store):
    bound(store).add("call the dentist", title="Dentist", at=T0)
    inj = Inject()
    engine.tick(store, S, inj, now=T0)
    assert inj.calls == [("⏰ Dentist", LOCAL["session_key"])]
    ctx = store.pop_context("⏰ Dentist")
    assert "call the dentist" in ctx and "Sam" in ctx and "[SILENT]" in ctx
    assert store.pop_context("⏰ Dentist") is None  # used once


def test_pending_context_matches_message_with_extra_text(store):
    store.push_context("⏰ Dentist", "CTX", "id1", now=T0)
    assert store.pop_context("[Sat 10:00] ⏰ Dentist") == "CTX"


def test_ordinary_messages_never_pick_up_wake_context(store):
    store.push_context("⏰ Dentist", "CTX", "id1", now=T0)
    assert store.pop_context("what about the dentist?") is None
    assert store.pop_context(None) is None


def test_messaging_chat_gets_full_prompt_inline(store):
    bound(store, DISCORD).add("call the dentist", title="Dentist", at=T0)
    inj = Inject()
    engine.tick(store, S, inj, now=T0)
    text, key = inj.calls[0]
    assert key == DISCORD["session_key"] and "call the dentist" in text and "[SILENT]" in text
    assert store.read("pending.json", []) == []


def test_late_wake_says_how_late(store):
    item = store.add("x", at=T0)
    text, ctx = engine.render(item, S, compact=False, now=T0 + 25 * 60)
    assert "Delivered 25 min late" in text
    _, ctx = engine.render(item, S, compact=True, now=T0 + 5 * 60)
    assert "late" not in ctx


def test_prompt_overrides(store):
    item = store.add("x", at=T0)
    text, _ = engine.render(item, dict(S, wake_prompt="NOTE={note} FOR={user}"), compact=False, now=T0)
    assert text == "NOTE=x FOR=Sam"


# --- cron delivery (deliver=wake_agent) --------------------------------------------------------------
FRAME = ("Cronjob Response: Inbox sweep\n(job_id: abc123)\n-------------\n\n{body}\n\n"
         "To stop or manage this job, send me a new message (e.g. \"stop reminder Inbox sweep\").")


def test_cron_frame_is_unwrapped_into_a_cron_wake(store):
    item = engine.from_delivery(store, FRAME.format(body="2 new invoices"), S)
    assert item["title"] == "Inbox sweep" and item["kind"] == "cron"
    text, _ = engine.render(item, S, compact=False, now=item["at"])
    assert "Scheduled job 'Inbox sweep'" in text and "2 new invoices" in text and "To stop" not in text


@pytest.mark.parametrize("body", ["[SILENT]", "SILENT", "  [silent]. ", "NO_REPLY", ""])
def test_silent_cron_runs_queue_nothing(store, body):
    assert engine.from_delivery(store, FRAME.format(body=body), S) is None
    assert store.queue() == []


def test_gateway_drain_runs_queue_nothing(store):
    assert engine.from_delivery(store, "Gateway draining: restart in progress", S) is None


def test_hermes_failure_frame_becomes_a_failure_wake(store):
    item = engine.from_delivery(store, FRAME.format(body="⚠️ Cron 'Inbox sweep' failed: timeout. Retry later."), S)
    assert item["kind"] == "cron_failed" and item["title"].startswith("⚠️")
    assert "FAILED" in item["note"]


def test_report_mentioning_failed_is_not_a_job_failure(store):
    item = engine.from_delivery(store, FRAME.format(body="Your payment failed: card expired."), S)
    assert item["kind"] == "cron"


def test_unframed_output_still_queues(store):
    item = engine.from_delivery(store, "raw output", S)
    assert item["title"] == "cron job" and "raw output" in item["note"]


def test_legacy_cron_items_render_as_is(store):
    item = {"id": "x", "at": T0, "note": "Scheduled job 'a' just ran.", "title": "a", "kind": "legacy"}
    text, _ = engine.render(item, S, compact=False, now=T0)
    assert text == "Scheduled job 'a' just ran."


# --- target binding ----------------------------------------------------------------------------------
def test_bind_requires_a_session_key(store):
    with pytest.raises(ValueError):
        store.bind("", "local")


def test_unbind(store):
    bound(store).unbind()
    assert store.target() is None


def test_cancel(store):
    a = store.add("x", at=T0)
    assert store.cancel(a["id"]) and not store.cancel(a["id"])


def test_empty_note_refused(store):
    with pytest.raises(ValueError):
        store.add("   ")


def test_corrupt_state_file_falls_back_to_default(store, tmp_path):
    (tmp_path / "queue.json").write_text("{not json")
    assert store.queue() == []


# --- time parsing ------------------------------------------------------------------------------------
LON = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 8, 17, 30, tzinfo=LON)


@pytest.mark.parametrize("s,expect", [
    ("now", NOW),
    ("+30m", datetime(2026, 11, 8, 18, 0, tzinfo=LON)),
    ("+2h", datetime(2026, 11, 8, 19, 30, tzinfo=LON)),
    ("+1d", datetime(2026, 11, 9, 17, 30, tzinfo=LON)),
    ("18:00", datetime(2026, 11, 8, 18, 0, tzinfo=LON)),
    ("09:00", datetime(2026, 11, 9, 9, 0, tzinfo=LON)),       # already passed today: tomorrow
    ("2026-12-01 08:15", datetime(2026, 12, 1, 8, 15, tzinfo=LON)),
])
def test_parse_when(s, expect):
    assert engine.parse_when(s, LON, now=NOW) == expect


def test_parse_when_uses_the_given_zone():
    dubai = ZoneInfo("Asia/Dubai")
    t = engine.parse_when("2026-12-01 08:00", dubai)
    assert t.astimezone(timezone.utc).hour == 4


def test_parse_when_keeps_explicit_offset():
    assert engine.parse_when("2026-12-01T08:00+00:00", LON).utcoffset().total_seconds() == 0


def test_parse_when_rejects_junk():
    with pytest.raises(ValueError):
        engine.parse_when("teatime", LON, now=NOW)


def test_tz_empty_is_system_local_and_bad_name_raises():
    assert engine.tz("") is not None
    with pytest.raises(Exception):
        engine.tz("Mars/Olympus")


def test_settings_ignore_unknown_and_empty():
    got = engine.settings(lambda k, d=None: {"user_name": "Ana", "timezone": "", "junk": "x"}.get(k, d))
    assert got["user_name"] == "Ana" and got["timezone"] == "" and "junk" not in got


# --- precheck: skip before the chat ever sees the wake ------------------------------------------------
class Check:
    def __init__(self, verdict):
        self.verdict, self.prompts = verdict, []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


def test_precheck_skip_leaves_no_trace(store, tmp_path):
    bound(store).add("inbox: nothing new", at=T0)
    inj, chk = Inject(), Check((False, "all clear"))
    assert engine.tick(store, S, inj, now=T0, precheck=chk).startswith("skipped:")
    assert inj.calls == [] and store.queue() == [] and store.read("pending.json", []) == []
    rec = json.loads((tmp_path / "done.jsonl").read_text().splitlines()[-1])
    assert rec["skipped"] == "all clear"
    assert "inbox: nothing new" in chk.prompts[0]


def test_precheck_notify_delivers_and_is_not_repeated_on_retry(store):
    bound(store).add("call the dentist", at=T0)
    chk = Check((True, "reminder"))
    assert engine.tick(store, S, Inject(False), now=T0, precheck=chk).startswith("retry:")
    assert engine.tick(store, S, Inject(), now=T0 + 100, precheck=chk).startswith("delivered:")
    assert len(chk.prompts) == 1


@pytest.mark.parametrize("verdict", [None, RuntimeError("model down")])
def test_precheck_unsure_or_broken_fails_open(store, verdict):
    bound(store).add("x", at=T0)
    assert engine.tick(store, S, Inject(), now=T0, precheck=Check(verdict)).startswith("delivered:")


def test_precheck_auto_skips_messaging_chats(store):
    bound(store, DISCORD).add("x", at=T0)
    chk = Check((False, "no"))
    assert engine.tick(store, S, Inject(), now=T0, precheck=chk).startswith("delivered:")
    assert chk.prompts == []


def test_precheck_always_and_off(store):
    bound(store, DISCORD).add("x", at=T0)
    assert engine.tick(store, dict(S, precheck="always"), Inject(), now=T0,
                       precheck=Check((False, "no"))).startswith("skipped:")
    bound(store).add("y", at=T0)
    assert engine.tick(store, dict(S, precheck="off"), Inject(), now=T0,
                       precheck=Check((False, "no"))).startswith("delivered:")


def test_test_wakes_bypass_precheck(store):
    bound(store).add("test", at=T0, kind="test")
    chk = Check((False, "no"))
    assert engine.tick(store, S, Inject(), now=T0, precheck=chk).startswith("delivered:")
    assert chk.prompts == []


def test_done_log_is_capped(store, tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "LOG_MAX", 2000)
    for n in range(100):
        store.log({"n": n, "pad": "x" * 50})
    lines = (tmp_path / "done.jsonl").read_text().splitlines()
    assert (tmp_path / "done.jsonl").stat().st_size <= 2000 + 200
    assert json.loads(lines[-1])["n"] == 99


def test_dropped_wake_context_never_reaches_a_newer_same_title_wake(store):
    store.push_context("⏰ Dentist", "OLD", "a", now=T0)
    store.push_context("⏰ Dentist", "NEW", "b", now=T0 + engine.INJECTED_GRACE + 1)
    assert store.pop_context("⏰ Dentist") == "NEW"
