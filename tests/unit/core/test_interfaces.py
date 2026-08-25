import pytest

from src.core.interfaces import AtomPoint, ResidueKey, detect_interface


def residue(chain, number):
    return ResidueKey("#1", chain, number, "", "ALA", f"#1/{chain}:{number}")


def point(residue_key, xyz):
    return AtomPoint(residue_key, xyz)


def test_detects_contact_at_inclusive_cutoff_and_sorts_results():
    a2, a1, b1 = residue("A", 2), residue("A", 1), residue("B", 1)
    result = detect_interface(
        [point(a2, (20.0, 0.0, 0.0)), point(a1, (0.0, 0.0, 0.0))],
        [point(b1, (4.5, 0.0, 0.0))],
        cutoff=4.5,
    )
    assert result.group_a == (a1,)
    assert result.group_b == (b1,)
    assert [(pair.a, pair.b) for pair in result.contacts] == [(a1, b1)]
    assert result.cutoff == 4.5


def test_returns_empty_result_without_contacts():
    result = detect_interface(
        [point(residue("A", 1), (0.0, 0.0, 0.0))],
        [point(residue("B", 1), (8.0, 0.0, 0.0))],
    )
    assert result.group_a == ()
    assert result.group_b == ()
    assert result.contacts == ()


@pytest.mark.parametrize("cutoff", [1.99, 10.01, 0.0])
def test_rejects_cutoff_outside_approved_range(cutoff):
    with pytest.raises(ValueError, match="2.0 and 10.0"):
        detect_interface([], [], cutoff=cutoff)


def test_rejects_a_residue_present_in_both_groups():
    shared = residue("A", 1)
    with pytest.raises(ValueError, match="must not overlap"):
        detect_interface([point(shared, (0, 0, 0))], [point(shared, (0, 0, 0))])


def test_multiple_atomic_contacts_produce_one_residue_pair():
    a1, b1 = residue("A", 1), residue("B", 1)
    result = detect_interface(
        [point(a1, (0, 0, 0)), point(a1, (0, 1, 0))],
        [point(b1, (3, 0, 0)), point(b1, (3, 1, 0))],
    )
    assert len(result.contacts) == 1


def test_cutoff_changes_contact_result():
    a1, b1 = residue("A", 1), residue("B", 1)
    group_a = [point(a1, (0, 0, 0))]
    group_b = [point(b1, (4.5, 0, 0))]
    assert detect_interface(group_a, group_b, cutoff=4.0).contacts == ()
    assert len(detect_interface(group_a, group_b, cutoff=5.0).contacts) == 1


def test_multi_chain_groups_are_supported():
    a1, c1 = residue("A", 1), residue("C", 1)
    b1, d1 = residue("B", 1), residue("D", 1)
    result = detect_interface(
        [point(a1, (0.0, 0.0, 0.0)), point(c1, (10.0, 0.0, 0.0))],
        [point(b1, (3.0, 0.0, 0.0)), point(d1, (13.0, 0.0, 0.0))],
    )
    assert result.group_a == (a1, c1)
    assert result.group_b == (b1, d1)
    assert len(result.contacts) == 2


def test_result_ordering_is_stable_across_input_order():
    a1, a2 = residue("A", 1), residue("A", 2)
    b1, b2 = residue("B", 1), residue("B", 2)
    forward = detect_interface(
        [point(a1, (0, 0, 0)), point(a2, (1, 0, 0))],
        [point(b1, (2, 0, 0)), point(b2, (3, 0, 0))],
    )
    reversed_input = detect_interface(
        [point(a2, (1, 0, 0)), point(a1, (0, 0, 0))],
        [point(b2, (3, 0, 0)), point(b1, (2, 0, 0))],
    )
    assert forward == reversed_input
