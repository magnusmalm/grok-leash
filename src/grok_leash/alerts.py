"""
grok_leash/alerts.py

Utilities for reading and presenting grok-leash alerts.
Used by the CLI (`grok-leash check-alerts`) and by the grok-leash skill.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

PARENT_ALERTS_FILE = Path.home() / ".grok-leash" / "parent-alerts.jsonl"
ACKNOWLEDGED_FILE = Path.home() / ".grok-leash" / "acknowledged.jsonl"
ACTIONS_DIR = Path.home() / ".grok-leash" / "actions"
LATEST_TUI_ALERT = Path.home() / ".grok-leash" / "latest-tui-alert.json"


def load_recent_alerts(minutes: int = 60, include_acknowledged: bool = False) -> List[Dict[str, Any]]:
    """Return alerts from the last N minutes (optionally filtering acknowledged ones)."""
    if not PARENT_ALERTS_FILE.exists():
        return []

    acknowledged = _load_acknowledged_set()
    cutoff = datetime.now() - timedelta(minutes=minutes)
    alerts = []

    try:
        with PARENT_ALERTS_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    ts = data.get("timestamp")
                    if not ts:
                        continue

                    alert_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if alert_time < cutoff:
                        continue

                    alert_id = _make_alert_id(data)
                    if not include_acknowledged and alert_id in acknowledged:
                        continue

                    data["_id"] = alert_id  # attach stable ID for acknowledgment
                    alerts.append(data)
                except Exception:
                    continue
    except Exception:
        pass

    return alerts


def _make_alert_id(alert: Dict[str, Any]) -> str:
    """Create a stable ID for an alert (used for acknowledgment tracking)."""
    details = alert.get("details", {})
    session = details.get("session_id", alert.get("session", "unknown"))
    ts = alert.get("timestamp", "")
    file_path = details.get("file_path", "")
    return f"{session}|{ts}|{file_path}"


def _load_acknowledged_set() -> set:
    """Load set of acknowledged alert IDs."""
    if not ACKNOWLEDGED_FILE.exists():
        return set()

    acknowledged = set()
    try:
        with ACKNOWLEDGED_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "_id" in data:
                        acknowledged.add(data["_id"])
                except Exception:
                    continue
    except Exception:
        pass
    return acknowledged


def acknowledge_alert(alert: Dict[str, Any]) -> bool:
    """Mark a specific alert as acknowledged (writes to acknowledged.jsonl)."""
    ACKNOWLEDGED_FILE.parent.mkdir(parents=True, exist_ok=True)

    alert_id = alert.get("_id") or _make_alert_id(alert)
    record = {
        "_id": alert_id,
        "timestamp": datetime.now().isoformat(),
        "original_alert": alert
    }

    try:
        with ACKNOWLEDGED_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return True
    except Exception as e:
        print(f"Failed to acknowledge alert: {e}")
        return False


def print_alerts_summary(alerts: List[Dict[str, Any]], console: Console | None = None):
    """Pretty print a list of alerts with their IDs (for acknowledgment)."""
    if console is None:
        console = Console()

    if not alerts:
        console.print("[green]No recent grok-leash alerts found.[/green]")
        return

    console.print(f"\n[bold red]grok-leash Alerts[/bold red] ({len(alerts)} recent)\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID (short)", style="dim")
    table.add_column("Time", style="dim")
    table.add_column("Session", style="cyan")
    table.add_column("Problem", style="yellow")
    table.add_column("Severity")

    for alert in alerts[-10:]:
        alert_id = alert.get("_id", "")
        short_id = alert_id.split("|")[0][:8] + "..." if "|" in alert_id else alert_id[:12]

        ts = alert.get("timestamp", "")[:19].replace("T", " ")
        details = alert.get("details", {})
        session = details.get("session_id", alert.get("session", "unknown"))[:12] + "..."
        problem = details.get("file_path", "?")
        if "read_count" in details:
            problem += f" ({details['read_count']} reads)"

        severity = details.get("severity", "medium")
        sev_style = "red" if severity == "high" else "yellow"

        table.add_row(short_id, ts, session, problem, f"[{sev_style}]{severity}[/{sev_style}]")

    console.print(table)

    # Show the most recent one in detail with full ID
    latest = alerts[-1]
    details = latest.get("details", {})
    full_id = latest.get("_id", "N/A")
    console.print(Panel(
        f"[bold]Latest Alert[/bold]  (ID: {full_id})\n\n"
        f"Session: {details.get('session_id')}\n"
        f"File:    {details.get('file_path')}\n"
        f"Reads:   {details.get('read_count')}\n"
        f"Instruction: {latest.get('instruction', 'Check the subagent')}\n\n"
        f"[dim]To acknowledge: Use the grok-leash skill with this ID[/dim]",
        title="Most Recent",
        border_style="red"
    ))


def check_alerts(minutes: int = 60, json_output: bool = False, include_acknowledged: bool = False):
    """Main function for `grok-leash check-alerts`."""
    alerts = load_recent_alerts(minutes, include_acknowledged=include_acknowledged)

    if json_output:
        print(json.dumps(alerts, indent=2))
        return

    console = Console()
    print_alerts_summary(alerts, console)

    if alerts:
        console.print("\n[dim]Tip: Ask the main agent to 'run the grok-leash skill' for interactive acknowledgment.[/dim]\n")


def cli_check_alerts():
    """Entry point for the `grok-leash check-alerts` command."""
    import argparse

    parser = argparse.ArgumentParser(description="Quickly show recent grok-leash alerts")
    parser.add_argument("--minutes", type=int, default=60,
                        help="Look back this many minutes")
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON")
    parser.add_argument("--show-acknowledged", action="store_true",
                        help="Include already acknowledged alerts")
    args = parser.parse_args()

    check_alerts(minutes=args.minutes, json_output=args.json, include_acknowledged=args.show_acknowledged)


def cli_acknowledge():
    """Entry point for acknowledging alerts (can be called from skill or CLI)."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Acknowledge a grok-leash alert")
    parser.add_argument("alert_id", help="The alert ID (from check-alerts output)")
    args = parser.parse_args()

    # For now, a simple implementation: user pastes the ID
    # In practice the skill will pass structured data
    alert = {"_id": args.alert_id}
    success = acknowledge_alert(alert)
    if success:
        print(f"Acknowledged: {args.alert_id}")
    else:
        print("Failed to acknowledge.")
        sys.exit(1)


if __name__ == "__main__":
    # Allow `python -m grok_leash.alerts check` or similar in future
    cli_check_alerts()