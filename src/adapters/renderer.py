"""Convert presets and interface results into scoped, deterministic ChimeraX commands."""

from ..core.confidence import ConfidenceReport, key_stops, palette_spec
from ..core.interactions import Interaction
from ..core.interfaces import InterfaceResult
from ..core.presets import Preset, assign_chain_colors
from ..core.viewpoint import camera_matrix, fan_offsets, offsets_at, place_labels, project
from .model_context import ModelRef

SCENE_BACKGROUND = "set bgColor white"


def scene_commands(preset: Preset, image_width: int | None = None) -> tuple[str, ...]:
    """The global scene setup for a preset: background, lighting, outlines.

    This used to be two frozen tuples chosen by a boolean, with one lighting
    and material block shared by every preset. That could not express the four
    styles of the 2026-08-16 handoff, which differ from each other mostly in
    exactly this block — so the preset now carries its own `Shading` and is
    asked to emit it.

    `image_width` is passed through to the silhouette width, which is measured
    in pixels and would otherwise mean a different line weight at every export
    size.
    """
    return (SCENE_BACKGROUND, *preset.shading.commands(image_width),
            *preset.geometry.cartoon_commands())


def build_reference_style_commands(
    model: ModelRef,
    references: tuple[ModelRef, ...],
    preset: Preset,
    interface: InterfaceResult,
    *,
    align_chain: str,
    partner_chain: str,
) -> tuple[str, ...]:
    """Build the versioned design-to-reference molecular overlay.

    The epitope is derived from the detected interface on ``model``.  Nothing
    in this rendering plan names a residue number, so the style is reusable
    for any two-chain design whose references use the same chain identifiers.
    """
    if not preset.reference_comparison:
        raise ValueError(f"preset {preset.slug} is not a reference-comparison style")
    if not references:
        raise ValueError("reference-comparison style needs at least one reference")
    # One colour per reference, never a cycle. `chains[index % len(chains)]`
    # would draw the third reference in the first one's colour, and a plate
    # with two identically coloured structures on it says nothing about which
    # is which — the reader cannot even tell that a colour was reused.
    if len(references) > len(preset.palette.chains):
        raise ValueError(
            f"{preset.slug} has {len(preset.palette.chains)} reference colours "
            f"and was given {len(references)} references; overlay them in "
            f"separate figures rather than drawing two in one colour"
        )

    all_models = (model, *references)
    for ref in all_models:
        known = {chain.chain_id for chain in ref.chains}
        missing = [chain for chain in (align_chain, partner_chain) if chain not in known]
        if missing:
            raise ValueError(
                f"{ref.model_id} has no protein chain(s) {', '.join(missing)}"
            )

    group_a = {key.chain_id for key in interface.group_a}
    group_b = {key.chain_id for key in interface.group_b}
    if align_chain in group_a and partner_chain in group_b:
        epitope = interface.group_a
    elif align_chain in group_b and partner_chain in group_a:
        epitope = interface.group_b
    else:
        raise ValueError(
            "align and partner must name opposite sides of the detected interface"
        )

    commands = []
    for reference in references:
        commands.append(
            f"matchmaker {reference.model_id}/{align_chain} "
            f"to {model.model_id}/{align_chain}"
        )
    for ref in all_models:
        commands.extend(
            (
                f"hide {ref.atomspec} atoms",
                f"hide {ref.atomspec} surfaces",
                f"hide {ref.atomspec} cartoons",
                f"hide {ref.atomspec} pseudobonds",
                f"label delete {ref.atomspec} residues",
            )
        )
    commands.extend(
        (
            "key delete",
            f"show {model.model_id}/{align_chain} surfaces",
            f"show {model.model_id}/{partner_chain} cartoons",
            f"color {model.model_id}/{align_chain} {preset.palette.body_a} target s",
            f"color {compact_residue_spec(epitope)} "
            f"{preset.palette.interface_a} target s",
            f"color {model.model_id}/{partner_chain} "
            f"{preset.palette.body_b} target c",
        )
    )
    for index, reference in enumerate(references):
        colour = preset.palette.chains[index % len(preset.palette.chains)]
        commands.extend(
            (
                f"show {reference.model_id}/{partner_chain} cartoons",
                f"color {reference.model_id}/{partner_chain} {colour} target c",
            )
        )
    commands.extend(scene_commands(preset))
    # Frame on the design complex only.  Deposited reference files can contain
    # additional crystallographic copies; including whole reference models in
    # ``view`` leaves large empty margins even though those copies are hidden.
    commands.append(f"view {model.model_id}")
    return tuple(commands)


