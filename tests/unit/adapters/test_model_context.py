import re
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from src.adapters.model_context import (
    amino_chain_sequence,
    atom_points,
    buried_area_specs,
    chain_group_atomspec,
    experimental_method,
    list_protein_models,
    model_ref,
    plddt_values,
    structure_stem,
)

CARBON = SimpleNamespace(number=6)
HYDROGEN = SimpleNamespace(number=1)


@dataclass
class FakeAtom:
    element: object
    coord: tuple[float, float, float]
    name: str = ""
    bfactor: float | None = None


@dataclass
class FakeResidue:
    polymer_type: int
    chain_id: str
    number: int
    insertion_code: str
    name: str
    atomspec: str
    atoms: tuple[FakeAtom, ...] = field(default_factory=tuple)


@dataclass
class FakeChain:
    chain_id: str
    residues: tuple[FakeResidue, ...]

    @property
    def atomspec(self):
        return f"#1/{self.chain_id}"


@pytest.fixture
def fake_model():
    amino = FakeResidue(
        1, "A", 1, "", "ALA", "#1/A:1",
        (
            FakeAtom(CARBON, (0, 0, 0), "CA"),
            FakeAtom(CARBON, (1, 0, 0), "CB"),
            FakeAtom(HYDROGEN, (9, 9, 9), "HB1"),
        ),
    )
    water = FakeResidue(0, "A", 2, "", "HOH", "#1/A:2", (FakeAtom(CARBON, (2, 0, 0), "O"),))
    glycine = FakeResidue(
        1, "A", 3, "", "GLY", "#1/A:3",
        (FakeAtom(CARBON, (3, 0, 0), "CA"), FakeAtom(CARBON, (3.5, 0, 0), "C")),
    )
    partner = FakeResidue(
        1, "B", 1, "", "SER", "#1/B:1",
        (FakeAtom(CARBON, (4, 0, 0), "CA"), FakeAtom(CARBON, (5, 0, 0), "CB")),
    )
    return SimpleNamespace(
        id=(1,), id_string="1", name="fake", atomspec="#1",
        chains=(FakeChain("A", (amino, water, glycine)), FakeChain("B", (partner,))),
    )


def test_model_ref_keeps_only_amino_acid_chains(fake_model):
    result = model_ref(fake_model)
    assert [chain.chain_id for chain in result.chains] == ["A", "B"]
    assert result.model_id == "#1"


def test_model_ref_drops_chains_without_amino_residues(fake_model):
    water_only = FakeChain(
        "W",
        (FakeResidue(0, "W", 1, "", "HOH", "#1/W:1"),),
    )
    fake_model.chains = fake_model.chains + (water_only,)
    result = model_ref(fake_model)
    assert [chain.chain_id for chain in result.chains] == ["A", "B"]


def test_heavy_criterion_excludes_hydrogen_water_and_ligand(fake_model):
    points = atom_points(fake_model, {"A"})
    assert [point.residue.atomspec for point in points] == [
        "#1/A:1", "#1/A:1", "#1/A:3", "#1/A:3",
    ]
    assert all(point.xyz != (9.0, 9.0, 9.0) for point in points)


def test_cbeta_criterion_selects_cb_with_gly_ca_fallback(fake_model):
    points = atom_points(fake_model, {"A"}, criterion="cbeta")
    assert [(point.residue.atomspec, point.xyz) for point in points] == [
        ("#1/A:1", (1.0, 0.0, 0.0)),  # ALA CB
        ("#1/A:3", (3.0, 0.0, 0.0)),  # GLY falls back to CA
    ]


def test_cbeta_criterion_applies_to_all_chains(fake_model):
    points = atom_points(fake_model, {"A", "B"}, criterion="cbeta")
    assert [point.residue.atomspec for point in points] == ["#1/A:1", "#1/A:3", "#1/B:1"]


def test_unknown_criterion_is_rejected(fake_model):
    with pytest.raises(ValueError, match="criterion must be"):
        atom_points(fake_model, {"A"}, criterion="magic")


def test_atom_points_rejects_unknown_chain(fake_model):
    with pytest.raises(ValueError, match=r"unknown protein chain\(s\) for #1: Z"):
        atom_points(fake_model, {"Z"})


def test_the_rejection_names_the_chains_that_do_exist(fake_model):
    with pytest.raises(ValueError, match=r"This model has A, B"):
        atom_points(fake_model, {"Z"})


@pytest.mark.parametrize("spec", ["/A", "#1/A"])
def test_an_atomspec_is_recognised_and_corrected(fake_model, spec):
    """Both forms an agent reached for before finding the plain identifier.

    Recorded against a live structure: two calls were spent guessing atomspec
    syntax that this layer never accepts. The message now carries the answer,
    so the second attempt succeeds instead of the fourth.
    """
    with pytest.raises(ValueError, match=rf"not an atomspec: {re.escape(spec)} -> A"):
        atom_points(fake_model, {spec})


