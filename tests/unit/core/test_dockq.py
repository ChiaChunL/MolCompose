import numpy as np
import pytest

from src.core.dockq import (
    apply_superposition,
    capri_class,
    dockq_score,
    evaluate,
    fnat_scores,
    kabsch_rotation,
    rmsd,
    scale_rmsd,
    superpose,
    superposed_rmsd,
)


def cube():
    return np.array(
        [[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1]], dtype=float
    )


def rotation_about_z(degrees):
    theta = np.radians(degrees)
    return np.array(
        [
            [np.cos(theta), -np.sin(theta), 0.0],
            [np.sin(theta), np.cos(theta), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )


# -- superposition ------------------------------------------------------------


def test_identical_point_sets_superpose_exactly():
    points = cube()
    assert superposed_rmsd(points, points) == pytest.approx(0.0, abs=1e-9)


def test_rigid_transform_is_fully_recovered():
    points = cube()
    moved = points @ rotation_about_z(37).T + np.array([5.0, -2.0, 1.5])
    assert superposed_rmsd(moved, points) == pytest.approx(0.0, abs=1e-9)


def test_kabsch_returns_a_proper_rotation():
    rotation = kabsch_rotation(cube() - cube().mean(axis=0), cube() - cube().mean(axis=0))
    assert np.linalg.det(rotation) == pytest.approx(1.0)
    assert rotation @ rotation.T == pytest.approx(np.eye(3), abs=1e-9)


def test_superposition_is_not_fooled_by_mirror_images():
    points = cube()
    mirrored = points * np.array([1.0, 1.0, -1.0])
    # A reflection is not a rotation, so the fit must be imperfect.
    assert superposed_rmsd(mirrored, points) > 0.1


def test_apply_superposition_moves_points_onto_the_target():
    points = cube()
    moved = points @ rotation_about_z(90).T + np.array([3.0, 0.0, 0.0])
    fitted = apply_superposition(moved, *superpose(moved, points))
    assert fitted == pytest.approx(points, abs=1e-9)


def test_superposition_rejects_mismatched_or_tiny_sets():
    with pytest.raises(ValueError, match="matched point sets"):
        superpose(cube(), cube()[:4])
    with pytest.raises(ValueError, match="at least three"):
        superpose(cube()[:2], cube()[:2])


def test_rmsd_is_a_plain_root_mean_square():
    a = np.zeros((4, 3))
    b = np.array([[3.0, 4, 0]] * 4)  # each point 5 Å away
    assert rmsd(a, b) == pytest.approx(5.0)


# -- Fnat ---------------------------------------------------------------------


def test_fnat_counts_shared_and_novel_contacts():
    native = {("A1", "B1"), ("A2", "B2"), ("A3", "B3"), ("A4", "B4")}
    model = {("A1", "B1"), ("A2", "B2"), ("A9", "B9")}
    fnat, fnonnat, n_native, n_shared = fnat_scores(native, model)
    assert fnat == pytest.approx(0.5)          # 2 of 4 reference contacts kept
    assert fnonnat == pytest.approx(1 / 3)     # 1 of 3 model contacts is novel
    assert (n_native, n_shared) == (4, 2)


def test_fnat_is_one_for_a_perfect_model():
    native = {("A1", "B1"), ("A2", "B2")}
    fnat, fnonnat, _, _ = fnat_scores(native, native)
    assert fnat == pytest.approx(1.0)
    assert fnonnat == pytest.approx(0.0)


def test_fnat_handles_a_model_with_no_contacts():
    fnat, fnonnat, _, shared = fnat_scores({("A1", "B1")}, set())
    assert fnat == 0.0 and fnonnat == 0.0 and shared == 0


def test_fnat_requires_reference_contacts():
    with pytest.raises(ValueError, match="no interface contacts"):
        fnat_scores(set(), {("A1", "B1")})


# -- DockQ combination --------------------------------------------------------


def test_scale_rmsd_halves_at_the_scale_distance():
    assert scale_rmsd(1.5, 1.5) == pytest.approx(0.5)
    assert scale_rmsd(0.0, 1.5) == pytest.approx(1.0)


def test_perfect_model_scores_one():
    assert dockq_score(1.0, 0.0, 0.0) == pytest.approx(1.0)


def test_dockq_matches_the_published_formula():
    fnat, irmsd, lrmsd = 0.75, 1.0, 4.0
    expected = (
        fnat + 1 / (1 + (irmsd / 1.5) ** 2) + 1 / (1 + (lrmsd / 8.5) ** 2)
    ) / 3
    assert dockq_score(fnat, irmsd, lrmsd) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.95, "High"),
        (0.80, "High"),
        (0.79, "Medium"),
        (0.49, "Medium"),
        (0.48, "Acceptable"),
        (0.23, "Acceptable"),
        (0.22, "Incorrect"),
        (0.0, "Incorrect"),
    ],
)
def test_capri_bands_follow_the_published_thresholds(score, expected):
    assert capri_class(score) == expected


def test_evaluate_bundles_every_component():
    result = evaluate(0.75, 0.1, 1.0, 4.0, native_contacts=40, shared_contacts=30,
                      interface_residues=22)
    assert result.dockq == pytest.approx(dockq_score(0.75, 1.0, 4.0))
    assert result.capri_class == capri_class(result.dockq)
    assert (result.native_contacts, result.shared_contacts) == (40, 30)
    assert result.interface_residues == 22


# -- F1 and clash counting (reported alongside DockQ, not part of it) ---------

def test_f1_is_the_harmonic_mean_of_precision_and_recall():
    from src.core.dockq import f1_score

    # Fnat is recall; precision is 1 - Fnonnat.
    assert f1_score(1.0, 0.0) == pytest.approx(1.0)
    assert f1_score(0.0, 0.0) == pytest.approx(0.0)
    assert f1_score(0.5, 0.5) == pytest.approx(0.5)


def test_f1_penalises_over_prediction_that_fnat_alone_rewards():
    """A model can recover every native contact by predicting far too many.

    Fnat sees only recall and reports a perfect 1.0; F1 does not.
    """
    from src.core.dockq import f1_score

    assert f1_score(1.0, 0.9) == pytest.approx(0.1818, abs=1e-4)


def test_f1_handles_the_degenerate_case():
    from src.core.dockq import f1_score

    assert f1_score(0.0, 1.0) == 0.0


def test_clashes_count_inter_chain_residue_pairs_below_the_cutoff():
    from src.core.dockq import count_clashes

    a = {("A", 1, ""): [(0.0, 0.0, 0.0)], ("A", 2, ""): [(10.0, 0.0, 0.0)]}
    b = {("B", 1, ""): [(1.5, 0.0, 0.0)]}
    # A:1–B:1 is 1.5 Å apart; A:2–B:1 is 8.5 Å.
    assert count_clashes(a, b) == 1            # default 2.0 Å cutoff
    assert count_clashes(a, b, cutoff=8.0) == 1
    assert count_clashes(a, b, cutoff=9.0) == 2


def test_evaluate_reports_f1_and_clashes_without_changing_dockq():
    from src.core.dockq import dockq_score, evaluate

    result = evaluate(0.965, 0.0, 0.29, 0.75, 57, 55, 40, clashes=3)
    assert result.clashes == 3
    assert result.f1 == pytest.approx(0.9822, abs=1e-4)
    # The score itself is unchanged by either.
    assert result.dockq == pytest.approx(dockq_score(0.965, 0.29, 0.75))
