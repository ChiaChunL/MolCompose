import pytest

from src.core.presets import PRESETS, assign_chain_colors, get_preset


def test_exact_preset_catalog():
    assert set(PRESETS) == {
        "clean-cartoon",
        "complex-by-chain",
        "design-reference",
        "interface-focus",
        "flat-outline",
        "licorice-closeup",
        "licorice-chain",
        "surface-complex",
        "epitope-surface",
        "surface-partner-a",
        "surface-translucent",
        "surface-epitope-map",
        "paratope-closeup",
        "hotspot-focus",
        "predicted-structure",
        "metric-map",
    }
    assert PRESETS["interface-focus"].requires_interface is True
    assert PRESETS["predicted-structure"].confidence_coloring is True
    assert PRESETS["design-reference"].reference_comparison is True
    assert PRESETS["design-reference"].panel_visible is False
    # The two interface presets carry versions because their colours changed
    # materially, and the version travels with every figure's provenance
    # record so a reader can tell which rendering produced a given figure.
    # interface-focus: v2 lightness (invisible under the cartoon's own
    # shading), v3 saturation with tinted bodies, v4 neutral grey bodies,
    # v5 one hue per partner split by saturation — which read as monochrome —
    # v6 a separate hue for each of the four regions, v7 no surface,
    # v8 side chains no longer painted with the interface colour, occlusion
    # added on top of the key light, interface colours a step brighter,
    # v9 the specular highlight cut from 0.45 to 0.08 — "too metallic",
    # three rounds running, and it was that term rather than the light.
    assert PRESETS["interface-focus"].version == 10
    # hotspot-focus and the two cartoons moved to the Shading/Geometry/Palette
    # schema in v8 of interface-focus; the rendering they emit changed with
    # it, so their versions move too rather than leaving figures made before
    # and after the change indistinguishable in a provenance record.
    assert PRESETS["hotspot-focus"].version == 6
    assert PRESETS["clean-cartoon"].version == 3
    assert PRESETS["complex-by-chain"].version == 3
    assert PRESETS["predicted-structure"].version == 3
    # flat-outline is at v2: the outline moved off pure black and lost a third
    # of its weight on the day it was added.
    assert PRESETS["flat-outline"].version == 2
    # The two close-up styles share PRESETS_CLOSEUP_GEOMETRY, so a change to it
    # moves both. They gained fanned labels on 2026-08-19: without the fan the
    # residues that earn a label are the ones burying the most surface, which
    # cluster by definition, and on 1BRS two of them printed on top of each
    # other. A figure made before and after must not be indistinguishable in a
    # provenance record, which is what these numbers are for.
    # v4 and v3: the interface carbons moved from the body hues to gold and
    # purple, and the nonpolar hydrogens stopped being drawn. On a structure
    # that carries hydrogens the close-up was putting more of them on screen
    # than the heavy atoms they hang off, and the patch colour and the carbon
    # colour on top of it were the same hue.
    assert PRESETS["licorice-closeup"].version == 4
    assert PRESETS["licorice-chain"].version == 3
    # The two antibody-figure styles are at v2: they were built on
    # FLAT_SHADING, which renders a near-white surface as a blank silhouette,
    # and moved to SURFACE_SHADING along with a fixed viewpoint.
    assert all(
        PRESETS[slug].version == 2
        for slug in ("epitope-surface", "paratope-closeup")
    )
    # The surface styles added on 2026-08-17 were born on SURFACE_SHADING,
    # so they start at v1. surface-complex is the only one of them in the
    # whole-structure group: it needs no interface to know what to draw.
    assert all(
        PRESETS[slug].version == 1
        for slug in ("surface-partner-a", "surface-translucent",
                     "surface-epitope-map", "surface-complex")
    )
    assert PRESETS["surface-complex"].requires_interface is False
    assert PRESETS["surface-complex"].geometry.surface_whole is True
    # And it is the only preset that draws the whole structure as a surface;
    # the Interface-group ones name a side instead.
    assert [slug for slug, p in PRESETS.items() if p.geometry.surface_whole] == [
        "surface-complex"
    ]


def test_hotspot_focus_grades_the_interface_instead_of_tinting_it():
    """It asks a different question from interface-focus, on the same geometry.

    interface-focus asks where the interface is and what chemistry is in it;
    hotspot-focus asks which residues carry it. That means a graded scale and
    no surface — a halo competes with a colour ramp for the same attention.
    """
    hotspot = PRESETS["hotspot-focus"]
    assert hotspot.requires_interface is True
    assert hotspot.hotspot_emphasis is True
    assert hotspot.show_interface_surface is False
    assert hotspot.chain_coloring is False
    # Every other preset leaves the emphasis off.
    assert [slug for slug, p in PRESETS.items() if p.hotspot_emphasis] == ["hotspot-focus"]


