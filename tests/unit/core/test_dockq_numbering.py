"""DockQ must not depend on the two structures sharing a residue-numbering scheme.

The failure this guards against was a confident wrong answer, not a crash: a
Boltz-2 prediction of the proteinase B - OMTKY3 complex scored DockQ 0.031
"Incorrect" against 3SGB, where the official DockQ package scores it 0.949
"High". Nothing was wrong with the geometry. 3SGB numbers chain E in
chymotrypsinogen convention (16-242, with insertion codes 192A and 192B) while
the predictor numbers it 1-185, so pairing residues by number compared the
catalytic His57 against whatever happened to be residue 57 of the model.

The real fixture for that case lives outside the repository, so the regression
is reproduced here on 1BRS, which is deposited with the barnase-barstar complex
twice over: A/D and B/E. Scoring one copy against the other gives a known
DockQ of 0.974 (see `test_golden_1brs.py`). Renumbering the model copy into a
different convention must leave every one of those numbers untouched --
that is the property under test.
"""

import pytest

from src.core import dockq as dq
from src.core.align import align_chains, relabel, residue_mapping
from tests import pdb_fixture as fx

FIXTURE = "1brs.pdb"
CHAIN_MAP = {"B": "A", "E": "D"}

# The golden values from test_golden_1brs.py, cross-checked against DockQ v2.
GOLDEN_DOCKQ = 0.974
GOLDEN_FNAT = 0.965
GOLDEN_IRMSD = 0.29
GOLDEN_LRMSD = 0.75


# -- renumbering schemes ------------------------------------------------------


def sequential(sequence, start=1):
    """{old key: new key} renumbering a chain 1..N, the way every predictor does."""
    return {
        key: (key[0], start + index, "") for index, (key, _name) in enumerate(sequence)
    }


def chymotrypsinogen_like(sequence, start=16, insert_after=20, insertions=2):
    """{old key: new key} for an offset scheme carrying insertion codes.

    Imitates 3SGB chain E: numbering starts above 1 and, part way along, a
    residue is followed by lettered insertions rather than by the next integer.
    """
    renumbered = {}
    number = start
    for index, (key, _name) in enumerate(sequence):
        if insert_after < index <= insert_after + insertions:
            icode = chr(ord("A") + index - insert_after - 1)
            renumbered[key] = (key[0], number, icode)
            continue
        if index > insert_after + insertions:
            number = start + index - insertions
        else:
            number = start + index
        renumbered[key] = (key[0], number, "")
    return renumbered


def apply_renumbering(grouped, renumbering):
    return {renumbering.get(key, key): value for key, value in grouped.items()}


def renumber_sequence(sequence, renumbering):
    return tuple((renumbering.get(key, key), name) for key, name in sequence)


# -- the scoring path under test ----------------------------------------------


def load(chains, scheme=None):
    """The four coordinate dicts plus sequences for a 1BRS copy, optionally renumbered.

    Chain IDs are relabelled B/E -> A/D as in the golden test, so the two copies
    are comparable; `scheme` then rewrites residue numbers within each chain.
    """
    mapping = {chain: CHAIN_MAP.get(chain, chain) for chain in chains}
    heavy = [fx.remap_chains(fx.heavy_atoms_by_residue(FIXTURE, c), mapping) for c in chains]
    backbone = [fx.remap_chains(fx.backbone_by_residue(FIXTURE, c), mapping) for c in chains]
    sequences = {
        mapping[chain]: tuple(
            ((mapping[chain],) + key[1:], name) for key, name in entries
        )
        for chain, entries in fx.residue_sequences(FIXTURE, chains).items()
    }

    if scheme is not None:
        renumbering = {}
        for entries in sequences.values():
            renumbering.update(scheme(entries))
        heavy = [apply_renumbering(group, renumbering) for group in heavy]
        backbone = [apply_renumbering(group, renumbering) for group in backbone]
        sequences = {
            chain: renumber_sequence(entries, renumbering)
            for chain, entries in sequences.items()
        }
    return heavy[0], heavy[1], backbone[0], backbone[1], sequences


def dockq_by_alignment(reference_chains, model_chains, scheme=None):
    """DockQ with the residue correspondence taken from a sequence alignment.

    Mirrors what `commands.cmd_dockq` does, at the core layer so no ChimeraX
    session is needed.
    """
    ref_a, ref_b, ref_bb_a, ref_bb_b, ref_seq = load(reference_chains)
    mod_a, mod_b, mod_bb_a, mod_bb_b, mod_seq = load(model_chains, scheme)

    group_a, group_b = CHAIN_MAP.get(reference_chains[0], reference_chains[0]), CHAIN_MAP.get(
        reference_chains[1], reference_chains[1]
    )
    alignments = align_chains(mod_seq, ref_seq, [(group_a, group_a), (group_b, group_b)])
    key_map = residue_mapping(alignments)

    mod_a, mod_b = relabel(mod_a, key_map), relabel(mod_b, key_map)
    mod_bb = {**relabel(mod_bb_a, key_map), **relabel(mod_bb_b, key_map)}
    ref_bb = {**ref_bb_a, **ref_bb_b}

    fnat, fnonnat, native, shared = dq.fnat_scores(
        dq.residue_contacts(ref_a, ref_b), dq.residue_contacts(mod_a, mod_b)
    )
    keys_a, keys_b = dq.interface_keys(ref_a, ref_b)
    coverage = dq.interface_coverage(keys_a | keys_b, mod_bb)
    mobile, target = dq.matched_backbone(ref_bb, mod_bb, keys_a | keys_b)
    irmsd = dq.superposed_rmsd(mobile, target)

    receptor_mobile, receptor_target = dq.matched_backbone(ref_bb_a, mod_bb, set(ref_bb_a))
    rotation, mobile_centre, target_centre = dq.superpose(receptor_mobile, receptor_target)
    ligand_mobile, ligand_target = dq.matched_backbone(ref_bb_b, mod_bb, set(ref_bb_b))
    lrmsd = dq.rmsd(
        dq.apply_superposition(ligand_mobile, rotation, mobile_centre, target_centre),
        ligand_target,
    )
    result = dq.evaluate(fnat, fnonnat, irmsd, lrmsd, native, shared, len(keys_a | keys_b))
    return result, coverage, alignments


