"""Whether the figure's colours can actually be told apart.

Three things had to be got right here, and each was got wrong first.

**Measure hue and saturation, not RGB distance.** The original check summed
absolute RGB differences and passed a palette that did not read at all: a
brick-red interface on a salmon body scores 238 there, which looks like
plenty, while on screen it was one colour in shadow. Lightness is already
spent — ambient-occlusion shading varies it across every cartoon — so two
shades of one hue read as the same colour lit differently no matter how far
apart their RGB values are.

**Compare within a colouring mode, not across all of them.** Requiring every
colour in the toolkit to differ from every other made the problem unsolvable:
two interfaces, two ramps and five interaction types need 9 x 42 = 378 degrees
of a 360-degree circle. But the modes are mutually exclusive. Painting by ΔΔG
*replaces* the interface colours, so they never share a figure and never have
to be distinguishable. Within a mode there are only ever three regions plus
the lines.

**Weight the threshold by form.** A dashed pseudobond crossing a filled
cartoon region is not mistakable for it — the shapes differ. Two filled
regions have nothing but colour. So region-against-region needs the full gap;
line-against-region needs less; line-against-line needs the full gap again,
because those are the same form as each other.
"""

import colorsys

import pytest

from src.adapters.renderer import INTERACTION_COLORS
from src.core.coloring import DIVERGING, SEQUENTIAL
from src.core.presets import BODY_GREY, NO_DATA, get_preset

REGION_HUE_GAP = 42.0   # degrees, between two filled regions
LINE_HUE_GAP = 25.0     # between a line and a region it crosses
SATURATION_GAP = 0.45   # enough on its own, whatever the hues
NEUTRAL = 0.12          # below this a colour has no usable hue


