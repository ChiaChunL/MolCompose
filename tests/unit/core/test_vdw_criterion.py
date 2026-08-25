"""Contact by van der Waals overlap, ChimeraX's own default criterion.

A fixed centre-to-centre cutoff treats a sulphur and a carbon alike, and they
are not alike: their van der Waals radii differ by 0.1 Å, so the distance at
which they touch differs too. This criterion asks whether the spheres overlap
instead, which is what the ChimeraX Contacts tool does and what "in contact"
means physically.
"""

import pytest

from src.core.interfaces import DEFAULT_VDW_OVERLAP, AtomPoint, ResidueKey, detect_interface


def key(chain, number):
    return ResidueKey("#1", chain, number, "", "ALA", f"#1/{chain}:{number}")


def point(chain, number, x, radius=1.7):
    return AtomPoint(key(chain, number), (x, 0.0, 0.0), radius)


def test_two_carbons_touch_within_the_default_overlap():
    """Two 1.7 Å spheres reach 3.4 Å; the default allows 0.4 Å more."""
    a = (point("A", 1, 0.0),)
    b = (point("D", 1, 3.7),)
    result = detect_interface(a, b, cutoff=DEFAULT_VDW_OVERLAP, criterion="vdw")
    assert len(result.contacts) == 1


def test_and_stop_touching_beyond_it():
    a = (point("A", 1, 0.0),)
    b = (point("D", 1, 3.9),)
    result = detect_interface(a, b, cutoff=DEFAULT_VDW_OVERLAP, criterion="vdw")
    assert not result.contacts


def test_a_larger_atom_reaches_further_at_the_same_overlap():
    """The whole point: sulphur touches at a distance carbon does not.

    A fixed 3.8 Å cutoff would call both of these contacts or neither.
    """
    carbon = detect_interface(
        (point("A", 1, 0.0, radius=1.7),), (point("D", 1, 3.85, radius=1.7),),
        cutoff=DEFAULT_VDW_OVERLAP, criterion="vdw",
    )
    sulphur = detect_interface(
        (point("A", 1, 0.0, radius=1.8),), (point("D", 1, 3.85, radius=1.8),),
        cutoff=DEFAULT_VDW_OVERLAP, criterion="vdw",
    )
    assert not carbon.contacts
    assert len(sulphur.contacts) == 1


def test_a_positive_overlap_demands_actual_interpenetration():
    """Two 1.7 Å spheres meet at 3.4 Å, so +0.2 overlap means 3.2 Å or closer."""
    a = (point("A", 1, 0.0),)
    assert detect_interface(a, (point("D", 1, 3.1),), cutoff=0.2,
                            criterion="vdw").contacts
    assert not detect_interface(a, (point("D", 1, 3.3),), cutoff=0.2,
                                criterion="vdw").contacts


def test_missing_radii_are_refused_rather_than_assumed():
    """Defaulting to a radius would silently answer a different question."""
    a = (AtomPoint(key("A", 1), (0.0, 0.0, 0.0), 0.0),)
    b = (point("D", 1, 3.0),)
    with pytest.raises(ValueError, match="van der Waals radii"):
        detect_interface(a, b, cutoff=DEFAULT_VDW_OVERLAP, criterion="vdw")


def test_overlapping_groups_are_refused_here_too():
    a = (point("A", 1, 0.0),)
    with pytest.raises(ValueError, match="must not overlap"):
        detect_interface(a, a, cutoff=DEFAULT_VDW_OVERLAP, criterion="vdw")


def test_an_absurd_overlap_is_refused():
    a, b = (point("A", 1, 0.0),), (point("D", 1, 3.0),)
    with pytest.raises(ValueError, match="between -2.0 and 2.0"):
        detect_interface(a, b, cutoff=9.0, criterion="vdw")


def test_the_distance_criteria_ignore_radii_entirely():
    """`heavy` must keep behaving exactly as before radii existed."""
    a = (point("A", 1, 0.0, radius=99.0),)
    b = (point("D", 1, 8.0, radius=99.0),)
    assert not detect_interface(a, b, cutoff=4.5).contacts
