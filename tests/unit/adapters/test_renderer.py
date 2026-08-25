import pytest

import src.adapters.renderer as renderer
from src.adapters.model_context import ChainRef, ModelRef
from src.adapters.renderer import (
    _wash,
    build_render_commands,
    focus_commands,
    render_preset,
    reset_commands,
    scene_commands,
)
from src.core.confidence import ConfidenceReport, key_stops
from src.core.interfaces import AtomPoint, detect_interface
from src.core.interfaces import ResidueKey as Key
from src.core.presets import get_preset


@pytest.fixture
def model_ref():
    return ModelRef(
        model_id="#1",
        name="fake",
        atomspec="#1",
        chains=(ChainRef("A", "#1/A", 5), ChainRef("B", "#1/B", 4)),
    )


@pytest.fixture
def interface_result():
    a1 = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    a2 = Key("#1", "A", 2, "", "GLY", "#1/A:2")
    b1 = Key("#1", "B", 1, "", "SER", "#1/B:1")
    return detect_interface(
        [AtomPoint(a1, (0.0, 0.0, 0.0)), AtomPoint(a2, (1.0, 0.0, 0.0))],
        [AtomPoint(b1, (3.0, 0.0, 0.0))],
    )


def test_reset_commands_are_model_scoped(model_ref):
    assert reset_commands(model_ref) == (
        "hide #1 atoms",
        "hide #1 surfaces",
        "show #1 cartoons",
        "color #1 #BBBBBB target c",
        # The annotation layer is cleared too, or the close-up's labels and
        # dashes survive into the next preset that never asked for them.
        "label delete #1 residues",
        # PDB missing-segment labels are pseudobond labels, not residue labels.
        # A labels=0 publication preset must clear those as well.
        "label missing #1 0",
        "~hbonds #1",
        # Scene furniture, so unscoped: nothing addressed to the structure
        # takes the colour key down.
        "key delete",
    )


def test_design_reference_style_aligns_references_and_maps_the_detected_epitope(
    model_ref, interface_result
):
    """Catch a comparison style that paints a case-specific hard-coded patch."""
    references = (
        ModelRef("#2", "crystal-one", "#2", model_ref.chains),
        ModelRef("#3", "crystal-two", "#3", model_ref.chains),
    )

    commands = renderer.build_reference_style_commands(
        model_ref,
        references,
        get_preset("design-reference"),
        interface_result,
        align_chain="A",
        partner_chain="B",
    )

    assert commands.count("matchmaker #2/A to #1/A") == 1
    assert commands.count("matchmaker #3/A to #1/A") == 1
    assert "hide #2 pseudobonds" in commands
    assert "hide #3 pseudobonds" in commands
    assert "show #1/A surfaces" in commands
    assert "color #1/A:1-2 #E8551F target s" in commands
    assert "color #1/B #159D91 target c" in commands
    assert "color #2/B #2F6FB2 target c" in commands
    assert "color #3/B #8583D9 target c" in commands
    assert commands[-1] == "view #1"


def test_clean_cartoon_starts_from_model_scoped_baseline(model_ref):
    commands = build_render_commands(model_ref, get_preset("clean-cartoon"))
    assert commands[:3] == (
        "hide #1 atoms",
        "hide #1 surfaces",
        "show #1 cartoons",
    )
    assert "color #1 #6C8EBF target c" in commands


def test_complex_chain_colors_are_stable(model_ref):
    commands = build_render_commands(model_ref, get_preset("complex-by-chain"))
    assert "color #1/A #4477AA target c" in commands
    assert "color #1/B #EE6677 target c" in commands


def test_scene_global_commands_appear_exactly_once(model_ref):
    preset = get_preset("clean-cartoon")
    commands = build_render_commands(model_ref, preset)
    for global_command in scene_commands(preset):
        assert commands.count(global_command) == 1


