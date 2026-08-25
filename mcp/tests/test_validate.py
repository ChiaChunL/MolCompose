"""What an agent may put inside a ChimeraX command.

Each test here is a shape that used to reach ChimeraX unexamined. The server
interpolates every typed tool's arguments into a command string, so before
`validate.py` the word "typed" named the parameter and not its contents:
`model="#1; delete all"` was a working way to run `delete all`.
"""

import pytest
from molcompose_mcp.server import build_interface_command, native_allowed
from molcompose_mcp.validate import (
    InvalidArgument,
    chain_ids,
    chain_map,
    model_spec,
    structure_path,
)


@pytest.mark.parametrize("value", ["#1", "#2", "#1.2", "#1.2.3", "#1,#2", "#1.1,#3"])
def test_a_model_specifier_is_accepted(value):
    assert model_spec(value) == value


def test_no_model_is_not_an_error(): 
    assert model_spec(None) is None
    assert model_spec("  ") is None


@pytest.mark.parametrize(
    "value",
    [
        "#1; delete all",       # the injection this module exists for
        "#1 ; close session",
        "#1|#2",
        "1",                    # a number is not a specifier
        "#1 or true",
        "$model",               # ChimeraX expands $-prefixed names
        "#1\\nclose all",
    ],
)
def test_anything_that_is_not_a_model_specifier_is_refused(value):
    with pytest.raises(InvalidArgument):
        model_spec(value)


def test_chain_ids_take_a_list_or_a_comma_string():
    assert chain_ids(["A", "B"]) == ["A", "B"]
    assert chain_ids("A,B") == ["A", "B"]


@pytest.mark.parametrize("value", ["A; delete all", "A B", "A:B", "", "ABCDE"])
def test_a_chain_that_is_not_a_label_is_refused(value):
    with pytest.raises(InvalidArgument):
        chain_ids([value] if value else [])


def test_a_chain_map_maps_chain_to_chain():
    assert chain_map("A:A,B:D") == "A:A,B:D"
    assert chain_map(None) is None


@pytest.mark.parametrize("value", ["A:A; delete all", "A", "A:", ":B", "A:A,"])
def test_a_malformed_chain_map_is_refused(value):
    with pytest.raises(InvalidArgument):
        chain_map(value)


@pytest.mark.parametrize("value", ["1brs", "/tmp/x.pdb", "/tmp/a b.cif"])
def test_a_structure_path_may_be_a_path_or_an_id(value):
    assert structure_path(value) == value


@pytest.mark.parametrize("value", ["x.cxc", "/tmp/EVIL.PY", "run.cmd"])
def test_a_path_chimerax_would_execute_is_refused(value):
    """`open` reads a structure or runs a script, and only one of those is
    what a tool called `open_structure` offers."""
    with pytest.raises(InvalidArgument, match="runs rather than opens"):
        structure_path(value)


def test_the_interface_command_refuses_an_injected_chain():
    with pytest.raises(InvalidArgument):
        build_interface_command(["A; delete all"], ["B"])


def test_the_interface_command_refuses_an_injected_model():
    with pytest.raises(InvalidArgument):
        build_interface_command(["A"], ["B"], model="#1; close session")


def test_a_clean_interface_command_still_builds():
    assert build_interface_command(["A"], ["B"], model="#1") == (
        "molcompose interface A B model #1 distance 4.5"
    )


def test_run_native_still_refuses_chaining():
    assert not native_allowed("view #1; delete #1")