def reset_commands(model: ModelRef) -> tuple[str, ...]:
    """Return the model to a neutral state before a preset paints it.

    The annotation layer is cleared here, not just the representation. Labels
    and hydrogen bonds are added by the presets that ask for them and by
    nothing else, so switching from the close-up to an overview used to leave
    the close-up's labels and dashes on top of it: a figure carrying
    annotations that its own preset never requested, and which a reader would
    take as part of the style. Every preset starts from a scene with no
    annotations rather than from whatever the last one happened to leave.
    """
    spec = model.atomspec
    return (
        f"hide {spec} atoms",
        f"hide {spec} surfaces",
        f"show {spec} cartoons",
        f"color {spec} #BBBBBB target c",
        f"label delete {spec} residues",
        # Missing-segment labels belong to ChimeraX's "missing structure"
        # pseudobonds, so deleting residue labels does not touch them.  They
        # otherwise survive `labels 0` and look like preset annotations.
        f"label missing {spec} 0",
        # `~hbonds` takes no options — `reveal` belongs to `hbonds`, and
        # passing it here makes ChimeraX reject the whole command.
        f"~hbonds {spec}",
        # The colour key is scene furniture, not part of any model, so nothing
        # scoped to the structure removes it. Switching from pLDDT to any
        # other colouring therefore left the pLDDT scale standing beside a
        # figure it no longer describes — a bar the reader has every reason to
        # read the new colours against. Only the presets that carry a
        # `color_key` draw one, so clearing it here is symmetric with how the
        # labels and hydrogen bonds are handled above.
        "key delete",
    )


def _number_ranges(numbers: list[int]) -> str:
    """Collapse sorted ints into ChimeraX range syntax: 27,35,37-38,56-60."""
    parts = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(parts)


def compact_residue_spec(residues) -> str:
    """Compact per-chain atomspec for a set of residues.

    A naive ``spec1|spec2|...`` union over hundreds of residues overflows the
    recursive ChimeraX atomspec parser (RecursionError). Grouping by chain and
    using comma/range residue lists keeps the spec flat and short.
    """
    grouped: dict[tuple[str, str], list] = {}
    order = []
    for key in residues:
        group_key = (key.model_id, key.chain_id)
        if group_key not in grouped:
            grouped[group_key] = []
            order.append(group_key)
        grouped[group_key].append(key)
    parts = []
    for model_id, chain_id in order:
        keys = sorted(grouped[(model_id, chain_id)], key=lambda k: (k.number, k.insertion_code))
        plain = [key.number for key in keys if not key.insertion_code]
        coded = [f"{key.number}{key.insertion_code}" for key in keys if key.insertion_code]
        pieces = []
        if plain:
            pieces.append(_number_ranges(sorted(set(plain))))
        pieces.extend(coded)
        parts.append(f"{model_id}/{chain_id}:{','.join(pieces)}")
    return "|".join(parts)


def _group_spec(residues) -> str:
    return compact_residue_spec(residues)


# The surface is a faint halo around the whole complex, not a thick shell over
# the interface: high transparency keeps the cartoon and the interaction lines
# legible, which is how these figures are drawn in the literature.
# 82 rather than 95. At 95 the halo is invisible once the figure is reduced to
# a journal column, which defeats its purpose: the surface is there to show the
# partners' shapes enclosing the interface.
SURFACE_TRANSPARENCY = 84
# Fallback for callers that want one neutral halo.
SURFACE_COLOR = "#B9BCC8"
# How far a body colour is washed out before it is used to tint a surface.
# The surface sits in front of the cartoon it belongs to, so at full strength
# it doubles the colour and the cartoon stops reading as the subject.
SURFACE_TINT = 0.60


def _wash(hex_color: str, towards_white: float = SURFACE_TINT) -> str:
    """Mix a colour towards white, for a tint that frames rather than competes."""
    value = hex_color.lstrip("#")
    channels = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    mixed = (round(c + (255 - c) * towards_white) for c in channels)
    return "#" + "".join(f"{c:02X}" for c in mixed)


# Margin around the framed subject, so the figure keeps some white space and
# survives being exported at an aspect ratio different from the window.
VIEW_PAD = 0.06