def test_a_surface_figure_omits_outlines(model_ref, interface_result):
    """Tried with outlines on, and they are wrong here.

    Silhouettes trace the transparent surface as well as the cartoon, and on a
    molecular surface that is not an edge — it is a line following every
    side-chain bump, which renders as pencil scribble around the complex. The
    shape has to come from shading and from a surface dense enough to catch
    it, which is what the reference figures actually do.
    """
    commands = build_render_commands(
        model_ref, get_preset("interface-focus"), interface_result
    )
    assert "graphics silhouettes false" in commands
    assert not any("silhouettes true" in command for command in commands)
    # Shading is what replaces them, and it has to be directional. `full` is
    # ChimeraX's two-light setup; the `multiShadow 0` right after strips the
    # ambient occlusion off it, which is what makes this read as PyMOL rather
    # than as computer graphics. Both lines matter, and in this order.
    assert "lighting full" in commands
    assert commands.index("lighting full") < commands.index("lighting multiShadow 0")


def test_interface_focus_requires_result(model_ref):
    with pytest.raises(ValueError, match="requires a detected interface"):
        build_render_commands(model_ref, get_preset("interface-focus"))


def test_interface_focus_highlights_groups_and_fits_view(model_ref, interface_result):
    preset = get_preset("interface-focus")
    commands = build_render_commands(model_ref, preset, interface_result)
    a_spec = "#1/A:1-2"
    b_spec = "#1/B:1"
    assert f"show {a_spec} atoms" in commands
    assert f"style {a_spec} stick" in commands
    # Four colours, not two: the bodies say "two proteins", the interfaces say
    # "and here is where they meet". Painting the interface in its own chain's
    # colour left it legible only by its stick representation, which at
    # journal-column size is two flat silhouettes touching.
    interface_a, interface_b = preset.interface_colors()
    # target c, not ac: the patch is the cartoon. Painting the side chains
    # with it too is the defect fixed on 2026-08-16.
    assert f"color {a_spec} {interface_a} target c" in commands
    assert f"color {b_spec} {interface_b} target c" in commands
    assert interface_a != preset.palette.body_a
    assert interface_b != preset.palette.body_b
    # The bodies keep their own, lighter colours underneath.
    assert f"color #1/A {preset.palette.body_a} target c" in commands
    assert f"color #1/B {preset.palette.body_b} target c" in commands
    # Interface sticks stay fully opaque over the faded context cartoon.
    assert f"transparency {a_spec} 0 target ac" in commands
    # The figure frames the whole complex, not just the interface residues.
    from src.adapters.renderer import VIEW_PAD

    # Padding keeps white space and survives export at another aspect ratio.
    assert commands[-1] == f"view #1/A|#1/B pad {VIEW_PAD}"


def test_interface_focus_builds_no_surface(model_ref, interface_result):
    """The surface was what made these figures look washed out.

    Every colour under a semi-transparent surface is dimmed by whatever
    fraction is not transparent, so a palette tuned against white renders
    muted — and three rounds of palette work were partly chasing that rather
    than the palette. The published interface figures have none: an opaque
    cartoon, a coloured patch at the interface, a few sticks.

    The panel can still add one, which is why SURFACE_TRANSPARENCY and
    SURFACE_COLOR remain.
    """
    commands = build_render_commands(
        model_ref, get_preset("interface-focus"), interface_result
    )
    assert not any(command.startswith("surface ") for command in commands)
    assert any(command.startswith("hide #1 surfaces") for command in commands)


def test_interface_focus_tints_each_partner_chain(model_ref, interface_result):
    preset = get_preset("interface-focus")
    commands = build_render_commands(model_ref, preset, interface_result)
    assert f"color #1/A {preset.palette.body_a} target c" in commands
    assert f"color #1/B {preset.palette.body_b} target c" in commands


def test_interface_focus_hides_chains_outside_the_pair(model_ref, interface_result):
    commands = build_render_commands(
        model_ref, get_preset("interface-focus"), interface_result
    )
    # Everything is hidden, then only the two partners are shown again, so
    # crystal copies and unrelated subunits do not clutter the figure.
    assert commands.index("hide #1 cartoons") < commands.index("show #1/A|#1/B cartoons")


