"""The geometry behind the two interface views."""

import math

import pytest

from src.core.viewpoint import (
    centroid,
    cross,
    interface_axis,
    norm,
    open_book,
    perpendicular,
)


def test_the_axis_runs_from_one_interface_centroid_to_the_other():
    a = [(0.0, 0.0, 0.0), (0.0, 2.0, 0.0)]
    b = [(10.0, 0.0, 0.0), (10.0, 2.0, 0.0)]
    assert interface_axis(a, b) == pytest.approx((1.0, 0.0, 0.0))


def test_the_axis_is_a_unit_vector_whatever_the_separation():
    a = [(0.0, 0.0, 0.0)]
    b = [(3.0, 4.0, 12.0)]
    assert norm(interface_axis(a, b)) == pytest.approx(1.0)


def test_coincident_centroids_are_refused_rather_than_producing_a_nan():
    """Two groups on top of each other define no axis, and dividing by its
    length would hand ChimeraX a NaN camera matrix."""
    points = [(1.0, 1.0, 1.0)]
    with pytest.raises(ValueError, match="no axis"):
        interface_axis(points, points)


@pytest.mark.parametrize(
    "axis",
    [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 1.0),
     (0.0, 0.6, 0.8), (-1.0, 0.0, 0.0)],
)
def test_the_hinge_is_perpendicular_and_never_degenerate(axis):
    """Crossing with a fixed cardinal would collapse when the axis matches it."""
    hinge = perpendicular(axis)
    assert norm(hinge) == pytest.approx(1.0)
    dot = sum(hinge[i] * axis[i] for i in range(3))
    assert dot == pytest.approx(0.0, abs=1e-9)


def test_open_book_moves_the_partners_in_opposite_directions():
    a = [(0.0, 0.0, 0.0), (0.0, 3.0, 0.0)]
    b = [(20.0, 0.0, 0.0), (20.0, 3.0, 0.0)]
    left, right = open_book(a, b)
    assert left.shift[0] < 0 < right.shift[0]
    assert left.shift[0] == pytest.approx(-right.shift[0])


def test_open_book_turns_one_partner_a_half_turn():
    """The turn is what makes the buried face point outwards; without it the
    two halves simply drift apart still facing each other."""
    a = [(0.0, 0.0, 0.0), (0.0, 3.0, 0.0)]
    b = [(20.0, 0.0, 0.0), (20.0, 3.0, 0.0)]
    left, right = open_book(a, b)
    assert left.angle == pytest.approx(180.0)
    assert right.angle == pytest.approx(0.0)


def test_both_partners_hinge_about_the_same_axis():
    a = [(0.0, 0.0, 0.0), (1.0, 2.0, 0.0)]
    b = [(9.0, 1.0, 2.0), (11.0, 0.0, 1.0)]
    left, right = open_book(a, b)
    assert left.axis == pytest.approx(right.axis)


def test_each_partner_turns_about_its_own_centre():
    a = [(0.0, 0.0, 0.0), (0.0, 4.0, 0.0)]
    b = [(20.0, 0.0, 0.0), (20.0, 4.0, 0.0)]
    left, right = open_book(a, b)
    assert left.centre == pytest.approx(centroid(a))
    assert right.centre == pytest.approx(centroid(b))


def test_the_gap_scales_with_the_larger_partner():
    """A nanobody against a receptor must not be flung out of frame, and two
    large domains must not still overlap."""
    small_a = [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    small_b = [(10.0, 0.0, 0.0), (10.0, 1.0, 0.0)]
    big_b = [(10.0, y, 0.0) for y in range(0, 40, 4)]
    small_gap = open_book(small_a, small_b)[1].shift[0]
    big_gap = open_book(small_a, big_b)[1].shift[0]
    assert big_gap > small_gap


def test_cross_follows_the_right_hand_rule():
    assert cross((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)) == pytest.approx((0.0, 0.0, 1.0))


def test_centroid_of_nothing_is_refused():
    with pytest.raises(ValueError, match="no points"):
        centroid([])


def test_the_hinge_of_a_diagonal_axis_is_still_a_unit_vector():
    hinge = perpendicular((1.0, 1.0, 1.0))
    assert norm(hinge) == pytest.approx(1.0)
    assert not any(math.isnan(component) for component in hinge)


class TestLabelPlacement:
    """`fan_offsets` spreads a label around its own residue; it cannot see that
    two residues are close together on screen. His102 and Tyr29 printed over
    each other as one unreadable word because of it."""

    def test_two_close_points_get_labels_pushed_apart(self):
        import math

        from src.core.viewpoint import place_labels

        # Two residues almost on top of each other in projection.
        points = [(0.0, 0.0), (0.3, 0.0)]
        angles = place_labels(points, angle_count=8, spread=1.0)
        positions = [
            (x + math.cos(a), y + math.sin(a))
            for (x, y), a in zip(points, angles, strict=True)
        ]
        separation = math.dist(positions[0], positions[1])
        # The naive fan would put them at 0° and 45°, which on these two points
        # lands the labels 0.83 apart — closer than the residues themselves.
        assert separation > 1.5

    def test_a_label_does_not_land_on_another_residue(self):
        import math

        from src.core.viewpoint import place_labels

        points = [(0.0, 0.0), (1.0, 0.0)]
        angles = place_labels(points, angle_count=8, spread=1.0)
        first = (math.cos(angles[0]), math.sin(angles[0]))
        # Angle 0 would put the first label exactly on the second residue.
        assert math.dist(first, points[1]) > 0.5

    def test_labels_point_away_from_the_crowd(self):
        """With room to choose, each label leans away from the other residues.

        Not the naive fan's fixed angles, and better than them: on a real
        interface every label ends up outside the cluster rather than pointing
        back into it.
        """
        import math

        from src.core.viewpoint import place_labels

        points = [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0)]
        angles = place_labels(points, angle_count=8, spread=1.0)
        positions = [
            (x + math.cos(a) * 1.0, y + math.sin(a) * 1.0)
            for (x, y), a in zip(points, angles, strict=True)
        ]
        centre = (sum(x for x, _ in points) / 3, sum(y for _, y in points) / 3)
        for point, label in zip(points, positions, strict=True):
            assert math.dist(label, centre) > math.dist(point, centre)

    def test_the_choice_is_deterministic(self):
        from src.core.viewpoint import place_labels

        points = [(0.0, 0.0), (0.4, 0.1), (1.2, 0.9)]
        assert (place_labels(points, 8, 1.0) == place_labels(points, 8, 1.0))

    def test_offsets_at_returns_camera_plane_vectors(self):
        from src.core.viewpoint import offsets_at

        offsets = offsets_at((0.0,), (1, 0, 0), (0, 1, 0), 2.0)
        assert offsets[0] == pytest.approx((2.0, 0.0, 0.0))

    def test_project_puts_a_point_in_the_camera_plane(self):
        from src.core.viewpoint import project

        assert project((3.0, 4.0, 5.0), (1, 0, 0), (0, 1, 0)) == (3.0, 4.0)