def assert_golden(result):
    assert result.dockq == pytest.approx(GOLDEN_DOCKQ, abs=0.0005)
    assert result.fnat == pytest.approx(GOLDEN_FNAT, abs=0.0005)
    assert result.irmsd == pytest.approx(GOLDEN_IRMSD, abs=0.005)
    assert result.lrmsd == pytest.approx(GOLDEN_LRMSD, abs=0.005)
    assert result.capri_class == "High"


# -- the regression -----------------------------------------------------------


def test_alignment_reproduces_the_golden_score_when_numbering_already_agrees():
    """The contrasting case that must keep working: introducing the alignment
    step must not perturb a pair that never needed it."""
    result, coverage, _ = dockq_by_alignment("BE", "AD")
    assert_golden(result)
    assert coverage.is_complete


def test_sequential_renumbering_does_not_change_the_score():
    """A predictor's 1-N numbering against a deposited structure's own scheme."""
    result, coverage, _ = dockq_by_alignment("BE", "AD", scheme=sequential)
    assert_golden(result)
    assert coverage.fraction == pytest.approx(1.0)


def test_insertion_codes_in_the_model_do_not_change_the_score():
    """The 3SGB case: an offset scheme whose numbers are not plain integers."""
    result, coverage, _ = dockq_by_alignment("BE", "AD", scheme=chymotrypsinogen_like)
    assert_golden(result)
    assert coverage.fraction == pytest.approx(1.0)


def test_renumbering_is_actually_a_change_the_old_code_would_have_seen():
    """Guards the two tests above from passing because the scheme did nothing."""
    _, _, _, _, plain = load("AD")
    _, _, _, _, renumbered = load("AD", scheme=chymotrypsinogen_like)
    plain_keys = {key for entries in plain.values() for key, _ in entries}
    new_keys = {key for entries in renumbered.values() for key, _ in entries}
    assert plain_keys != new_keys
    assert any(key[2] for key in new_keys), "the scheme must introduce insertion codes"


def test_pairing_by_number_gives_a_wrong_answer_on_renumbered_input():
    """The bug, reproduced: without the alignment the same model scores as garbage.

    This is what `molcompose dockq` used to report -- a confident "Incorrect" for
    a model that is in fact a near-perfect match.
    """
    ref_a, ref_b, ref_bb_a, ref_bb_b, _ = load("BE")
    mod_a, mod_b, mod_bb_a, mod_bb_b, _ = load("AD", scheme=sequential)

    fnat, _, _, _ = dq.fnat_scores(
        dq.residue_contacts(ref_a, ref_b), dq.residue_contacts(mod_a, mod_b)
    )
    assert fnat < 0.5, "expected by-number pairing to lose most native contacts"


# -- the coverage guard -------------------------------------------------------


def test_coverage_is_complete_when_the_reference_is_fully_modelled():
    _, coverage, _ = dockq_by_alignment("BE", "AD")
    assert coverage.mapped == coverage.total
    assert coverage.is_scorable and coverage.is_complete


def test_coverage_refuses_when_almost_nothing_maps():
    """The second defect: scoring must not proceed silently on an empty mapping.

    Independent of the alignment -- however the correspondence was obtained, a
    DockQ built from a handful of residues describes the mapping, not the model.
    """
    ref_a, ref_b, ref_bb_a, ref_bb_b, _ = load("BE")
    keys_a, keys_b = dq.interface_keys(ref_a, ref_b)
    interface = keys_a | keys_b

    empty = dq.interface_coverage(interface, {})
    assert empty.mapped == 0
    assert not empty.is_scorable

    barely = dq.interface_coverage(interface, dict(list({**ref_bb_a, **ref_bb_b}.items())[:2]))
    assert not barely.is_scorable


def test_coverage_report_names_the_numbers():
    coverage = dq.Coverage(mapped=3, total=106)
    assert "3/106" in dq.coverage_report(coverage)
    assert "3%" in dq.coverage_report(coverage)


def test_partial_coverage_still_scores_but_is_not_complete():
    """Between the two thresholds the score is reported with the shortfall named."""
    coverage = dq.Coverage(mapped=60, total=100)
    assert coverage.is_scorable
    assert not coverage.is_complete


def test_coverage_of_an_empty_interface_is_not_a_division_by_zero():
    coverage = dq.Coverage(mapped=0, total=0)
    assert coverage.fraction == 0.0
    assert not coverage.is_scorable
