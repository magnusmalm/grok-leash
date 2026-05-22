# grok-leash

**Keep your Grok subagents on a leash.**

`grok-leash` is a monitoring and safety tool for [grok-build](https://x.ai) (the Grok CLI / grok-build TUI). It watches for the exact class of runaway subagent behavior that caused a ~750 million token incident in May 2026.

## The Problem

In May 2026, a subagent was given the simple request:

> "Let's make Agent 2 do the commit."

It ran for 82 minutes, performed **2,384 tool calls** (almost all tiny `read_file limit=5` loops on the same two files), and consumed roughly **750 million tokens** before being manually cancelled.

Root causes observed:
- No termination budget in the subagent prompt
- Repeated `read_file` with very small `limit` values on the same paths
- O(N²) token cost due to context replay
- No early warning system for the user

## What grok-leash Does

- Watches active Grok sessions in real time
- Detects dangerous patterns:
  - Excessive repeated reads of the same file with small `limit`
  - Very high tool call counts in a single turn
  - Long-running subagent turns without progress
  - Subagent spawns that lack an explicit termination budget
- Emits loud, actionable alerts (terminal + desktop notifications)
- Designed to be run alongside `grok-tap` from the [grokscope](https://github.com/daniel-farina/grokscope) project

## Installation

This project is managed exclusively with `uv`.

```bash
cd /path/to/your/grok-leash-clone
uv sync
```

This creates a `.venv`, installs all dependencies, and makes the CLI entry points available.

After `uv sync`, you can run the tools via:

```bash
uv run grok-leash
uv run grok-leash-acknowledge "<id>"
uv run pytest
```

(You can also activate the venv with `source .venv/bin/activate` and then use the commands directly.)

### Host-level pieces (not included in this repo)

This repository provides the monitor, launchers, and systemd example.

For the **complete defense-in-depth setup** on a new machine you will also need (maintained separately on each host):

- The `grok-leash` skill at `~/.grok/skills/grok-leash/SKILL.md`
- The `read-file-guard` PreToolUse hook (`~/.grok/hooks/`)
- Subagent Safety rules in `~/.claude/CLAUDE-shared.md` (and project `CLAUDE.md` files)

Cloning + `uv sync` + the persistent monitor only covers the **real-time monitoring** layer.

## Usage

### Basic runaway monitoring (recommended)

```bash
uv run grok-leash
# or
uv run grok-leash monitor
```

Watches the most recent session for the classic `read_file` runaway pattern.

### Live actions watcher (new)

```bash
uv run grok-leash watch-actions
```

This runs a separate live tailer on `~/.grok-leash/actions/`. When the main monitor detects a problem, this watcher will:

- Print rich alerts
- Send desktop notifications
- Write structured alerts to `~/.grok-leash/parent-alerts.jsonl`
- Write the most recent alert to `~/.grok-leash/latest-tui-alert.json` (preferred by the grok-leash skill)

### Quick alerts check (very useful from the parent session)

```bash
uv run grok-leash check-alerts
uv run grok-leash check-alerts --minutes 30 --json
```

This is the command the main Grok agent (via the `grok-leash` skill) will usually call.

### Periodic / Proactive Checking + Acknowledgment

See `prompts/periodic-checker.md` for a ready-to-paste instruction you can give your main Grok session so it automatically checks for problems after subagents or every N turns.

The `grok-leash` skill now supports both **manual** and **automatic acknowledgment**:

- Manual: “acknowledge this alert” or “mark as seen”.
- Automatic: When the user says things like “okay, I cancelled it”, “I killed the subagent”, “that’s fine”, or “problem solved”, the skill will automatically acknowledge the relevant alert.

Acknowledged alerts are hidden by default in future checks.

You can also acknowledge from the terminal:

```bash
uv run grok-leash-acknowledge "<full-alert-id>"
```

### With a specific session

```bash
uv run grok-leash --session 019e41cd
```

### Running alongside grok-tap (highest fidelity)

```bash
# Terminal 1
grok-tap

# Terminal 2
GROK_CLI_CHAT_PROXY_BASE_URL=http://127.0.0.1:18080/v1 uv run grok-leash
```

### Running persistently (systemd or tmux)

For day-to-day use you almost certainly want the monitor running in the background so it can alert you (and your main Grok session) in real time.

#### Option 1: systemd user service (fire-and-forget)

1. Install the launchers:

   ```bash
   mkdir -p ~/.local/bin
   cp contrib/grok-leash-monitor contrib/grok-leash-watch ~/.local/bin/
   chmod +x ~/.local/bin/grok-leash-*
   ```

2. Copy and enable the service:

   ```bash
   mkdir -p ~/.config/systemd/user
   cp contrib/grok-leash.service ~/.config/systemd/user/
   # Edit the service file if your clone is not in a location the launcher can auto-detect
   systemctl --user daemon-reload
   systemctl --user enable --now grok-leash.service
   ```

**Project location detection:**  
The launchers automatically detect the project root using:

- The `PROJECT_DIR` environment variable (if set), or
- The current git repository root (if you run the command while inside the clone).

This means you usually do **not** need to set `PROJECT_DIR` as long as you are inside the grok-leash directory or have the launcher in PATH.

3. Watch logs:

   ```bash
   journalctl --user -u grok-leash.service -f
   ```

#### Option 2: tmux (easy to inspect)

```bash
tmux new-session -s grok-leash
# pane 1
grok-leash-monitor
# split pane (Ctrl-b ") and run:
grok-leash-watch
```

**Project location detection:**  
The launchers will find the project automatically if you are inside the git repository, or you can set `PROJECT_DIR`. See the note in the systemd section above.

See `contrib/` for the exact files.

## Configuration

Create `~/.config/grok-leash/config.toml` (copy from `config.example.toml` in this repo as a starting point):

```toml
[monitor]
read_threshold = 30
time_window_minutes = 6
small_limit_threshold = 80

[actions]
enable_desktop_notifications = true
enable_kill_action = false          # experimental
write_action_file = true
notify_parent_via_file = true

[detection]
warn_on_missing_budget = true
```

## How It Fits Into the Larger Picture

`grok-leash` is the **monitoring layer** in a defense-in-depth strategy:

| Layer                    | Purpose                              | Tool                          |
|--------------------------|--------------------------------------|-------------------------------|
| Prompt rules             | Prevent bad prompts at source        | CLAUDE.md / project rules     |
| PreToolUse hooks         | Hard block dangerous tool patterns   | `~/.grok/hooks/` + scripts    |
| Dedicated skills         | Safe paths for common tasks (e.g. commit) | `~/.grok/skills/commit/`   |
| **Real-time monitoring** | Catch problems even when rules fail  | **grok-leash** (this project) |
| Post-incident forensics  | Understand what happened             | grokscope + forensic scripts  |

## Development

```bash
# Run the monitor with verbose output
uv run grok-leash --verbose

# Run tests
uv run pytest
```

## Companion Grok Skill

A full `grok-leash` skill is available at:

`~/.grok/skills/grok-leash/SKILL.md`

This lets the **main Grok session** (the parent) proactively or periodically check for alerts using natural language ("check grok-leash", "run the grok-leash skill", etc.).

See `prompts/periodic-checker.md` for a standing instruction you can give the main agent.

## Status

This project was created in May 2026 as an emergency defense-in-depth response to a severe subagent runaway incident. It was always intended as a **temporary mitigation layer** while the root causes were addressed in Grok Build and the underlying models.

As the platform improves and adds stronger native safeguards against runaway behavior, tools like `grok-leash` will naturally become less necessary. This is the desired outcome. In the meantime, the patterns here (strict termination budgets, external monitoring, dedicated safe skills, and hard tool-use hooks) remain useful techniques for working with agentic systems.

## License

MIT (same as grokscope)

## Related

- grokscope (grok-tap + grok-monitor): https://github.com/daniel-farina/grokscope
- Grok Build TUI documentation (user guide)
