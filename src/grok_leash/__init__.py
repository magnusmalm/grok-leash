"""
grok-leash - Real-time monitoring and safety for Grok subagents.

Prevents the kind of runaway read_file loops that caused the May 2026
~750M token incident.
"""

__version__ = "0.1.0"

from .config import GrokLeashConfig, load_config
from .monitor import RunawayMonitor, monitor_session

__all__ = ["GrokLeashConfig", "load_config", "RunawayMonitor", "monitor_session"]