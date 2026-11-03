# hermes-wake

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that lets the agent speak first.

Cron jobs normally post into your chat as if you'd sent the message. With this plugin, they wake the agent
instead. The agent gets a hidden turn, checks what happened, and messages you itself, like
"Google Cloud is switching you to threshold billing, nothing to do".

## What it adds

- **Wake Agent delivery target.** Pick it under a cron job's *Send to*, or run
  `hermes cron edit <job> --deliver wake_agent`. The job's output becomes a wake, and silent runs stay silent.
- **Self-scheduled wakes.** Run `wake add 18:00 "remind them about check-in"`, or `wake now "<note>"` from a script.
  The note reaches the agent at that time as a hidden turn.
- **No fake user bubbles.** Wakes are submitted with `display_kind: hidden` and queued behind any running turn,
  so one that lands mid-reply waits its turn instead of failing.

## Install

```bash
hermes plugins install zzzubair/hermes-wake --enable
hermes gateway restart
ln -s ~/.hermes/plugins/wake/cli.py ~/.local/bin/wake   # optional CLI
```

## Settings

These go in `config.yaml` under `plugins.entries.wake.settings`, or in the desktop app's Plugins page.

```yaml
plugins:
  entries:
    wake:
      settings:
        user_name: Sam            # who the agent messages
        session_title: Bot Chat   # chat that wakes land in
        timezone: Europe/London   # for the CLI; empty = system local
```

`wake_prompt` and `cron_prompt` override the built-in prompts.

## Files

- `engine.py` holds the logic and hot-reloads when edited.
- `platform.py` is the Wake Agent target.
- `__init__.py` is the loop.
- `cli.py` is the `wake` command.

State lives in `$HERMES_HOME/state/wake/`.

MIT licensed.
