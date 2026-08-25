"""The file format ChimeraX's Sequence Viewer reads back."""

import pytest

from src.core.scf import rgb255, runs, scf_text


def test_hex_becomes_the_integer_triple_scf_wants():
    assert rgb255("#FF7D45") == (255, 125, 69)
    assert rgb255("0053D6") == (0, 83, 214)
    with pytest.raises(ValueError, match="six-digit"):
        rgb255("#FFF")


def test_consecutive_columns_of_one_colour_become_one_run():
    """400 residues would otherwise be 400 lines and 400 regions.

    The parser groups by (colour, comment), so merging here is what makes the
    region browser list bands instead of hundreds of one-column entries.
    """
    entries = [(1, "#FF0000", "a"), (2, "#FF0000", "a"), (3, "#FF0000", "a")]
    assert runs(entries) == [(1, 3, "#FF0000", "a")]


def test_a_gap_in_the_columns_ends_the_run():
    """The columns between were not given this colour and must not be swept in.

    This is what makes a missing residue safe: the caller never emits a column
    for it, and the run stops there rather than spanning the gap.
    """
    entries = [(1, "#FF0000", "a"), (2, "#FF0000", "a"), (4, "#FF0000", "a")]
    assert runs(entries) == [(1, 2, "#FF0000", "a"), (4, 4, "#FF0000", "a")]


def test_a_change_of_colour_or_label_ends_the_run():
    assert runs([(1, "#FF0000", "a"), (2, "#00FF00", "a")]) == [
        (1, 1, "#FF0000", "a"), (2, 2, "#00FF00", "a"),
    ]
    # Same colour, different label: two regions, because the parser keys on
    # both and the labels are what name them.
    assert runs([(1, "#FF0000", "a"), (2, "#FF0000", "b")]) == [
        (1, 1, "#FF0000", "a"), (2, 2, "#FF0000", "b"),
    ]


def test_every_data_line_is_seven_integers_then_a_comment():
    text = scf_text([(3, "#FF7D45", "pLDDT 0-50")], header=("made by a test",))
    lines = text.splitlines()
    assert lines[0] == "# made by a test"
    assert lines[1] == "3 3 1 1 255 125 69  # pLDDT 0-50"
    numbers, _, comment = lines[1].partition("#")
    assert len(numbers.split()) == 7
    assert comment.strip() == "pLDDT 0-50"


def test_the_trailing_comment_is_what_names_the_region():
    """The parser keys regions on ((r,g,b), comment), so this is the name."""
    text = scf_text([(1, "#FF0000", "interface, group A"),
                     (2, "#FF0000", "interface, group A")])
    assert "# interface, group A" in text
    assert len([line for line in text.splitlines() if not line.startswith("#")]) == 1


def test_no_line_is_ever_indented():
    """`load_scf_file` line 791 calls line.strip() without assigning it.

    A comment with leading whitespace therefore fails the `line[0] == '#'`
    test, is parsed as data, and the whole file is rejected with "Bad format".
    """
    text = scf_text(
        [(1, "#FF0000", "x"), (5, "#00FF00", "y")],
        header=("a header line", "another"),
    )
    for line in text.splitlines():
        assert line == line.lstrip(), f"indented line would break the parser: {line!r}"


def test_the_sequence_index_is_one_based():
    assert scf_text([(1, "#FF0000", "")], sequence_index=2).startswith("1 1 2 2 ")
    with pytest.raises(ValueError, match="1-based"):
        scf_text([(1, "#FF0000", "")], sequence_index=0)


def test_a_file_with_no_entries_still_parses_as_a_file():
    """No regions is a legitimate answer; a crash is not."""
    assert scf_text([], header=("nothing to colour",)) == "# nothing to colour\n"