def hsv(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return colorsys.rgb_to_hsv(*(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def reads_apart(first: str, second: str, *, both_regions: bool = True) -> bool:
    (hue_a, sat_a, _), (hue_b, sat_b, _) = hsv(first), hsv(second)
    if min(sat_a, sat_b) < NEUTRAL:
        # One of them is effectively grey; hue carries no information, so the
        # separation has to come from vividness alone.
        return abs(sat_a - sat_b) > SATURATION_GAP
    hue = abs(hue_a - hue_b) * 360
    needed = REGION_HUE_GAP if both_regions else LINE_HUE_GAP
    return min(hue, 360 - hue) > needed or abs(sat_a - sat_b) > SATURATION_GAP


LINES = tuple(INTERACTION_COLORS.items())


def mode_regions(name):
    """The filled regions visible at once, per colouring mode."""
    preset = get_preset("interface-focus")
    interface_a, interface_b = preset.interface_colors()
    return {
        "partners": [("body", BODY_GREY), ("interface A", interface_a),
                     ("interface B", interface_b)],
        "ddg": [("body", BODY_GREY), ("no data", NO_DATA),
                ("ramp low", DIVERGING[0]), ("ramp high", DIVERGING[-1])],
        "dsasa": [("body", BODY_GREY), ("no data", NO_DATA),
                  ("ramp mid", SEQUENTIAL[2]), ("ramp high", SEQUENTIAL[-1])],
    }[name]


@pytest.mark.parametrize("mode", ["partners", "ddg", "dsasa"])
def test_the_regions_of_a_mode_read_against_each_other(mode):
    regions = mode_regions(mode)
    for index, (name_a, colour_a) in enumerate(regions):
        for name_b, colour_b in regions[index + 1:]:
            if {name_a, name_b} == {"body", "no data"}:
                continue  # deliberately the same colour: see NO_DATA
            if name_a.startswith("ramp") and name_b.startswith("ramp"):
                continue  # two steps of one scale are meant to be a gradient
            assert reads_apart(colour_a, colour_b), f"{mode}: {name_a} vs {name_b}"


@pytest.mark.parametrize("mode", ["partners", "ddg", "dsasa"])
def test_the_lines_read_against_every_region_they_cross(mode):
    for region_name, region in mode_regions(mode):
        for kind, colour in LINES:
            assert reads_apart(colour, region, both_regions=False), \
                f"{mode}: {kind} over {region_name}"


def test_the_dashed_lines_read_against_each_other():
    """Same form as each other, so colour is all they have.

    The disulfide is exempt because it is not the same form: it is drawn
    solid, being a covalent bond, which is both chemically right and what
    freed a hue for the four region colours to spread into.
    """
    dashed = [(k, c) for k, c in LINES if k != "disulfide"]
    for index, (kind, colour) in enumerate(dashed):
        for other_kind, other in dashed[index + 1:]:
            assert reads_apart(colour, other), f"{kind} vs {other_kind}"


def test_the_disulfide_is_drawn_solid():
    from src.adapters.renderer import INTERACTION_DASH_COUNT

    assert INTERACTION_DASH_COUNT["disulfide"] == 0


def test_the_bodies_carry_no_colour_of_their_own():
    """Grey bodies, coloured interface — the scheme the author asked for.

    Every palette this shipped before 2026-08-16 coloured the two bodies, and
    the whole set was rejected at once for it. The figure's subject is the
    interface; two saturated bodies compete with the one patch that matters,
    and on a complex where the bodies are most of the pixels they win. So the
    bodies give up their hue and the interface keeps it, which is also what
    the antibody figures this borrows from do — a neutral antigen with the
    epitope picked out.
    """
    preset = get_preset("interface-focus")
    for body in (preset.palette.body_a, preset.palette.body_b):
        assert hsv(body)[1] < NEUTRAL, f"{body} still carries a hue"
        # Pale, not dark: these sit under the whole figure.
        assert hsv(body)[2] > 0.7, f"{body} is too dark to be context"


def test_the_two_partners_are_still_separable():
    """Neutral is not the same as identical.

    The bodies have to be told apart where the two chains overlap, which is
    exactly where the interface is. They do it on lightness alone, since they
    have no hue left to do it with — a small gap, but the only one available,
    and enough because the two are adjacent rather than far apart.
    """
    preset = get_preset("interface-focus")
    a, b = hsv(preset.palette.body_a)[2], hsv(preset.palette.body_b)[2]
    assert abs(a - b) > 0.04, "the two greys are indistinguishable"


def test_a_side_chain_reads_on_either_interface_colour():
    """Side chains sit on the patch, not on the body.

    They are one neutral for both partners, so that one colour has to hold up
    against both interface colours rather than against the greys underneath.
    """
    preset = get_preset("interface-focus")
    sidechain = preset.palette.sidechain
    for interface in preset.interface_colors():
        assert abs(hsv(sidechain)[2] - hsv(interface)[2]) > 0.2, (
            f"{sidechain} has nothing to separate it from {interface}"
        )


def test_a_ramp_preset_greys_its_bodies_instead():
    """A ramp wants the colour circle to itself, so the partners give it up."""
    preset = get_preset("hotspot-focus")
    assert preset.palette.body_a == preset.palette.body_b == BODY_GREY
    assert hsv(BODY_GREY)[1] < 0.05


def test_the_interfaces_are_the_saturated_thing():
    for interface in get_preset("interface-focus").interface_colors():
        assert hsv(interface)[1] > 0.60


def test_no_data_is_the_body_colour():
    """A residue the metric cannot speak for should look like unremarked context.

    It used to keep its partner colour, which on this palette is the same red
    the diverging ramp uses for "highly destabilising" — one figure, two
    meanings, one colour.
    """
    assert NO_DATA == BODY_GREY


def test_the_measure_would_have_failed_the_palette_it_replaced():
    """A regression guard on the check itself, not on the colours.

    Brick #A62B1A on salmon #E8836E was shipped because RGB distance scored it
    238. Three degrees of hue apart, and it was invisible.
    """
    assert not reads_apart("#A62B1A", "#E8836E")