def _chain_specs(model, residues) -> str:
    """Whole-chain atomspec for the chains the given residues belong to."""
    wanted = {key.chain_id for key in residues}
    specs = [chain.atomspec for chain in model.chains if chain.chain_id in wanted]
    return "|".join(specs)


def _hotspot_commands(interface, hotspots) -> tuple[str, ...]:
    """Colour interface residues by buried area on one ramp across both partners.

    Deliberately a single scale for the whole interface rather than one per
    chain: the question the preset asks is which residues carry the interface,
    and a per-chain scale would make the most buried residue of a small partner
    look equal to the most buried residue of a large one.
    """
    from ..core.coloring import assign, build_scale, group_by_color

    keys = {(key.chain_id, key.number): key for key in
            tuple(interface.group_a) + tuple(interface.group_b)}
    entries = [
        (keys[(chain, number)].atomspec, delta)
        for (chain, number, _icode), _name, _alone, _complexed, delta in hotspots
        if (chain, number) in keys
    ]
    if not entries:
        return ()
    scale = build_scale([value for _spec, value in entries], "sequential")
    commands = []
    for color, specs in group_by_color(assign(entries, scale)).items():
        commands.append(f"color {'|'.join(specs)} {color} target ac")
    return tuple(commands)


def _ranked_by_side(interface, hotspots, count):
    """The `count` most buried residues of each group, most buried first.

    Per side, not over the interface as a whole. One ranking across both
    partners can starve one of them — on APIM1-nanobody the top eight by
    buried area fell 2 and 6, so one partner's contribution went essentially
    undrawn, and a figure that shows what one side brings and not the other is
    not describing an interface. Where these counts were tuned, on
    barnase-barstar, the global top eight already split 4 and 4, so per-side
    selection picks exactly the same residues there.
    """
    order = {(chain, number): position for position, ((chain, number, _icode), *_)
             in enumerate(hotspots)}
    picked = []
    for side in (interface.group_a, interface.group_b):
        ranked = sorted(
            (key for key in side if (key.chain_id, key.number) in order),
            key=lambda key: order[(key.chain_id, key.number)],
        )
        picked.append(ranked[:count] if count else ranked)
    return picked


def _stick_specs(preset, interface, hotspots, a_spec, b_spec):
    """Which residues of each group get side chains drawn.

    Without hot-spot data there is nothing to rank by, so every interface
    residue keeps its sticks — the same behaviour as before this existed.
    """
    if not preset.geometry.stick_top or not hotspots:
        return a_spec, b_spec
    picked_a, picked_b = _ranked_by_side(
        interface, hotspots, preset.geometry.stick_top
    )
    return (
        compact_residue_spec(picked_a) if picked_a else a_spec,
        compact_residue_spec(picked_b) if picked_b else b_spec,
    )


