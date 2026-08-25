"""Every registered tool, called once, against a ChimeraX that answers nothing.

The suite this sits beside tests the pure functions — the ones that build a
command string out of arguments — and never assembles the server. That left
the wiring between them untested, and it broke: renaming `_invoke`'s `source`
parameter to `_source` to stop it shadowing the enclosing name updated the two
definitions and missed four call sites, so `list_models`, `render_preview` and
the bundle-version lookup raised `TypeError` on their first line. The whole
suite passed.

What this asks of each tool is only that it reaches ChimeraX: the fake client
returns an empty payload, so a tool may well report that it found nothing. A
`TypeError`, `NameError` or `AttributeError` is different in kind — it means
the call never got as far as the wire, which is the failure that hid here.
"""

import asyncio
import inspect

import pytest
from molcompose_mcp import server as server_module

WIRING_ERRORS = (TypeError, NameError, AttributeError)

# Arguments good enough to satisfy the schema. The values are not exercised;
# the fake ChimeraX answers everything the same way.
ARGUMENTS = {
    "path_or_id": "1brs",
    "group_a": ["A"],
    "group_b": ["D"],
    "chain": "A",
    "chains": ["A"],
    "preset": "cartoon-clean",
    "criterion": "contact",
    "cutoff": 4.5,
    "path": "/tmp/molcompose-test-input.json",
    "output_path": "/tmp/molcompose-test-output.png",
    "command": "show cartoon",
    "model_id": "#1",
    "reference": "1brs",
    "top_n": 5,
    "width": 400,
    "height": 300,
}


class _Nothing:
    """A ChimeraX that is reachable and has nothing to say."""

    def __init__(self, *args, **kwargs):
        self.commands = []

    def run(self, command):
        self.commands.append(command)
        return {"json values": [], "python values": [], "log messages": {}}


@pytest.fixture
def stub_client(monkeypatch):
    calls = []

    def factory(*args, **kwargs):
        client = _Nothing()
        calls.append(client)
        return client

    monkeypatch.setattr(server_module, "ChimeraXClient", factory)
    return calls


def _arguments_for(tool):
    schema = tool.input_schema or {}
    required = set(schema.get("required", ()))
    supplied = {}
    for name in schema.get("properties", ()):
        if name in ARGUMENTS:
            supplied[name] = ARGUMENTS[name]
        elif name in required:
            supplied[name] = "A"
    return supplied


def test_every_registered_tool_reaches_chimerax(stub_client):
    app = server_module.create_server("http://127.0.0.1:65500", source="agent:codex")
    tools = asyncio.run(app.list_tools())
    assert tools, "the server registered no tools at all"

    broken = []
    for tool in tools:
        try:
            asyncio.run(app.call_tool(tool.name, _arguments_for(tool)))
        except Exception as error:  # noqa: BLE001 - the point is what kind
            cause = error.__cause__ or error
            if isinstance(cause, WIRING_ERRORS):
                broken.append(f"{tool.name}: {type(cause).__name__}: {cause}")
    assert not broken, "tools that never reached ChimeraX:\n  " + "\n  ".join(broken)


def test_the_source_is_declared_to_the_bundle_before_the_command(stub_client):
    """The provenance name has to arrive first, or it attributes the wrong turn.

    `molcompose source …` arms a one-shot declaration that the next command
    consumes, so the order is the whole mechanism.
    """
    app = server_module.create_server("http://127.0.0.1:65500", source="agent:codex")
    asyncio.run(app.call_tool("open_structure", {"path_or_id": "1brs"}))

    issued = [c for client in stub_client for c in client.commands]
    assert issued, "no command was sent"
    assert issued[0] == "molcompose source agent:codex"


def test_create_server_takes_the_source_by_keyword():
    """The panel passes it by name; a positional-only signature would break it."""
    parameters = inspect.signature(server_module.create_server).parameters
    assert "source" in parameters
    assert parameters["source"].default == "agent"
