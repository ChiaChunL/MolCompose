"""Canonical session recipes and process diagnostics are not interchangeable."""

import asyncio
import json
import re
from pathlib import Path

from molcompose_mcp import server as server_module
from molcompose_mcp.recipe import RecipeLog, build_provenance, read_canonical_recipe


def test_canonical_sidecar_carries_commands_from_before_this_mcp_process(tmp_path):
    sidecar = tmp_path / "figure.cxc"
    sidecar.write_text(
        "# MolCompose recipe\n"
        "molcompose interface A D model #1 distance 4.5\n"
        "molcompose buriedarea model #1\n"
        "molcompose style interface-focus model #1\n",
        encoding="utf-8",
    )
    process = RecipeLog(client_name="Codex")
    process.add("molcompose style interface-focus model #1", "agent:codex")

    canonical = read_canonical_recipe(sidecar)
    record = build_provenance(
        process,
        "0.1.2",
        "0.1.1",
        canonical_commands=canonical,
        scope="session",
    )

    assert [entry["command"] for entry in record["commands"]] == [
        "molcompose interface A D model #1 distance 4.5",
        "molcompose buriedarea model #1",
        "molcompose style interface-focus model #1",
    ]
    assert record["commands"][0]["source"] == "unknown"
    assert record["commands"][-1]["source"] == "agent:codex"
    assert record["recipe_scope"] == "session"
    assert record["canonical_recipe"] is True
    assert record["complete"] is True
    assert "canonical ChimeraX recipe" in record["disclosure_text"]


def test_process_only_provenance_says_it_is_incomplete():
    process = RecipeLog(client_name="Claude Code")
    process.add("molcompose confidence model #1", "agent:claude")
    record = build_provenance(process, "0.1.2", "0.1.1")

    assert record["recipe_scope"] == "process"
    assert record["canonical_recipe"] is False
    assert record["complete"] is False
    assert "not a complete ChimeraX session recipe" in record["disclosure_text"]


def test_export_uses_canonical_sidecar_and_records_effective_sources(tmp_path, monkeypatch):
    target = tmp_path / "figure.png"

    class _ExportingClient:
        def __init__(self, *args, **kwargs):
            self.commands = []

        def run(self, command):
            self.commands.append(command)
            if command.startswith("molcompose export "):
                quoted = re.search(r'"([^"\n]+)"', command)
                image_path = Path(quoted.group(1))
                image_path.write_bytes(b"png")
                image_path.with_suffix(".cxc").write_text(
                    "# Canonical recipe\n"
                    "molcompose interface A D model #1 distance 4.5\n",
                    encoding="utf-8",
                )
            if command == "toolshed list installed":
                return {"log messages": {"note": ["MolCompose (0.1.2)"]}}
            return {"python values": [], "log messages": {}}

    monkeypatch.setattr(server_module, "ChimeraXClient", _ExportingClient)
    monkeypatch.setattr(server_module, "bridge_is_up", lambda *args, **kwargs: True)
    monkeypatch.setattr(server_module, "bundle_is_missing", lambda run: False)
    app = server_module.create_server(
        "http://127.0.0.1:65500",
        source="agent:test",
        launch=False,
    )

    asyncio.run(app.call_tool("list_models", {}))
    asyncio.run(
        app.call_tool(
            "detect_interface",
            {"group_a": ["A"], "group_b": ["D"], "model": "#1"},
        )
    )
    result = asyncio.run(
        app.call_tool("export_figure", {"path": str(target), "save_recipe": True})
    )
    assert result.is_error is False

    record = json.loads(target.with_suffix(".provenance.json").read_text())
    assert record["recipe_scope"] == "session"
    assert [item["command"] for item in record["commands"]] == [
        "molcompose interface A D model #1 distance 4.5"
    ]
    assert record["commands"][0]["source"] == "agent:test"
    process_sources = {item["command"]: item["source"] for item in record["process_commands"]}
    assert process_sources["info models"] == "server"
    assert process_sources["info chains"] == "server"
    assert process_sources["molcompose interface A D model #1 distance 4.5"] == "agent:test"