def test_repeated_build_is_idempotent(model_ref, interface_result):
    preset = get_preset("interface-focus")
    assert build_render_commands(model_ref, preset, interface_result) == build_render_commands(
        model_ref, preset, interface_result
    )


def test_every_structural_command_is_model_scoped(model_ref, interface_result):
    for slug in ("clean-cartoon", "complex-by-chain", "interface-focus"):
        preset = get_preset(slug)
        interface = interface_result if slug == "interface-focus" else None
        # `wait` is a timing command and `key delete` removes scene
        # furniture; neither names a model, because neither acts on anything
        # in the structure.
        scene = set(scene_commands(preset)) | {"wait 1", "key delete"}
        for command in build_render_commands(model_ref, preset, interface):
            if command in scene:
                continue
            assert "#1" in command, command


@pytest.fixture
def confidence_report():
    k1 = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    k2 = Key("#1", "A", 2, "", "GLY", "#1/A:2")
    return ConfidenceReport("0-100", ((k1, 95.0), (k2, 30.0)))


def test_predicted_structure_requires_confidence(model_ref):
    with pytest.raises(ValueError, match="requires pLDDT confidence data"):
        build_render_commands(model_ref, get_preset("predicted-structure"))


def test_predicted_structure_colors_by_bfactor_and_fades_low(model_ref, confidence_report):
    commands = build_render_commands(
        model_ref, get_preset("predicted-structure"), confidence=confidence_report
    )
    assert (
        "color bfactor #1 palette 0,#FF7D45:49.99,#FF7D45:50,#FFDB13:69.99,#FFDB13:"
        "70,#65CBF3:89.99,#65CBF3:90,#0053D6:100,#0053D6 noValueColor #DCDCE2"
        in commands
    )
    assert "transparency #1/A:2 70 target c" in commands


def test_predicted_structure_zero_one_scale_palette(model_ref):
    k1 = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    report = ConfidenceReport("0-1", ((k1, 0.95),))
    commands = build_render_commands(
        model_ref, get_preset("predicted-structure"), confidence=report
    )
    assert (
        "color bfactor #1 palette 0,#FF7D45:0.4999,#FF7D45:0.5,#FFDB13:0.6999,#FFDB13:"
        "0.7,#65CBF3:0.8999,#65CBF3:0.9,#0053D6:1,#0053D6 noValueColor #DCDCE2"
        in commands
    )
    assert not any(command.startswith("transparency") for command in commands)


def test_compact_residue_spec_collapses_ranges_and_chains():
    from src.adapters.renderer import compact_residue_spec

    keys = [
        Key("#1", "A", n, "", "ALA", f"#1/A:{n}") for n in (27, 35, 37, 38, 56, 57, 58)
    ] + [Key("#1", "D", 100, "A", "GLY", "#1/D:100A"), Key("#1", "D", 30, "", "SER", "#1/D:30")]
    assert compact_residue_spec(keys) == "#1/A:27,35,37-38,56-58|#1/D:30,100A"


def test_render_preset_executes_commands_in_order(model_ref):
    calls = []

    def runner(session, command):
        calls.append((session, command))

    session = object()
    commands = render_preset(session, model_ref, get_preset("clean-cartoon"), runner=runner)
    assert [command for _, command in calls] == list(commands)
    assert all(recorded_session is session for recorded_session, _ in calls)


def test_hbond_commands_restrict_to_interface_groups(interface_result):
    from src.adapters.renderer import hbond_commands

    (command,) = hbond_commands(interface_result)
    assert command == (
        "hbonds #1/A:1-2 restrict #1/B:1 reveal true "
        "dashes 6 radius 0.08 color #705E9C"
    )
    assert hbond_commands(None, off=True) == ("~hbonds",)
    with pytest.raises(ValueError, match="requires a detected interface"):
        hbond_commands(None)