def _interface_commands(
    model: ModelRef, preset: Preset, interface: InterfaceResult, hotspots=None,
    camera=None,
    label_positions=None,
) -> tuple[str, ...]:
    a_spec = _group_spec(interface.group_a)
    b_spec = _group_spec(interface.group_b)
    chains_a = _chain_specs(model, interface.group_a)
    chains_b = _chain_specs(model, interface.group_b)

    partners = "|".join(spec for spec in (chains_a, chains_b) if spec)
    commands = []
    # Only the two partners are part of the story: other chains (crystal copies,
    # unrelated subunits) are hidden rather than left as grey clutter.
    if partners:
        commands.append(f"hide {model.atomspec} cartoons")
        commands.append(f"show {partners} cartoons")
    # Tint each side's cartoon so the two partners read apart at a glance,
    # then saturate only the interface residues.
    if chains_a:
        commands.append(f"color {chains_a} {preset.palette.body_a} target c")
    if chains_b:
        commands.append(f"color {chains_b} {preset.palette.body_b} target c")
    # The cartoon stays opaque: it is the subject of the figure, and only the
    # surface is reduced to a halo around it.
    commands.append(f"transparency {model.atomspec} 0 target c")
    # Chains that take no part in the interface recede to neutral context.
    commands.append(f"hide {model.atomspec} surfaces")
    # One partner may be drawn as a solid surface instead of a ribbon: the
    # antibody-figure convention, where the antigen is a shape with the
    # epitope painted on it and the binder stays a cartoon so its loops read.
    # Done here, before the interface colours, so the patch lands on the
    # surface rather than being overwritten by the body colour.
    side = preset.geometry.surface_side
    surface_spec = {"a": chains_a, "b": chains_b}.get(side)
    if surface_spec:
        body = preset.palette.body_a if side == "a" else preset.palette.body_b
        commands += [
            # A translucent surface keeps its cartoon: the fold showing through
            # the envelope is the whole point of making it see-through.
            f"show {surface_spec} cartoons"
            if preset.geometry.surface_over_cartoon
            else f"hide {surface_spec} cartoons",
            f"surface {surface_spec}",
            # Over a cartoon the envelope steps back to a wash of the body
            # colour and lets the ribbon keep the full one. Same colour at
            # full strength on both would give a shape and a fold that are
            # only told apart by the transparency between them.
            f"color {surface_spec} "
            f"{_wash(body) if preset.geometry.surface_over_cartoon else body} "
            f"target s",
            f"transparency {surface_spec} "
            f"{preset.geometry.surface_transparency} target s",
        ]
    # The interface gets its own two colours, deeper than the bodies carrying
    # it. They go on the *cartoon* — target c — so the patch reads as a patch
    # at a glance rather than only where side chains happen to be drawn.
    #
    # Until 2026-08-16 this was `target ac`, which painted the side chains the
    # same colour as the patch they stand on: red sticks on a red patch, blue
    # on blue, and the interface turned to mush at exactly the place the
    # figure exists to show. The two now carry different information. The
    # patch says where the interface is; the side chains, in one neutral
    # colour, say which residues carry it. Heteroatoms go to element colours
    # on top, so donor and acceptor are readable without a legend.
    interface_a, interface_b = preset.interface_colors()
    geometry, palette = preset.geometry, preset.palette
    # Which residues get side chains. The interface patch is painted on the
    # whole of both groups either way; only the drawn side chains are limited.
    stick_a, stick_b = _stick_specs(preset, interface, hotspots, a_spec, b_spec)
    sidechain_target = "ac" if not palette.sidechain else "c"
    for side, spec, stick_spec, colour in (("a", a_spec, stick_a, interface_a),
                                           ("b", b_spec, stick_b, interface_b)):
        # The side drawn as a surface gets its patch on the surface, and no
        # side chains: they would be buried inside it and only show as lumps.
        if side == geometry.surface_side:
            # `sc` when the cartoon is still drawn underneath: through a 55%
            # surface the ribbon is what the eye actually reads, so a patch
            # painted only on the surface would be the faintest thing in the
            # figure at the place the figure is about.
            target = "sc" if geometry.surface_over_cartoon else "s"
            commands.append(f"color {spec} {colour} target {target}")
            continue
        commands += [
            f"show {stick_spec} atoms",
            # Nonpolar hydrogens only. On a structure that carries them they
            # outnumber the atoms they decorate — measured on the Der f 7
            # design, showing the interface side chains put 355 hydrogens on
            # screen against 354 heavy atoms — and none of them is what the
            # figure is about.
            #
            # `HC` rather than `H`, and the difference is not cosmetic:
            # ChimeraX anchors a hydrogen bond on the donor *hydrogen* when
            # one is present, so hiding every hydrogen hides the dashes with
            # them. Same structure, same preset: hiding all hydrogens left 2
            # of 3 bonds drawn, hiding only the nonpolar ones left all 3 and
            # still removed 82% of the hydrogens.
            f"hide {stick_spec} & HC atoms",
            f"style {stick_spec} {geometry.sidechain_style}",
            geometry.size_command(stick_spec),
            f"color {spec} {colour} target {sidechain_target}",
            f"transparency {spec} 0 target ac",
        ]
    drawn = [stick for side, stick in (("a", stick_a), ("b", stick_b))
             if side != geometry.surface_side]
    if palette.sidechain_a and palette.sidechain_b:
        # `target a`, so the cartoon patch underneath keeps its own colour:
        # the patch says where the interface is, the carbons say which side
        # each residue belongs to. Painting both with one command — `target
        # ac` — is what put a solid slab of the side-chain colour across the
        # ribbon and lost the patch.
        per_side = {"a": palette.sidechain_a, "b": palette.sidechain_b}
        for side, stick_spec in (("a", stick_a), ("b", stick_b)):
            if side != geometry.surface_side:
                commands.append(f"color {stick_spec} {per_side[side]} target a")
    elif palette.sidechain:
        for stick_spec in drawn:
            commands.append(f"color {stick_spec} {palette.sidechain} target a")
    if palette.sidechain_byhetero:
        # After the flat colour, never before: byhetero keeps carbon and
        # repaints everything else, so the order decides whether carbon ends
        # up the side-chain colour or the colour it happened to have.
        for stick_spec in drawn:
            commands.append(f"color {stick_spec} byhetero target a")
    if preset.hotspot_emphasis and hotspots:
        # Applied after the per-chain tint so the graded scale wins on the
        # interface while the surrounding cartoon keeps its partner colour.
        commands.extend(_hotspot_commands(interface, hotspots))
    if preset.show_interface_surface and partners:
        # The halo wraps the two partners, not every chain in the file: other
        # copies in a crystal stay as neutral context. Each side's surface is
        # tinted towards its own body colour rather than left neutral grey, so
        # the enclosing shape belongs visibly to a partner; at this
        # transparency the tint is a suggestion, not a second colour competing
        # with the cartoon underneath.
        commands.append(f"surface {partners}")
        for spec, colour in ((chains_a, preset.palette.body_a),
                             (chains_b, preset.palette.body_b)):
            if spec:
                commands.append(f"color {spec} {_wash(colour)} target s")
        commands.append(f"transparency {partners} {SURFACE_TRANSPARENCY} target s")
    commands.extend(_annotation_commands(
        preset, interface, hotspots, chains_a, chains_b, camera, label_positions
    ))
    # Before framing, not after: `view matrix` sets where the camera is, and
    # the `view <spec>` below then slides it along its own axis to fit. The
    # other order throws the fit away.
    if camera is not None and preset.geometry.viewpoint:
        commands.append(f"view matrix camera {camera_matrix(*camera)}")
    # Frame the pair being described, rather than zooming out onto unrelated
    # chains — unless the preset is a close-up, which frames on the residues
    # it is a close-up of. A close-up that fits both whole proteins in is an
    # overview drawn with thin sticks.
    subject = partners or model.atomspec
    if preset.geometry.surface_side:
        # `view <atomspec>` fits the *displayed* atoms, and the partner drawn
        # as a surface has its atoms hidden — so it contributes nothing to the
        # bounding box and the framing crops it away. The model spec picks up
        # the surface, which is a child model of the structure.
        #
        # This only became visible once the viewpoint was fixed. Before that
        # the orientation was whatever the user had dragged to, and a framing
        # computed from one partner happened to contain the other often enough
        # to pass for correct.
        subject = model.atomspec
    if preset.geometry.frame_top and hotspots:
        framed = [key for side in
                  _ranked_by_side(interface, hotspots, preset.geometry.frame_top)
                  for key in side]
        if framed:
            subject = compact_residue_spec(framed)
    # One frame before framing. `view` fits the scene as currently realised,
    # and the show/hide commands above are not realised until the next redraw,
    # so without this it fits geometry that is on its way out and the figure
    # comes back cropped. Measured on 1BRS: the same `view` gave a subject
    # spanning 100% of the frame — overflowing it — inside the batch and 49%
    # once the scene had settled. A figure's framing must not depend on when
    # the renderer happened to get a frame.
    commands.append("wait 1")
    commands.append(f"view {subject} pad {preset.geometry.view_pad:g}")
    return tuple(commands)


