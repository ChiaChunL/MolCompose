"""Reject dangerous native semantics, including host keyword abbreviations."""

import asyncio

import pytest
from molcompose_mcp.server import native_allowed
from test_structure_safety import registered as registered

UNSAFE = [
    "turn y 90 atoms #1", "turn y 90 a #1", "turn y 90 mod #1",
    "turn y 90 models #1", "roll y 1 atoms #1", "roll y 1 mod #1",
    "rock y 30 atoms #1", "rock y 30 mod #1", "move x 5 mod #1",
    "info models saveF /tmp/unsafe.txt", "info chains s /tmp/unsafe.txt",
    'turn y 90 "atoms" #1', "turn y 90 'models' #1",
    'info models "saveF" /tmp/unsafe.txt', "turn y 90 at\\oms #1",
    "view initial #1", "view ini #1", "view position #1 sameAsModels #2",
    "view matrix models #1,1,0,0,0,1,0,0,0,1,0,0,0", "view saved-view",
    "info notify start models listener url http://example.invalid",
    "color alias red blue", "measure rotation #1 toModel #2",
    "turn y 30; version", "turn y 30\nversion", "turn y 30\rversion",
    "turn y 30\tmodels #1", "version\x00", "version\x1b", "version\x7f",
    "turn $axis 30", "v #1", "view #1 cl true", "lighting sof",
    # Malformed objectspecs make native Or(ObjectsArg, NamedViewArg) retry
    # a saved view with the same name, which restores model placements.
    "view #1:---", "view #1:,,", "view #1:1,", "view #1:,1",
    "view #1:1,,2", "view #1:1-", "view #1:--2", "view #1:1---2",
    "view #1/A,", "view #1/,A", "view #1/A,,B", "view #1@CA,",
    "view #1@,CA", "view #1@CA,,CB", "view #1,@CA", "view #1,#2",
    "view #123456", "view #1.123456", "view #١", "view #１",
    "view #1/İ", "view #1@K", "view 10", "view ALL", "view protein",
]

SAFE = [
    "view", "view #1", "view #1/A clip false", "view #1 orient",
    "turn y 30", "turn x -45 10", "roll z 1 20", "rock y 15 30",
    "turn y 30 center 0,0,0 coordinateSystem #1", "zoom 1.5", "zoom 2 10",
    "select clear", "select #1/A:10-20", "select add #1/B",
    "show #1 cartoons", "hide #1 atoms", "color #1/A red",
    "color #1 #ff0000 target c", "info models", "info chains #1",
    "info residues #1/A", "info atoms #1/A:10", "version", "version verbose",
    "lighting soft", "lighting shadows true", "graphics bgColor white",
    "graphics silhouettes true width 1", "graphics quality 2", "stop",
    "view #1/A,B:-10--2,-1,0,1-10@CA,CB 10", "view #1,2",
    "view #1#2", "view #1.2/A:10-20", "view #99999.99999",
]


@pytest.mark.parametrize("command", UNSAFE)
def test_native_grammar_rejects_dangerous_or_unlisted_forms(command):
    assert not native_allowed(command)


@pytest.mark.parametrize("command", UNSAFE)
def test_registered_native_rejects_before_bridge(registered, command):
    build, client = registered
    try:
        asyncio.run(build("expert").call_tool("run_native", {"command": command}))
    except Exception:
        pass
    assert command not in client.commands


@pytest.mark.parametrize("command", SAFE)
def test_registered_native_preserves_supported_display(registered, command):
    build, client = registered
    assert native_allowed(command)
    result = asyncio.run(build("expert").call_tool("run_native", {"command": command}))
    assert not result.is_error
    assert command in client.commands
