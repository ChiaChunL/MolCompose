"""An export must not overwrite sidecars or invent command occurrence identity."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from molcompose_mcp import server
from molcompose_mcp.recipe import CommandRecord, RecipeLog, build_provenance


def exporting_app(monkeypatch, target, *, race_sidecar=False):
    issued = []

    class Exporter:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, command):
            issued.append(command)
            if command.startswith("molcompose export "):
                target.write_bytes(b"new image")
                if "saveRecipe true" in command:
                    target.with_suffix(".cxc").write_text(
                        "molcompose style clean-cartoon model #1\n"
                    )
                if race_sidecar:
                    target.with_suffix(".provenance.json").write_text("concurrent owner")
            if command == "toolshed list installed":
                return {"log messages": {"note": ["MolCompose (0.1.3)"]}}
            return {"python values": [], "log messages": {}}

    monkeypatch.setattr(server, "ChimeraXClient", Exporter)
    monkeypatch.setattr(server, "bridge_is_up", lambda *args, **kwargs: True)
    monkeypatch.setattr(server, "bundle_is_missing", lambda run: False)
    return server.create_server(launch=False), issued


@pytest.mark.parametrize("suffix,options", [
    (".provenance.json", {}),
    (".cxc", {"save_recipe": True}),
    (".cxs", {"save_session": True}),
    (".png", {}),
])
def test_existing_export_target_is_preserved_before_host_execution(
    monkeypatch, tmp_path, suffix, options
):
    target = tmp_path / "figure.png"
    existing = target.with_suffix(suffix)
    existing.write_text("previous owner")
    app, issued = exporting_app(monkeypatch, target)

    with pytest.raises(ToolError, match="already exists"):
        asyncio.run(app.call_tool("export_figure", {"path": str(target), **options}))
    assert existing.read_text() == "previous owner"
    assert not any(command.startswith("molcompose export ") for command in issued)
    if existing != target:
        assert not target.exists()


def test_explicit_overwrite_replaces_provenance(monkeypatch, tmp_path):
    target = tmp_path / "figure.png"
    sidecar = target.with_suffix(".provenance.json")
    sidecar.write_text("previous owner")
    app, _issued = exporting_app(monkeypatch, target)

    reply = asyncio.run(app.call_tool("export_figure", {"path": str(target), "overwrite": True}))

    assert not reply.is_error
    assert target.read_bytes() == b"new image"
    assert json.loads(sidecar.read_text())["molcompose_version"] == "0.1.3"


def test_sidecar_created_during_export_is_not_overwritten(monkeypatch, tmp_path):
    target = tmp_path / "figure.png"
    app, _issued = exporting_app(monkeypatch, target, race_sidecar=True)

    with pytest.raises(ToolError, match="exists"):
        asyncio.run(app.call_tool("export_figure", {"path": str(target)}))
    assert target.with_suffix(".provenance.json").read_text() == "concurrent owner"


def test_dangling_sidecar_link_is_not_followed(monkeypatch, tmp_path):
    target = tmp_path / "figure.png"
    outside = tmp_path / "unrelated.json"
    target.with_suffix(".provenance.json").symlink_to(outside)
    app, issued = exporting_app(monkeypatch, target)

    with pytest.raises(ToolError, match="already exists"):
        asyncio.run(app.call_tool("export_figure", {"path": str(target)}))
    assert not outside.exists()
    assert not target.exists()
    assert not any(command.startswith("molcompose export ") for command in issued)


@pytest.mark.parametrize("suffix", [".png", ".provenance.json", ".cxc"])
def test_assistant_confirms_dangling_export_target(monkeypatch, tmp_path, suffix):
    target = tmp_path / "figure.png"
    existing = target.with_suffix(suffix)
    linked_target = tmp_path / "confirmed-target"
    existing.symlink_to(linked_target)
    app, issued = exporting_app(monkeypatch, target)

    initial = asyncio.run(app.call_tool("export_artifact", {"path": str(target)}))
    assert initial.structured_content["status"] == "needs_confirmation"
    assert str(existing) in initial.structured_content["choices"]
    assert not linked_target.exists()
    assert not any(command.startswith("molcompose export ") for command in issued)

    confirmed = asyncio.run(app.call_tool("export_artifact", {
        "path": str(target), "confirmed_overwrite": True,
    }))
    assert confirmed.structured_content["status"] == "completed"
    assert linked_target.exists()
    assert confirmed.structured_content["qa"]["passed"]


@pytest.mark.parametrize("observations", [1, 2])
def test_repeated_canonical_commands_have_no_guessed_occurrence_attribution(observations):
    command = "molcompose style clean-cartoon model #1"
    process = RecipeLog(records=[
        CommandRecord(command, f"2026-09-08T08:00:0{n}+00:00", "agent:test")
        for n in range(observations)
    ])
    record = build_provenance(process, "0.1.3", "0.1.2", canonical_commands=[
        command, "molcompose interface A B model #1 distance 4.5", command,
    ], scope="session")

    for index in (0, 2):
        assert record["commands"][index]["source"] == "unknown"
        assert record["commands"][index]["timestamp"] is None
    assert len(record["process_commands"]) == observations


def test_repeated_process_observations_do_not_guess_a_deduplicated_occurrence():
    command = "molcompose style clean-cartoon model #1"
    process = RecipeLog(records=[
        CommandRecord(command, "2026-09-08T08:00:00+00:00", "agent:first"),
        CommandRecord(command, "2026-09-08T08:00:01+00:00", "agent:second"),
    ])
    record = build_provenance(
        process, "0.1.3", "0.1.2", canonical_commands=[command], scope="session"
    )

    assert record["commands"][0]["source"] == "unknown"
    assert record["commands"][0]["timestamp"] is None


def test_unique_command_match_retains_observed_identity():
    command = "molcompose style clean-cartoon model #1"
    process = RecipeLog(records=[CommandRecord(command, "2026-09-08T08:00:00+00:00", "agent:test")])
    record = build_provenance(
        process, "0.1.3", "0.1.2", canonical_commands=[command], scope="session"
    )

    assert record["commands"][0] == {
        "command": command, "timestamp": "2026-09-08T08:00:00+00:00", "source": "agent:test",
    }
