"""Read `gmx rmsf` output.

The file under `examples/data/1brs/` is real output from the same 100 ns run
the MM/PBSA decomposition came from.
"""

from pathlib import Path

import pytest

from src.core import rmsf

FIXTURE = Path(__file__).parents[3] / "examples/data/1brs/rmsf_complex_CA.xvg"


@pytest.fixture(scope="module")
def values():
    return rmsf.load(FIXTURE)


def test_reads_every_residue_of_the_complex(values):
    assert len(values) == 199
    assert values[0].index == 1


def test_converts_nanometres_to_angstrom(values):
    """Every other length in this tool is in Å, and a B-factor column is Å²."""
    assert values[0].rmsf == pytest.approx(2.304, abs=0.001)


def test_termini_move_most(values):
    """A sanity check on the physics rather than on the parser: chain ends and
    loops fluctuate, cores do not."""
    ordered = sorted(values, key=lambda v: v.rmsf, reverse=True)
    assert ordered[0].rmsf > 2 * min(v.rmsf for v in values)


class TestRefusals:
    def _xvg(self, yaxis, xaxis="Residue", rows=("1 0.5",)):
        return "\n".join([
            "# comment",
            f'@    xaxis  label "{xaxis}"',
            f'@    yaxis  label "{yaxis}"',
            "@TYPE xy",
            *rows,
        ])

    def test_refuses_a_curve_that_is_not_a_fluctuation(self):
        """gmx writes RMSD and half a dozen other quantities in this exact
        shape; one of them painted as fluctuation would look plausible."""
        with pytest.raises(rmsf.FluctuationError, match="nm"):
            rmsf.parse(self._xvg("RMSD (kJ/mol)"))

    def test_refuses_a_file_indexed_by_time(self):
        with pytest.raises(rmsf.FluctuationError, match="residue or atom"):
            rmsf.parse(self._xvg("(nm)", xaxis="Time (ps)"))

    def test_refuses_a_file_with_no_data(self):
        with pytest.raises(rmsf.FluctuationError, match="no two-column"):
            rmsf.parse(self._xvg("(nm)", rows=()))


class TestPlacing:
    """`gmx rmsf -res` restarts its numbering per chain: this file is 1..110
    then 1..89, not 1..199."""

    def test_splits_where_the_index_restarts(self, values):
        found = rmsf.blocks(values)
        assert [len(block) for block in found] == [110, 89]

    def test_places_each_block_on_its_own_chain(self, values):
        placed = rmsf.by_residue(values, (
            ("A", tuple(range(1, 111))),
            ("D", tuple(range(1, 90))),
        ))
        assert len(placed) == 199
        assert placed[("A", 1)] == pytest.approx(2.304, abs=0.001)
        # The second block's first row, which a flat read would have put on A:1.
        assert placed[("D", 1)] == pytest.approx(1.179, abs=0.001)

    def test_refuses_a_mismatched_chain_count(self, values):
        with pytest.raises(rmsf.FluctuationError, match="chain"):
            rmsf.by_residue(values, (("A", tuple(range(1, 111))),))

    def test_refuses_a_block_that_does_not_fit_its_chain(self, values):
        """The usual cause is real: 1BRS chain A is 108 residues as deposited
        and 110 once the disordered ones are rebuilt, so this exact file
        refuses to load onto the crystal structure — and would have shifted
        every value by two from the first gap onward if it had not."""
        with pytest.raises(rmsf.FluctuationError, match="repaired"):
            rmsf.by_residue(values, (
                ("A", tuple(range(1, 90))),
                ("D", tuple(range(1, 111))),
            ))
