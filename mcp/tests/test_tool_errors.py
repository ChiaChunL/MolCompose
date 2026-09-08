"""Recoverable tool errors remain actionable without echoing credentials."""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from molcompose_mcp import server
from molcompose_mcp.chimerax import ChimeraXCommandError, ChimeraXUnavailable


def error_app(monkeypatch, error):
    class Host:
        def __init__(self, *_args):
            pass

        def run(self, command):
            if command.startswith("molcompose source "):
                return {"error": None}
            raise error

    monkeypatch.setattr(server, "ChimeraXClient", Host)
    monkeypatch.setattr(server, "bridge_is_up", lambda *_a, **_kw: True)
    monkeypatch.setattr(server, "bundle_is_missing", lambda _run: False)
    return server.create_server(launch=False)


@pytest.mark.parametrize(("name", "arguments"), [
    ("list_models", {}),
    ("open_structure", {"path_or_id": "1brs"}),
])
@pytest.mark.parametrize("error", [
    ChimeraXCommandError("info models", "Select a structure before retrying."),
    ChimeraXUnavailable("Start the ChimeraX bridge before retrying."),
    ValueError("Select a valid chain before retrying."),
    FileExistsError("The export already exists; choose another name before retrying."),
])
def test_expected_errors_retain_recovery_instructions(monkeypatch, name, arguments, error):
    app = error_app(monkeypatch, error)

    with pytest.raises(ToolError) as failure:
        asyncio.run(app.call_tool(name, arguments))

    assert str(error) in str(failure.value)


@pytest.mark.parametrize("credential", [
    "Authorization: Bearer private-test-credential",
    "Authorization: Basic private-test-credential",
    "Authorization: Custom private-test-credential",
    '"api_key": "private-test-credential"',
    "api-key='private-test-credential'",
])
def test_expected_errors_redact_credentials_but_keep_recovery(monkeypatch, credential):
    app = error_app(monkeypatch, ChimeraXCommandError(
        "info models", f"Request refused ({credential}); retry after checking access."
    ))

    with pytest.raises(ToolError) as failure:
        asyncio.run(app.call_tool("list_models", {}))

    message = str(failure.value)
    assert "retry after checking access" in message
    assert "private-test-credential" not in message
    assert "[REDACTED]" in message


def test_programming_errors_remain_unexpected_exceptions(monkeypatch):
    original = TypeError("unexpected host implementation bug")
    app = error_app(monkeypatch, original)

    with pytest.raises(ToolError) as failure:
        asyncio.run(app.call_tool("list_models", {}))

    # Do not reclassify a programming bug as a deliberately exposed tool error.
    assert failure.value.__cause__ is original
