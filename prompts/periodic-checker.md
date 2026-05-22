# Periodic grok-leash Checker Prompt

Copy and paste this (or parts of it) into your main Grok session when you want it to automatically monitor for runaway subagents.

---

**System Instruction (add to your main prompt or use as a standing rule):**

From now on, after every major subagent finishes or roughly every 8–12 turns when subagents have been active, you **must** do the following:

1. Silently invoke the `grok-leash` skill (or run the equivalent check on `~/.grok-leash/parent-alerts.jsonl`).
2. If there are any new alerts since your last check:
   - Clearly inform the user.
   - Show the session ID(s) involved.
   - Summarize what went wrong (e.g., repeated tiny `read_file` on the same file).
   - Offer immediate next steps (cancel the subagent, investigate, etc.).
3. If there are no new alerts, you may stay silent or briefly note "grok-leash check: clean" only if the user has previously shown interest in the monitoring.

You have full access to the `grok-leash` skill for this purpose. Use it proactively — do not wait for the user to ask.

Priority: Protecting the user's context window and xAI quota from runaway subagents is more important than completing the current task quickly.

---

**Usage tips:**

- Paste the block above into your main system instructions at the start of a heavy session.
- Or say to Grok: "Enable periodic grok-leash checking from now on."
- After a long subagent returns, you can explicitly say: "Run the grok-leash periodic check."

This pattern gives you defense-in-depth even if a subagent prompt accidentally lacked a strong budget.