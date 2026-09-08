"""Process diagnostics and canonical ChimeraX figure provenance records."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class CommandRecord:
    command: str
    timestamp: str
    source: str  # "agent" | "server"


@dataclass
class RecipeLog:
    client_name: str = "unknown"
    records: list[CommandRecord] = field(default_factory=list)

    def add(self, command: str, source: str = "agent") -> None:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        self.records.append(CommandRecord(command, stamp, source))

    def commands(self) -> list[str]:
        return [record.command for record in self.records]


def read_canonical_recipe(path: str | Path) -> list[str]:
    """Read replayable commands from a bundle-written ``.cxc`` sidecar."""
    commands = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        command = line.strip()
        if command and not command.startswith("#"):
            commands.append(command)
    return commands


def disclosure_text(
    recipe: RecipeLog,
    molcompose_version: str,
    *,
    command_count: int | None = None,
    scope: Literal["session", "process"] = "process",
) -> str:
    count = len(recipe.records) if command_count is None else command_count
    prefix = (
        f"This figure was composed with MolCompose v{molcompose_version} in UCSF "
        f"ChimeraX via commands issued through the molcompose-mcp agent interface "
        f"(client: {recipe.client_name}). "
    )
    if scope == "session":
        return (
            f"{prefix}The canonical ChimeraX recipe ({count} commands) is "
            "embedded in this provenance record and written as a replayable .cxc sidecar."
        )
    return (
        f"{prefix}This record includes {count} commands observed by this MCP "
        "process; it is not a complete ChimeraX session recipe."
    )


def _records(records: Sequence[CommandRecord]) -> list[dict]:
    return [
        {
            "command": record.command,
            "timestamp": record.timestamp,
            "source": record.source,
        }
        for record in records
    ]


def _canonical_records(
    commands: Sequence[str],
    process_records: Sequence[CommandRecord],
) -> list[dict]:
    # A replayable .cxc has command strings, not occurrence IDs. Repetition
    # in either record makes a timestamp/source match ambiguous (including
    # deduplication and model-ID reuse), so do not guess with FIFO matching.
    canonical_counts = Counter(commands)
    observed = defaultdict(list)
    for record in process_records:
        observed[record.command].append(record)
    result = []
    for command in commands:
        matches = observed.get(command)
        record = (
            matches[0]
            if canonical_counts[command] == 1 and matches and len(matches) == 1
            else None
        )
        result.append(
            {
                "command": command,
                "timestamp": record.timestamp if record else None,
                "source": record.source if record else "unknown",
            }
        )
    return result


def build_provenance(
    recipe: RecipeLog,
    molcompose_version: str,
    server_version: str,
    *,
    canonical_commands: Sequence[str] | None = None,
    scope: Literal["session", "process"] = "process",
) -> dict:
    if scope == "session" and canonical_commands is None:
        raise ValueError("session provenance requires canonical_commands")
    commands = (
        _canonical_records(canonical_commands, recipe.records)
        if canonical_commands is not None
        else _records(recipe.records)
    )
    return {
        "molcompose_version": molcompose_version,
        "molcompose_mcp_version": server_version,
        "generated_by": {
            "kind": "agent",
            "client": recipe.client_name,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "recipe_scope": scope,
        "canonical_recipe": scope == "session",
        "complete": scope == "session",
        "commands": commands,
        "process_commands": _records(recipe.records),
        "disclosure_text": disclosure_text(
            recipe,
            molcompose_version,
            command_count=len(commands),
            scope=scope,
        ),
    }
