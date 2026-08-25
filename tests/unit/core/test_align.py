"""Residue correspondence by sequence alignment, independent of residue numbering.

These are the unit-level checks on `core/align.py`. The structure-level proof
that the alignment fixes a real scoring failure is in `test_dockq_numbering.py`.
"""

import pytest

from src.core.align import (
    ChainAlignment,
    align_chain,
    align_chains,
    align_sequences,
    canonical_name,
    relabel,
    residue_mapping,
)

BARNASE_START = (
    "ALA GLN VAL ILE ASN THR PHE ASP GLY VAL ALA ASP TYR LEU GLN THR TYR HIS LYS".split()
)


def sequence(names, chain="A", start=1, icodes=None):
    """[(key, name), ...] for `names`, numbered from `start` in chain `chain`."""
    icodes = icodes or {}
    return tuple(
        ((chain, start + i, icodes.get(i, "")), name) for i, name in enumerate(names)
    )


# -- the alignment itself -----------------------------------------------------


def test_identical_sequences_pair_every_residue_in_order():
    a = sequence(BARNASE_START)
    pairs = align_sequences(a, a)
    assert len(pairs) == len(BARNASE_START)
    assert all(model == reference for model, reference in pairs)


def test_numbering_offset_is_irrelevant_to_the_correspondence():
    """The whole point: a predictor's 1-N numbering against a deposited 16-242."""
    model = sequence(BARNASE_START, start=1)
    reference = sequence(BARNASE_START, start=16)
    pairs = align_sequences(model, reference)
    assert len(pairs) == len(BARNASE_START)
    # Residue i of the model pairs with residue i+15 of the reference throughout.
    assert all(
        model_key[1] + 15 == reference_key[1] for model_key, reference_key in pairs
    )


def test_insertion_codes_need_no_special_handling():
    """3SGB's 192/192A/192B is the case that breaks any integer-based mapping."""
    names = "ALA GLU PRO GLY ASP SER".split()
    numbering = [(192, ""), (192, "A"), (192, "B"), (193, ""), (194, ""), (195, "")]
    reference = tuple(
        (("E", number, icode), name)
        for (number, icode), name in zip(numbering, names, strict=True)
    )
    model = sequence(names, chain="E", start=136)
    pairs = align_sequences(model, reference)
    assert [(m[1], r[1], r[2]) for m, r in pairs] == [
        (136, 192, ""),
        (137, 192, "A"),
        (138, 192, "B"),
        (139, 193, ""),
        (140, 194, ""),
        (141, 195, ""),
    ]


def test_leading_and_trailing_gaps_are_free():
    """A reference missing disordered termini must still align cleanly.

    3SGB chain I is deposited as residues 7-56 while the model predicts 1-56;
    the six extra model residues should cost nothing and simply not pair.
    """
    model = sequence(BARNASE_START, start=1)
    reference = sequence(BARNASE_START[6:], start=7)
    pairs = align_sequences(model, reference)
    assert len(pairs) == len(BARNASE_START) - 6
    assert pairs[0][0][1] == 7  # model residue 7 pairs with the reference's first


def test_an_internal_deletion_is_skipped_not_shifted():
    """A missing loop must open a gap, not slide the rest of the chain out of register.

    Register is checked by residue identity rather than by which numbers pair:
    where a sequence repeats, several equal-scoring alignments exist and any of
    them is a correct answer, but every aligned pair must still match in identity.
    """
    model = sequence(BARNASE_START, start=1)
    without_loop = BARNASE_START[:8] + BARNASE_START[12:]
    reference = sequence(without_loop, start=1)
    pairs = align_sequences(model, reference)
    assert len(pairs) == len(without_loop)

    model_names = dict(model)
    reference_names = dict(reference)
    assert all(model_names[m] == reference_names[r] for m, r in pairs)
    # And the correspondence stays monotonic -- no crossing pairs.
    assert [m for m, _ in pairs] == sorted(m for m, _ in pairs)
    assert [r for _, r in pairs] == sorted(r for _, r in pairs)


def test_empty_sequence_aligns_to_nothing():
    assert align_sequences((), sequence(BARNASE_START)) == ()
    assert align_sequences(sequence(BARNASE_START), ()) == ()


# -- modified residues --------------------------------------------------------


def test_selenomethionine_is_methionine_for_alignment():
    assert canonical_name("MSE") == "MET"
    model = sequence(["MET", "ALA", "MET"])
    reference = sequence(["MSE", "ALA", "MSE"], start=50)
    alignment = align_chain(model, reference, "A", "A")
    assert alignment.aligned == 3
    assert alignment.identity == pytest.approx(1.0)


def test_an_unknown_residue_name_is_left_alone():
    assert canonical_name("XYZ") == "XYZ"


# -- the reported alignment quality -------------------------------------------


def test_identity_is_measured_against_the_shorter_chain():
    """A truncated reference of the same protein is 100% identity, not 50%."""
    model = sequence(BARNASE_START, start=1)
    reference = sequence(BARNASE_START[:10], start=1)
    alignment = align_chain(model, reference, "A", "A")
    assert alignment.aligned == 10
    assert alignment.identity == pytest.approx(1.0)


def test_identity_falls_when_the_chains_are_different_proteins():
    model = sequence(BARNASE_START)
    reference = sequence(["GLY"] * len(BARNASE_START), start=1)
    alignment = align_chain(model, reference, "A", "B")
    assert alignment.identity < 0.3


def test_empty_alignment_reports_zero_identity_rather_than_dividing_by_zero():
    alignment = ChainAlignment("A", "B", (), 0, 0, 0)
    assert alignment.identity == 0.0
    assert alignment.aligned == 0


# -- turning alignments into a usable mapping ---------------------------------


def test_align_chains_skips_a_chain_absent_from_either_structure():
    model = {"A": sequence(BARNASE_START, chain="A")}
    reference = {"A": sequence(BARNASE_START, chain="A", start=16)}
    alignments = align_chains(model, reference, [("A", "A"), ("B", "B")])
    assert [(a.model_chain, a.reference_chain) for a in alignments] == [("A", "A")]


def test_residue_mapping_covers_every_aligned_pair_across_chains():
    model = {
        "A": sequence(BARNASE_START, chain="A"),
        "B": sequence(BARNASE_START, chain="B"),
    }
    reference = {
        "A": sequence(BARNASE_START, chain="A", start=16),
        "B": sequence(BARNASE_START, chain="B", start=16),
    }
    mapping = residue_mapping(align_chains(model, reference, [("A", "A"), ("B", "B")]))
    assert len(mapping) == 2 * len(BARNASE_START)
    assert mapping[("A", 1, "")] == ("A", 16, "")
    assert mapping[("B", 1, "")] == ("B", 16, "")


def test_relabel_rekeys_into_the_reference_key_space():
    mapping = {("A", 1, ""): ("A", 16, "")}
    assert relabel({("A", 1, ""): "value"}, mapping) == {("A", 16, ""): "value"}


def test_relabel_drops_unmapped_residues_rather_than_letting_numbers_collide():
    """An unaligned model residue must not survive under a number that means
    something else in the reference -- that is the original bug in miniature."""
    mapping = {("A", 1, ""): ("A", 16, "")}
    relabelled = relabel({("A", 1, ""): "kept", ("A", 57, ""): "dropped"}, mapping)
    assert relabelled == {("A", 16, ""): "kept"}
