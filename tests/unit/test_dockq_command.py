"""`molcompose dockq` at the command layer: alignment, refusal and warning.

The core-layer proof that the residue correspondence is right lives in
`unit/core/test_dockq_numbering.py`. What is checked here is the behaviour the
user actually meets: that the command pairs residues by alignment rather than by
number, that it refuses rather than reporting a verdict when the mapping reaches
too little of the interface, and that it says so when the mapping is partial.
"""

from types import SimpleNamespace

import pytest
from chimerax.core.errors import UserError

from src.commands import cmd_dockq, cmd_interface

# Two short chains placed 4 Å apart so every residue pair is in contact, which
# makes the interface the whole of both chains and the arithmetic easy to reason
# about. Sequences differ between the chains so the alignment cannot cross them.
CHAIN_A_SEQUENCE = "ALA GLN VAL ILE ASN THR PHE ASP GLY VAL ALA ASP".split()
CHAIN_B_SEQUENCE = "LYS TRP SER TYR HIS GLU MET LEU CYS ARG PRO PHE".split()


class Logger:
    def __init__(self):
        self.infos = []
        self.warnings = []

    def info(self, message):
        self.infos.append(message)

    def warning(self, message):
        self.warnings.append(message)


def residue(chain_id, number, icode, name, origin):
    """One residue with a full backbone, built around `origin`."""
    x, y, z = origin
    atoms = [
        SimpleNamespace(name="N", element=SimpleNamespace(number=7), coord=(x, y, z)),
        SimpleNamespace(name="CA", element=SimpleNamespace(number=6), coord=(x + 0.5, y, z)),
        SimpleNamespace(name="C", element=SimpleNamespace(number=6), coord=(x + 1.0, y, z)),
        SimpleNamespace(name="O", element=SimpleNamespace(number=8), coord=(x + 1.5, y, z)),
    ]
    return SimpleNamespace(
        polymer_type=1,
        chain_id=chain_id,
        number=number,
        insertion_code=icode,
        name=name,
        atomspec=f"/{chain_id}:{number}{icode}",
        atoms=tuple(atoms),
    )


def chain(chain_id, sequence, numbering, y):
    """A chain laid out along x at height `y`, numbered as `numbering` says."""
    residues = tuple(
        residue(chain_id, number, icode, name, (index * 3.0, y, 0.0))
        for index, (name, (number, icode)) in enumerate(zip(sequence, numbering, strict=True))
    )
    return SimpleNamespace(
        chain_id=chain_id, residues=residues, atomspec=f"#1/{chain_id}"
    )


def sequential(sequence, start=1):
    return [(start + i, "") for i in range(len(sequence))]


def deposited(sequence, start=16, insert_at=3):
    """An offset scheme with a lettered insertion, as 3SGB chain E has."""
    numbering, number = [], start
    for index in range(len(sequence)):
        if index == insert_at:
            numbering.append((number - 1, "A"))
            continue
        numbering.append((number, ""))
        number += 1
    return numbering


def structure(model_id, chain_a, chain_b):
    return SimpleNamespace(
        id=(int(model_id),),
        id_string=model_id,
        name=f"model{model_id}",
        atomspec=f"#{model_id}",
        chains=(chain_a, chain_b),
    )


def model_pair(model_numbering=sequential, reference_numbering=deposited, sequences=None):
    """A model and a reference of the same complex under two numbering schemes."""
    a_sequence, b_sequence = sequences or (CHAIN_A_SEQUENCE, CHAIN_B_SEQUENCE)
    model = structure(
        "1",
        chain("A", a_sequence, model_numbering(a_sequence), 0.0),
        chain("B", b_sequence, model_numbering(b_sequence), 4.0),
    )
    reference = structure(
        "2",
        chain("A", CHAIN_A_SEQUENCE, reference_numbering(CHAIN_A_SEQUENCE), 0.0),
        chain("B", CHAIN_B_SEQUENCE, reference_numbering(CHAIN_B_SEQUENCE), 4.0),
    )
    return model, reference


@pytest.fixture
def session():
    return SimpleNamespace(logger=Logger())


def score(session, model, reference, **kwargs):
    cmd_interface(session, "A", "B", model=model)
    return cmd_dockq(session, reference, model=model, **kwargs)


