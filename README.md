# Wake

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that lets your agent speak first.

You ask your agent to remind you about something at 6pm, or a cron job finishes a sweep of your
inbox. With Wake, that moment arrives as a turn for **your own agent, in your own chat**: the Desktop
Bot Chat, a Discord or Slack DM, Telegram, whichever one you picked. The agent checks what is worth
checking and messages you in its own voice:

> Google Cloud is switching you to threshold billing next month. Nothing to do.

When there is nothing worth saying, it stays quiet, and you never see that the wake happened.

## What Hermes already does, and what Wake adds

Hermes cron can already post a job's output to Discord, Slack and the rest (`--deliver discord`), and
a job that answers `[SILENT]` posts nothing. `--deliver bot-chat` hands the output to a profile's
Desktop Bot Chat as an incoming message. Use those when they fit.

Wake adds three things:

- **Your agent, in its own voice, with context, in any chat.** The cron run's isolated agent doesn't
  write the message. The agent you actually talk to does, inside your conversation, so you can just
  reply to it. That works in a messaging DM as well as in the Bot Chat.
- **Notes to self.** The agent (or you, or a script) schedules a note for later: "+2h check whether
  the deploy finished". At that time it comes back to the agent as a turn.
- **Skips that leave no trace.** A wake with nothing in it is dropped before it reaches the chat.

## Install

Paste this to your Hermes agent:

```text
Install the wake plugin for me: https://github.com/zzzubair/hermes-wake

1. Run `hermes plugins install wake` (if it isn't in the catalog on this Hermes, `hermes plugins install zzzubair/hermes-wake`), then `hermes plugins enable wake`.
2. Ask me to restart the Hermes gateway once from a terminal, so it picks up the Wake Agent cron target.
3. Load the `wake:setup` skill and follow it: ask me which chat should get wakes, my name and my timezone, then ask me to allow `allow_gateway_injection`.
4. Send a test wake and confirm it arrived in the chat I picked.
```

Or by hand:

```bash
hermes plugins install wake        # from the plugin catalog
hermes plugins enable wake
hermes gateway restart             # once, so the gateway picks up the Wake Agent cron target
```

Not in the catalog yet on your Hermes? `hermes plugins install zzzubair/hermes-wake` installs it
straight from GitHub. Needs Hermes 0.23.0 or newer.

Then tell your agent: **"set up wakes"**. It loads the bundled `wake:setup` skill and walks you
through three questions: which chat, your name, your timezone. Then it asks you to allow one
permission and sends a test wake. You can do the same by hand:

```bash
hermes config set plugins.entries.wake.allow_gateway_injection true   # lets wakes start a turn in your chat
```

Then, in the chat that should get wakes, type `/wakes here`, then `/wakes test`.

With no setup at all, the first wake your agent schedules binds the chat it was scheduled from.

## Use it

**Ask your agent.** "Remind me at 18:00 to call the dentist." "Check again in two hours whether the
deploy finished." The agent uses its `wake` tool.

**Send a cron job's report to your agent** instead of straight to you:

```bash
hermes cron create --deliver wake_agent --name "Inbox sweep" "every 2h" "List new mail that needs me"
hermes cron edit <job> --deliver wake_agent       # an existing job
```

Or pick **Wake Agent** under *Send to* in the Desktop. Your agent gets the report, checks what is
worth checking, and tells you only what matters. When a job fails, it gets the failure output and is
asked to find out why. Silent runs and runs cut short by a gateway restart are dropped.

**From the terminal or scripts:**

```bash
hermes wake add 18:00 "call the dentist"         # also: now, +30m, +2h, +1d, "2026-12-01 08:15"
hermes wake now "the backup script failed, look at /var/log/backup.log"
hermes wake list                                 # the bound chat and the queue
hermes wake cancel <id>
hermes wake test
```

**In any chat:** `/wakes here`, `/wakes test`, `/wakes add <when> <note>`, `/wakes list`,
`/wakes cancel <id>`, `/wakes off`.

## How a wake is delivered

1. Wakes wait in a queue in the plugin's data directory, in order.
2. When one is due, Wake waits until the bound chat is idle. A wake never lands in the middle of a
   turn, and later wakes never overtake an earlier one.
3. On chats that show the injected text (Desktop Bot Chat, TUI, classic CLI), Wake first makes one
   small call on your current model: is this worth interrupting you for? If not, the wake ends there
   and the chat shows nothing. If the check can't decide or fails, the wake goes ahead. Set
   `precheck: off` to skip this call, or `always` to use it on every chat.
