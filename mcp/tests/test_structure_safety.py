"""Structure-only policy is enforced at both registered MCP entry points."""

import asyncio

import pytest
from molcompose_mcp import server


class RecordingClient:
    def __init__(self, *args, **kwargs):
        self.commands = []

    def run(self, command):
        self.commands.append(command)
        return {"json values": [], "python values": [], "log messages": {}}


@pytest.fixture
def registered(monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(server, "ChimeraXClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(server, "bundle_is_missing", lambda run: False)
    return lambda profile: server.create_server(
        "http://127.0.0.1:65500", launch=False, profile=profile
    ), client


@pytest.mark.parametrize("profile", ["assistant", "expert"])
@pytest.mark.parametrize("path", [
    "inert.py.gz", "inert.py.bz2", "inert.py.xz", "inert.pyo",
    "inert.pyc.gz", "inert.cxc.gz", "session.cxs", "session.cxs.gz",
    "unknown.dat", "https://example.invalid/structure.pdb", "python:inert.pdb",
    'inert.pdb" format python', "inert.pdb format python", "inert.py#x",
    "inert.py.gz.gz", "inert.pdb; version", "inert\npdb.pdb",
    "inert\x00.pdb", "$input.pdb", "*.pdb",
])
def test_registered_structure_open_rejects_nonstructure_dispatch(registered, profile, path):
    build, client = registered
    app = build(profile)
    try:
        asyncio.run(app.call_tool("open_structure", {"path_or_id": path}))
    except Exception:
        pass
    assert not any(command.startswith("open ") for command in client.commands)


@pytest.mark.parametrize("profile", ["assistant", "expert"])
@pytest.mark.parametrize("path", [
    "1brs", "1BRS", "pdb:1brs", "/tmp/a b.pdb", "model.cif", "model.mmcif",
    "model.pdb.gz", "model.pdb.bz2", "model.pdb.xz", "model.cif.gz",
    "model.cif.bz2", "model.mmcif.xz", "model.ent", "model.pqr", "ligand.sdf",
])
def test_registered_structure_open_preserves_data_and_identifiers(registered, profile, path):
    build, client = registered
    result = asyncio.run(build(profile).call_tool("open_structure", {"path_or_id": path}))
    assert not result.is_error
    assert f'open "{path}"' in client.commands
