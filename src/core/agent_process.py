"""Small, dependency-free helpers for stopping an Agent CLI process tree."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Iterable


def descendant_pids(
    root_pid: int, process_rows: Iterable[tuple[int, int]]
) -> tuple[int, ...]:
    """Return descendants in post-order so grandchildren are stopped first."""
    children: dict[int, list[int]] = {}
    for pid, parent_pid in process_rows:
        children.setdefault(parent_pid, []).append(pid)

    ordered = []
    visited = {root_pid}

    def visit(parent_pid: int) -> None:
        for child_pid in children.get(parent_pid, ()):
            if child_pid in visited:
                continue
            visited.add(child_pid)
            visit(child_pid)
            ordered.append(child_pid)

    visit(root_pid)
    return tuple(ordered)


def _process_rows(runner: Callable) -> tuple[tuple[int, int], ...]:
    try:
        result = runner(
            ["ps", "-axo", "pid=,ppid="],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    rows = []
    for line in getattr(result, "stdout", "").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1])))
        except ValueError:
            continue
    return tuple(rows)


def terminate_process_tree(
    root_pid: int,
    *,
    grace_seconds: float = 1.0,
    runner: Callable = subprocess.run,
    send_signal: Callable[[int, int], None] = os.kill,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Send TERM child-first, then KILL only processes that remain alive."""
    if root_pid <= 0:
        return
    targets = (*descendant_pids(root_pid, _process_rows(runner)), root_pid)
    for pid in targets:
        try:
            send_signal(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            continue
    sleeper(max(0.0, grace_seconds))
    survivors = []
    for pid in targets:
        try:
            send_signal(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass
        survivors.append(pid)
    for pid in survivors:
        try:
            send_signal(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            continue
