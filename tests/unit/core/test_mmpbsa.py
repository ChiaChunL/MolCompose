"""Read gmx_MMPBSA's per-residue decomposition.

The file under `examples/data/1brs/` is real output from a 100 ns run on
barnase–barstar, kept so this is tested against what gmx_MMPBSA writes rather
than against the format as documented.
"""

from pathlib import Path

import pytest

from src.core import mmpbsa

FIXTURE = Path(__file__).parents[3] / "examples/data/1brs/FINAL_DECOMP_MMPBSA.dat"


# The 1BRS run computed both solvation models, so the file carries the whole
# decomposition twice and `load` refuses to pick. The tests below are about
# parsing rather than about the choice, so they name one.
@pytest.fixture(scope="module")
def energies():
    return mmpbsa.load(FIXTURE, "gb")


def test_a_file_with_two_solvation_models_refuses_to_choose_one():
    """The 1BRS run computed both GB and PB, so the decomposition carries the
    whole thing twice. Reading whichever DELTAS came first -- which is what
    this did until 2026-08-21 -- put an unlabelled choice into every figure
    made from such a run, and `parse_totals` in the same module reports the
    two models eight kcal/mol apart."""
    with pytest.raises(mmpbsa.DecompositionError) as caught:
        mmpbsa.load(FIXTURE)
    message = str(caught.value)
    assert "Generalized Born" in message and "Poisson Boltzmann" in message


def test_naming_the_solvation_model_reads_that_section():
    gb = mmpbsa.load(FIXTURE, "gb")
    pb = mmpbsa.load(FIXTURE, "pb")
    assert len(gb) == len(pb)
    # Same residues, different numbers: that is the whole reason the choice
    # cannot be made silently.
    assert [e.number for e in gb] == [e.number for e in pb]
    assert [e.energy for e in gb] != [e.energy for e in pb]


def test_an_unknown_solvation_model_is_named_back():
    with pytest.raises(mmpbsa.DecompositionError, match="unknown solvation model"):
        mmpbsa.load(FIXTURE, "born-again")


def test_reads_every_residue_of_both_sides(energies):
    assert len(energies) == 62
    assert sorted({energy.group for energy in energies}) == ["L", "R"]
    assert sorted({energy.chain for energy in energies}) == ["A", "B"]


def test_takes_the_deltas_section_not_the_complex(energies):
    """The complex section holds absolute energies of one state.

    Arg59 is −178.49 kcal/mol there and −10.13 as a binding contribution. A
    loader that took the first would report numbers an order of magnitude
    larger that mean something else entirely.
    """
    arg59 = next(e for e in energies if e.chain == "A" and e.number == 59)
    assert arg59.energy == pytest.approx(-10.13, abs=0.01)
    assert arg59.residue_name == "ARG"


def test_the_sign_is_the_file_s_own(energies):
    """Negative where a residue contributes favourably.

    Not normalised to the mutational ΔΔG convention: the number a user reads
    in the panel has to be the number in their file. The ramp is what gets
    oriented.
    """
    assert all(e.energy < 0 for e in mmpbsa.ranked(energies, top=10))
    assert max(energies, key=lambda e: e.energy).energy > 0


def test_ranks_the_salt_bridge_network_first(energies):
    """Independent agreement with what the geometry already said.

    These are the residues the 1BRS full workflow reports as the salt-bridge
    network and the top buried-area hot spots, arrived at from an energy the
    interface detection knows nothing about.
    """
    top = [(e.chain, e.number) for e in mmpbsa.ranked(energies, top=5)]
    assert ("B", 39) in top  # Asp39, barstar, anchors four salt bridges
    assert ("A", 59) in top  # Arg59, the largest buried area
    assert ("A", 102) in top  # His102


def test_standard_error_comes_along(energies):
    arg59 = next(e for e in energies if e.chain == "A" and e.number == 59)
    assert arg59.standard_error == pytest.approx(0.44, abs=0.01)


class TestChainMap:
    def test_parses_the_pairs(self):
        assert mmpbsa.parse_chain_map("A:A,B:D") == {"A": "A", "B": "D"}

    def test_tolerates_spacing(self):
        assert mmpbsa.parse_chain_map(" A : A , B : D ") == {"A": "A", "B": "D"}

    @pytest.mark.parametrize("bad", ["A", "A:A:B", "", ":", "A:"])
    def test_refuses_what_is_not_a_pair(self, bad):
        with pytest.raises(mmpbsa.DecompositionError):
            mmpbsa.parse_chain_map(bad)

    def test_refuses_a_chain_mapped_twice(self):
        with pytest.raises(mmpbsa.DecompositionError, match="twice"):
            mmpbsa.parse_chain_map("A:A,A:D")

    def test_remap_renames_the_chains(self, energies):
        remapped = mmpbsa.remap(energies, {"A": "A", "B": "D"})
        assert sorted({e.chain for e in remapped}) == ["A", "D"]
        assert len(remapped) == len(energies)

    def test_remap_drops_a_chain_the_map_does_not_mention(self, energies):
        """A map states which chains the file describes.

        Passing the rest through would put unmapped residues into the
        structure under whatever letter the simulation happened to use.
        """
        remapped = mmpbsa.remap(energies, {"A": "A"})
        assert {e.chain for e in remapped} == {"A"}
        assert len(remapped) < len(energies)


