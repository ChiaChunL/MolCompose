import math

import numpy as np
import pytest

from src.core.interactions import (
    KINDS,
    AtomRecord,
    InteractionParams,
    detect_interactions,
    ring_angle,
    ring_geometry,
    summarize,
)
from src.core.interfaces import ResidueKey

PHE_RING = ("CG", "CD1", "CD2", "CE1", "CE2", "CZ")


def residue(chain, number, name):
    return ResidueKey("#1", chain, number, "", name, f"#1/{chain}:{number}")


def atom(key, name, xyz, element=6):
    return AtomRecord(key, name, element, tuple(float(value) for value in xyz))


def benzene(key, centre, plane="xy", radius=1.39):
    """Six coplanar ring atoms around `centre` in the requested plane."""
    atoms = []
    for index, name in enumerate(PHE_RING):
        angle = math.radians(60 * index)
        offset = radius * math.cos(angle), radius * math.sin(angle)
        if plane == "xy":
            delta = (offset[0], offset[1], 0.0)
        else:  # "xz" -> ring plane perpendicular to the xy one
            delta = (offset[0], 0.0, offset[1])
        atoms.append(atom(key, name, tuple(c + d for c, d in zip(centre, delta, strict=True))))
    return atoms


# -- geometry helpers ---------------------------------------------------------


def test_ring_geometry_returns_centroid_and_unit_normal():
    key = residue("A", 1, "PHE")
    centroid, normal = ring_geometry(benzene(key, (0.0, 0.0, 0.0)))
    assert centroid == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    assert abs(float(np.dot(normal, [0.0, 0.0, 1.0]))) == pytest.approx(1.0, abs=1e-6)
    assert float(np.linalg.norm(normal)) == pytest.approx(1.0)


def test_ring_geometry_needs_three_atoms():
    key = residue("A", 1, "PHE")
    assert ring_geometry([atom(key, "CG", (0, 0, 0)), atom(key, "CZ", (1, 0, 0))]) is None


def test_ring_angle_is_orientation_independent():
    assert ring_angle(np.array([0, 0, 1.0]), np.array([0, 0, 1.0])) == pytest.approx(0.0)
    assert ring_angle(np.array([0, 0, 1.0]), np.array([0, 0, -1.0])) == pytest.approx(0.0)
    assert ring_angle(np.array([0, 0, 1.0]), np.array([0, 1.0, 0])) == pytest.approx(90.0)


# -- salt bridges -------------------------------------------------------------


def test_salt_bridge_detected_within_cutoff_either_orientation():
    arg = residue("A", 10, "ARG")
    asp = residue("B", 20, "ASP")
    found = detect_interactions(
        [atom(arg, "NH1", (0, 0, 0), 7)],
        [atom(asp, "OD1", (3.5, 0, 0), 8)],
        kinds=["salt-bridge"],
    )
    assert [(item.kind, item.a, item.b) for item in found] == [("salt-bridge", arg, asp)]
    assert found[0].distance == pytest.approx(3.5)
    assert found[0].detail == "NH1–OD1"
    assert found[0].atomspec_a() == "#1/A:10@NH1"
    assert found[0].atomspec_b() == "#1/B:20@OD1"

    # Reversed roles: acidic residue in group A, basic in group B.
    reversed_found = detect_interactions(
        [atom(asp, "OD1", (0, 0, 0), 8)],
        [atom(arg, "NH1", (3.5, 0, 0), 7)],
        kinds=["salt-bridge"],
    )
    assert len(reversed_found) == 1


def test_salt_bridge_rejected_beyond_cutoff():
    found = detect_interactions(
        [atom(residue("A", 10, "LYS"), "NZ", (0, 0, 0), 7)],
        [atom(residue("B", 20, "GLU"), "OE1", (4.6, 0, 0), 8)],
        kinds=["salt-bridge"],
    )
    assert found == ()


def test_salt_bridge_ignores_uncharged_pairs():
    found = detect_interactions(
        [atom(residue("A", 10, "SER"), "OG", (0, 0, 0), 8)],
        [atom(residue("B", 20, "ALA"), "CB", (3.0, 0, 0))],
        kinds=["salt-bridge"],
    )
    assert found == ()


# -- hydrophobic --------------------------------------------------------------


def test_hydrophobic_contact_between_apolar_side_chains():
    leu = residue("A", 5, "LEU")
    val = residue("B", 8, "VAL")
    found = detect_interactions(
        [atom(leu, "CD1", (0, 0, 0))],
        [atom(val, "CG1", (4.0, 0, 0))],
        kinds=["hydrophobic"],
    )
    assert len(found) == 1
    assert found[0].distance == pytest.approx(4.0)


def test_hydrophobic_ignores_backbone_and_polar_residues():
    found = detect_interactions(
        [atom(residue("A", 5, "LEU"), "CA", (0, 0, 0))],  # backbone atom
        [atom(residue("B", 8, "VAL"), "CG1", (3.0, 0, 0))],
        kinds=["hydrophobic"],
    )
    assert found == ()
    found = detect_interactions(
        [atom(residue("A", 5, "SER"), "CB", (0, 0, 0))],  # polar residue
        [atom(residue("B", 8, "VAL"), "CG1", (3.0, 0, 0))],
        kinds=["hydrophobic"],
    )
    assert found == ()


# -- aromatic interactions ----------------------------------------------------