def test_contact_commands_restrict_to_interface_groups(interface_result):
    from src.adapters.renderer import contact_commands

    (command,) = contact_commands(interface_result)
    assert command.startswith("contacts #1/A:1-2 restrict #1/B:1 ")
    assert contact_commands(None, off=True) == ("~contacts",)
    with pytest.raises(ValueError, match="requires a detected interface"):
        contact_commands(None)


def test_interaction_commands_create_and_delete_named_groups():
    from src.adapters.renderer import INTERACTION_COLORS, interaction_commands
    from src.core.interactions import Interaction

    arg = Key("#1", "A", 10, "", "ARG", "#1/A:10")
    asp = Key("#1", "B", 20, "", "ASP", "#1/B:20")
    found = (Interaction("salt-bridge", arg, asp, 3.5, "NH1–OD1", "NH1", "OD1"),)
    (create,) = interaction_commands(found)
    assert create.startswith("pbond #1/A:10@NH1|#1/B:20@OD1 name mc-salt-bridge ")
    assert f"color {INTERACTION_COLORS['salt-bridge']}" in create
    assert "showDist false" in create
    (delete,) = interaction_commands(found, off=True)
    assert delete == "pbond delete #1/A:10@NH1|#1/B:20@OD1 name mc-salt-bridge"


def test_interaction_commands_skip_entries_without_atom_anchors():
    from src.adapters.renderer import interaction_commands
    from src.core.interactions import Interaction

    arg = Key("#1", "A", 10, "", "ARG", "#1/A:10")
    asp = Key("#1", "B", 20, "", "ASP", "#1/B:20")
    assert interaction_commands((Interaction("salt-bridge", arg, asp, 3.5),)) == ()


def test_focus_commands_target_model_or_interface(model_ref, interface_result):
    from src.adapters.renderer import VIEW_PAD

    assert focus_commands(model_ref) == (f"view #1 pad {VIEW_PAD}",)
    joined = "#1/A:1-2|#1/B:1"
    assert focus_commands(model_ref, interface_result) == (
        f"view {joined} pad {VIEW_PAD}",
    )


def test_the_side_chains_outweigh_the_dashes_annotating_them():
    """Thick sticks, thin dashes — the hierarchy the published close-ups use.

    This assertion ran the other way round for three rounds, on the reasoning
    that the typed interactions are the finding and should be the heaviest
    thing drawn. They are the finding, and they are still an annotation: a
    caption is not set larger than the figure. Sticks spent that time at 0.13,
    thinner than ChimeraX's own 0.2 stick default, and read as wire.
    """
    from src.adapters.renderer import INTERACTION_RADIUS

    # Checked on every preset that draws both, since the radius moved onto
    # Geometry and each style now picks its own.
    for slug in ("interface-focus", "flat-outline", "licorice-closeup"):
        radius = get_preset(slug).geometry.stick_radius
        assert radius > INTERACTION_RADIUS, slug
        # Not thinner than what ChimeraX draws by default; that was the bug.
        assert radius >= 0.20, slug


def _draws_labels(command):
    """A label being drawn, as opposed to `label delete` clearing them."""
    return command.startswith("label ") and " text " in command


def _hotspots():
    """Ranked (key, name, alone, complexed, delta) rows, most buried first."""
    return [
        (("A", 2, ""), "GLY", 100.0, 40.0, 60.0),
        (("B", 1, ""), "SER", 90.0, 40.0, 50.0),
        (("A", 1, ""), "ALA", 80.0, 45.0, 35.0),
    ]


def test_the_annotation_layer_is_off_unless_a_preset_asks(model_ref, interface_result):
    """Labels and hydrogen bonds fail differently from everything else.

    A ribbon drawn too small is coarse; a label drawn too small is unreadable,
    and a plate with a label on every panel is a smear. So neither is on by
    default, and the overview preset does not get them.
    """
    commands = build_render_commands(
        model_ref, get_preset("interface-focus"), interface_result,
        hotspots=_hotspots(),
    )
    assert not any(_draws_labels(command) for command in commands)
    assert not any(command.startswith("hbonds ") for command in commands)
    # The clearing commands are always there; only the drawing is optional.
    assert "label delete #1 residues" in commands