# Labels are one colour per side, so a residue's chain is readable without
# tracing the ribbon back. Black and red rather than the partner colours: at
# label size a tint is not distinguishable, and these two survive greyscale.
LABEL_COLORS = ("black", "#E01B24")
LABEL_HEIGHT = 1.8
# ChimeraX draws labels on an opaque plate by default. The published figures
# set the text straight on the structure, and a plate at this size hides more
# of the thing being labelled than the label is worth.
LABEL_BACKGROUND = "none"
_LABEL_TEXT = "text '{0.one_letter_code}{0.number}'"


def _angles_clear_of(mine, crowd, total, spread, start):
    """Fan angles for `mine` that also keep clear of every other residue."""
    order = {point: index for index, point in enumerate(mine)}
    combined = list(mine) + [point for point in crowd if point not in order]
    return place_labels(combined, total, spread, start=start)[:len(mine)]


def _annotation_commands(preset, interface, hotspots, chains_a, chains_b,
                         camera=None, label_positions=None):
    """Residue labels and cross-interface hydrogen bonds — the annotation layer.

    Separate from everything above because it fails differently. A ribbon that
    is too small is coarse; a label that is too small is unreadable, and in a
    multi-panel plate a label on every panel is a smear. Both are off unless
    the preset asks, and `label_top` is a count rather than a switch because
    what is wanted is never all-or-nothing but "label a few".
    """
    geometry = preset.geometry
    commands: list[str] = []

    if geometry.label_top and hotspots:
        ranked = [(chain, number) for (chain, number, _icode), *_ in hotspots]
        # Both sides are fanned around one circle rather than a circle each,
        # so one partner's labels cannot land on the other's.
        fanning = geometry.label_spread > 0 and camera is not None
        total = geometry.label_top * 2
        for index, (side, colour) in enumerate(
            zip((interface.group_a, interface.group_b), LABEL_COLORS, strict=True)
        ):
            keys = {(key.chain_id, key.number): key for key in side}
            picked = [keys[pair] for pair in ranked if pair in keys]
            if not picked:
                continue
            picked = picked[:geometry.label_top]
            if not fanning:
                commands.append(
                    f"label {compact_residue_spec(picked)} residues "
                    f"{_LABEL_TEXT} height {LABEL_HEIGHT:g} color {colour} "
                    f"bgColor {LABEL_BACKGROUND}"
                )
                continue
            # One command per residue: an offset is a single vector, so a
            # fanned set cannot be expressed as one command over a group.
            cam_x, cam_y = camera[0], camera[1]
            points = [
                (label_positions or {}).get((key.chain_id, key.number))
                for key in picked
            ]
            if all(point is not None for point in points) and label_positions:
                # Every labelled residue on both sides, so a label chosen for
                # one side still clears the other side's side chains.
                crowd = [
                    project(point, cam_x, cam_y)
                    for point in label_positions.values()
                ]
                mine = [project(point, cam_x, cam_y) for point in points]
                offsets = offsets_at(
                    _angles_clear_of(mine, crowd, total,
                                     geometry.label_spread,
                                     start=index * geometry.label_top),
                    cam_x, cam_y, geometry.label_spread,
                )
            else:
                offsets = fan_offsets(
                    len(picked), cam_x, cam_y, geometry.label_spread,
                    start=index * geometry.label_top, total=total,
                )
            for key, offset in zip(picked, offsets, strict=True):
                commands.append(
                    f"label {compact_residue_spec([key])} residues "
                    f"{_LABEL_TEXT} height {LABEL_HEIGHT:g} color {colour} "
                    f"bgColor {LABEL_BACKGROUND} "
                    f"offset {','.join(f'{value:.2f}' for value in offset)}"
                )

    if geometry.hbonds and chains_a and chains_b:
        # Named on both sides rather than `restrict cross`. With both chains
        # inside one spec there is no "other side" to cross to and ChimeraX
        # returns nothing at all — which reads as "this interface has no
        # hydrogen bonds" rather than as a mistake in the question.
        commands.append(
            f"hbonds {chains_a} restrict {chains_b} reveal false "
            f"color {geometry.hbond_color} dashes {geometry.hbond_dashes} "
            f"radius {geometry.hbond_radius:g}"
        )
    return tuple(commands)


