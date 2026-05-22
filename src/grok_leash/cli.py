#!/usr/bin/env python3
"""CLI entry point for grok-leash."""

import argparse

from .monitor import cli_main as monitor_cli
from .actions_watcher import cli_watch_actions
from .alerts import check_alerts


def main():
    parser = argparse.ArgumentParser(
        prog="grok-leash",
        description="Safety and monitoring tools for Grok subagents"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Main monitor
    monitor_parser = subparsers.add_parser(
        "monitor", help="Run the main runaway detector (default)"
    )
    monitor_parser.add_argument("--session", help="Specific session id")
    monitor_parser.add_argument("--threshold", type=int, default=30)

    # Actions watcher
    watch_parser = subparsers.add_parser(
        "watch-actions", help="Live tail the actions directory and surface alerts"
    )
    watch_parser.add_argument("--no-live", action="store_true",
                              help="Disable rich live display")

    # Quick alerts checker (very useful for parent sessions)
    check_parser = subparsers.add_parser(
        "check-alerts", help="Quickly show recent alerts from parent-alerts.jsonl"
    )
    check_parser.add_argument("--minutes", type=int, default=60,
                              help="How far back to look for alerts")
    check_parser.add_argument("--json", action="store_true",
                              help="Output raw JSON instead of pretty table")

    args = parser.parse_args()

    if args.command == "watch-actions":
        cli_watch_actions()
    elif args.command == "check-alerts":
        check_alerts(minutes=args.minutes, json_output=args.json)
    else:
        # Default to monitor
        monitor_cli()


if __name__ == "__main__":
    main()