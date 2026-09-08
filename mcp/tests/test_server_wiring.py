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
    app = server_module.create_server("http://127.0.0.1:65500", source="agent:codex", launch=False)
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
    app = server_module.create_server("http://127.0.0.1:65500", source="agent:codex", launch=False)
    asyncio.run(app.call_tool("open_structure", {"path_or_id": "1brs"}))

    issued = [c for client in stub_client for c in client.commands]
    assert issued, "no command was sent"
    # The bundle probe runs before anything else and is not part of the
    # session: it asks ChimeraX whether it has the command at all, and is not
    # attributed to anyone because it does nothing.
    assert issued[0] == "usage molcompose"
    assert issued[1] == "molcompose source agent:codex"
    assert issued[2].startswith("open ")


def test_create_server_takes_the_source_by_keyword():
    """The panel passes it by name; a positional-only signature would break it."""
    parameters = inspect.signature(server_module.create_server).parameters
    assert "source" in parameters
    assert parameters["source"].default == "agent"


def test_every_preset_the_tool_accepts_is_named_in_its_description(stub_client):
    """A preset the description omits is one an agent can only reach by guessing.

    `apply_style` takes a free-form string — there is no enum to constrain it —
    so its docstring is the entire discovery surface. It listed eight of
    sixteen. The missing half included paratope-closeup, and asking an agent
    for it by the panel's name for it, "Interface (binder loop)", gave it
    nothing to map from: neither that phrase nor the slug appeared anywhere in
    the tool contract.

    This fails whenever a preset is added and the docstring is not.
    """
    import asyncio

    from molcompose_mcp.server import PRESETS

    app = server_module.create_server("http://127.0.0.1:65500", launch=False)
    tool = {t.name: t for t in asyncio.run(app.list_tools())}["apply_style"]
    described = tool.description or ""

    missing = sorted(name for name in PRESETS if name not in described)
    assert not missing, "presets apply_style accepts and does not describe: " + ", ".join(missing)


def test_the_instructions_do_not_point_at_anything_that_is_not_there():
    """A URI in the instructions is a promise every client is handed.

    `instructions` reaches every client at connect, so a line telling an agent
    to read `molcompose://skill` is read by all of them — and there were no
    resources registered at all, so every one of them would have looked and
    found nothing. This is the same failure the tool descriptions were audited
    for, arriving through the one surface that is not a tool.
    """
    import asyncio
    import re

    app = server_module.create_server("http://127.0.0.1:65500", launch=False)
    text = app.instructions or ""
    promised = set(re.findall(r"molcompose://[\w/-]+", text))
    served = {str(r.uri) for r in asyncio.run(app.list_resources())}
    assert promised <= served, (
        "instructions name resources the server does not serve: "
        + ", ".join(sorted(promised - served))
    )


def test_the_skill_resource_serves_the_file_that_ships_in_the_wheel():
    """The skill reaches an agent without anyone installing it.

    A skill file copied into a directory by hand reaches only clients that
    have such a directory, and only users who went looking. Serving it as a
    resource reaches anything that speaks MCP with nothing asked of the
    person. That only works if the file is in the wheel: a resource reading
    `skill/SKILL.md` would find nothing on an installed copy, because that
    path exists only in the repository.
    """
    import asyncio
    import tomllib
    from pathlib import Path

    package = Path(server_module.__file__).with_name("SKILL.md")
    assert package.is_file(), "SKILL.md is not beside the module that serves it"

    config = tomllib.load((Path(server_module.__file__).parents[1] / "pyproject.toml").open("rb"))
    declared = config["tool"]["setuptools"]["package-data"]["molcompose_mcp"]
    assert "SKILL.md" in declared, "not declared as package data, so the wheel omits it"

    app = server_module.create_server("http://127.0.0.1:65500", launch=False)
    served = {str(r.uri) for r in asyncio.run(app.list_resources())}
    assert "molcompose://skill" in served

    body = list(asyncio.run(app.read_resource("molcompose://skill")))[0].content
    assert body == package.read_text(encoding="utf-8")
    assert "name: molcompose" in body


def test_the_two_copies_of_the_skill_are_identical():
    """One is browsed, one is shipped, and they are the same words.

    skill/SKILL.md is what a person reads on the repository page;
    molcompose_mcp/SKILL.md is what the wheel carries and the resource serves.
    Editing either alone would give an agent different guidance from the one
    the maintainer is reading.
    """
    from pathlib import Path

    shipped = Path(server_module.__file__).with_name("SKILL.md")
    browsed = Path(server_module.__file__).parents[2] / "skill" / "SKILL.md"
    assert browsed.is_file(), browsed
    assert shipped.read_bytes() == browsed.read_bytes(), (
        "skill/SKILL.md and mcp/molcompose_mcp/SKILL.md have drifted"
    )
