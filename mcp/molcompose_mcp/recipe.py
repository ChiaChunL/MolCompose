"""Command recipe tracking and figure provenance records."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


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


def disclosure_text(recipe: RecipeLog, molcompose_version: str) -> str:
    return (
        f"This figure was composed with MolCompose v{molcompose_version} in UCSF "
        f"ChimeraX via commands issued through the molcompose-mcp agent interface "
        f"(client: {recipe.client_name}). The complete command log "
        f"({len(recipe.records)} commands) is embedded in this provenance record."
    )


def build_provenance(
    recipe: RecipeLog,
    molcompose_version: str,
    server_version: str,
) -> dict:
    return {
        "molcompose_version": molcompose_version,
        "molcompose_mcp_version": server_version,
        "generated_by": {
            "kind": "agent",
            "client": recipe.client_name,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "commands": [
            {"command": record.command, "timestamp": record.timestamp, "source": record.source}
            for record in recipe.records
        ],
        "disclosure_text": disclosure_text(recipe, molcompose_version),
    }