class TestResidueNameCheck:
    def _names(self, energies, chain_map):
        return {
            (e.chain, e.number): e.residue_name
            for e in mmpbsa.remap(energies, chain_map)
        }

    def test_silent_when_the_structure_agrees(self, energies):
        remapped = mmpbsa.remap(energies, {"A": "A", "B": "D"})
        names = {(e.chain, e.number): e.residue_name for e in remapped}
        assert mmpbsa.verify_residue_names(remapped, names) == ()

    def test_names_the_residues_that_disagree(self, energies):
        """The wrong chain map is the failure this catches.

        Mapping barstar onto barnase's letter lines Asp39 up against whatever
        barnase has at 39, and the energies would attach to the wrong protein
        without a single error.
        """
        remapped = mmpbsa.remap(energies, {"A": "A", "B": "D"})
        names = {(e.chain, e.number): e.residue_name for e in remapped}
        names[("D", 39)] = "ALA"
        problems = mmpbsa.verify_residue_names(remapped, names)
        assert len(problems) == 1
        assert "D:39 is ALA in the structure and ASP in the file" in problems[0]

    def test_reports_a_residue_the_structure_does_not_have(self, energies):
        remapped = mmpbsa.remap(energies, {"A": "A"})
        problems = mmpbsa.verify_residue_names(remapped, {})
        assert len(problems) == len(remapped)
        assert "not in the structure" in problems[0]


class TestRefusals:
    def test_refuses_a_file_with_no_deltas(self):
        text = "\n".join([
            "| Run on today",
            "Complex:",
            "Total Energy Decomposition:",
            "Residue,Internal,,,TOTAL,,",
            ",Avg.,Std. Dev.,Std. Err. of Mean",
            "R:A:LYS:27," + ",".join("1.0" for _ in range(18)),
        ])
        with pytest.raises(mmpbsa.DecompositionError, match="DELTAS"):
            mmpbsa.parse(text)

    def test_refuses_a_deltas_section_with_no_residues(self):
        text = "\n".join([
            "DELTAS:",
            "Total Energy Decomposition:",
            "Residue,Internal,,,TOTAL,,",
            ",Avg.,Std. Dev.,Std. Err. of Mean",
            "",
        ])
        with pytest.raises(mmpbsa.DecompositionError, match="no residues"):
            mmpbsa.parse(text)

    def test_refuses_a_row_too_short_to_hold_the_total(self):
        text = "\n".join([
            "DELTAS:",
            "Total Energy Decomposition:",
            "Residue,Internal,,,TOTAL,,",
            ",Avg.,Std. Dev.,Std. Err. of Mean",
            "R:A:LYS:27,1.0,2.0,3.0",
        ])
        with pytest.raises(mmpbsa.DecompositionError, match="column"):
            mmpbsa.parse(text)


def test_by_residue_is_keyed_for_the_colouring(energies):
    values = mmpbsa.by_residue(mmpbsa.remap(energies, {"A": "A", "B": "D"}))
    assert values[("A", 59)] == pytest.approx(-10.13, abs=0.01)
    assert values[("D", 39)] == pytest.approx(-10.30, abs=0.01)


def test_the_chain_map_in_the_example_is_the_right_one_for_1brs(energies):
    """A:A,B:D, checked against the deposited entry rather than asserted.

    This is the claim the whole loader rests on: the simulation's chains A and
    B are the crystal's A and D. If it were wrong the energies would attach to
    the wrong protein and every figure drawn from them would be confidently
    mislabelled, so it is verified against 1BRS itself.
    """
    fixture = Path(__file__).parents[2] / "fixtures/1brs.pdb"
    if not fixture.is_file():
        pytest.skip("tests/fixtures/1brs.pdb is not present")

    names = {}
    for line in fixture.read_text().splitlines():
        if line.startswith("ENDMDL"):
            break
        if not line.startswith("ATOM"):
            continue
        names[(line[21], int(line[22:26]))] = line[17:20].strip()

    assert mmpbsa.verify_residue_names(
        mmpbsa.remap(energies, {"A": "A", "B": "D"}), names
    ) == ()


def test_the_obvious_wrong_map_is_caught(energies):
    """Mapping the ligand onto the receptor's partner chain.

    B:C is wrong and looks just as plausible as B:D to anyone who has not
    looked up which chain barstar is.
    """
    fixture = Path(__file__).parents[2] / "fixtures/1brs.pdb"
    if not fixture.is_file():
        pytest.skip("tests/fixtures/1brs.pdb is not present")

    names = {}
    for line in fixture.read_text().splitlines():
        if line.startswith("ENDMDL"):
            break
        if line.startswith("ATOM"):
            names[(line[21], int(line[22:26]))] = line[17:20].strip()

    problems = mmpbsa.verify_residue_names(
        mmpbsa.remap(energies, {"A": "A", "B": "C"}), names
    )
    assert problems


