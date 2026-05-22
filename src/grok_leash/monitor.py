#!/usr/bin/env python3
"""
grok_leash/monitor.py

Core monitoring logic for detecting runaway subagent behavior.

Focus: repeated read_file calls on the same files with small limits
(the exact failure mode from the 2026-05-19 incident).
"""

import json
import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .config import GrokLeashConfig, load_config, ensure_action_dir


def has_termination_budget(text: str) -> bool:
    """Heuristic: does the prompt text mention any form of termination budget?"""
    if not text:
        return False
    t = text.lower()
    markers = [
        "at most", "hard limit", "stop after", "report back after",
        "tool calls", "minutes", "termination budget", "budget",
        "whichever comes first"
    ]
    return any(m in t for m in markers)

GROK_SESSIONS = Path.home() / ".grok" / "sessions"
ALERT_COOLDOWN_SECONDS = 60


console = Console()


@dataclass
class ReadStats:
    count: int = 0
    small_limit_count: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None


def find_most_recent_session() -> Optional[Path]:
    """Return the most recently modified session directory."""
    candidates = []
    for cwd_dir in GROK_SESSIONS.iterdir():
        if not cwd_dir.is_dir():
            continue
        for session_dir in cwd_dir.iterdir():
            if not session_dir.is_dir():
                continue
            jsonls = list(session_dir.glob("*.jsonl"))
            if jsonls:
                latest_mtime = max(f.stat().st_mtime for f in jsonls)
                candidates.append((latest_mtime, session_dir))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def send_desktop_notification(title: str, body: str) -> bool:
    """Try to send a desktop notification. Returns True on success."""
    try:
        # Linux (notify-send)
        subprocess.run(
            ["notify-send", "--urgency=normal", title, body],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Fallback: just print (already done by rich)
        return False


def parse_update_line(line: str) -> dict:
    """Safely parse a line from updates.jsonl or events.jsonl."""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {}


def extract_read_file_info(data: dict) -> Optional[tuple[str, Optional[int]]]:
    """
    Extract (file_path, limit) from a Grok session/update event if it is a read_file call.
    Returns None if this line does not represent a read_file tool call.
    """
    if not isinstance(data, dict):
        return None

    params = data.get("params", {})
    update = params.get("update", {})

    session_update = update.get("sessionUpdate", "")

    # We care about tool_call and tool_call_update events
    if session_update not in ("tool_call", "tool_call_update"):
        return None

    title = update.get("title", "") or ""
    raw_input = update.get("rawInput", {}) or {}

    # Check if this is a read_file operation
    if "read_file" not in title.lower():
        # Some versions put the tool name in different places
        if "Read" not in str(raw_input) and "read_file" not in str(raw_input).lower():
            return None

    # Try to find the file path in common locations
    file_path = None
    for key in ("file_path", "path", "target_file", "file"):
        if key in raw_input:
            file_path = str(raw_input[key])
            break

    if not file_path and "file" in str(raw_input):
        # Fallback heuristic
        match = re.search(r'["\']([^"\']+\.(c|h|py|rs|go|ts|js|java|md))["\']', str(raw_input))
        if match:
            file_path = match.group(1)

    # Try to get limit if present
    limit = None
    for key in ("limit", "max_lines", "line_count"):
        if key in raw_input:
            try:
                limit = int(raw_input[key])
            except (ValueError, TypeError):
                pass
            break

    if file_path:
        return file_path, limit

    return None


class RunawayMonitor:
    def __init__(self, config: GrokLeashConfig | None = None):
        self.config = config or load_config()
        self.read_stats: dict[str, ReadStats] = defaultdict(ReadStats)
        self.last_alert: dict[str, datetime] = {}
        self.known_subagents: dict[str, dict] = {}   # subagent_id -> metadata

        ensure_action_dir(self.config)

    def process_update(self, data: dict, session_name: str):
        """Main entry point for each line from the session log."""
        if not isinstance(data, dict):
            return

        # 1. Detect read_file repetition (core anti-runaway)
        self._handle_read_file(data, session_name)

        # 2. Detect subagent creation (improved)
        self._handle_subagent_spawn(data, session_name)

    def _handle_read_file(self, data: dict, session_name: str):
        info = extract_read_file_info(data)
        if not info:
            return

        file_path, limit = info
        key = f"{session_name}:{file_path}"
        now = datetime.now()

        stats = self.read_stats[key]
        stats.count += 1
        if limit is not None and limit < self.config.small_limit_threshold:
            stats.small_limit_count += 1
        if stats.first_seen is None:
            stats.first_seen = now
        stats.last_seen = now

        # Trigger when we see the dangerous pattern
        if (stats.count >= self.config.read_threshold and
            stats.small_limit_count >= 5):
            last = self.last_alert.get(key)
            if last is None or (now - last).total_seconds() > ALERT_COOLDOWN_SECONDS:
                self._trigger_threshold_crossed(key, stats, file_path, session_name, limit)
                self.last_alert[key] = now

    def _handle_subagent_spawn(self, data: dict, session_name: str):
        """Detect when a subagent is created and whether it has a budget."""
        if not self.config.warn_on_missing_budget:
            return

        params = data.get("params", {})
        update = params.get("update", {})
        title = str(update.get("title", "")).lower()

        if not any(kw in title for kw in self.config.subagent_spawn_keywords):
            return

        raw_input = update.get("rawInput", {}) or {}
        description = str(raw_input.get("description", "") or raw_input.get("prompt", ""))

        if description and not has_termination_budget(description):
            console.print(
                Panel(
                    f"[yellow]Subagent spawned without explicit termination budget[/yellow]\n\n"
                    f"Title: {update.get('title')}\n"
                    f"Description snippet: {description[:220]}...",
                    title="[orange]grok-leash[/orange] - Subagent Warning",
                    border_style="yellow"
                )
            )

    def _trigger_threshold_crossed(
        self,
        key: str,
        stats: ReadStats,
        file_path: str,
        session: str,
        last_limit: Optional[int],
    ):
        duration = ""
        if stats.first_seen and stats.last_seen:
            delta = stats.last_seen - stats.first_seen
            duration = f" over {delta.seconds // 60} min"

        # Terminal alert
        msg = Text()
        msg.append("🚨 RUNAWAY SUBAGENT THRESHOLD CROSSED\n\n", style="bold red")
        msg.append(f"Session : {session}\n", style="cyan")
        msg.append(f"File    : {file_path}\n", style="yellow")
        msg.append(f"Reads   : {stats.count} (small-limit: {stats.small_limit_count}){duration}\n")
        if last_limit is not None:
            msg.append(f"Last limit: {last_limit}\n")

        panel = Panel(msg, title="[bold red]grok-leash[/bold red]", border_style="red")
        console.print(panel)

        # Desktop notification
        if self.config.enable_desktop_notifications:
            send_desktop_notification(
                "grok-leash: Runaway Detected",
                f"{Path(file_path).name} read {stats.count}x (small limits)"
            )

        # Action system
        self._execute_actions(session, file_path, stats, last_limit)

    def _execute_actions(self, session: str, file_path: str, stats: ReadStats, last_limit: Optional[int]):
        """Perform configured actions when a threshold is crossed."""
        now = datetime.now()
        action = {
            "timestamp": now.isoformat(),
            "type": "runaway_read_file",
            "session_id": session,
            "file_path": str(file_path),
            "read_count": stats.count,
            "small_limit_reads": stats.small_limit_count,
            "last_limit_seen": last_limit,
            "first_seen": stats.first_seen.isoformat() if stats.first_seen else None,
            "last_seen": stats.last_seen.isoformat() if stats.last_seen else None,
            "severity": "high" if stats.count > 50 else "medium",
            "suggested_action": "Cancel the subagent immediately via the TUI (Ctrl+C or equivalent)",
        }

        action_dir = ensure_action_dir(self.config)

        # Always write a timestamped, well-structured JSON action file
        if self.config.write_action_file or self.config.notify_parent_via_file:
            safe_name = session.replace("/", "_")
            action_file = action_dir / f"runaway_{safe_name}_{int(now.timestamp())}.json"
            try:
                action_file.write_text(json.dumps(action, indent=2))
                console.print(f"[dim]Action written to[/dim] {action_file}")
            except Exception as e:
                console.print(f"[red]Failed to write action file:[/red] {e}")

        # Strong "kill" signal (opt-in)
        if self.config.enable_kill_action:
            kill_file = action_dir / "KILL_REQUEST.json"
            try:
                kill_file.write_text(json.dumps({
                    "timestamp": now.isoformat(),
                    "session_id": session,
                    "reason": "runaway_read_file_pattern",
                    "file": str(file_path),
                    "read_count": stats.count,
                    "instruction": "IMMEDIATE ACTION REQUIRED: Cancel this subagent in the Grok TUI"
                }, indent=2))
                console.print(Panel(
                    "[bold red]KILL REQUEST FILE CREATED[/bold red]\n"
                    f"{kill_file}\n\n"
                    "The parent session (or an external watcher) should act on this.",
                    title="grok-leash",
                    border_style="red"
                ))
            except Exception as e:
                console.print(f"[red]Failed to write KILL_REQUEST:[/red] {e}")
            last_alert_time = self.last_alert.get(key)
            if last_alert_time is None or (now - last_alert_time) > timedelta(seconds=ALERT_COOLDOWN_SECONDS):
                self._trigger_alert(key, count, limit, file_path, session_name, now)
                self.last_alert[key] = now

    def _trigger_alert(self, key: str, count: int, limit: Optional[int], file_path: str, session: str, now: datetime):
        msg = Text()
        msg.append("🚨 RUNAWAY SUSPECTED\n", style="bold red")
        msg.append(f"Session: {session}\n", style="cyan")
        msg.append(f"File:    {file_path}\n", style="yellow")
        msg.append(f"Reads:   {count} (threshold = {self.read_threshold})\n")
        if limit is not None:
            msg.append(f"Last limit: {limit}  ", style="red" if limit < 50 else "white")
            if limit < 50:
                msg.append("(very suspicious)", style="red")
        msg.append(f"\nTime: {now.isoformat()}\n")
        msg.append("\nConsider cancelling this subagent or session.\n")

        panel = Panel(msg, title="[red]grok-leash ALERT[/red]", border_style="red")
        console.print(panel)

        # Future: desktop notification
        # os.system(f'notify-send "grok-leash" "Runaway detected: {file_path}"')


def monitor_session(session_dir: Path, monitor: RunawayMonitor):
    updates_file = session_dir / "updates.jsonl"
    if not updates_file.exists():
        candidates = list(session_dir.glob("*.jsonl"))
        if not candidates:
            return
        updates_file = candidates[0]

    console.print(f"[green]Monitoring session[/green] {session_dir.name}")
    console.print(f"Watching file: {updates_file.name}")

    last_size = 0

    while True:
        try:
            if not updates_file.exists():
                time.sleep(3)
                continue

            current_size = updates_file.stat().st_size
            if current_size > last_size:
                with updates_file.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(last_size)
                    for line in f:
                        if line.strip():
                            data = parse_update_line(line)
                            monitor.process_update(data, session_dir.name)
                last_size = current_size

        except Exception as e:
            console.print(f"[red]Error in monitor:[/red] {e}")

        time.sleep(2.0)


def cli_main():
    import argparse

    parser = argparse.ArgumentParser(description="grok-leash - Subagent runaway monitor")
    parser.add_argument("--session", help="Specific session id (partial match)")
    parser.add_argument("--threshold", type=int,
                        help="Number of repeated reads that triggers an alert (overrides config)")
    args = parser.parse_args()

    config = load_config()
    if args.threshold is not None:
        config.read_threshold = args.threshold

    monitor = RunawayMonitor(config=config)

    if args.session:
        for cwd_dir in GROK_SESSIONS.iterdir():
            for s in cwd_dir.iterdir():
                if args.session in s.name:
                    monitor_session(s, monitor)
                    return
        console.print(f"[red]No session matching[/red] {args.session}")
        return

    # Auto-watch latest session
    while True:
        session = find_most_recent_session()
        if session:
            monitor_session(session, monitor)
        else:
            console.print("[yellow]No active Grok sessions found. Sleeping...[/yellow]")
            time.sleep(8)


if __name__ == "__main__":
    cli_main()