# -- the correspondence -------------------------------------------------------


def test_numbering_schemes_may_differ_without_affecting_the_score(session):
    """The model is numbered 1-N, the reference 16-N with an insertion code."""
    model, reference = model_pair()
    result = score(session, model, reference)
    assert result.fnat == pytest.approx(1.0)
    assert result.dockq == pytest.approx(1.0)
    assert result.capri_class == "High"


def test_identical_numbering_still_works(session):
    """The contrasting case: nothing about the alignment disturbs an easy pair."""
    model, reference = model_pair(reference_numbering=sequential)
    result = score(session, model, reference)
    assert result.dockq == pytest.approx(1.0)


def test_the_alignment_is_reported(session):
    model, reference = model_pair()
    score(session, model, reference)
    line = next(m for m in session.logger.infos if "sequence alignment" in m)
    assert "A->A 12 aligned, 100% identity" in line
    assert "B->B 12 aligned, 100% identity" in line


def test_a_full_mapping_warns_about_nothing(session):
    model, reference = model_pair()
    score(session, model, reference)
    assert session.logger.warnings == []


# -- refusals -----------------------------------------------------------------


def test_unrelated_chains_are_refused_rather_than_scored(session):
    """A wrong chain pairing is a different fault from a wrong numbering, and
    the message has to say so -- chainMap is the fix, not the alignment."""
    model, reference = model_pair(sequences=(["GLY"] * 12, ["GLY"] * 12))
    with pytest.raises(UserError, match="not the same protein"):
        score(session, model, reference)


def test_the_refusal_names_the_identity_it_measured(session):
    model, reference = model_pair(sequences=(["GLY"] * 12, ["GLY"] * 12))
    with pytest.raises(UserError, match=r"identity"):
        score(session, model, reference)


def test_a_mapping_reaching_too_little_of_the_interface_is_refused(session):
    """The second defect: a near-empty mapping must not produce a verdict.

    The model here is the same protein but only two residues of it, so the
    chains align at full identity and the alignment is not what is wrong --
    there is simply almost nothing to score.
    """
    model, reference = model_pair(
        sequences=(CHAIN_A_SEQUENCE[:2], CHAIN_B_SEQUENCE[:2])
    )
    with pytest.raises(UserError, match="refusing to score"):
        score(session, model, reference)


def test_the_refusal_names_how_many_residues_mapped(session):
    model, reference = model_pair(
        sequences=(CHAIN_A_SEQUENCE[:2], CHAIN_B_SEQUENCE[:2])
    )
    with pytest.raises(UserError, match=r"4/24 reference interface residues"):
        score(session, model, reference)


def test_a_chain_missing_from_the_reference_names_only_that_chain(session):
    """Predictors disagree on chain naming -- Protenix emits A/B where AF3 and
    Boltz-2 emit A/D -- so this is a routine way a run goes wrong, and the
    message has to point at the chain that is actually absent."""
    model, reference = model_pair()
    reference.chains[1].chain_id = "D"
    for chain_residue in reference.chains[1].residues:
        chain_residue.chain_id = "D"

    with pytest.raises(UserError, match=r"no protein residues in chain\(s\) B") as raised:
        score(session, model, reference)
    assert "chainMap A:A,B:B" in str(raised.value)


def test_chain_map_pairs_differently_named_chains(session):
    model, reference = model_pair()
    reference.chains[1].chain_id = "D"
    for chain_residue in reference.chains[1].residues:
        chain_residue.chain_id = "D"

    result = score(session, model, reference, chainMap="B:D")
    assert result.dockq == pytest.approx(1.0)


# -- partial coverage ---------------------------------------------------------


def test_partial_coverage_scores_but_warns(session):
    """Above the floor the score is still reported -- with the shortfall named,
    so a number computed from two thirds of the interface is never mistaken for
    one computed from all of it."""
    model, reference = model_pair(
        sequences=(CHAIN_A_SEQUENCE[:8], CHAIN_B_SEQUENCE[:8])
    )
    result = score(session, model, reference)
    assert result.dockq > 0
    warning = next(m for m in session.logger.warnings if "16/24" in m)
    assert "67%" in warning
