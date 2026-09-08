"""PB and GB choice reaches the canonical loader, including assistant routing."""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from molcompose_mcp import server


@pytest.fixture
def energy_server(monkeypatch):
    commands = []

    class Host:
        def __init__(self, *_args):
            pass

        def run(self, command):
            commands.append(command)
            error = None
            if command.startswith("molcompose energy") and " solvation " not in command:
                error = ("this decomposition carries 2 solvation models "
                         "(Generalized Born, Poisson Boltzmann); say which one to read.")
            return {"json values": [], "python values": [],
                    "log messages": {}, "error": error}

    monkeypatch.setattr(server, "ChimeraXClient", Host)
    monkeypatch.setattr(server, "bridge_is_up", lambda *_a, **_kw: True)
    monkeypatch.setattr(server, "bundle_is_missing", lambda _run: False)
    return server.create_server(launch=False), commands


@pytest.mark.parametrize("tool", ["load_energy", "load_external_evidence"])
@pytest.mark.parametrize("solvation", ["pb", "gb"])
def test_explicit_solvation_reaches_same_file_and_map(energy_server, tool, solvation):
    app, commands = energy_server
    arguments = {"path": "/tmp/decomp-rep1.dat", "chains": "A:A,B:B",
                 "model": "#1", "solvation": solvation}
    if tool == "load_external_evidence":
        arguments["kind"] = "energy"
    result = asyncio.run(app.call_tool(tool, arguments))
    assert not result.is_error
    energy = [command for command in commands if command.startswith("molcompose energy")]
    assert energy == [
        'molcompose energy "/tmp/decomp-rep1.dat" chains A:A,B:B '
        f'model #1 solvation {solvation}'
    ]
    if tool == "load_external_evidence":
        assert result.structured_content["status"] == "completed"
        assert isinstance(result.structured_content["result"], dict)


@pytest.mark.parametrize("tool", ["load_energy", "load_external_evidence"])
def test_invalid_solvation_is_rejected_before_host(energy_server, tool):
    app, commands = energy_server
    arguments = {"path": "/tmp/decomp-rep1.dat", "chains": "A:A,B:B",
                 "solvation": "other"}
    if tool == "load_external_evidence":
        arguments["kind"] = "energy"
    with pytest.raises(ToolError, match="solvation"):
        asyncio.run(app.call_tool(tool, arguments))
    assert not commands


@pytest.mark.parametrize("tool", ["load_energy", "load_external_evidence"])
def test_dual_section_file_requests_actionable_choice(energy_server, tool):
    app, commands = energy_server
    arguments = {"path": "/tmp/decomp-rep1.dat", "chains": "A:A,B:B"}
    if tool == "load_external_evidence":
        arguments["kind"] = "energy"
    if tool == "load_energy":
        with pytest.raises(ToolError) as failure:
            asyncio.run(app.call_tool(tool, arguments))
        assert "solvation='pb'" in str(failure.value)
        assert "solvation='gb'" in str(failure.value)
    else:
        result = asyncio.run(app.call_tool(tool, arguments))
        assert not result.is_error
        assert result.structured_content["status"] == "needs_input"
        assert result.structured_content["choices"] == ["pb", "gb"]
        assert "solvation" in result.structured_content["question"]
    assert not any(" solvation " in command for command in commands)