def test_the_closeup_labels_a_few_residues_per_side_in_two_colours(
    model_ref, interface_result
):
    preset = get_preset("licorice-closeup")
    commands = build_render_commands(
        model_ref, preset, interface_result, hotspots=_hotspots(),
    )
    labels = [command for command in commands if _draws_labels(command)]
    # One per side, not one per residue, and each side gets its own colour so
    # a residue's chain is readable without tracing the ribbon back.
    assert len(labels) == 2
    assert "color black" in labels[0]
    assert "color #E01B24" in labels[1]
    # Both of A's interface residues rank inside the top three, so both are
    # labelled — and the spec is compacted to a range, as everywhere else.
    assert "#1/A:1-2" in labels[0]
    assert "#1/B:1" in labels[1]


def test_a_labelled_preset_still_respects_its_count(model_ref, interface_result):
    """`label_top` is a count, not a switch.

    What is wanted in practice is never all-or-nothing but "label a few", and
    three a side is the most that fits before they collide. A boolean would
    hard-code that number where a caller cannot reach it.
    """
    from dataclasses import replace

    preset = get_preset("licorice-closeup")
    one = replace(preset, geometry=replace(preset.geometry, label_top=1))
    labels = [
        command
        for command in build_render_commands(
            model_ref, one, interface_result, hotspots=_hotspots()
        )
        if _draws_labels(command)
    ]
    # A's two interface residues are both ranked, but only the top one is
    # labelled.
    assert "#1/A:2" in labels[0]
    assert "#1/A:1" not in labels[0]


def test_cross_interface_hbonds_name_both_sides(model_ref, interface_result):
    """`restrict cross` returns nothing when both chains sit in one spec.

    With no "other side" to cross to ChimeraX finds zero bonds, and a figure
    then says this interface has no hydrogen bonds rather than saying the
    question was put wrongly. Naming the two sides is the fix.
    """
    commands = build_render_commands(
        model_ref, get_preset("licorice-closeup"), interface_result,
        hotspots=_hotspots(),
    )
    hbonds = next(c for c in commands if c.startswith("hbonds "))
    assert hbonds.startswith("hbonds #1/A restrict #1/B")
    assert "restrict cross" not in hbonds
    assert "reveal false" in hbonds


def test_a_metric_figure_carries_its_colour_key(model_ref, confidence_report):
    """A figure whose content is a colour needs the scale beside it.

    Every confidence figure this tool produced went out without one until
    2026-08-16 — the renderer emitted no `key` command at all. The colours
    were then only readable by someone who already knew them, which is the
    same failure the interpolated pLDDT palette had.
    """
    commands = build_render_commands(
        model_ref, get_preset("predicted-structure"), confidence=confidence_report
    )
    # Not `startswith("key ")`: the baseline clears any previous key with
    # `key delete`, which would match first.
    key = next(c for c in commands if c.startswith("key ") and " pos " in c)
    for colour, label in key_stops(confidence_report.scale):
        assert f"{colour}:{label}" in key
    # `blended` is what puts a label at every band boundary: ChimeraX centres
    # labels on blocks under `distinct` and draws them at the stop positions
    # under `blended`. The bands do not blend, because each colour is emitted
    # twice and every blend runs between a colour and itself.
    assert "colorTreatment blended" in key
    # The boundaries of the AlphaFold scale, ends included. Labelling one edge
    # of each block instead drops 0, which is what this key did until
    # 2026-08-18.
    for boundary in ("0", "50", "70", "90", "100"):
        assert f":{boundary} " in key or key.endswith(f":{boundary}")
    assert key.count("#FF7D45:") == 2
    # Residues the metric says nothing about are named explicitly. Anything
    # left holding an earlier colour would be read as a value.
    assert any("noValueColor" in command for command in commands)


