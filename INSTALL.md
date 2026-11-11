# Install wake (prompt for a Hermes agent)

Install the wake plugin for me: https://github.com/zzzubair/hermes-wake

1. Run `hermes plugins install wake` (if it isn't in the catalog on this Hermes, `hermes plugins install zzzubair/hermes-wake`), then `hermes plugins enable wake`.
2. Ask me to restart the Hermes gateway once from a terminal, so it picks up the Wake Agent cron target.
3. Load the `wake:setup` skill and follow it: ask me which chat should get wakes, my name and my timezone, then ask me to allow `allow_gateway_injection`.
4. Send a test wake and confirm it arrived in the chat I picked.
