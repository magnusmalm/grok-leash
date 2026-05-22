"""
grok_leash/config.py

Small, safe TOML config loader for grok-leash.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "grok-leash" / "config.toml"


@dataclass
class GrokLeashConfig:
    # Core detection
    read_threshold: int = 30
    time_window_minutes: int = 6
    small_limit_threshold: int = 80

    # Notifications
    enable_desktop_notifications: bool = True

    # Actions when threshold crossed
    enable_kill_action: bool = False          # Dangerous - off by default
    write_action_file: bool = True            # Write JSON to ~/.grok-leash/actions/
    notify_parent_via_file: bool = True       # Write structured alert for parent to consume

    # Subagent detection
    warn_on_missing_budget: bool = True
    subagent_spawn_keywords: list[str] = field(default_factory=lambda: [
        "spawn_subagent", "task", "delegate", "subagent"
    ])

    # Misc
    action_dir: Path = Path.home() / ".grok-leash" / "actions"


def load_config(path: Path | None = None) -> GrokLeashConfig:
    """Load config from TOML, falling back to sensible defaults."""
    cfg_path = path or DEFAULT_CONFIG_PATH

    if not cfg_path.exists():
        return GrokLeashConfig()

    try:
        with cfg_path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        print(f"[grok-leash] Warning: failed to load config {cfg_path}: {e}")
        return GrokLeashConfig()

    # Flatten "monitor" and "actions" sections if present
    monitor = data.get("monitor", {})
    actions = data.get("actions", {})
    detection = data.get("detection", {})

    return GrokLeashConfig(
        read_threshold=monitor.get("read_threshold", 30),
        time_window_minutes=monitor.get("time_window_minutes", 6),
        small_limit_threshold=monitor.get("small_limit_threshold", 80),
        enable_desktop_notifications=actions.get("enable_desktop_notifications", True),
        enable_kill_action=actions.get("enable_kill_action", False),
        write_action_file=actions.get("write_action_file", True),
        notify_parent_via_file=actions.get("notify_parent_via_file", True),
        warn_on_missing_budget=detection.get("warn_on_missing_budget", True),
    )


def ensure_action_dir(config: GrokLeashConfig) -> Path:
    """Make sure the actions directory exists."""
    config.action_dir.mkdir(parents=True, exist_ok=True)
    return config.action_dir