def test_a_structural_figure_carries_no_key(model_ref, interface_result):
    """Partner colours are categories, not values; a scale would invent one."""
    commands = build_render_commands(
        model_ref, get_preset("interface-focus"), interface_result
    )
    # `key delete` from the baseline is fine and expected; what must not
    # appear is a key being *drawn*.
    assert not any(" pos " in command and command.startswith("key ")
                   for command in commands)


def test_the_colour_key_is_corrected_for_the_export_aspect(model_ref, confidence_report):
    """Key position and size are fractions of the frame, not absolutes.

    Same class of bug as `graphics silhouettes width` being in pixels: a bar
    set to 0.40 of the width on a 4:3 preview is a different bar on a square
    or portrait export. Both are corrected from the output geometry now.
    """
    preset = get_preset("predicted-structure")

    def key_for(size):
        commands = build_render_commands(
            model_ref, preset, confidence=confidence_report, image_size=size
        )
        return next(c for c in commands if c.startswith("key ") and " pos " in c)

    reference = key_for((1600, 1200))          # 4:3, what it was tuned on
    wide = key_for((2400, 1000))               # 12:5
    assert reference != wide
    # A wider frame must not give a wider bar: the fraction would grow with it.
    def width_of(command):
        return float(command.split("size ")[1].split(",")[0])
    assert width_of(wide) < width_of(reference)
    # And it stays centred whatever the frame.
    for command in (reference, wide):
        x = float(command.split(" pos ")[1].split(",")[0])
        assert abs((x + width_of(command) / 2) - 0.5) < 1e-6


def _lopsided_hotspots():
    """A ranking where one side dominates, as on APIM1-nanobody.

    B's single interface residue buries less than both of A's, so a ranking
    taken over the interface as a whole puts it last.
    """
    return [
        (("A", 2, ""), "GLY", 100.0, 30.0, 70.0),
        (("A", 1, ""), "ALA", 90.0, 35.0, 55.0),
        (("B", 1, ""), "SER", 60.0, 45.0, 15.0),
    ]


def test_side_chains_are_chosen_per_side_not_across_the_interface(
    model_ref, interface_result
):
    """A global ranking can leave one partner undrawn.

    On APIM1-nanobody the top eight by buried area fell 2 on one chain and 6
    on the other, so one side's contribution was essentially invisible — and a
    figure showing what one partner brings to an interface but not the other
    is not describing an interface. With `stick_top` at 1 a side, the weaker
    side still gets its best residue.
    """
    from dataclasses import replace

    preset = get_preset("interface-focus")
    one_each = replace(preset, geometry=replace(preset.geometry, stick_top=1))
    commands = build_render_commands(
        model_ref, one_each, interface_result, hotspots=_lopsided_hotspots()
    )
    shown = [c for c in commands if c.startswith("show ") and c.endswith(" atoms")]
    # A's best is residue 2; B's only residue is drawn despite ranking last.
    assert "show #1/A:2 atoms" in shown
    assert "show #1/B:1 atoms" in shown


def test_a_closeup_frames_its_residues_not_the_whole_pair(model_ref, interface_result):
    """A close-up that fits both proteins in is an overview with thin sticks."""
    closeup = build_render_commands(
        model_ref, get_preset("licorice-closeup"), interface_result,
        hotspots=_hotspots(),
    )
    overview = build_render_commands(
        model_ref, get_preset("interface-focus"), interface_result,
        hotspots=_hotspots(),
    )
    assert overview[-1] == "view #1/A|#1/B pad 0.06"
    # Framed on residues, and with the wider margin a close-up needs.
    assert closeup[-1].startswith("view #1/A:")
    assert closeup[-1].endswith("pad 0.12")


