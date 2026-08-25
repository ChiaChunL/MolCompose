import pytest

from src.core.confidence import (
    ConfidenceReport,
    build_report,
    detect_plddt_scale,
    interface_plddt,
    palette_spec,
    pdockq_score,
)
from src.core.interfaces import ResidueKey


def key(number):
    return ResidueKey("#1", "A", number, "", "ALA", f"#1/A:{number}")


def test_detects_zero_to_one_scale():
    assert detect_plddt_scale([0.3, 0.9, 1.0]) == "0-1"


def test_detects_zero_to_hundred_scale():
    assert detect_plddt_scale([35.0, 92.5, 100.0]) == "0-100"


def test_rejects_values_above_plddt_range():
    with pytest.raises(ValueError, match="does not look like pLDDT"):
        detect_plddt_scale([12.0, 180.0])


def test_rejects_empty_values():
    with pytest.raises(ValueError, match="no B-factor/pLDDT values"):
        detect_plddt_scale([])


def test_rejects_uniform_zero_placeholder_values():
    """A zero-filled PDB B-factor field is missing data, not 0-1 pLDDT."""
    with pytest.raises(ValueError, match="uniformly zero"):
        detect_plddt_scale([0.0, 0.0, 0.0])


def test_palette_spec_uses_afdb_colors_on_both_scales():
    assert palette_spec("0-100") == (
        "0,#FF7D45:49.99,#FF7D45:50,#FFDB13:69.99,#FFDB13:"
        "70,#65CBF3:89.99,#65CBF3:90,#0053D6:100,#0053D6"
    )
    assert palette_spec("0-1") == (
        "0,#FF7D45:0.4999,#FF7D45:0.5,#FFDB13:0.6999,#FFDB13:"
        "0.7,#65CBF3:0.8999,#65CBF3:0.9,#0053D6:1,#0053D6"
    )


def _sample_palette(spec, value):
    """The colour a linearly interpolating renderer draws at `value`.

    ChimeraX blends between palette stops, so this is what actually reaches
    the screen — not the stop list.
    """
    stops = [(float(v), c) for v, c in (s.split(",") for s in spec.split(":"))]
    if value <= stops[0][0]:
        return stops[0][1].upper()
    if value >= stops[-1][0]:
        return stops[-1][1].upper()
    for (low, low_colour), (high, high_colour) in zip(stops, stops[1:], strict=False):
        if low <= value <= high:
            if high == low or low_colour == high_colour:
                return low_colour.upper()
            fraction = (value - low) / (high - low)
            channels = (
                round(int(low_colour[i:i + 2], 16) * (1 - fraction)
                      + int(high_colour[i:i + 2], 16) * fraction)
                for i in (1, 3, 5)
            )
            return "#" + "".join(f"{c:02X}" for c in channels)
    raise AssertionError(f"{value} fell outside {spec}")


@pytest.mark.parametrize(
    ("scale", "samples"),
    [
        ("0-100", ((10.0, "#FF7D45"), (60.0, "#FFDB13"), (80.0, "#65CBF3"),
                   (95.0, "#0053D6"))),
        ("0-1", ((0.10, "#FF7D45"), (0.60, "#FFDB13"), (0.80, "#65CBF3"),
                 (0.95, "#0053D6"))),
    ],
)
def test_palette_paints_flat_bands_not_a_gradient(scale, samples):
    """A value inside a band must render as that band's exact colour.

    This is the defect the repeated stops exist to prevent. With four stops
    the palette was a continuous ramp where AlphaFold defines four flat bands:
    pLDDT 60 came out #B2D383, a yellow-green that corresponds to no band at
    all, and readers who know the AlphaFold colours misread it. Asserting the
    stop string would not have caught this — the old string was a perfectly
    well-formed palette, just not the one the convention calls for.
    """
    spec = palette_spec(scale)
    for value, expected in samples:
        assert _sample_palette(spec, value) == expected, (
            f"{scale} at {value} renders {_sample_palette(spec, value)}, "
            f"not the band colour {expected}"
        )


def test_low_confidence_keys_respect_scale():
    report_100 = ConfidenceReport("0-100", ((key(1), 92.0), (key(2), 49.9), (key(3), 50.0)))
    assert report_100.low_confidence_keys() == (key(2),)
    report_1 = ConfidenceReport("0-1", ((key(1), 0.92), (key(2), 0.49)))
    assert report_1.low_confidence_keys() == (key(2),)


def test_normalized_mean_is_always_on_hundred_scale():
    report = ConfidenceReport("0-1", ((key(1), 0.8), (key(2), 0.6)))
    assert report.normalized_mean == pytest.approx(70.0)
    report = ConfidenceReport("0-100", ((key(1), 80.0), (key(2), 60.0)))
    assert report.normalized_mean == pytest.approx(70.0)


def test_build_report_detects_scale_from_residue_values():
    report = build_report([(key(1), 0.95), (key(2), 0.40)])
    assert report.scale == "0-1"
    assert report.low_confidence_keys() == (key(2),)


def test_interface_plddt_averages_only_interface_residues():
    report = ConfidenceReport(
        "0-100", ((key(1), 90.0), (key(2), 70.0), (key(3), 30.0))
    )
    assert interface_plddt(report, [key(1), key(2)]) == 80.0
    assert interface_plddt(report, []) is None
    zero_one = ConfidenceReport("0-1", ((key(1), 0.9),))
    assert interface_plddt(zero_one, [key(1)]) == 90.0


def test_pdockq_matches_reference_sigmoid():
    # x = 90 * log10(100) = 180 -> 0.724/(1+exp(-0.052*27.389)) + 0.018
    assert pdockq_score(90.0, 100) == pytest.approx(0.6015, abs=1e-3)
    assert pdockq_score(90.0, 0) is None


def test_the_band_lookup_and_the_palette_come_from_one_table():
    """A second copy of four colours is a promise to eventually disagree.

    The sequence export needs a colour per value; the structure gets a palette
    string. Both are generated from `_AF_BANDS`, so a band boundary can only
    move in both at once.
    """
    from src.core.confidence import _AF_BANDS, band_color, band_label, palette_spec

    for boundary, colour in _AF_BANDS:
        if boundary is None:
            continue
        # Just below a boundary is the band below; the boundary itself is the
        # band above, which is how AlphaFold defines them.
        assert band_color(boundary - 0.01) == colour
        assert band_color(boundary) != colour

    # Every band colour the lookup can return also appears in the palette the
    # structure is painted with.
    spec = palette_spec("0-100")
    for _boundary, colour in _AF_BANDS:
        assert colour in spec

    assert band_color(95) == "#0053D6"
    assert band_label(95) == "pLDDT 90-100"
    # The 0-1 scale is the same bands on a different axis.
    assert band_color(0.95, "0-1") == band_color(95)