def test_an_atomspec_for_a_chain_that_is_absent_gets_no_false_hint(fake_model):
    """Stripping "/Z" yields "Z", which this model does not have either."""
    with pytest.raises(ValueError) as error:
        atom_points(fake_model, {"/Z"})
    assert "not an atomspec" not in str(error.value)


def test_chain_group_atomspec_is_stable(fake_model):
    ref = model_ref(fake_model)
    assert chain_group_atomspec(ref, {"B", "A"}) == "#1/A|#1/B"


def test_chain_group_atomspec_rejects_unknown_chain(fake_model):
    ref = model_ref(fake_model)
    with pytest.raises(ValueError, match=r"unknown protein chain\(s\) for #1: Q"):
        chain_group_atomspec(ref, {"Q"})


def test_amino_chain_sequence_orders_residues_like_the_file(fake_model):
    assert amino_chain_sequence(fake_model) == ("A", "A", "B")


def test_experimental_method_reads_pdb_metadata(fake_model):
    assert experimental_method(fake_model) is None
    fake_model.metadata = {"EXPDTA": ["EXPDTA    X-RAY DIFFRACTION      "]}
    assert experimental_method(fake_model) == "X-RAY DIFFRACTION"
    fake_model.metadata = {"_exptl.method": "ELECTRON MICROSCOPY"}
    assert experimental_method(fake_model) == "ELECTRON MICROSCOPY"
    fake_model.metadata = {"EXPDTA": []}
    assert experimental_method(fake_model) is None


def test_buried_area_specs_are_validated(fake_model):
    ref = model_ref(fake_model)
    assert buried_area_specs(ref, ("A",), ("B",)) == ("#1/A", "#1/B")
    with pytest.raises(ValueError, match="disjoint"):
        buried_area_specs(ref, ("A",), ("A",))
    with pytest.raises(ValueError, match=r"unknown protein chain\(s\)"):
        buried_area_specs(ref, ("A",), ("Z",))


def test_plddt_values_average_heavy_atom_bfactors(fake_model):
    amino = fake_model.chains[0].residues[0]
    for index, atom in enumerate(amino.atoms):
        atom.bfactor = [90.0, 70.0, 999.0][index]  # hydrogen value must be ignored
    values = plddt_values(fake_model)
    by_spec = {key.atomspec: value for key, value in values}
    assert by_spec["#1/A:1"] == 80.0
    assert "#1/A:2" not in by_spec  # water has no amino residues


def test_plddt_values_skip_residues_without_bfactors(fake_model):
    values = plddt_values(fake_model)
    assert values == ()


def test_list_protein_models_filters_and_sorts(monkeypatch, fake_model):
    class FakeAtomicStructure(SimpleNamespace):
        pass

    monkeypatch.setattr("chimerax.atomic.AtomicStructure", FakeAtomicStructure)
    first = FakeAtomicStructure(**vars(fake_model))
    first.id, first.id_string, first.atomspec = (1,), "1", "#1"
    second = FakeAtomicStructure(**vars(fake_model))
    second.id, second.id_string, second.atomspec = (2,), "2", "#2"
    non_atomic = SimpleNamespace(id=(3,), name="volume")
    session = SimpleNamespace(models=SimpleNamespace(list=lambda: [second, non_atomic, first]))

    assert [ref.model_id for ref in list_protein_models(session)] == ["#1", "#2"]


def test_structure_stem_drops_the_extension_the_model_name_carries():
    """A model opened from a file is named after the file, extension included.

    Left in, it ended up inside every derived filename — the SCF for a
    complex came out as `predicted_complex.cif_interface_A.scf`.
    """
    assert structure_stem(SimpleNamespace(name="predicted_complex.cif")) == "predicted_complex"
    assert structure_stem(SimpleNamespace(name="1brs.pdb")) == "1brs"
    assert structure_stem(SimpleNamespace(name="model.cif.gz")) == "model"


def test_structure_stem_keeps_dots_that_are_not_an_extension():
    """`8ol1.2` is a name, not a file type; only known suffixes are stripped."""
    assert structure_stem(SimpleNamespace(name="8ol1.2")) == "8ol1.2"
    assert structure_stem(SimpleNamespace(name="1brs")) == "1brs"


def test_structure_stem_falls_back_when_there_is_no_usable_name():
    assert structure_stem(None) == "figure"
    assert structure_stem(SimpleNamespace(name="")) == "figure"
    assert structure_stem(SimpleNamespace(name="///"), "model") == "model"