def test_switching_preset_clears_the_previous_one_s_annotations(
    model_ref, interface_result
):
    """The close-up's labels must not survive into an overview.

    Seen in a live session: rendering licorice-closeup and then
    interface-focus left the labels and the hydrogen-bond dashes on the
    overview, which never asked for either. Nothing else in the pipeline
    removes them — the presets only add — so the reset has to.
    """
    overview = build_render_commands(
        model_ref, get_preset("interface-focus"), interface_result,
        hotspots=_hotspots(),
    )
    assert "label delete #1 residues" in overview
    assert "~hbonds #1" in overview
    # And the clearing happens before anything is drawn.
    closeup = build_render_commands(
        model_ref, get_preset("licorice-closeup"), interface_result,
        hotspots=_hotspots(),
    )
    drawn = next(i for i, c in enumerate(closeup) if _draws_labels(c))
    assert closeup.index("label delete #1 residues") < drawn


def test_one_partner_can_be_a_surface_while_the_other_stays_a_cartoon(
    model_ref, interface_result
):
    """The antibody-figure convention, and it has to be asymmetric.

    Two surfaces hide both folds; two cartoons cannot show a patch as a patch.
    So the bound side becomes a solid shape with its epitope painted on it,
    and the binder keeps its ribbon.
    """
    commands = build_render_commands(
        model_ref, get_preset("epitope-surface"), interface_result,
        hotspots=_hotspots(),
    )
    # B is the surface: shown as one, and its cartoon taken away.
    assert "surface #1/B" in commands
    assert "hide #1/B cartoons" in commands
    assert commands.index("hide #1/B cartoons") < commands.index("surface #1/B")
    # A keeps its ribbon and its side chains.
    assert "hide #1/A cartoons" not in commands
    assert any(c.startswith("show #1/A:") and c.endswith(" atoms") for c in commands)
    # The patch lands on B's surface, not on a cartoon it no longer has.
    interface_b = get_preset("epitope-surface").interface_colors()[1]
    assert f"color #1/B:1 {interface_b} target s" in commands
    # And B grows no side chains: inside a solid surface they are invisible
    # except as lumps.
    assert not any(c.startswith("show #1/B:") and c.endswith(" atoms")
                   for c in commands)


def test_the_surface_side_is_a_property_of_the_preset_not_of_the_file(
    model_ref, interface_result
):
    """Which group becomes the surface has to be selectable both ways.

    Depositions do not agree on chain order — an antibody-antigen entry
    usually puts the antigen second and a receptor-ligand one often does not.
    With only a side-B style, half of all complexes need their chains
    re-lettered to get the intended figure.
    """
    commands = build_render_commands(
        model_ref, get_preset("surface-partner-a"), interface_result,
        hotspots=_hotspots(),
    )
    assert "surface #1/A" in commands
    assert "hide #1/A cartoons" in commands
    assert "hide #1/B cartoons" not in commands
    # The side chains follow the surface: B has them, A does not.
    assert any(c.startswith("show #1/B:") and c.endswith(" atoms") for c in commands)
    assert not any(c.startswith("show #1/A:") and c.endswith(" atoms")
                   for c in commands)


def test_a_translucent_surface_keeps_the_cartoon_underneath(
    model_ref, interface_result
):
    """Otherwise it is a see-through shell over nothing.

    The solid styles hide the cartoon they cover because it cannot be seen;
    at 55% the ribbon inside is the reason to choose the style at all, and
    the interface patch has to reach it — through the surface the cartoon is
    what the eye actually reads.
    """
    preset = get_preset("surface-translucent")
    commands = build_render_commands(
        model_ref, preset, interface_result, hotspots=_hotspots(),
    )
    assert "show #1/B cartoons" in commands
    assert "hide #1/B cartoons" not in commands
    assert "transparency #1/B 55 target s" in commands
    interface_b = preset.interface_colors()[1]
    assert f"color #1/B:1 {interface_b} target sc" in commands
    # The envelope steps back from the ribbon it covers rather than matching
    # it; same colour at full strength on both is one shape, not two.
    body = preset.palette.body_b
    assert f"color #1/B {body} target c" in commands
    assert f"color #1/B {_wash(body)} target s" in commands


