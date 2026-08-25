"""Structure-level golden values for barnase-barstar (PDB 1BRS).

Every number asserted here is a number the manuscript reports. The rest of the
suite checks the science in pieces — that the PRODIGY coefficients match the
reference, that Kabsch recovers a known rotation — but nothing else runs the
core layer end to end on a real structure, so nothing else would catch a change
in a selection rule or a threshold that silently moved a published figure.

Fixture: `tests/fixtures/1brs.pdb`, the deposited entry unmodified. Chains A/B/C
are barnase copies and D/E/F barstar copies, which is what makes the file usable
both as a complex (A/D) and as its own DockQ reference (B/E).

Values that depend on solvent accessibility -- buried surface area, %NIS and
therefore dG itself -- cannot appear here: they need the ChimeraX SASA engine
and so belong to the integration check, not to the host-light suite. What is
locked below is exactly the part the manuscript claims reproduces the reference
implementations *exactly*: the contact terms.

If one of these fails, do not adjust the expected value to match. Find out which
rule changed and whether the manuscript now says something untrue.
"""

import pytest

from src.core import dockq as dq
from src.core.affinity import classify_contacts
from src.core.interactions import detect_interactions, summarize
from src.core.interfaces import detect_interface
from tests import pdb_fixture as fx

FIXTURE = "1brs.pdb"

# PRODIGY counts contacts at 5.5 A; MolCompose's interface default is 4.5 A.
# Both appear in the manuscript and they are not interchangeable.
PRODIGY_CUTOFF = 5.5
INTERFACE_CUTOFF = 4.5

CHAIN_MAP = {"B": "A", "E": "D"}


@pytest.fixture(scope="module")
def barnase_barstar():
    return fx.atom_points(FIXTURE, "A"), fx.atom_points(FIXTURE, "D")


# -- interface geometry -------------------------------------------------------


def test_interface_at_default_cutoff(barnase_barstar):
    """The residue counts a `molcompose interface` call reports for 1BRS A/D."""
    group_a, group_b = barnase_barstar
    result = detect_interface(group_a, group_b, cutoff=INTERFACE_CUTOFF)
    assert len(result.contacts) == 43
    assert len(result.group_a) == 19
    assert len(result.group_b) == 16


def test_interface_at_prodigy_cutoff(barnase_barstar):
    group_a, group_b = barnase_barstar
    result = detect_interface(group_a, group_b, cutoff=PRODIGY_CUTOFF)
    assert len(result.contacts) == 68
    assert len(result.group_a) == 25
    assert len(result.group_b) == 21


def test_contact_terms_match_the_published_prodigy_counts(barnase_barstar):
    """CC/AC/PP/AP as reported by `prodigy-prot` for 1BRS A/D: 11, 25, 2, 11.

    This is the manuscript's strongest single claim -- that the four regression
    inputs reproduce the reference implementation exactly -- so it is asserted
    on exact integers, not tolerances.
    """
    group_a, group_b = barnase_barstar
    result = detect_interface(group_a, group_b, cutoff=PRODIGY_CUTOFF)
    bins = classify_contacts([(pair.a.name, pair.b.name) for pair in result.contacts])
    assert bins["CC"] == 11
    assert bins["AC"] == 25
    assert bins["PP"] == 2
    assert bins["AP"] == 11
    assert sum(bins.values()) == 68


# -- interaction typing -------------------------------------------------------


@pytest.fixture(scope="module")
def interactions():
    return detect_interactions(
        fx.atom_records(FIXTURE, "A"), fx.atom_records(FIXTURE, "D")
    )


def test_interaction_class_counts(interactions):
    assert summarize(interactions) == {
        "salt-bridge": 4,
        "hydrophobic": 2,
        "pi-stacking": 1,
        "cation-pi": 2,
        "disulfide": 0,
    }