def test_chain_colors_are_stable_and_input_order_independent():
    palette = ("#4477AA", "#EE6677", "#228833")
    expected = {"A": "#4477AA", "B": "#EE6677", "C": "#228833"}
    assert assign_chain_colors(["C", "A", "B"], palette) == expected
    assert assign_chain_colors(["B", "C", "A"], palette) == expected


def test_palette_wraps_when_chains_exceed_palette():
    palette = ("#111111", "#222222")
    colors = assign_chain_colors(["A", "B", "C"], palette)
    assert colors == {"A": "#111111", "B": "#222222", "C": "#111111"}


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="unknown MolCompose preset"):
        get_preset("glossy-rainbow")


def test_presets_are_immutable():
    with pytest.raises(AttributeError):
        PRESETS["clean-cartoon"].version = 2


def test_presets_are_grouped_for_the_panel():
    """The panel files them under headings, in the ChimeraX preset menu's idiom."""
    from src.core.presets import grouped_presets

    groups = grouped_presets()
    assert list(groups) == ["Whole structure", "Interface"]
    # Cartoons first, surfaces last, in both groups — the author's ordering,
    # 2026-08-17. Declaration order is the display order, so this assertion is
    # what keeps a preset added later from landing in the middle of the list.
    assert [p.display_name for p in groups["Whole structure"]] == [
        "Cartoon", "Cartoon (chain colours)", "Cartoon (metric map)",
        "Cartoon (pLDDT confidence)", "Surface (chain colours)",
    ]
    assert [p.display_name for p in groups["Interface"]] == [
        "Interface (partners)", "Interface (flat outline)",
        "Interface close-up", "Interface close-up (chain colours)",
        "Interface (binder loop)", "Interface (buried area)",
        "Interface (group B as surface)", "Interface (group A as surface)",
        "Interface (translucent surface)", "Interface (epitope map)",
    ]
    # The rule stated as a rule, so it survives the next preset: nothing that
    # draws a surface may appear before something that does not.
    for group in groups.values():
        surfaces = [i for i, p in enumerate(group)
                    if p.geometry.surface_whole or p.geometry.surface_side]
        if surfaces:
            assert min(surfaces) + len(surfaces) == len(group), (
                "surface styles must be the tail of their group")


def test_every_interface_preset_needs_an_interface():
    """The grouping is not cosmetic — it predicts which are gated."""
    from src.core.presets import grouped_presets

    for preset in grouped_presets()["Interface"]:
        assert preset.requires_interface
    for preset in grouped_presets()["Whole structure"]:
        assert not preset.requires_interface


class TestColorKeyClearance:
    """`y` is a fraction of the image and the labels are a fixed number of
    pixels, so the room reserved for them shrinks with the image while they do
    not. Measured on real exports: at 1300 px tall the numbers end 79 px clear
    of the edge, at 900 they end 1 px clear, and below that they are cut off —
    the range "Match window" lands in on a laptop."""

    def _y(self, command: str) -> float:
        position = command.split("pos ", 1)[1].split(" ", 1)[0]
        return float(position.split(",")[1])

    def test_the_clearance_is_the_same_number_of_pixels_at_every_size(self):
        """Which is the point: a key placed by fraction drifts towards the
        edge as the image shortens, and this is what stops it."""
        from src.core.presets import ColorKey

        key = ColorKey()
        pixels = {
            round(self._y(key.commands(image_height=h)[0]) * h)
            for h in (900, 1300, 1600)
        }
        assert len(pixels) == 1, f"clearance varies with height: {pixels}"

    def test_an_image_tall_enough_keeps_the_shipped_position(self):
        """Above about 2000 px the shipped fraction already clears the labels."""
        from src.core.presets import ColorKey

        key = ColorKey()
        assert self._y(key.commands(image_height=2000)[0]) == pytest.approx(key.y)

    def test_a_short_image_lifts_the_key_clear_of_the_edge(self):
        from src.core.presets import ColorKey

        key = ColorKey()
        for height in (900, 700, 500):
            y = self._y(key.commands(image_height=height)[0])
            assert y > key.y, f"{height} px still uses the tall-image position"
            # The labels' own height, in fractions of this image.
            assert y * height >= key.font_size * 1.6

    def test_without_a_height_nothing_changes(self):
        """The caller may not know the export size; the old behaviour stands."""
        from src.core.presets import ColorKey

        key = ColorKey()
        assert self._y(key.commands()[0]) == pytest.approx(key.y)

    def test_a_larger_font_asks_for_more_room(self):
        """`keyFontSize` exists so a caller can enlarge the key; the clearance
        has to follow it, or enlarging the font pushes it off the edge."""
        from dataclasses import replace

        from src.core.presets import ColorKey

        small = self._y(ColorKey().commands(image_height=900)[0])
        large = self._y(replace(ColorKey(), font_size=96).commands(image_height=900)[0])
        assert large > small