def test_render_preset_forwards_every_argument_build_accepts():
    """The two entry points must not drift apart.

    `render_preset` is what the commands layer calls; `build_render_commands`
    is what every test in this file calls. A parameter added to the second and
    forgotten on the first therefore passes the whole suite and fails on the
    first real invocation — which is exactly what happened to `camera`.
    """
    import inspect

    build = set(inspect.signature(build_render_commands).parameters)
    forwarded = set(inspect.signature(render_preset).parameters)
    # `model` is `ModelRef` on both; `session` and `runner` belong to the
    # caller side only.
    missing = build - forwarded - {"image_size"}
    assert not missing, f"render_preset drops {sorted(missing)}"


def test_a_surface_preset_frames_the_model_not_the_hidden_atoms(
    model_ref, interface_result
):
    """A partner drawn as a surface has hidden atoms.

    `view <atomspec>` fits displayed atoms only, so framing on the chain specs
    leaves the surface partner out of the bounding box entirely and the figure
    comes back cropped through it.
    """
    commands = build_render_commands(
        model_ref, get_preset("epitope-surface"), interface_result
    )
    view = [line for line in commands if line.startswith("view ")][-1]
    assert view.startswith(f"view {model_ref.atomspec} ")


def test_an_all_surface_preset_undoes_the_cartoon_baseline(model_ref):
    """`reset_commands` shows cartoons and hides surfaces, for every other style.

    The one style that is nothing but surface has to undo both, and its colour
    has to land on `target s`: painting the cartoon would put it on hidden
    geometry and leave the surface at the neutral grey the reset applies.
    """
    commands = build_render_commands(model_ref, get_preset("surface-complex"), None)
    assert f"hide {model_ref.atomspec} cartoons" in commands
    assert f"surface {model_ref.atomspec}" in commands
    # Cartoon hidden after the reset showed it, so order matters.
    assert (commands.index(f"hide {model_ref.atomspec} cartoons")
            > commands.index(f"show {model_ref.atomspec} cartoons"))
    assert (commands.index(f"surface {model_ref.atomspec}")
            > commands.index(f"hide {model_ref.atomspec} surfaces"))
    coloured = [c for c in commands if c.startswith("color #1/") and "target s" in c]
    assert coloured, "chain colours must be painted on the surface"
    assert not any(c.startswith("color #1/") and c.endswith("target c")
                   for c in commands)


def test_it_needs_no_interface_to_draw(model_ref):
    """It is in the whole-structure group, so it must render with nothing else run."""
    preset = get_preset("surface-complex")
    assert preset.requires_interface is False
    commands = build_render_commands(model_ref, preset, None)
    assert any(c.startswith("surface ") for c in commands)
    # And no interface machinery leaks in.
    assert not any("mc1_iface" in c for c in commands)


def test_the_closeup_fans_its_labels_apart(model_ref, interface_result):
    """Close-up labels must not stack, and only a camera can spread them.

    The residues that earn a label are the ones burying the most surface, and
    those cluster by definition — that is what makes them the interface. On
    1BRS two of them, D39 and Y29, printed on top of each other and the second
    was unreadable.

    `PRESETS_CLOSEUP_GEOMETRY` now carries a `label_spread`, which is also what
    makes `_side_on_camera` produce a basis for these presets. The offsets live
    in the camera plane, so one command per residue is the only way to express
    them: an offset is a single vector and cannot be given to a group.

    The neighbouring test passes no camera and therefore still sees one
    command per side. That is why this defect survived — the grouped path is
    the one under test, and the fanned path is the one that ships.
    """
    camera = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
    for slug in ("licorice-closeup", "licorice-chain"):
        commands = build_render_commands(
            model_ref, get_preset(slug), interface_result,
            hotspots=_hotspots(), camera=camera,
        )
        labels = [command for command in commands if _draws_labels(command)]
        # One per labelled residue rather than one per side.
        assert len(labels) == 3, slug
        assert all(" offset " in command for command in labels), slug
        # Distinct offsets: two labels sharing one is the bug this prevents.
        offsets = {command.split(" offset ")[1] for command in labels}
        assert len(offsets) == 3, slug