def test_asp39_triple_salt_bridge_is_recovered(interactions):
    """Barstar Asp39 to barnase Arg83, Arg87 and His102.

    The textbook hot-spot architecture of this complex. Recovering all three,
    and only these four salt bridges, is what the manuscript claims in S3.2.
    """
    bridges = {
        (i.a.name + str(i.a.number), i.b.name + str(i.b.number)): i.distance
        for i in interactions
        if i.kind == "salt-bridge"
    }
    assert bridges.keys() == {
        ("ARG59", "GLU76"),
        ("ARG83", "ASP39"),
        ("ARG87", "ASP39"),
        ("HIS102", "ASP39"),
    }
    assert bridges[("ARG83", "ASP39")] == pytest.approx(2.50, abs=0.005)
    assert bridges[("ARG87", "ASP39")] == pytest.approx(2.93, abs=0.005)
    assert bridges[("HIS102", "ASP39")] == pytest.approx(2.81, abs=0.005)
    assert bridges[("ARG59", "GLU76")] == pytest.approx(2.97, abs=0.005)


def test_aromatic_contacts_and_geometry(interactions):
    by_kind = {}
    for interaction in interactions:
        key = (
            interaction.kind,
            interaction.a.name + str(interaction.a.number),
            interaction.b.name + str(interaction.b.number),
        )
        by_kind[key] = interaction

    cation_lys = by_kind[("cation-pi", "LYS27", "TRP38")]
    cation_arg = by_kind[("cation-pi", "ARG59", "TRP38")]
    assert cation_lys.distance == pytest.approx(4.66, abs=0.005)
    assert cation_arg.distance == pytest.approx(4.18, abs=0.005)

    stack = by_kind[("pi-stacking", "HIS102", "TYR29")]
    assert stack.distance == pytest.approx(4.79, abs=0.005)
    # Geometry classification, not just detection: 79 degrees is T-shaped.
    assert stack.detail == "T-shaped (79°)"


def test_hydrophobic_core_contacts(interactions):
    pairs = {
        (i.a.name + str(i.a.number), i.b.name + str(i.b.number))
        for i in interactions
        if i.kind == "hydrophobic"
    }
    assert pairs == {("PHE82", "TRP44"), ("TYR103", "ALA36")}


def test_the_reported_interactions_name_their_residues(interactions):
    """What `characterise` puts in its structured summary, not just counts.

    A recorded agent session had only the counts and the display commands'
    atom specs to work from, so it read `/A:27@NZ` and wrote "Arg27" in its
    answer. 1BRS has LYS27 there. The residue names below are the fix: the
    summary states them, and this pins the one that was misread.
    """
    from src.core.interactions import describe

    rows = describe(interactions)
    assert len(rows) == len(list(interactions))

    cation_pi = [row for row in rows if row["kind"] == "cation-pi"]
    assert {row["a"] for row in cation_pi} == {"LYS A:27", "ARG A:59"}
    assert {row["b"] for row in cation_pi} == {"TRP D:38"}

    stacking = next(row for row in rows if row["kind"] == "pi-stacking")
    assert (stacking["a"], stacking["b"]) == ("HIS A:102", "TYR D:29")
    assert stacking["detail"] == "T-shaped (79°)"
    assert stacking["distance"] == pytest.approx(4.79, abs=0.005)


def test_a_salt_bridge_names_the_atoms_that_make_it(interactions):
    """Which atoms pair matters: Arg has two NH donors and they are not alike."""
    from src.core.interactions import describe

    bridges = {
        row["a"]: row["detail"]
        for row in describe(interactions)
        if row["kind"] == "salt-bridge"
    }
    assert bridges["ARG A:59"] == "NH1–OE1"
    assert set(bridges) == {"ARG A:59", "ARG A:83", "ARG A:87", "HIS A:102"}


# -- DockQ against a second copy in the asymmetric unit -----------------------


