"""
grok_leash/actions_watcher.py

Live watcher for the actions directory.

This can be run in a separate terminal (or as a background process) to:
- Surface alerts when grok-leash detects problems
- "Notify the parent" by writing to a well-known file the main Grok session can check
- Optionally trigger stronger actions
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import GrokLeashConfig, load_config, ensure_action_dir

console = Console()

PARENT_ALERTS_FILE = Path.home() / ".grok-leash" / "parent-alerts.jsonl"


class ActionEventHandler(FileSystemEventHandler):
    def __init__(self, config: GrokLeashConfig, on_alert: Callable | None = None):
        super().__init__()
        self.config = config
        self.on_alert = on_alert
        self.seen_files: set[str] = set()

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle_file(Path(event.src_path))

    def on_modified(self, event):
        if event.is_directory:
            return
        self._handle_file(Path(event.src_path))

    def _handle_file(self, path: Path):
        if path.suffix != ".json":
            return
        if str(path) in self.seen_files:
            return

        self.seen_files.add(str(path))

        try:
            data = json.loads(path.read_text())
        except Exception:
            return

        self._process_action(data, path)

    def _process_action(self, data: dict, path: Path):
        """Handle a new action file."""
        action_type = data.get("type", "unknown")

        if action_type == "runaway_read_file":
            self._handle_runaway(data, path)
        else:
            # Generic action
            msg = Text(f"New action: {action_type}")
            console.print(Panel(msg, title="grok-leash Action", border_style="blue"))

    def _handle_runaway(self, data: dict, path: Path):
        session = data.get("session_id", "unknown")
        file_path = data.get("file_path", "?")
        count = data.get("read_count", 0)

        # Terminal alert
        msg = Text()
        msg.append("🚨 RUNAWAY DETECTED (from actions watcher)\n\n", style="bold red")
        msg.append(f"Session: {session}\n")
        msg.append(f"File   : {file_path}\n")
        msg.append(f"Reads  : {count}\n")
        msg.append(f"File   : {path.name}\n")

        panel = Panel(msg, title="[red]grok-leash[/red] - Live Action", border_style="red")
        console.print(panel)

        # Desktop notification
        try:
            from .monitor import send_desktop_notification
            send_desktop_notification(
                "grok-leash: Runaway",
                f"{Path(file_path).name} — {count} reads"
            )
        except Exception:
            pass

        # Notify parent session via well-known file
        if self.config.notify_parent_via_file:
            self._notify_parent(data)

        # Extra: Write a rich "TUI-friendly" notification file
        # The grok-leash skill prefers this file for quick "what's the latest problem?" checks.
        tui_notify_file = Path.home() / ".grok-leash" / "latest-tui-alert.json"
        try:
            enriched = {
                "timestamp": datetime.now().isoformat(),
                "summary": f"Runaway detected: {data.get('details', {}).get('file_path', 'unknown file')}",
                "severity": data.get("details", {}).get("severity", "high"),
                "recommended_action": "Cancel the subagent via the TUI (use Ctrl+C or the session manager)",
                "raw_alert": data
            }
            tui_notify_file.write_text(json.dumps(enriched, indent=2))
        except Exception:
            pass

    def _notify_parent(self, data: dict):
        """Write a structured alert that the parent Grok session can read."""
        PARENT_ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)

        alert = {
            "timestamp": datetime.now().isoformat(),
            "source": "grok-leash-actions-watcher",
            "type": "runaway_detected",
            "details": data,
            "instruction": "A subagent appears to be running away. Check recent activity."
        }

        try:
            with PARENT_ALERTS_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(alert) + "\n")
            console.print(f"[dim]Parent notification written to {PARENT_ALERTS_FILE.name}[/dim]")
        except Exception as e:
            console.print(f"[red]Failed to notify parent:[/red] {e}")


def watch_actions(config: GrokLeashConfig | None = None, live: bool = True):
    """Start watching the actions directory."""
    cfg = config or load_config()
    action_dir = ensure_action_dir(cfg)

    console.print(f"[green]Watching for grok-leash actions in[/green] {action_dir}")

    event_handler = ActionEventHandler(cfg)
    observer = Observer()
    observer.schedule(event_handler, str(action_dir), recursive=False)
    observer.start()

    try:
        if live:
            with Live(Panel("grok-leash actions watcher running...\nPress Ctrl+C to stop.",
                           title="grok-leash"), refresh_per_second=4):
                while True:
                    time.sleep(1)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping watcher...[/yellow]")
    finally:
        observer.stop()
        observer.join()


def cli_watch_actions():
    """Entry point for `grok-leash watch-actions`."""
    import argparse
    parser = argparse.ArgumentParser(description="Watch grok-leash action files live")
    parser.add_argument("--no-live", action="store_true", help="Disable rich live display")
    args = parser.parse_args()

    config = load_config()
    watch_actions(config, live=not args.no_live)


if __name__ == "__main__":
    cli_watch_actions()