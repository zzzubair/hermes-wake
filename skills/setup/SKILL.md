---
name: setup
description: Walk the user through setting up the wake plugin (which chat wakes go to, their name, timezone, the gateway-injection permission), then prove it works with a test wake. Use right after `hermes plugins install wake`, or when wakes are not arriving.
---

# Set up wakes

Wakes let you speak first. A note scheduled for later, or a cron job's report, arrives in the user's
chat as a turn for you. You then message the user in your own voice, or reply exactly `[SILENT]` when
there is nothing worth saying (then the user sees nothing).

Keep this conversational and short. Ask one thing at a time. Work out whatever you can yourself
before you ask.

## 1. Check where things stand

Call `wake(action="status")`. It shows the chat wakes go to (`target`), the settings and the queue.

## 2. Pick the chat (question 1)

Wakes go to exactly one chat. The usual choice is **the chat you are in right now**.

- If the user is talking to you in the chat they want wakes in (their Desktop Bot Chat, a Discord or
  Slack DM, Telegram...), call `wake(action="bind_here")`.
- If they want a different chat, tell them to open that chat and type `/wakes here`.

## 3. Name and timezone (questions 2 and 3)

The prompts call the user by name, and times like `18:00` use the timezone.

- If you already know their name, confirm it rather than asking. Otherwise ask.
- Suggest the timezone you can infer (from what they have told you, or the system's); ask them to
  confirm. It must be an IANA name such as `Europe/London` or `Asia/Dubai`.

Then call `wake(action="configure", user_name="...", timezone="...")`.

## 4. Allow the plugin to start turns

Hermes lets a plugin start a turn in a chat only with the user's permission. This is one config line:

```bash
hermes config set plugins.entries.wake.allow_gateway_injection true
```

Explain what it does in one sentence ("it lets wakes start a turn in your chat; nothing else gets
access") and ask before you run it with the terminal tool, or let the user run it. It takes effect
without a restart.

If the plugin was enabled only just now, the gateway has to restart once to pick up the Wake Agent
delivery target: `hermes gateway restart` (ask first; it briefly drops open chats).

## 5. Prove it works

Call `wake(action="test")`. Within a few seconds a test wake should arrive in the bound chat. When it
does, answer it the way the test note asks.

If nothing arrives within a minute, call `wake(action="status")`. A queued wake with `last_error`
tells you why. The usual causes:

- `not admitted`: `allow_gateway_injection` is not `true`, or the bound chat is not open. A Desktop
  Bot Chat has to be open (live) at least once after a gateway restart.
- No target: go back to step 2.
- The gateway was not restarted after enabling the plugin.

## 6. Show them how to use it

Give the user two or three lines, no more:

- "Ask me to remind you about something at a time, and I'll message you then."
- Send a cron job's report to you instead of straight to them:
  `hermes cron edit <job> --deliver wake_agent` (or pick **Wake Agent** under *Send to*). You read
  the report, check what is worth checking, and tell them only what matters, or stay quiet.
- From scripts: `hermes wake now "<note>"` or `hermes wake add 18:00 "<note>"`.

## Using wakes yourself

- `wake(action="schedule", when="+2h", note="...")` schedules a note to yourself. Write the note so
  that future-you, with no memory of this moment, knows what to check and what to tell the user.
- When a wake arrives, check what's needed first, then speak briefly in your own voice. If it no
  longer matters, reply exactly `[SILENT]` and nothing else.
