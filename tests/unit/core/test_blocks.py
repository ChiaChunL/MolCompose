"""The four named parts a characterised complex divides into."""

import pytest

from src.core.blocks import KINDS, Block, block_name, clear_commands, define_commands


def test_names_are_qualified_by_model():
    """ChimeraX names are session-global; the things they point at are not.

    DockQ needs two structures open at once, so an unqualified `ifaceA` would
    silently mean whichever was characterised last.
    """
    assert block_name("#1", "ifaceA") == "mc1_ifaceA"
    assert block_name("#2", "ifaceA") == "mc2_ifaceA"
    assert block_name("#1", "ifaceA") != block_name("#2", "ifaceA")


def test_a_submodel_id_still_yields_an_identifier():
    """ChimeraX names cannot contain dots."""
    name = block_name("#1.2", "groupB")
    assert name == "mc1_2_groupB"
    assert name.replace("_", "").isalnum()


def test_an_unknown_block_is_refused():
    with pytest.raises(ValueError, match="unknown block"):
        block_name("#1", "hotspots")


def test_the_four_are_defined_in_reading_order():
    """Each side entire, then the part of each side that touches the other."""
    commands = define_commands("#1", {
        "groupA": "#1/A", "groupB": "#1/D",
        "ifaceA": "#1/A:27,35", "ifaceB": "#1/D:29,35",
    })
    assert commands == (
        "name mc1_groupA #1/A",
        "name mc1_groupB #1/D",
        "name mc1_ifaceA #1/A:27,35",
        "name mc1_ifaceB #1/D:29,35",
    )


def test_an_empty_block_is_skipped_not_named_empty():
    """A name resolving to nothing is worse than a name that does not exist."""
    commands = define_commands("#1", {"groupA": "#1/A", "ifaceA": ""})
    assert commands == ("name mc1_groupA #1/A",)


def test_clearing_covers_every_kind():
    """Re-detecting at another cutoff must not leave the old list named."""
    assert clear_commands("#1") == tuple(
        f"name delete mc1_{kind}" for kind in KINDS
    )


def test_a_block_carries_its_label():
    block = Block("ifaceA", "mc1_ifaceA", "#1/A:27", 1)
    assert block.label == "Interface on A"