def _dockq(reference_chains, model_chains):
    """DockQ of `model_chains` against `reference_chains`, both from 1BRS."""

    def load(chains):
        first, second = chains
        mapping = {chain: CHAIN_MAP.get(chain, chain) for chain in chains}
        return (
            fx.remap_chains(fx.heavy_atoms_by_residue(FIXTURE, first), mapping),
            fx.remap_chains(fx.heavy_atoms_by_residue(FIXTURE, second), mapping),
            fx.remap_chains(fx.backbone_by_residue(FIXTURE, first), mapping),
            fx.remap_chains(fx.backbone_by_residue(FIXTURE, second), mapping),
        )

    ref_a, ref_b, ref_bb_a, ref_bb_b = load(reference_chains)
    mod_a, mod_b, mod_bb_a, mod_bb_b = load(model_chains)

    fnat, fnonnat, native, shared = dq.fnat_scores(
        dq.residue_contacts(ref_a, ref_b), dq.residue_contacts(mod_a, mod_b)
    )
    keys_a, keys_b = dq.interface_keys(ref_a, ref_b)
    mobile, target = dq.matched_backbone(
        {**ref_bb_a, **ref_bb_b}, {**mod_bb_a, **mod_bb_b}, keys_a | keys_b
    )
    irmsd = dq.superposed_rmsd(mobile, target)

    # LRMSD: superpose on the receptor, then measure the ligand where it lands.
    receptor_mobile, receptor_target = dq.matched_backbone(ref_bb_a, mod_bb_a, set(ref_bb_a))
    rotation, mobile_centre, target_centre = dq.superpose(receptor_mobile, receptor_target)
    ligand_mobile, ligand_target = dq.matched_backbone(ref_bb_b, mod_bb_b, set(ref_bb_b))
    lrmsd = dq.rmsd(
        dq.apply_superposition(ligand_mobile, rotation, mobile_centre, target_centre),
        ligand_target,
    )
    return dq.evaluate(fnat, fnonnat, irmsd, lrmsd, native, shared, len(keys_a | keys_b))


def test_dockq_matches_the_official_package():
    """0.974 -- the value cross-checked against `DockQ` v2, to three decimals.

    Direction matters and is easy to get backwards: the reference is B/E and the
    model is A/D. Fnat is the fraction of *native* contacts recovered, so
    swapping the two changes the score (see the test below).
    """
    result = _dockq(reference_chains="BE", model_chains="AD")
    assert result.dockq == pytest.approx(0.974, abs=0.0005)
    assert result.fnat == pytest.approx(0.965, abs=0.0005)
    assert (result.shared_contacts, result.native_contacts) == (55, 57)
    assert result.irmsd == pytest.approx(0.29, abs=0.005)
    assert result.lrmsd == pytest.approx(0.75, abs=0.005)
    assert result.capri_class == "High"


def test_dockq_fnat_is_asymmetric_in_the_reference():
    """Documenting the asymmetry rather than leaving it to be rediscovered.

    With A/D as the reference every one of its 55 contacts is present in B/E, so
    Fnat is 1.0 and DockQ rises to 0.985. Both values are correct; a report that
    does not name the reference is not.
    """
    result = _dockq(reference_chains="AD", model_chains="BE")
    assert result.fnat == pytest.approx(1.0)
    assert (result.shared_contacts, result.native_contacts) == (55, 55)
    assert result.dockq == pytest.approx(0.985, abs=0.0005)
    # The geometry terms are reference-independent; only Fnat moves.
    assert result.irmsd == pytest.approx(0.29, abs=0.005)
    assert result.lrmsd == pytest.approx(0.75, abs=0.005)


# -- fixture integrity --------------------------------------------------------


def test_fixture_is_the_deposited_entry():
    """Guards against the fixture being trimmed or re-saved by another tool."""
    text = (fx.FIXTURES / FIXTURE).read_text()
    assert text.startswith("HEADER    ENDONUCLEASE")
    assert "EXPDTA    X-RAY DIFFRACTION" in text
    assert len(fx.atom_points(FIXTURE, "A")) == 864
    assert len(fx.atom_points(FIXTURE, "D")) == 693