def build_render_commands(
    model: ModelRef,
    preset: Preset,
    interface: InterfaceResult | None = None,
    confidence: ConfidenceReport | None = None,
    hotspots=None,
    image_size: tuple[int, int] | None = None,
    camera=None,
    label_positions=None,
) -> tuple[str, ...]:
    """Commands for one figure.

    `image_size` is the (width, height) the figure will be exported at. Two
    things depend on it and are wrong without it: silhouette width, which is
    in pixels and does not scale, and the colour key, whose position and size
    are fractions of the frame. Omitting it keeps the values as authored,
    which is right for on-screen work.

    `camera` is a `(cam_x, cam_y, cam_z, origin)` basis from
    `viewpoint.side_on`, needed by presets that ask for a fixed viewpoint and
    by label fanning. This layer takes it rather than computing it because it
    only ever sees atomspecs; `commands.py` has the coordinates. Omitting it
    keeps whatever orientation the view is already in, and leaves labels on
    their residue centroids — the behaviour of every preset that does not ask
    for either.
    """
    if preset.requires_interface and interface is None:
        raise ValueError(f"preset {preset.slug} requires a detected interface")
    if preset.confidence_coloring and confidence is None:
        raise ValueError(f"preset {preset.slug} requires pLDDT confidence data")

    width, height = image_size or (None, None)
    commands = list(reset_commands(model))

    if preset.confidence_coloring:
        # noValueColor is named rather than left implicit. On a figure whose
        # entire content is a colour scale, a residue that keeps whatever
        # colour it happened to have gets read as a value.
        commands.append(
            f"color bfactor {model.atomspec} palette {palette_spec(confidence.scale)} "
            f"noValueColor {preset.palette.no_data}"
        )
        low_keys = confidence.low_confidence_keys()
        if low_keys:
            commands.append(f"transparency {_group_spec(low_keys)} 70 target c")
    elif preset.chain_coloring:
        # `target s` when the whole structure is a surface: the cartoon is
        # hidden, so painting it would put the colour on geometry nobody sees
        # and leave the surface at the neutral grey `reset_commands` sets.
        target = "s" if preset.geometry.surface_whole else "c"
        colors = assign_chain_colors(
            [chain.chain_id for chain in model.chains], preset.palette.chains
        )
        chain_specs = {chain.chain_id: chain.atomspec for chain in model.chains}
        if preset.geometry.surface_whole:
            commands.extend(_whole_surface_commands(model, preset))
        for chain_id in sorted(colors):
            commands.append(
                f"color {chain_specs[chain_id]} {colors[chain_id]} target {target}"
            )
    else:
        target = "s" if preset.geometry.surface_whole else "c"
        if preset.geometry.surface_whole:
            commands.extend(_whole_surface_commands(model, preset))
        commands.append(
            f"color {model.atomspec} {preset.palette.primary} target {target}"
        )

    commands.extend(scene_commands(preset, width))

    if preset.requires_interface and interface is not None:
        commands.extend(
            _interface_commands(model, preset, interface, hotspots, camera,
                                label_positions)
        )

    if preset.color_key is not None:
        aspect = width / height if width and height else None
        # The key's colours come from the same table as the palette, so the
        # scale drawn beside the figure cannot disagree with the scale the
        # figure was painted with.
        stops = key_stops(confidence.scale) if preset.confidence_coloring else ()
        # `blended`, not `distinct`, and the bands stay discrete anyway:
        # `key_stops` emits each colour twice, at its lower and upper bound,
        # so every blend runs between a colour and itself. What blending buys
        # is where the labels go — ChimeraX centres labels on blocks under
        # `distinct` and puts them at the stop positions under `blended`, and
        # the AlphaFold bands are named by their boundaries.
        commands.extend(
            preset.color_key.commands(
                aspect, stops=stops, treatment="blended" if stops else "",
                image_height=height,
            )
        )

    return tuple(commands)


