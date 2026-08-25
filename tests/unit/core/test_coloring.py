"""Per-residue metric colour scales."""

import pytest

from src.core.coloring import (
    DIVERGING,
    SEQUENTIAL,
    ColorScale,
    assign,
    build_scale,
    group_by_color,
    quantile,
)


def test_quantile_interpolates_between_neighbours():
    values = [0.0, 1.0, 2.0, 3.0]
    assert quantile(values, 0.0) == 0.0
    assert quantile(values, 1.0) == 3.0
    assert quantile(values, 0.5) == pytest.approx(1.5)


def test_quantile_handles_a_single_value():
    assert quantile([2.5], 0.98) == 2.5


def test_scale_comes_from_the_data_not_a_documented_range():
    """The reason this is data-driven rather than fixed.

    PythiaStudio documents Pythia ΔΔG as spanning −5 to 5; a real export spans
    −11.7 to +36.4. A scale hard-coded to the documented ends would paint every
    residue past them the same colour — and those are the residues worth
    looking at.
    """
    values = [-11.7, -2.0, 0.0, 1.0, 8.6, 36.4]
    scale = build_scale(values, "diverging")
    assert scale.high > 5.0
    # The extreme residue is not in the same band as a merely strong one.
    assert scale.color_for(36.4) == DIVERGING[-1]
    assert scale.bucket(36.4) != scale.bucket(1.0)


def test_diverging_scale_is_symmetric_about_zero():
    """Equal magnitudes of opposite sign must read as equally strong."""
    scale = build_scale([-1.0, 0.5, 8.0], "diverging")
    assert scale.low == pytest.approx(-scale.high)
    assert scale.color_for(0.0) == DIVERGING[len(DIVERGING) // 2]


def test_diverging_scale_puts_the_two_directions_on_opposite_arms():
    scale = build_scale([-4.0, 0.0, 4.0], "diverging")
    assert scale.color_for(-3.9) == DIVERGING[0]
    assert scale.color_for(3.9) == DIVERGING[-1]


def test_sequential_scale_starts_at_zero_for_magnitude_only_metrics():
    scale = build_scale([12.0, 40.0, 120.7], "sequential")
    assert scale.low == 0.0
    assert scale.colors == SEQUENTIAL


def test_outliers_do_not_own_the_scale():
    """Clipping at the 2nd/98th percentile keeps one extreme from flattening the rest."""
    values = [*[1.0] * 50, 1000.0]
    scale = build_scale(values, "sequential")
    assert scale.high < 100.0


def test_values_beyond_the_scale_clamp_rather_than_error():
    scale = build_scale([0.0, 1.0], "sequential")
    assert scale.color_for(-500.0) == scale.colors[0]
    assert scale.color_for(500.0) == scale.colors[-1]


def test_a_constant_metric_does_not_divide_by_zero():
    scale = build_scale([2.0, 2.0, 2.0], "diverging")
    assert scale.color_for(2.0) in DIVERGING


def test_all_zero_values_produce_a_usable_scale():
    scale = build_scale([0.0, 0.0], "diverging")
    assert scale.high > 0
    assert scale.color_for(0.0) in DIVERGING


def test_empty_input_is_rejected():
    with pytest.raises(ValueError, match="no values"):
        build_scale([], "diverging")


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="scale kind must be one of"):
        build_scale([1.0], "rainbow")


def test_assignments_group_so_one_command_paints_each_band():
    scale = build_scale([-4.0, 0.0, 4.0], "diverging")
    grouped = group_by_color(assign([("#1/A:1", -3.9), ("#1/A:2", -3.8)], scale))
    assert list(grouped) == [DIVERGING[0]]
    assert grouped[DIVERGING[0]] == ["#1/A:1", "#1/A:2"]


def test_a_value_between_anchors_gets_a_colour_between_them():
    """The ramp is continuous, because every metric on it is.

    Five blocks would claim a structure buried area and ddG do not have. Only
    pLDDT keeps discrete bands, and it is drawn from a different table.
    """
    scale = ColorScale("sequential", 0.0, 100.0, SEQUENTIAL)
    middle = scale.color_for(12.5)
    assert middle not in SEQUENTIAL
    # Between the first two anchors, not off somewhere else on the ramp.
    for channel in (1, 3, 5):
        low = int(SEQUENTIAL[0][channel:channel + 2], 16)
        high = int(SEQUENTIAL[1][channel:channel + 2], 16)
        assert min(low, high) <= int(middle[channel:channel + 2], 16) <= max(low, high)


def test_anchor_values_land_on_their_anchor_colour_exactly():
    """What the key prints has to be a colour a residue can actually be."""
    scale = ColorScale("diverging", -4.0, 4.0, DIVERGING)
    assert scale.color_for(-4.0) == DIVERGING[0]
    assert scale.color_for(0.0) == DIVERGING[2]
    assert scale.color_for(4.0) == DIVERGING[-1]


def test_the_key_carries_each_anchor_once_so_the_bar_is_a_gradient():
    """Drawn `blended`, one stop per anchor is a ramp; doubled stops step.

    The bar and the structure are interpolated between the same anchors, so
    emitting a colour twice would make the key stepped while the figure is
    smooth.
    """
    scale = ColorScale("diverging", -4.0, 4.0, DIVERGING)
    colours = [colour for colour, _label in scale.key_labels]
    assert colours == list(DIVERGING)
    assert [label for _colour, label in scale.key_labels][2] == "0"


def test_legend_covers_the_full_range_in_order():
    scale = ColorScale("diverging", -2.0, 2.0, DIVERGING)
    legend = scale.legend
    assert len(legend) == len(DIVERGING)
    assert legend[0][0] == DIVERGING[0]
    assert "-2.00" in legend[0][1]


def test_a_negative_favourable_metric_reads_the_ramp_the_other_way():
    """Red has to mean "matters more" on both kcal/mol metrics.

    Mutational ΔΔG is positive where a residue matters; MM/PBSA decomposition
    is negative there. On one ramp red would mean "important" on one panel and
    "unfavourable" on the next, so the ramp is oriented per metric while the
    values stay as the file gave them.
    """
    ddg = build_scale([-2.0, 0.0, 8.0], kind="diverging")
    energy = build_scale([-10.0, 0.0, 2.0], kind="diverging-negative")
    assert ddg.colors == tuple(reversed(energy.colors))
    # The important end is the same colour on both.
    assert ddg.color_for(8.0) == energy.color_for(-10.0)
    # And the values are untouched: both stay symmetric about zero.
    assert energy.low == -energy.high


def test_the_reversed_scale_still_labels_signed_values():
    scale = build_scale([-10.3, -1.0, 2.3], kind="diverging-negative")
    labels = [label for _colour, label in scale.key_labels]
    assert any(text.startswith("-") for text in labels)
    assert any(text.startswith("+") for text in labels)

