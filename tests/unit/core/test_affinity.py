import math

import pytest

from src.core.affinity import (
    BINS,
    IC_CLASS,
    MAX_ASA,
    NIS_CLASS,
    binding_free_energy,
    classify_contacts,
    dg_to_kd,
    nis_percentages,
    predict_affinity,
    relative_accessibility,
)

# The reference package is a dev-only dependency; skip cross-checks without it.
prodigy_models = pytest.importorskip("prodigy_prot.modules.models")
prodigy_utils = pytest.importorskip("prodigy_prot.modules.utils")
prodigy_props = pytest.importorskip("prodigy_prot.modules.aa_properties")


# -- reference-parity checks --------------------------------------------------


def test_residue_class_tables_match_reference():
    assert IC_CLASS == prodigy_props.aa_character_ic
    assert NIS_CLASS == prodigy_props.aa_character_protorp


def test_max_asa_table_matches_reference():
    assert MAX_ASA == pytest.approx(prodigy_props.rel_asa["total"])


@pytest.mark.parametrize(
    ("cc", "ac", "pp", "ap", "nis_a", "nis_c"),
    [
        (10, 20, 5, 15, 32.0, 24.0),
        (0, 0, 0, 0, 0.0, 0.0),
        (57, 103, 18, 61, 41.7, 19.3),
    ],
)
def test_regression_matches_reference_implementation(cc, ac, pp, ap, nis_a, nis_c):
    bins = {"CC": cc, "AC": ac, "PP": pp, "AP": ap}
    assert binding_free_energy(bins, nis_a, nis_c) == pytest.approx(
        prodigy_models.IC_NIS(cc, ac, pp, ap, nis_a, nis_c), abs=1e-9
    )


@pytest.mark.parametrize("temperature", [4.0, 25.0, 37.0])
def test_kd_conversion_matches_reference(temperature):
    assert dg_to_kd(-11.5, temperature) == pytest.approx(
        prodigy_utils.dg_to_kd(-11.5, temperature), rel=1e-12
    )


# -- unit behaviour -----------------------------------------------------------


def test_contacts_bin_by_sorted_class_pair():
    bins = classify_contacts(
        [
            ("ARG", "ASP"),   # C + C -> CC
            ("ALA", "LYS"),   # A + C -> AC
            ("LYS", "ALA"),   # C + A -> AC (order independent)
            ("SER", "THR"),   # P + P -> PP
            ("LEU", "ASN"),   # A + P -> AP
            ("VAL", "ILE"),   # A + A -> AA
        ]
    )
    assert bins["CC"] == 1
    assert bins["AC"] == 2
    assert bins["PP"] == 1
    assert bins["AP"] == 1
    assert bins["AA"] == 1
    assert set(bins) == set(BINS)


def test_non_standard_residues_are_skipped():
    bins = classify_contacts([("ARG", "HOH"), ("MSE", "ASP"), ("ARG", "ASP")])
    assert sum(bins.values()) == 1


def test_relative_accessibility_uses_reference_maximum():
    assert relative_accessibility("ALA", 107.95) == pytest.approx(1.0)
    assert relative_accessibility("TRP", 24.936) == pytest.approx(0.1)
    assert relative_accessibility("XYZ", 50.0) is None


def test_nis_percentages_count_only_accessible_residues():
    residues = [
        ("ALA", 107.95),   # RSA 1.00 -> apolar
        ("LEU", 178.63),   # RSA 1.00 -> apolar
        ("ARG", 238.76),   # RSA 1.00 -> charged
        ("SER", 116.50),   # RSA 1.00 -> polar
        ("VAL", 1.0),      # RSA ~0.007 -> buried, ignored
    ]
    apolar, charged = nis_percentages(residues)
    assert apolar == pytest.approx(50.0)
    assert charged == pytest.approx(25.0)


def test_nis_requires_accessible_residues():
    with pytest.raises(ValueError, match="no solvent-accessible"):
        nis_percentages([("ALA", 0.1)])


def test_predict_affinity_reports_full_breakdown():
    pairs = [("ARG", "ASP")] * 10 + [("ALA", "LYS")] * 20 + [("LEU", "ASN")] * 15
    residues = [("ALA", 107.95)] * 8 + [("ARG", 238.76)] * 6 + [("SER", 116.5)] * 11
    result = predict_affinity(pairs, residues, temperature=25.0)
    assert result.contact_pairs == 45
    assert result.bins["CC"] == 10
    assert result.bins["AC"] == 20
    assert result.bins["AP"] == 15
    assert result.nis_apolar == pytest.approx(32.0)
    assert result.nis_charged == pytest.approx(24.0)
    assert result.delta_g == pytest.approx(
        prodigy_models.IC_NIS(10, 20, 0, 15, 32.0, 24.0), abs=1e-9
    )
    assert result.kd == pytest.approx(math.exp(result.delta_g / (0.0019858775 * 298.15)))


def test_predict_affinity_requires_contacts():
    with pytest.raises(ValueError, match="no intermolecular contacts"):
        predict_affinity([], [("ALA", 107.95)])