4. Wake starts a turn in the chat with Hermes's `ctx.inject_message`. On a messaging platform only the
   agent's reply is posted. On the Desktop a one-line notice (`⏰ Dentist`) marks the turn. The full
   instructions reach the model through the `pre_llm_call` hook, so they are not drawn in the chat.
5. The agent replies, or answers `[SILENT]` and Hermes posts nothing.
6. If Hermes refuses the turn (permission off, chat not open), the wake retries with backoff, up to
   every 5 minutes, and `hermes wake list` shows why.

## Settings

In `config.yaml` under `plugins.entries.wake.settings`, or on the Desktop Plugins page. All are
optional.

| Setting | Default | What it does |
|---|---|---|
| `user_name` | `the user` | Who the agent should message. Used in the prompts. |
| `timezone` | system | IANA name (`Europe/London`) for times like `18:00`. |
| `precheck` | `auto` | `auto`: skip-check on Desktop/TUI/CLI chats. `always`, or `off`. |
| `wake_prompt` | built in | Replaces the wake prompt. Placeholders `{note}`, `{user}`. |
| `cron_prompt` | built in | Replaces the cron prompt. Placeholders `{name}`, `{body}`, `{user}`. |

`plugins.entries.wake.allow_gateway_injection: true` is required for delivery. It sits beside
`settings`, not inside it.

## Limits

- **Linux and macOS only.** The queue uses POSIX file locks.
- **One chat per profile.** Wakes go to the chat bound last.
- **Desktop shows a one-line notice per wake.** Hermes has no public way for a plugin to start a
  hidden turn, and the Desktop draws plugin-started turns as your own bubble. Wake keeps that bubble
  to `⏰ <title>`. Messaging platforms show nothing but the reply.
- **A `[SILENT]` reply can show on the Desktop.** If a wake passes the skip-check and the agent then
  answers `[SILENT]`, Hermes posts nothing, but the Desktop transcript still draws the `[SILENT]` row.
  The skip-check exists to make this rare.
- **The Desktop Bot Chat must be live.** After a gateway restart, open the Bot Chat once. Until then,
  wakes wait in the queue.
- **Times are checked every 5 seconds**, and only while the gateway runs. Wakes due while it was down
  go out when it is back, with a note saying how late they are.

## Disclosures

- **Starts agent turns** in the chat you bind, which needs your `allow_gateway_injection` permission.
  Each wake is one normal turn on your model, billed like a message, with your normal tools and
  approval prompts.
- **One extra model call per wake** on Desktop/TUI/CLI chats while `precheck` is `auto`. It goes to
  your active model through Hermes (`ctx.llm`) and contains the wake's text, which for cron is the
  job report, up to 6,000 characters. Set `precheck: off` to turn it off.
- **Background task:** while the gateway runs, a task reads the plugin's local queue every 5 seconds.
  It makes no network calls.
- **Hooks:** `pre_llm_call` runs on every turn. It checks for a wake's notice and records when the
  bound chat's turn starts. `on_session_end` records when the turn ends. Neither stores message text.
- **Stored in plaintext** under `$HERMES_HOME/plugin-data/` (the plugin's own directory): queued
  notes, cron reports (up to 6,000 characters each), the bound chat's session key, and a capped
  delivery log.
- **Reads outside its own data:** once, it moves a 0.x queue from `$HERMES_HOME/state/wake/` into its
  data directory.
- No third-party network calls, no telemetry, no shell commands, no credentials. The setup skill asks
  the agent to propose `hermes config set ...`, which runs through Hermes's normal approval.

## Upgrading from 0.x

- The `session_title` setting is gone. Run `/wakes here` in the chat that should get wakes.
- Set `plugins.entries.wake.allow_gateway_injection: true`.
- The standalone `wake` script (`cli.py`) is now `hermes wake`. Repoint any symlink or script.
- Queued wakes move over on the first start.

## Development

```bash
python -m pytest tests                              # engine tests, no Hermes needed
hermes plugins validate . --install-deps            # the catalog's own check
```

`engine.py` holds the queue, prompts and the delivery step, and doesn't import Hermes.
`__init__.py` connects it to Hermes. `cron_target.py` is the Wake Agent delivery target, and its
`connect()` starts the delivery loop inside the gateway. `skills/setup/SKILL.md` is the setup
walkthrough the agent follows.

MIT licensed.