def test_parallel_pi_stacking_is_classified():
    ring_a = residue("A", 30, "PHE")
    ring_b = residue("B", 40, "TYR")
    found = detect_interactions(
        benzene(ring_a, (0.0, 0.0, 0.0), plane="xy"),
        benzene(ring_b, (0.0, 0.0, 4.0), plane="xy"),
        kinds=["pi-stacking"],
    )
    assert len(found) == 1
    assert found[0].distance == pytest.approx(4.0, abs=1e-6)
    assert found[0].detail.startswith("parallel")
    assert found[0].atom_a in PHE_RING and found[0].atom_b in PHE_RING


def test_t_shaped_pi_stacking_is_classified():
    ring_a = residue("A", 30, "PHE")
    ring_b = residue("B", 40, "PHE")
    found = detect_interactions(
        benzene(ring_a, (0.0, 0.0, 0.0), plane="xy"),
        benzene(ring_b, (0.0, 0.0, 4.0), plane="xz"),
        kinds=["pi-stacking"],
    )
    assert len(found) == 1
    assert found[0].detail.startswith("T-shaped")


def test_pi_stacking_rejected_beyond_centroid_cutoff():
    ring_a = residue("A", 30, "PHE")
    ring_b = residue("B", 40, "PHE")
    found = detect_interactions(
        benzene(ring_a, (0.0, 0.0, 0.0)),
        benzene(ring_b, (0.0, 0.0, 7.0)),
        kinds=["pi-stacking"],
    )
    assert found == ()


def test_incomplete_ring_is_skipped():
    ring_a = residue("A", 30, "PHE")
    ring_b = residue("B", 40, "PHE")
    partial = benzene(ring_b, (0.0, 0.0, 4.0))[:4]
    found = detect_interactions(
        benzene(ring_a, (0.0, 0.0, 0.0)), partial, kinds=["pi-stacking"]
    )
    assert found == ()


def test_cation_pi_detected_in_both_directions():
    lys = residue("A", 12, "LYS")
    phe = residue("B", 44, "PHE")
    found = detect_interactions(
        [atom(lys, "NZ", (0.0, 0.0, 0.0), 7)],
        benzene(phe, (0.0, 0.0, 5.0)),
        kinds=["cation-pi"],
    )
    assert len(found) == 1
    assert found[0].distance == pytest.approx(5.0, abs=1e-6)

    flipped = detect_interactions(
        benzene(phe, (0.0, 0.0, 0.0)),
        [atom(lys, "NZ", (0.0, 0.0, 5.0), 7)],
        kinds=["cation-pi"],
    )
    assert len(flipped) == 1
    assert flipped[0].a == phe and flipped[0].b == lys


# -- disulfide ----------------------------------------------------------------


def test_disulfide_detected_at_bonding_distance():
    cys_a = residue("A", 7, "CYS")
    cys_b = residue("B", 96, "CYS")
    found = detect_interactions(
        [atom(cys_a, "SG", (0, 0, 0), 16)],
        [atom(cys_b, "SG", (2.05, 0, 0), 16)],
        kinds=["disulfide"],
    )
    assert len(found) == 1
    found = detect_interactions(
        [atom(cys_a, "SG", (0, 0, 0), 16)],
        [atom(cys_b, "SG", (3.5, 0, 0), 16)],
        kinds=["disulfide"],
    )
    assert found == ()


# -- API contract -------------------------------------------------------------


def test_only_requested_kinds_are_returned():
    arg = residue("A", 10, "ARG")
    asp = residue("B", 20, "ASP")
    group_a = [atom(arg, "NH1", (0, 0, 0), 7), atom(arg, "CB", (1, 0, 0))]
    group_b = [atom(asp, "OD1", (3.0, 0, 0), 8), atom(asp, "CB", (3.5, 0, 0))]
    kinds = {item.kind for item in detect_interactions(group_a, group_b, ["salt-bridge"])}
    assert kinds == {"salt-bridge"}


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="unknown interaction type"):
        detect_interactions([], [], kinds=["magnetism"])


def test_overlapping_groups_are_rejected():
    shared = residue("A", 1, "ARG")
    with pytest.raises(ValueError, match="must not overlap"):
        detect_interactions(
            [atom(shared, "NH1", (0, 0, 0), 7)],
            [atom(shared, "NH1", (0, 0, 0), 7)],
        )


def test_custom_params_widen_detection():
    lys = residue("A", 10, "LYS")
    glu = residue("B", 20, "GLU")
    group_a = [atom(lys, "NZ", (0, 0, 0), 7)]
    group_b = [atom(glu, "OE1", (5.0, 0, 0), 8)]
    assert detect_interactions(group_a, group_b, ["salt-bridge"]) == ()
    widened = detect_interactions(
        group_a, group_b, ["salt-bridge"], InteractionParams(salt_bridge=5.5)
    )
    assert len(widened) == 1


def test_summarize_covers_every_kind():
    counts = summarize(detect_interactions([], []))
    assert set(counts) == set(KINDS)
    assert all(value == 0 for value in counts.values())


def test_results_are_stably_ordered():
    arg = residue("A", 10, "ARG")
    asp = residue("B", 20, "ASP")
    lys = residue("A", 11, "LYS")
    glu = residue("B", 21, "GLU")
    group_a = [atom(arg, "NH1", (0, 0, 0), 7), atom(lys, "NZ", (10, 0, 0), 7)]
    group_b = [atom(asp, "OD1", (3.0, 0, 0), 8), atom(glu, "OE1", (13.0, 0, 0), 8)]
    first = detect_interactions(group_a, group_b, ["salt-bridge"])
    second = detect_interactions(group_a[::-1], group_b[::-1], ["salt-bridge"])
    assert first == second
    assert len(first) == 2
