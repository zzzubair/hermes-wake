# Submitting Wake to the Hermes plugin catalog

This folder holds the draft catalog entry (`wake.yaml`), the text for the upstream PR, and feature
requests for seams Hermes doesn't have yet. Nothing here has been sent anywhere. The PR to
NousResearch/hermes-agent is yours to open.

## Steps

1. Merge the 1.0.0 PR on zzzubair/hermes-wake. Note the full 40-character SHA of the commit on `main`
   you want reviewed: `git rev-parse origin/main`.
2. On a checkout at that SHA, run the catalog's own check:
   `hermes plugins validate /path/to/hermes-wake --install-deps`. It should print `Validation passed.`
   with no warnings.
3. Fork NousResearch/hermes-agent. Copy `catalog/wake.yaml` to `plugin-catalog/wake.yaml`, replace the
   zero `sha` with the SHA from step 1, and delete the three comment lines at the top.
4. Open the PR with the title and body below. Catalog CI clones the repo at your pin and runs the same
   validate.
5. For a later release: bump `version` in `plugin.yaml`, merge, then open a new upstream PR that changes
   only `sha` and `version`.

## Upstream PR

**Title:** `plugin-catalog: add wake (agent speaks first: wakes and cron reports in any chat)`

**Body:**

> Adds `plugin-catalog/wake.yaml` for [zzzubair/hermes-wake](https://github.com/zzzubair/hermes-wake)
> (I'm the author), pinned at `<sha>`, version 1.0.0.
>
> **What it does.** A note the agent scheduled for later, or a cron job's report sent to the
> `wake_agent` target, arrives as a turn for the user's own agent in one chat they bind with
> `/wakes here`. That can be the Desktop Bot Chat or a Discord, Slack or Telegram DM. The agent checks
> what matters and messages the user in its own voice, or stays silent. Wakes wait until the chat is
> idle and keep their order. Setup is agent-led through the bundled `wake:setup` skill.
>
> **Hermes surfaces used (all public):**
> - `ctx.inject_message(session_key=...)` for delivery, gated by `allow_gateway_injection`
> - `ctx.register_platform("wake_agent", standalone_sender_fn=...)` as the cron delivery target. Its
>   adapter's `connect()` starts the delivery loop with `ctx.spawn_task`, and `disconnect()` /
>   `ctx.on_unload` stop it.
> - `pre_llm_call` (hands a wake its instructions as context, records turn start) and
>   `on_session_end` (records turn end)
> - `ctx.llm.complete_structured` (the optional skip-check, no overrides), `ctx.get_config` /
>   `ctx.set_config`, `ctx.state.data_dir`
> - `ctx.register_tool("wake")`, `ctx.register_command("wakes")` with calling-session keywords,
>   `ctx.register_cli_command("wake")`, `ctx.register_skill("setup")`
> - `gateway.session_context.get_session_env`, as documented for tool handlers
>
> `hermes plugins validate --install-deps` passes with no warnings: no private imports and no
> runtime rebinds. No UI, so no screenshots.
>
> **Disclosures:**
> - Starts agent turns in the bound chat (needs `allow_gateway_injection: true`), billed like a
>   message, with normal tools and approvals.
> - With `precheck: auto` (the default), each wake for a Desktop, TUI or CLI chat costs one extra
>   structured call on the user's active model via `ctx.llm`, carrying the wake text (up to 6,000
>   characters of a cron report). `precheck: off` removes it.
> - A background task in the gateway reads the local queue every 5 s. It makes no network calls.
> - `pre_llm_call` / `on_session_end` run on every turn. They store no message text.
> - Notes, cron reports, the bound session key and a capped delivery log are stored in plaintext in
>   the plugin's data dir.
> - On first start it moves its own 0.x queue out of `$HERMES_HOME/state/wake/`.
> - No third-party network calls, shell commands, credentials or telemetry.
>
> **Known limits** (in `known_issues`): on the Desktop each wake shows a one-line `⏰ <title>` user
> bubble, and an in-chat `[SILENT]` answer still shows its row. Both need core seams (feature
> requests: <links, if filed>).

## Admission rules checklist (1.0.0)

| # | Rule | Status |
|---|---|---|
| 1 | Human-merged gate | Pass: submitted by PR |
| 2 | Exact SHA pin | Pending: fill in the merged SHA (step 3) |
| 3 | No self-updating code | Pass: the 0.x engine hot-reload is removed, and nothing fetches code |
| 4 | SHA bumps are new PRs | Process: follow step 5 |
| 5 | Who may submit | Pass: you own the repo |
| 6 | Declared capabilities match | Pass: `declared tools/hooks/middleware` checks |
| 7 | Install scanner | Pass: `security scan — safe` |
| 8 | Desktop plugins stay in the SDK | N/A: no desktop plugin |
| 9 | No runtime overrides of core | Pass: the `_silence_allowed_for_source` rebind and all private gateway imports are gone, and validate shows no warnings |
| 10 | Dependency policy | Pass: no Python dependencies |
| 11 | Credentials through Hermes | Pass: none used |
| 12 | Approvals / unattended runs | Pass: never approves anything. The skill has the agent propose `hermes config set` through normal approval. Nothing waits on a person under cron. |
| 13 | Risky behaviour disclosed | Pass: README "Disclosures", entry description, PR body |
| 14 | Truthful compatibility | Pass: `requires_hermes: ">=0.23.0"` in both files (tested on v0.23.0), and `version` matches |
| 15 | No skins/forks of bundled plugins | Pass |
| 16 | One listing per lineage | Pass: original |
| 17 | No unscannable payloads | Pass: Python and Markdown only |
| 18 | Password managers from vendor | N/A |

## Feature requests (seams a plugin can't reach)

These are written so you can file them on NousResearch/hermes-agent as issues if you choose.

### 1. Let a plugin start a turn the Desktop doesn't draw as the user's message

`ctx.inject_message` turns are persisted as `internal_notification` user rows. The Desktop
(`apps/desktop/src/lib/chat-messages/hydration.ts`) hides only `display_kind: "hidden"` rows and
draws every other user row as the user's own bubble. A proactive plugin therefore puts a line in the
user's mouth on every wake. Wake keeps it to `⏰ <title>` and sends the real instructions through
`pre_llm_call` context. Ask: an `inject_message(..., display="hidden")` option, or a
plugin-supplied one-line notice card like the `process_complete` card.

### 2. Draw `internal_notification` rows as system notices, not user bubbles

Same root cause, wider effect. Background-process notices without a producer card are persisted as
`internal_notification`, and the Desktop shows the raw
`[IMPORTANT: Background process … matched watch pattern …]` text as if the user had sent it. That
covers watch-pattern matches (`gateway/run_notifications.py::_local_completion_card` returns `{}` for
them) and any completion admitted without `display_text`. Plugins can't fix this:
`pre_gateway_dispatch` runs after the internal-event guard, so internal events never reach plugin
hooks, and no hook or Desktop SDK slot can change a row's display kind. Ask: render
`internal_notification` user rows as a compact system notice (or hidden), and give watch-pattern
events a card the way completions have one.

### 3. Persist a suppressed silence reply as hidden

When the gateway suppresses an intentional `[SILENT]` on a machinery turn ("Suppressing intentional
silence marker"), the assistant row is still stored as plain `[SILENT]` with no display kind, so the
Desktop transcript draws it. Ask: store that row with `display_kind: "hidden"`, keeping the pair for
the model, or have the Desktop skip bare silence markers. Today a plugin can only do this by
rebinding `GatewayRunner._silence_allowed_for_source` and writing the row's display kind through
`SessionDB`, which rule 9 forbids.

### 4. A public "is this session busy?" check

Wake avoids queuing a wake behind a running turn by tracking `pre_llm_call` / `on_session_end` for
the bound chat itself. A `ctx.session_busy(session_key)`, or an `inject_message(..., when="idle")`
mode, would make that exact and survive hook misses.