def _whole_surface_commands(model: ModelRef, preset) -> tuple[str, ...]:
    """Turn the whole structure into a surface, cartoon hidden.

    `reset_commands` has already shown the cartoons and hidden the surfaces,
    which is the right baseline for every other preset; this undoes both for
    the one that is nothing but surface.
    """
    spec = model.atomspec
    commands = [f"hide {spec} cartoons", f"surface {spec}"]
    if preset.geometry.surface_transparency:
        commands.append(
            f"transparency {spec} {preset.geometry.surface_transparency} target s"
        )
    return tuple(commands)


def hbond_commands(interface: InterfaceResult | None, off: bool = False) -> tuple[str, ...]:
    """Native ChimeraX hbonds restricted to the detected interface groups."""
    if off:
        return ("~hbonds",)
    if interface is None:
        raise ValueError("hydrogen-bond display requires a detected interface")
    a_spec = _group_spec(interface.group_a)
    b_spec = _group_spec(interface.group_b)
    return (
        f"hbonds {a_spec} restrict {b_spec} reveal true "
        "dashes 6 radius 0.08 color #705E9C",
    )


# Typed interactions are the point of the interface figure, so they have to
# survive reduction to a journal column. At 0.06 the dashes disappear at print
# size; 0.24 reads at 85 mm and still looks like a dashed line rather than a
# rod.
#
# Thick side chains, thin dashes. That is the hierarchy the published
# close-ups use, and it took being told twice to get there: the side chains
# are the molecular content and the dashes are annotation over it.
#
# I had it inverted, on the reasoning that the typed interactions are the
# finding and should therefore be the heaviest thing drawn. They are the
# finding, and they are still an annotation — a caption is not set larger
# than the figure.
#
# 0.24 for the sticks. ChimeraX's own stick default is 0.2 and the previous
# 0.13 was thinner than that, which is why they read as wire rather than as
# bonds. 0.12 for the dashes, six of them: at 0.30 with three dashes each
# dash became a short fat block over a 3 Å contact, which looked like debris.
INTERACTION_RADIUS = 0.12
INTERACTION_DASHES = 6

