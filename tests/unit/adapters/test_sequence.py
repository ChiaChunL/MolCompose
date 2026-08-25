"""Residue numbers are not column numbers, and this is where that is fixed."""

from types import SimpleNamespace

from src.adapters.sequence import chain_columns, model_columns


def _residue(number, chain_id="A", insertion=""):
    return SimpleNamespace(number=number, chain_id=chain_id,
                           insertion_code=insertion)


def _chain(chain_id, residues):
    return SimpleNamespace(chain_id=chain_id, residues=residues,
                           characters="X" * len(residues))


def test_the_column_counts_from_the_start_of_the_sequence_not_the_numbering():
    """Measured on 3SGB chain E: residue 16 is column 1, residue 242 is 185.

    `residue number - column` takes fifteen distinct values across that chain,
    so treating the number as the column shifts most of the colouring — and
    every line still parses, so nothing reports it. (1BRS chain A happens to
    agree, because ChimeraX pads `.residues` with None for its two unresolved
    leading residues and the numbering starts at 3 to match. Agreement there
    is a property of that file, not a rule.)
    """
    chain = _chain("E", [_residue(16, "E"), _residue(17, "E"), _residue(18, "E")])
    assert chain_columns(chain) == {
        ("E", 16, ""): 1, ("E", 17, ""): 2, ("E", 18, ""): 3,
    }


def test_a_missing_residue_still_occupies_its_column():
    """`.residues` has None where the sequence has a residue the structure lacks.

    The gap consumes its columns, so residue 149 after a 146→149 break is
    column 4 here rather than column 2. Measured: 1ACB chain E has 245 columns
    for 241 residues, 1BRS chain A 110 for 108 — the padding is why both of
    those happen to keep number == column.
    """
    chain = _chain("E", [_residue(146, "E"), None, None,
                         _residue(149, "E"), _residue(150, "E")])
    columns = chain_columns(chain)
    assert columns[("E", 146, "")] == 1
    assert columns[("E", 149, "")] == 4
    assert columns[("E", 150, "")] == 5
    # The gap itself is not a key: nothing to colour, so nothing is emitted.
    assert len(columns) == 3


def test_insertion_codes_are_part_of_the_key():
    """3SGB numbers 192A and 192B; they are different residues and columns."""
    chain = _chain("E", [_residue(192, "E"),
                         _residue(192, "E", insertion="A"),
                         _residue(192, "E", insertion="B")])
    columns = chain_columns(chain)
    assert columns[("E", 192, "")] == 1
    assert columns[("E", 192, "A")] == 2
    assert columns[("E", 192, "B")] == 3


def test_each_chain_is_numbered_from_its_own_start():
    """SCF columns are per sequence: chain B's column 1 is B's first residue."""
    model = SimpleNamespace(chains=[
        _chain("A", [_residue(3, "A"), _residue(4, "A")]),
        _chain("B", [_residue(1, "B"), _residue(2, "B")]),
    ])
    columns = model_columns(model)
    assert columns["A"][("A", 3, "")] == 1
    assert columns["B"][("B", 1, "")] == 1


def test_a_chain_without_residues_is_not_an_error():
    assert chain_columns(SimpleNamespace(chain_id="A", residues=None)) == {}