RESULTS = Path(__file__).parents[3] / "examples/data/1brs/FINAL_RESULTS_MMPBSA.dat"


class TestOverallTotals:
    def test_reads_both_solvation_models(self):
        """Reported, never used as the interface's ΔG.

        Against an experimental −19 kcal/mol for this complex, both are large:
        an MM/PBSA total carries no entropy term. Printing them with that
        caveat is more use than printing neither, which is what a user who had
        computed them got before.
        """
        totals = mmpbsa.parse_totals(RESULTS.read_text())
        assert [(t.label, round(t.total, 2)) for t in totals] == [
            ("MM/GBSA", -80.75), ("MM/PBSA", -72.93)
        ]

    def test_takes_the_delta_not_the_complex_total(self):
        """Each solvation model reports TOTAL for the complex, the receptor
        and the ligand before it reports ΔTOTAL."""
        text = "\n".join([
            "GENERALIZED BORN:", "Complex:",
            "TOTAL                  -9999.00   1.0   1.0   1.0   1.0", "",
            "ΔTOTAL                   -80.75   1.0   1.0   1.0   1.0",
        ])
        totals = mmpbsa.parse_totals(text)
        assert len(totals) == 1
        assert totals[0].total == pytest.approx(-80.75)

    def test_found_beside_a_decomposition(self):
        totals = mmpbsa.totals_beside(FIXTURE)
        assert len(totals) == 2

    def test_absent_results_file_is_not_an_error(self, tmp_path):
        """Most people will load a decomposition on its own."""
        lonely = tmp_path / "FINAL_DECOMP_MMPBSA.dat"
        lonely.write_text("")
        assert mmpbsa.totals_beside(lonely) == ()


def test_solvation_models_are_reported_before_a_load_is_attempted():
    """The panel has to know there is a choice in order to offer one."""
    from pathlib import Path

    from src.core.mmpbsa import solvation_models

    root = Path(__file__).parents[3]
    both = root / "examples/data/1brs/FINAL_DECOMP_MMPBSA.dat"
    if both.is_file():
        assert solvation_models(both) == ["Generalized Born", "Poisson Boltzmann"]
    assert solvation_models(root / "no-such-file.dat") == []


def test_the_files_chains_are_reported_for_a_chain_map_suggestion():
    """The panel pre-filled one structure's answer for every structure.

    gmx_MMPBSA names chains by group — `R:A` and `L:B` whatever the deposited
    entry called them — so a map is always needed. The box offered "A:A,B:D",
    right for barnase and barstar and wrong for anything whose second chain is
    not D, and the error that followed named a residue the map had invented
    ("D:23 is not in the structure"), which reads as a problem with the data.
    """
    from pathlib import Path

    from src.core.mmpbsa import file_chains

    packaged = Path(__file__).parents[3] / "examples/data/1emv/FINAL_DECOMP_MMPBSA.dat"
    if packaged.is_file():
        # 1EMV's structure is A/B, so pairing the file's chains in order gives
        # A:A,B:B — the map "A:A,B:D" could never have been right for it.
        assert file_chains(packaged, "gb") == ["A", "B"]
    assert file_chains(Path("/no/such/file.dat")) == []


def test_a_constant_shift_is_recognised_as_a_shift():
    """Reported as "26 of 67 disagree", which a fraction threshold read as a
    chain-map problem — and it was not one.

    Repair adds the residues a crystal did not resolve, so every number after
    the first gap moves by the same amount. How much then disagrees depends on
    where the gaps fall rather than on how wrong the pairing is: the reported
    case had 61% still agreeing, well under any "almost none matches" rule,
    while every residue in the file sat one position out.

    The reported residues are the fixture: the structure had ILE, GLY, PRO at
    A:28-30 and the file had THR, ILE, GLY.
    """
    from src.core.mmpbsa import ResidueEnergy, numbering_offset

    seq = ["THR", "ILE", "GLY", "PRO", "SER", "LYS", "ALA", "VAL",
           "ASP", "GLU", "PHE", "TRP"]
    file_side = tuple(
        ResidueEnergy("R", "A", seq[index], 28 + index, 0.0)
        for index in range(len(seq))
    )
    shifted = {("A", 28 + i): seq[i + 1] for i in range(len(seq) - 1)}
    assert numbering_offset(file_side, shifted) == -1

    aligned = {("A", 28 + i): seq[i] for i in range(len(seq))}
    assert numbering_offset(file_side, aligned) is None

    # Two unrelated proteins must not be reported as a shift, however many
    # residues coincide.
    unrelated = {
        ("A", 28 + i): name
        for i, name in enumerate(
            ["CYS", "MET", "HIS", "ARG", "ASN", "GLN",
             "TYR", "LEU", "ILE", "VAL", "THR", "SER"]
        )
    }
    assert numbering_offset(file_side, unrelated) is None
