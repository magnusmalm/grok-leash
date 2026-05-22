"""Basic tests for grok-leash monitor."""

import pytest
from grok_leash.monitor import RunawayMonitor


def test_read_counting():
    monitor = RunawayMonitor(read_threshold=5)
    line = '{"tool": "read_file", "file_path": "/tmp/test.c", "limit": 5}'

    for _ in range(4):
        monitor.process_line(line, "test-session")

    assert monitor.read_counts["test-session:/tmp/test.c"] == 4


def test_alert_threshold():
    """Just a smoke test that the class doesn't crash."""
    monitor = RunawayMonitor(read_threshold=3)
    line = '{"tool": "read_file", "file_path": "/tmp/foo.py", "limit": 5}'

    for i in range(5):
        monitor.process_line(line, "sess-123")

    # Should have triggered internally (we don't capture output here)
    assert monitor.read_counts["sess-123:/tmp/foo.py"] >= 3