# Distinct, colour-vision-conscious hues per interaction type.
#
# Chosen to contrast with the partners rather than only with each other. The
# earlier salt-bridge orange (#E8734A) sat between the salmon body and the
# brick interface and vanished into both; the lines carry the finding, so they
# have to be the one thing in the figure that belongs to neither partner.
# Greens, teals, magenta and gold are all off the red-blue axis the partners
# occupy, and all dark enough to hold their own against a stick thicket.
# Five of the palette's seven hues; the other two are the interface colours
# these are drawn on top of. Seven at 360/7 = 51.4 degrees is the widest any
# seven can be spread, and it is derived rather than chosen — hand-picking put
# a salt-bridge gold 30 degrees from the interface beneath it and a disulfide
# gold 15 degrees from the salt bridge, both of which a contrast test caught
# only after they had shipped.
#
# Convention is followed where the spacing leaves room for it: yellow-green
# for the sulphur-bearing disulfide, green for hydrophobic contacts.
INTERACTION_COLORS = {
    "salt-bridge": "#8B9916",
    "hydrophobic": "#2C9916",
    "cation-pi": "#231699",
    "pi-stacking": "#831699",
    # Solid, not dashed, and so allowed a hue closer to the others: a
    # disulfide is a covalent bond and drawing it as a dashed contact was
    # wrong on its own terms. Freeing it from the hue budget is what let the
    # four region colours be spread this far.
    "disulfide": "#8C7A23",
}

# Dashes per interaction type. Everything non-covalent is dashed; the
# disulfide is drawn solid.
INTERACTION_DASH_COUNT = {"disulfide": 0}


def interaction_commands(
    interactions: "tuple[Interaction, ...]", off: bool = False
) -> tuple[str, ...]:
    """Named pseudobond groups per interaction type; `off` removes the same groups."""
    commands = []
    for interaction in interactions:
        if not (interaction.atom_a and interaction.atom_b):
            continue  # no atom anchor: nothing to draw
        spec = f"{interaction.atomspec_a()}|{interaction.atomspec_b()}"
        name = f"mc-{interaction.kind}"
        if off:
            commands.append(f"pbond delete {spec} name {name}")
        else:
            color = INTERACTION_COLORS[interaction.kind]
            dashes = INTERACTION_DASH_COUNT.get(interaction.kind, INTERACTION_DASHES)
            commands.append(
                f"pbond {spec} name {name} color {color} "
                f"dashes {dashes} "
                f"radius {INTERACTION_RADIUS} showDist false reveal true"
            )
    return tuple(commands)


def contact_commands(interface: InterfaceResult | None, off: bool = False) -> tuple[str, ...]:
    """Native ChimeraX close-contact pseudobonds restricted to the interface."""
    if off:
        return ("~contacts",)
    if interface is None:
        raise ValueError("contact display requires a detected interface")
    a_spec = _group_spec(interface.group_a)
    b_spec = _group_spec(interface.group_b)
    return (
        f"contacts {a_spec} restrict {b_spec} reveal true "
        "radius 0.05 dashes 4 color #C46A2B",
    )


def focus_commands(
    model: ModelRef,
    interface: InterfaceResult | None = None,
) -> tuple[str, ...]:
    if interface is None:
        return (f"view {model.atomspec} pad {VIEW_PAD}",)
    joined = _group_spec(tuple(interface.group_a) + tuple(interface.group_b))
    return (f"view {joined} pad {VIEW_PAD}",)


def render_preset(
    session, model, preset, interface=None, runner=None, confidence=None,
    hotspots=None, camera=None, label_positions=None,
):
    if runner is None:
        from chimerax.core.commands import run as runner
    commands = build_render_commands(
        model, preset, interface, confidence, hotspots, camera=camera,
        label_positions=label_positions,
    )
    for command in commands:
        runner(session, command)
    return commands
