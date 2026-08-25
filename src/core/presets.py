"""Immutable preset schema, the MVP presets, and stable chain coloring.

A preset is three independent things, and they are three dataclasses here
rather than one flat list of fields:

    Shading    how the scene is lit and how surfaces answer the light
    Geometry   how thick the ribbon is, how side chains are drawn, what is
               annotated
    Palette    which colour each role gets

They are separate because the styles reuse them separately. The licorice
close-up and the superposition style are lit exactly like the flat-outline
style and differ only in geometry; the figure-style handoff of 2026-08-16
records both as "shading same as 2.2" because that is literally what they are.
Flattened into one dataclass that relationship can only be spelled by copying
thirty-odd fields three times, and the next person to change the lighting
changes it in one of the three.

The split also keeps the field count honest. The four styles need lighting
mode and three intensities, three material terms, three shadow switches,
depth cue, silhouettes and their width and colour, cartoon cross-section,
thickness, sides, divisions, arrows and arrow scale, helix mode, side-chain
representation, stick radius, ball scale, how many side chains, how many
labels, and whether hydrogen bonds are drawn. That is past the point where a
flat record is readable.
"""

from dataclasses import dataclass, field, replace

# Four region colours, each its own hue: a solid backbone per chain, and an
# interface highlight in a hue nothing else uses.
#
# The version before this shared one hue between a body and its interface and
# separated them by saturation, which is what RFdiffusion's figures do — a
# #FCD8A8 target against a #FC7800 hotspot, five degrees apart. It is a real
# convention and it reads as monochrome: the whole figure sits in one colour
# and the interface is a darker patch of it rather than a different thing.
#
# The protein-engineering figures do it the other way and it is far louder: a
# gold or teal backbone, a crimson hotspot, a blue mutated position, no two
# sharing a hue. That is what is copied here.
# Both bodies grey, only the interface in colour. Every palette this project
# shipped before 2026-08-16 coloured the two bodies instead, and the whole set
# was rejected at once for it: the figure's subject is the interface, and two
# saturated bodies compete with the one patch that matters. The two greys
# differ just enough to keep the partners apart where they overlap, without
# either becoming a colour of its own.
BODY_WARM, INTERFACE_WARM = "#D9D9DE", "#2E6FD6"
BODY_COOL, INTERFACE_COOL = "#C3C3CA", "#E8641E"

# Side chains sit on the coloured interface patch, so they need to read
# against blue and orange rather than against a body colour. A dark neutral
# does that on both, and keeps the two jobs separate: the patch says where
# the interface is, the drawn shapes say which residues carry it.
SIDECHAIN_NEUTRAL = "#4A4A55"

# Flat-outline family: form is carried by the outline, not by shading, so the
# fills are few and light. This palette will not carry a complex colour
# scheme — every region is flat, and nothing is available to separate two
# similar colours the way a highlight would.
FLAT_GREY = "#D5D5DA"
FLAT_PERIWINKLE = "#7B7BD8"
FLAT_TEAL = "#17BFA8"
FLAT_TEAL_DEEP = "#12A08C"
# The close-up interface pair. Warm gold against deep purple rather than the
# teal/periwinkle used for the bodies: at close-up scale the side chains sit
# *on* the coloured patch, so a patch colour and a carbon colour drawn from
# the same half of the wheel read as one mass. These two are far enough apart
# in hue and in lightness to stay separable where they overlap, and neither
# collides with the element colours `byhetero` puts back on N, O and S.
CLOSEUP_CARBON_A = "#D99000"
CLOSEUP_CARBON_B = "#7651A8"

# The antibody-figure family. One partner is the neutral shape being bound and
# the other carries the colour, which is the opposite of treating two chains
# symmetrically — and it is what the published epitope figures do.
ANTIGEN_WHITE = "#F2F2F4"
BINDER_BLUE = "#2E7BD6"
EPITOPE_BLUE = "#1F5FAF"
CONTACT_YELLOW = "#D8C230"
BINDER_LILAC = "#B9A8DC"
LOOP_ORANGE = "#E8551F"
DESIGN_TEAL = "#159D91"
REFERENCE_BLUE = "#2F6FB2"
REFERENCE_LILAC = "#8583D9"

# For a cartoon that is seen *through* a translucent surface. Darker than
# anything used for an exposed ribbon: 55% of surface over it costs roughly
# half the contrast, so a colour chosen by how it looks on its own comes back
# as a ghost.
SLATE_UNDER_SURFACE = "#7C879B"

# Used when a metric ramp is painted onto the interface instead of the partner
# colours. The ramp needs the whole colour circle to itself: ΔΔG is red-to-blue
# by convention and would otherwise sit on the same hues as the partners.
# Lightened from #B0B0B4 on 2026-08-18: at 55 mm column width a whole partner
# in the old grey read as a dark mass rather than as context, which is the one
# thing a body must not do.
#
# It cannot go much lighter. The body has to stay separable from the palest
# band of every ramp painted over it, in greyscale as well as in colour, or a
# residue at the bottom of a scale becomes indistinguishable from one carrying
# no value at all. The binding neighbour is the sequential ramp's #FEE5D9 at
# luma 233; this sits at 198, a gap of 35. #DCDCE2 would leave 13, which does
# not survive a greyscale print.
BODY_GREY = "#C6C6CB"
# Interface residues a metric has nothing to say about. Without this they kept
# their partner colour, which on the red/blue interface palette is the same
# red the diverging ramp uses for "highly destabilising" — one figure, two
# meanings, same colour.
NO_DATA = BODY_GREY

COLORBLIND_PALETTE = (
    "#4477AA",
    "#EE6677",
    "#228833",
    "#CCBB44",
    "#66CCEE",
    "#AA3377",
    "#BBBBBB",
)

# `graphics silhouettes width` is in pixels and does not scale with the
# exported image, so a width chosen while previewing at one size is a
# different line at another. Widths below are quoted at this reference width
# and converted on the way out; see `Shading.commands`.
SILHOUETTE_REFERENCE_WIDTH = 1500


@dataclass(frozen=True)
class Shading:
    """Lighting, material and outlines — everything that is not colour or form.

    `lighting simple` with ambient occlusion added on top, rather than one of
    ChimeraX's four lighting presets chosen alone. They are not mutually
    exclusive: the key light gives the body its form and the occlusion gives
    its hollows depth, and `soft` alone (occlusion, no key light) is what
    flattened these figures for three rounds of palette work.

    Cast shadows stay off. On an extended beta sheet they draw regular dark
    bands of one strand on the next, and raising the depth bias fourfold does
    not clear them; the occlusion has already darkened everything that should
    be dark. Depth cue stays off for the same family of reason — on white it
    fades the far side of the molecule towards the paper, which is the "washed
    out" that kept being chased in the palette.
    """

    lighting: str = "simple"
    intensity: float | None = None
    fill_intensity: float | None = None
    ambient_intensity: float | None = None
    # A named ChimeraX material ("dull", "shiny"). When set, the three
    # numeric terms below are not emitted — the named preset defines them.
    material: str | None = None
    reflectivity: float | None = None
    specular_reflectivity: float | None = None
    exponent: float | None = None
    shadows: bool = False
    multi_shadow: int = 0
    ms_map_size: int = 4096
    ms_depth_bias: float = 0.03
    depth_cue: bool = False
    silhouettes: bool = False
    silhouette_width: float = 3.0
    silhouette_color: str = "black"

    def commands(self, image_width: int | None = None) -> tuple[str, ...]:
        """The ChimeraX lines that set this up, in dependency order.

        `image_width` is the width the figure will be exported at. Silhouette
        width is in pixels, so a 3.0 chosen at 1500 px is 58% of that relative
        weight at 2600 px — the figure reviewed and the figure submitted are
        not the same drawing. Passing the output width converts it; omitting
        it keeps the reference width, which is right for on-screen work.
        """
        lines = [f"lighting {self.lighting}"]
        intensities = (
            ("intensity", self.intensity),
            ("fillIntensity", self.fill_intensity),
            ("ambientIntensity", self.ambient_intensity),
        )
        terms = " ".join(f"{name} {value:g}"
                         for name, value in intensities if value is not None)
        if terms:
            lines.append(f"lighting {terms}")
        if self.material:
            lines.append(f"material {self.material}")
        else:
            for name, value in (("reflectivity", self.reflectivity),
                                ("specularReflectivity", self.specular_reflectivity),
                                ("exponent", self.exponent)):
                if value is not None:
                    lines.append(f"material {name} {value:g}")
        lines.append(f"lighting shadows {'true' if self.shadows else 'false'}")
        if self.multi_shadow:
            lines.append(
                f"lighting multiShadow {self.multi_shadow} "
                f"msMapSize {self.ms_map_size} msDepthBias {self.ms_depth_bias:g}"
            )
        else:
            lines.append("lighting multiShadow 0")
        lines.append(f"lighting depthCue {'true' if self.depth_cue else 'false'}")
        if self.silhouettes:
            scale = (image_width or SILHOUETTE_REFERENCE_WIDTH) / SILHOUETTE_REFERENCE_WIDTH
            lines.append(
                f"graphics silhouettes true width {self.silhouette_width * scale:g} "
                f"color {self.silhouette_color}"
            )
        else:
            lines.append("graphics silhouettes false")
        return tuple(lines)


@dataclass(frozen=True)
class Geometry:
    """Ribbon form, side-chain representation, and the annotation layer.

    `label_top` and `hbonds` are the annotation layer and both default off.
    They fail differently from everything else here: a ribbon that is too
    small is merely coarse, but a label that is too small is unreadable, and
    in a multi-panel plate labels on every panel become a smear. `label_top`
    is a count rather than a switch because what is wanted in practice is
    never all-or-nothing but "label a few" — three a side is the most that
    fits before they collide — and a boolean hard-codes that number.
    """

    cartoon_xsection: str = "oval"
    cartoon_thickness: float = 0.22
    cartoon_sides: int | None = None
    cartoon_divisions: int | None = None
    arrows: bool | None = None
    arrow_scale: float | None = None
    helix_mode: str | None = None
    # stick | ball | sphere. `ball` reads as most solid at small sizes while
    # keeping side chains identifiable; `sphere` merges them into a blob.
    sidechain_style: str = "stick"
    # Side chains and backbone are drawn at a shared radius in stick style —
    # ChimeraX gives atoms and bonds one radius here — so this is measured
    # against the ribbon. ChimeraX draws helix and strand as a 2.0 x 0.22 Å
    # ribbon and coil as a 0.22 Å tube, so 0.42 makes a side chain four times
    # the backbone's thickness: it swallows the backbone it hangs off, and
    # neighbouring atoms merge into lumps. 0.22 leaves it twice the width of
    # coil, still the subject, with white between adjacent bonds. Below about
    # 0.15 it goes to wire and the heteroatom colours stop being readable.
    stick_radius: float = 0.25
    ball_scale: float | None = None
    # How many interface residues get side chains, counted *per side*. 0 means
    # all of them, which is what a close-up wants and what an overview cannot
    # survive.
    #
    # Per side rather than over the interface as a whole. A single ranking
    # across both partners can starve one of them: on APIM1-nanobody the top
    # eight by buried area fell 2 on one chain and 6 on the other, leaving one
    # partner's contribution essentially undrawn — and a figure that shows
    # what one side brings to an interface and not the other is not describing
    # an interface. On barnase-barstar, where these numbers were tuned, the
    # global top eight already split 4 and 4, so per-side 4 selects exactly
    # the same eight residues and nothing about that figure changes.
    stick_top: int = 0
    # Frame on this many top-ranked residues a side instead of on the whole
    # pair. 0 frames the pair. A close-up that fits both proteins in is an
    # overview with thin sticks.
    frame_top: int = 0
    view_pad: float = 0.06
    # Draw one partner as a solid surface and leave the other a cartoon.
    # "" is both cartoon; "a" or "b" names the side that becomes surface.
    #
    # This is the antibody-figure convention and it is asymmetric on purpose:
    # the antigen is a solid shape with the epitope painted on it, and the
    # binder is a ribbon so its fold and its loops stay readable. Two surfaces
    # would hide both folds; two cartoons cannot show a patch as a patch.
    surface_side: str = ""
    # Opaque, unlike the faint halo `show_interface_surface` adds. A surface
    # standing in for a whole protein has to read as that protein's shape.
    surface_transparency: int = 0
    # Whether the cartoon under the surface stays drawn. Off for a solid
    # surface, where it would only be hidden geometry slowing the render; on
    # for a translucent one, where the point is seeing the fold inside the
    # envelope — a see-through surface over a hidden cartoon shows through
    # onto nothing, which looks like a rendering fault rather than a style.
    surface_over_cartoon: bool = False
    # Draw the *whole* structure as a surface, cartoon hidden. Distinct from
    # `surface_side`, which needs a detected interface to know which group
    # becomes the surface: this one applies to a lone structure, so it belongs
    # to the whole-structure group and is available before any analysis has
    # run. What it answers is the shape question — how the assembly packs, what
    # it presents to solvent — which no ribbon shows.
    surface_whole: bool = False

    @property
    def draws_surface(self) -> bool:
        """Whether this geometry builds a surface of its own.

        Asked by anything that would otherwise clear or repaint surfaces as a
        housekeeping step: for these presets the surface *is* the figure.
        """
        return bool(self.surface_side or self.surface_whole)
    # How many residues a side gets labelled. 0 means none.
    label_top: int = 0
    # How far to fan the labels apart, in Å, measured in the camera plane.
    #
    # 0 leaves every label on its residue's centroid, which is where they
    # collide: the residues worth labelling are the ones that bury the most
    # surface, and those are by definition clustered in one patch. Fanning
    # them around a circle separates them.
    #
    # The plane matters. An offset computed in scene coordinates — radially
    # away from the contact centre, say — mostly points along the view axis,
    # where it produces no separation on the page at all and looks like the
    # offset was ignored. Only the camera's own x and y do anything, so this
    # is applied by `commands.py`, which is where the camera basis is known.
    label_spread: float = 0.0
    # Put the interface axis horizontal on screen, so the partners sit left
    # and right with the contact as a vertical seam.
    #
    # `viewpoint.py` already had face-on (looking down that axis) and
    # open-book (splitting the partners apart); neither is the overview the
    # published binder figures use. Empty keeps whatever orientation the user
    # has dragged to, which is right for interactive work and wrong for a
    # multi-panel plate, where every panel has to be the same viewpoint.
    viewpoint: str = ""
    # Roll about the interface axis, in degrees. The one free parameter once
    # the axis is horizontal, with no principled value — dialled by eye.
    viewpoint_roll: float = 0.0
    hbonds: bool = False
    hbond_color: str = "#F2C200"
    hbond_dashes: int = 6
    hbond_radius: float = 0.08

    def cartoon_commands(self) -> tuple[str, ...]:
        parts = [f"xsection {self.cartoon_xsection}",
                 f"thickness {self.cartoon_thickness:g}"]
        if self.cartoon_sides is not None:
            parts.append(f"sides {self.cartoon_sides}")
        if self.cartoon_divisions is not None:
            parts.append(f"divisions {self.cartoon_divisions}")
        if self.arrows is not None:
            parts.append(f"arrows {'true' if self.arrows else 'false'}")
        if self.arrow_scale is not None:
            parts.append(f"arrowScale {self.arrow_scale:g}")
        lines = [f"cartoon style {' '.join(parts)}"]
        if self.helix_mode:
            lines.append(f"cartoon style modeHelix {self.helix_mode}")
        return tuple(lines)

    def size_command(self, spec: str) -> str:
        parts = [f"stickRadius {self.stick_radius:g}"]
        if self.sidechain_style == "ball" and self.ball_scale is not None:
            parts.append(f"ballScale {self.ball_scale:g}")
        return f"size {spec} {' '.join(parts)}"


@dataclass(frozen=True)
class Palette:
    """Which colour each role gets.

    `sidechain` is the field the previous schema did not have, and its absence
    was the worst thing about the interface figures. Side chains were painted
    with the interface colour — `color <spec> <interface> target ac` covers
    cartoon and atoms together — so red sticks sat on a red patch and blue on
    blue, and the interface, the one region the figure exists to show, turned
    to mush. A neutral grey for the side chains splits the work in two: the
    colour patch says where the interface is, the drawn shapes say which
    residues carry it. Dropping the patch entirely is cleaner still but throws
    away the interface's extent, which is worth more than the tidiness.
    """

    body_a: str = BODY_GREY
    body_b: str = BODY_GREY
    interface_a: str = ""
    interface_b: str = ""
    # "" keeps the old behaviour of painting side chains with the interface
    # colour. Any colour here separates them.
    sidechain: str = ""
    # Per-side side-chain colour, when the two sides should be told apart by
    # their carbons rather than share one neutral. Set both or neither; they
    # override `sidechain`. They paint `target a` only, so the cartoon patch
    # underneath keeps whatever `interface_a`/`interface_b` gave it — which
    # is the difference between marking which residues carry the interface
    # and repainting the region they sit in.
    sidechain_a: str = ""
    sidechain_b: str = ""
    # Heteroatoms in element colours while carbon keeps the colour above, so
    # which atom donates and which accepts is readable without a legend.
    sidechain_byhetero: bool = False
    primary: str = "#6C8EBF"
    chains: tuple[str, ...] = COLORBLIND_PALETTE
    no_data: str = NO_DATA

    def interface_colors(self) -> tuple[str, str]:
        """Interface colours, falling back to the body colours when unset."""
        return (self.interface_a or self.body_a, self.interface_b or self.body_b)


# The close-up geometry, shared by the two close-up presets so a change to
# stick radius, framing, labels or hydrogen bonds reaches both. They differ
# only in whether the colour stops at the interface or runs to the chain ends.
PRESETS_CLOSEUP_GEOMETRY = Geometry(
    cartoon_xsection="rectangle", cartoon_thickness=0.22,
    arrows=True, arrow_scale=1.6, helix_mode="default",
    sidechain_style="stick", stick_radius=0.22,
    stick_top=0, label_top=3, hbonds=True,
    frame_top=3, view_pad=0.12,
    # Without this the labels do not fan, and on 1BRS "D39" and "Y29" printed
    # on top of each other: the residues that earn a label are the ones that
    # bury the most surface, and those cluster by definition. It is the defect
    # paratope-closeup fixed in its version 2, left unfixed here because the
    # fix was made on that preset rather than on the geometry both share.
    #
    # 6.0 rather than paratope-closeup's 5.0 because this geometry labels
    # three residues a side, not two. `fan_offsets` spaces the labels around
    # one shared circle, so adjacent ones sit 2*spread*sin(pi/total) apart:
    # 7.1 A at spread 5 over four labels, but only 5.0 A at spread 5 over six.
    # 6.0 restores 6.0 A without pushing a label so far from its residue that
    # the pairing stops being obvious.
    label_spread=6.0,
)

# The lighting the flat-outline family shares. Written once and referenced by
# every style that uses it, so "same shading as flat-outline" is a fact in the
# code and not a comment that can go stale.
FLAT_SHADING = Shading(
    lighting="flat",
    material="dull",
    shadows=False,
    multi_shadow=0,
    depth_cue=False,
    silhouettes=True,
    # Author's choice from the 2026-08-16 candidate sheet: the outline was
    # reading as too black, for both of its two possible reasons at once, so
    # both moved. The colour is off pure black, and the line is 69% of its
    # former weight — the ratio between the two frames compared, carried onto
    # the stored value rather than copied from it, since the sheet sent raw
    # widths and so bypassed the reference-width scaling that stored value
    # feeds. At 2600 px this now draws 3.6 where it drew 5.2.
    silhouette_width=2.1,
    silhouette_color="#4A4A4A",
)

# The flat-outline shading with the light put back, for the styles that draw a
# molecular surface.
#
# `lighting flat` is right for a cartoon and wrong for a surface, and the
# reason is where each gets its form from. A cartoon is a thin ribbon whose
# shape is carried by its outline and by the secondary structure it traces, so
# flat fill inside a contour still reads. A surface is a large smooth solid
# with no internal edges: under pure ambient light a near-white one renders as
# a blank silhouette, and every pocket — which is the only reason to draw a
# surface rather than a cartoon — disappears.
#
# `gentle` keeps the flat look far more than `simple` does while restoring
# enough directional falloff to see a hollow, and a light touch of occlusion
# (16, against the 48 the rendered styles use) darkens the pockets without the
# crevices reading as dirt on a matte surface.
SURFACE_SHADING = replace(
    FLAT_SHADING,
    lighting="gentle",
    multi_shadow=16,
    ms_map_size=2048,
)

# The rendered look: a key light for form, ambient occlusion for depth.
MODELLED_SHADING = Shading(
    # PyMOL's rendering, chosen from the 2026-08-16 sweep after the ChimeraX
    # look was rejected outright rather than adjusted.
    #
    # The difference is ambient occlusion, and it is switched off here on
    # purpose. `lighting full` is ChimeraX's two-light setup *with* occlusion;
    # `multiShadow 0` immediately after takes the occlusion away and leaves
    # the lights. Occlusion darkens every crevice, which is the thing that
    # reads as computer graphics rather than as a published figure — PyMOL has
    # no equivalent on by default, and takes its form from the key light and a
    # soft but present specular instead.
    #
    # So the specular comes back up to 0.35 after being cut to 0.08 earlier
    # the same day. That is not a reversal: at 0.08 it was compensating for a
    # look built on occlusion, and with the occlusion gone the highlight is
    # what carries the roundness. Judged in the sweep, not reasoned about.
    lighting="full",
    intensity=None,
    fill_intensity=None,
    ambient_intensity=None,
    # Author's choice from the 2026-08-16 candidate sheet, after "too
    # reflective", "too metallic" and "the light is too strong" three rounds
    # running. The specular term is what those describe — it is the bright
    # highlight riding on top of the fill, and at 0.45 it turned a cartoon
    # ribbon into something that looked extruded in metal. At 0.08 the
    # highlight is essentially gone and the form is carried by the key light
    # and the occlusion, which is what it should have been carried by.
    #
    # Not zero. Matte was on the sheet as well and was not chosen: with no
    # highlight at all the rendered style starts drifting back toward flat,
    # and the whole reason it exists beside flat-outline is that it is not.
    reflectivity=0.9,
    specular_reflectivity=0.35,
    exponent=60,
    shadows=False,
    multi_shadow=0,
    depth_cue=False,
    silhouettes=False,
)


# How much room the key's labels need below `y`, as a multiple of the font
# size. Measured by exporting the same figure at 900 px with the key stepped
# up: at 0.055 and 0.08 the numbers are cut in half, at 0.11 they are whole.
# 0.11 x 900 / 42 = 2.36, and 2.6 is that with enough margin not to sit on the
# edge. Not derived from the font metrics because ChimeraX draws the ticks,
# the gap and the text, and only the last of those is the font.
LABEL_CLEARANCE = 2.6


def key_clearance_y(y: float, font_size: int, image_height: int | None) -> float:
    """The lowest `y` that still leaves room for the key's own labels.

    The position is a fraction of the image and the labels under it are a fixed
    number of pixels, so the room reserved for them shrinks with the image
    while they do not. Measured on real exports: at 1300 px tall the numbers
    end 79 px clear of the edge, at 900 they end 1 px clear, and below that
    they are cut off entirely — which is the range "Match window" lands in on
    a laptop.

    It lifts the key on tall exports too, where nothing was being clipped: the
    same clearance at every size is what makes the position predictable, and a
    key that sits a little higher was what the author asked for. Figures
    exported before this will place their key slightly lower.
    """
    if not image_height:
        return y
    return max(y, font_size * LABEL_CLEARANCE / image_height)


@dataclass(frozen=True)
class ColorKey:
    """The colour scale drawn beside a figure whose content is a colour.

    Mandatory on anything that paints a metric. A pLDDT or ΔΔG figure without
    a key is a picture of colours the reader has to already know, and until
    2026-08-16 every confidence figure this tool produced went out without
    one — `grep key` over the renderer found nothing.

    Position and size are fractions of the window, so they are aspect-ratio
    dependent in exactly the way `graphics silhouettes width` is
    resolution-dependent: values tuned on a 4:3 preview drift on a square or
    portrait export. `commands` takes the output aspect and corrects for it.
    """

    x: float = 0.30
    y: float = 0.055
    width: float = 0.40
    height: float = 0.028
    # 26, not 15. Measured on the plate: at 15 the tick labels came out 11
    # plate units against 22 for the panel caption above them — half the size
    # of the smallest other type in the figure, and under the 7 pt a journal
    # asks for at final size. The key is the only thing that makes a colour
    # figure readable, so it cannot be the smallest thing on it.
    # 42, and the limit is the pLDDT key rather than the widest label.
    #
    # Boundary labels are placed proportionally, so the AlphaFold bands get
    # widths in the ratio 50:20:20:10 and the last pair, 90 and 100, sit only a
    # tenth of the bar apart. Measured on the plate: the bar is 725 px in an
    # 1800 px export, so that gap is 72 px, and two adjacent labels need about
    # 1.5x the font size between their centres. At 60 they collided and the key
    # printed "90100"; 42 leaves 63 px against the 72 available.
    #
    # The other two keys have room to spare — dSASA's six labels are evenly
    # spaced at 120 px, ddG's five at 145 — so this is the pLDDT key setting
    # the ceiling for all three, which is the price of one shared key style.
    #
    # It works out at about 2.2 pt at final size in Figure 1, still under the
    # 7 pt a journal asks. Getting there needs fewer labels or larger cells,
    # not a larger font: at four panels to a row there is no font that fits.
    font_size: int = 42
    label_color: str = "black"
    ticks: bool = True
    tick_thickness: int = 2
    reference_aspect: float = 4 / 3

    def commands(self, aspect: float | None = None, stops=(),
                 treatment: str = "", image_height: int | None = None
                 ) -> tuple[str, ...]:
        # A bar holding a constant fraction of the width would grow in
        # proportion as the frame narrows, and its height in proportion as the
        # frame shortens. Both are corrected against the aspect it was set on.
        ratio = (aspect or self.reference_aspect) / self.reference_aspect
        width = self.width / ratio if ratio > 1 else self.width
        height = self.height * ratio if ratio < 1 else self.height
        x = 0.5 - width / 2
        # `y` is a fraction of the image and the labels under it are a fixed
        # number of pixels, so the room reserved for them shrinks with the
        # image while they do not. Measured: at 1300 px tall the numbers end
        # 79 px clear of the edge, at 900 they end 1 px clear, and below that
        # they are cut off — which is exactly the range "Match window" lands
        # in on a laptop. The floor is the labels' own height, so the default
        # is untouched wherever it was already enough.
        y = self.y
        if image_height:
            y = max(y, self.font_size * LABEL_CLEARANCE / image_height)
        # The colours come first, as `key` expects, and without them ChimeraX
        # draws whatever key already existed — which on a fresh session is a
        # generic blue-to-red bar labelled min/max. A pLDDT figure was going
        # out with an AlphaFold-coloured structure beside a blue-red scale
        # that had nothing to do with it: worse than no key, because a key is
        # read as authoritative.
        pairs = " ".join(f"{colour}:{label}" for colour, label in stops)
        head = f"key {pairs} " if pairs else "key "
        # `distinct` draws one block per colour instead of blending between
        # them. Bands that the palette keeps discrete must stay discrete here
        # too, or the key promises a gradient the figure does not have.
        tail = f" colorTreatment {treatment}" if treatment else ""
        return (
            f"{head}pos {x:.3f},{y:.4g} size {width:.3f},{height:.3f} "
            f"fontSize {self.font_size} labelColor {self.label_color} "
            f"ticks {'true' if self.ticks else 'false'} "
            f"tickThickness {self.tick_thickness}{tail}",
        )


@dataclass(frozen=True)
class Preset:
    """A named figure style: what it is called, and its three parts."""

    slug: str
    display_name: str
    version: int
    requires_interface: bool = False
    chain_coloring: bool = False
    confidence_coloring: bool = False
    hotspot_emphasis: bool = False
    show_interface_surface: bool = False
    reference_comparison: bool = False
    panel_visible: bool = True
    group: str = "Whole structure"
    shading: Shading = field(default_factory=Shading)
    geometry: Geometry = field(default_factory=Geometry)
    palette: Palette = field(default_factory=Palette)
    # None means the figure's colours are categories, not values, and a scale
    # would be meaningless.
    color_key: ColorKey | None = None

    def interface_colors(self) -> tuple[str, str]:
        return self.palette.interface_colors()

    def with_shading(self, **changes) -> "Preset":
        return replace(self, shading=replace(self.shading, **changes))


def grouped_presets() -> dict[str, tuple[Preset, ...]]:
    """Presets under their headings, in declaration order within each."""
    groups: dict[str, list[Preset]] = {}
    for preset in PRESETS.values():
        if not preset.panel_visible:
            continue
        groups.setdefault(preset.group, []).append(preset)
    return {name: tuple(items) for name, items in groups.items()}


PRESETS = {
    "clean-cartoon": Preset(
        # The default, and the author's first impression of the whole tool —
        # so it gets the same rendering the interface styles were converged
        # on, not a bare `lighting simple` over a thin ribbon. That bare
        # version is what drew "thin, metallic, no substance" the moment
        # Apply was clicked: a 0.22 ribbon under one naked directional light.
        "clean-cartoon", "Cartoon", 3,
        shading=MODELLED_SHADING,
        geometry=Geometry(cartoon_xsection="oval", cartoon_thickness=0.55,
                          cartoon_sides=20, cartoon_divisions=24),
        palette=Palette(body_a="#4477AA", body_b="#EE7733", primary="#6C8EBF"),
    ),
    "complex-by-chain": Preset(
        "complex-by-chain", "Cartoon (chain colours)", 3, chain_coloring=True,
        shading=MODELLED_SHADING,
        geometry=Geometry(cartoon_xsection="oval", cartoon_thickness=0.55,
                          cartoon_sides=20, cartoon_divisions=24),
        palette=Palette(body_a="#4477AA", body_b="#EE7733", primary="#6C8EBF"),
    ),
    "design-reference": Preset(
        "design-reference", "Design–reference overlay", 1,
        requires_interface=True,
        reference_comparison=True,
        panel_visible=False,
        group="Comparison",
        shading=replace(
            SURFACE_SHADING,
            silhouettes=True,
            silhouette_width=1.2,
            silhouette_color="#4A4A4A",
        ),
        geometry=Geometry(
            cartoon_xsection="oval", cartoon_thickness=0.55,
            cartoon_sides=20, cartoon_divisions=24,
        ),
        palette=Palette(
            body_a=ANTIGEN_WHITE,
            body_b=DESIGN_TEAL,
            interface_a=LOOP_ORANGE,
            chains=(REFERENCE_BLUE, REFERENCE_LILAC),
        ),
    ),
    "interface-focus": Preset(
        # The "Modelled" style of the 2026-08-16 handoff, replacing the
        # version that shipped as v7. Three changes, in the order they matter:
        #
        # 1. Side chains are no longer the interface colour. See Palette.
        # 2. Ambient occlusion is added on top of the key light rather than
        #    chosen instead of it. See Shading.
        # 3. The interface colours are a step brighter. Same hue, more light,
        #    so a neutral side chain reads against them.
        #
        # No surface and no outlines. The surface was the single thing making
        # these figures look washed out: everything under it is dimmed by
        # whatever fraction is not transparent, so a palette tuned against
        # white renders muted. The published interface figures this borrows
        # from have no surface at all. It is still one checkbox away, because
        # the enclosing shape is worth seeing on a first look at an unfamiliar
        # complex — it is just not what a figure wants.
        "interface-focus", "Interface (partners)", 10, requires_interface=True,
        group="Interface",
        shading=MODELLED_SHADING,
        geometry=Geometry(
            # PyMOL's cartoons are rounder and much thicker than ChimeraX's,
            # and with the occlusion gone the thickness is doing some of the
            # work the occlusion used to.
            cartoon_xsection="oval", cartoon_thickness=0.55,
            cartoon_sides=20, cartoon_divisions=24, arrow_scale=1.5,
            sidechain_style="stick", stick_radius=0.25, stick_top=4,
        ),
        palette=Palette(
            body_a=BODY_WARM, body_b=BODY_COOL,
            interface_a=INTERFACE_WARM, interface_b=INTERFACE_COOL,
            sidechain=SIDECHAIN_NEUTRAL, sidechain_byhetero=True,
            primary="#DCDCE2",
        ),
    ),
    "flat-outline": Preset(
        # Form carried by the outline instead of by shading, which is why it
        # holds up at journal single-column width and in greyscale where the
        # rendered style softens. Not a better style — a different question.
        #
        # Interface residues are drawn as ball-and-stick rather than sticks:
        # under a flat fill with an outline, a stick reads as one more ribbon,
        # while a ball has its own silhouette and sits in the fold.
        "flat-outline", "Interface (flat outline)", 2, requires_interface=True,
        group="Interface",
        shading=FLAT_SHADING,
        geometry=Geometry(
            cartoon_xsection="rectangle", cartoon_thickness=0.22,
            arrows=True, arrow_scale=1.6, helix_mode="default",
            sidechain_style="ball", stick_radius=0.32, ball_scale=0.42,
            stick_top=4,
        ),
        palette=Palette(
            body_a=FLAT_GREY, body_b=FLAT_GREY,
            interface_a=FLAT_PERIWINKLE, interface_b=FLAT_TEAL,
            sidechain=SIDECHAIN_NEUTRAL, sidechain_byhetero=True,
            primary=FLAT_GREY,
        ),
    ),
    "licorice-closeup": Preset(
        # The close-up: every interface side chain rather than the top few,
        # because at this scale the ribbon has left the frame and the side
        # chains are the subject. Carbon keeps its chain colour — it is the
        # only thing left that tells the two proteins apart — and everything
        # else goes to element colours.
        # Version 4: the interface carbons go to gold and purple.
        "licorice-closeup", "Interface close-up", 4, requires_interface=True,
        group="Interface",
        shading=FLAT_SHADING,
        geometry=PRESETS_CLOSEUP_GEOMETRY,
        palette=Palette(
            body_a=FLAT_GREY, body_b=FLAT_GREY,
            interface_a=FLAT_TEAL_DEEP, interface_b=FLAT_PERIWINKLE,
            sidechain_a=CLOSEUP_CARBON_A, sidechain_b=CLOSEUP_CARBON_B,
            sidechain="", sidechain_byhetero=True,
            primary=FLAT_GREY,
        ),
    ),
    "licorice-chain": Preset(
        # The same close-up with the colour taken all the way out to the ends
        # of both chains, instead of a grey body carrying a coloured patch.
        #
        # Both readings are useful and they answer different questions. Grey
        # bodies say "here is the interface, and here is the rest"; coloured
        # bodies say "here are two proteins, and this is where they touch".
        # At close-up scale most of the ribbon has left the frame anyway, so
        # the grey no longer reads as context — it reads as an absence.
        #
        # Only the palette differs from licorice-closeup, and it is written
        # that way: `replace` on the shared geometry, so the two cannot drift
        # apart in stick radius, framing, labels or hydrogen bonds.
        # Version 3: the interface carbons go to gold and purple while the
        # bodies keep the chain colours, so the patch no longer disappears
        # into the chain it sits on.
        "licorice-chain", "Interface close-up (chain colours)", 3,
        requires_interface=True, group="Interface",
        shading=FLAT_SHADING,
        geometry=PRESETS_CLOSEUP_GEOMETRY,
        palette=Palette(
            body_a=FLAT_TEAL_DEEP, body_b=FLAT_PERIWINKLE,
            interface_a=FLAT_TEAL_DEEP, interface_b=FLAT_PERIWINKLE,
            sidechain_a=CLOSEUP_CARBON_A, sidechain_b=CLOSEUP_CARBON_B,
            sidechain="", sidechain_byhetero=True,
            primary=FLAT_GREY,
        ),
    ),
    "paratope-closeup": Preset(
        # The published close-up this is modelled on: binder in a pale tint
        # with the loop that does the work in a hot accent, target in white
        # with its side chains drawn thin so the packing is visible without
        # the target competing for attention.
        # Version 2: labels fan apart, and the viewpoint is fixed. The
        # residues worth labelling are the ones that bury the most surface,
        # and those cluster by definition — on APIM1-nanobody all four landed
        # on top of each other.
        "paratope-closeup", "Interface (binder loop)", 2,
        requires_interface=True, group="Interface",
        shading=replace(SURFACE_SHADING, silhouette_width=1.6),
        geometry=Geometry(
            cartoon_xsection="oval", cartoon_thickness=0.4,
            cartoon_sides=20, cartoon_divisions=24, arrow_scale=1.4,
            sidechain_style="stick", stick_radius=0.2,
            stick_top=0, label_top=2, frame_top=4, view_pad=0.16,
            label_spread=5.0, viewpoint="side-on",
        ),
        palette=Palette(
            body_a=BINDER_LILAC, body_b=ANTIGEN_WHITE,
            interface_a=LOOP_ORANGE, interface_b=ANTIGEN_WHITE,
            sidechain="", sidechain_byhetero=True,
            primary=ANTIGEN_WHITE,
        ),
    ),
    "hotspot-focus": Preset(
        # Same geometry as interface-focus, different question. Where
        # interface-focus asks "where is the interface and what chemistry is
        # in it", this asks "which residues carry it": the interface is
        # coloured by buried area on one sequential ramp across both partners,
        # so the eye compares magnitude rather than chain membership. Grey
        # bodies, because a ramp wants the colour circle to itself.
        "hotspot-focus", "Interface (buried area)", 6, requires_interface=True,
        hotspot_emphasis=True, group="Interface",
        shading=MODELLED_SHADING,
        geometry=Geometry(cartoon_xsection="oval", cartoon_thickness=0.34,
                          cartoon_sides=16, cartoon_divisions=24),
        palette=Palette(body_a=BODY_GREY, body_b=BODY_GREY, primary="#DCDCE2"),
    ),
    "metric-map": Preset(
        # The carrier for a figure whose whole content is a colour: DDG,
        # B-factor, anything painted by `molcompose color by`. It supplies the
        # rendering and the key; the metric command supplies the colours.
        #
        # One carrier rather than one per metric, which is where this departs
        # from section 8 of the handoff. Every field a DDG map and a B-factor
        # map would need is identical - flat fill, outline, no side chains,
        # a key - and what differs between them is the palette, which comes
        # from the data rather than from the style. Two presets differing in
        # nothing would be two things to keep in step for no gain.
        #
        # `lighting flat` here is correctness, not taste. A flat fill has no
        # shading gradient, so the colour on screen is the colour on the key.
        # Under a directional light one value renders as two different RGBs on
        # the lit and unlit faces of the same helix, and the reader necessarily
        # misreads the scale.
        #
        # No side chains: `byhetero`'s red oxygen and blue nitrogen would sit
        # on a red-to-blue DDG ramp, giving one figure two red-blue schemes
        # that mean different things.
        "metric-map", "Cartoon (metric map)", 1,
        shading=replace(FLAT_SHADING, silhouettes=True),
        geometry=Geometry(cartoon_xsection="oval", cartoon_thickness=0.30,
                          cartoon_sides=16, cartoon_divisions=24),
        # Residues the metric says nothing about must not keep an earlier
        # colour: on a figure that is entirely a scale, any leftover colour is
        # read as a value.
        palette=Palette(primary=NO_DATA, no_data=NO_DATA),
        color_key=ColorKey(),
    ),
    "predicted-structure": Preset(
        # Flat lighting here is a correctness requirement, not a preference.
        # A flat fill has no shading gradient, so the colour on screen is the
        # colour on the key. Under a directional light one pLDDT value renders
        # as two different RGBs on the lit and unlit faces of the same helix,
        # and the reader necessarily misreads the key. Elsewhere lighting is
        # taste; on a figure whose whole content is a colour scale it is a
        # reading error.
        "predicted-structure", "Cartoon (pLDDT confidence)", 3,
        confidence_coloring=True,
        shading=replace(FLAT_SHADING, silhouettes=True),
        geometry=Geometry(cartoon_xsection="oval", cartoon_thickness=0.30,
                          cartoon_sides=16, cartoon_divisions=24),
        # noValueColor is explicit rather than left to whatever the residue
        # already was. On a figure that is entirely a colour scale, any colour
        # left over from an earlier command gets read as a value.
        palette=Palette(primary="#BBBBBB", no_data="#DCDCE2"),
        color_key=ColorKey(),
    ),
    "surface-complex": Preset(
        # All surface, no ribbon, one colour per chain. The question a ribbon
        # cannot answer: what shape is this, how do the chains pack, what does
        # the assembly present to solvent.
        #
        # In the whole-structure group on purpose. The four `surface-*` styles
        # in the Interface group each need a detected interface to know which
        # chain group becomes the surface; this one needs nothing, so it is
        # available the moment a structure is open — which is where someone
        # asking "what does this look like" actually is.
        #
        # Chain colours rather than one colour, because an all-surface figure
        # of a complex in a single colour is one undifferentiated blob: the
        # chains are exactly what the shape is made of. SURFACE_SHADING for the
        # documented reason — under flat lighting a surface renders as a blank
        # silhouette with no form at all.
        "surface-complex", "Surface (chain colours)", 1, chain_coloring=True,
        shading=SURFACE_SHADING,
        geometry=Geometry(surface_whole=True, surface_transparency=0),
        palette=Palette(chains=COLORBLIND_PALETTE, primary=ANTIGEN_WHITE),
    ),
    "epitope-surface": Preset(
        # The antibody-figure convention, and the style that went missing when
        # the presets were rebuilt: the antigen is a solid surface with the
        # epitope painted on it, the binder stays a ribbon so its fold and its
        # loops still read, and the contacting side chains come forward in a
        # bright accent.
        #
        # Asymmetric on purpose. Two surfaces hide both folds; two cartoons
        # cannot show a patch as a patch. Which side becomes the surface is
        # group B here — detection puts the second chain group there, and in
        # an antibody-antigen file the antigen is normally the second.
        # Version 2: the shading moved off FLAT_SHADING. A near-white surface
        # under `lighting flat` renders as a blank silhouette — see
        # SURFACE_SHADING — so the antigen arrived as an empty outline with
        # every pocket gone, which is the one thing the surface is drawn for.
        "epitope-surface", "Interface (group B as surface)", 2,
        requires_interface=True, group="Interface",
        shading=SURFACE_SHADING,
        geometry=Geometry(
            cartoon_xsection="oval", cartoon_thickness=0.45,
            cartoon_sides=20, cartoon_divisions=24, arrow_scale=1.4,
            sidechain_style="stick", stick_radius=0.24, stick_top=0,
            surface_side="b", surface_transparency=0,
            viewpoint="side-on",
        ),
        palette=Palette(
            # The binder carries the colour; the antigen is the neutral shape
            # the epitope is painted on.
            body_a=BINDER_BLUE, body_b=ANTIGEN_WHITE,
            interface_a=BINDER_BLUE, interface_b=EPITOPE_BLUE,
            sidechain=CONTACT_YELLOW, sidechain_byhetero=True,
            primary=ANTIGEN_WHITE,
        ),
    ),
    "surface-partner-a": Preset(
        # The same asymmetry the other way round. Which chain group becomes
        # the surface is a property of the file, not of the question: an
        # antibody-antigen deposition usually puts the antigen second, but a
        # receptor-ligand one often does not, and re-lettering chains to suit
        # a preset is not something a figure tool should make anyone do.
        # Everything except the side comes from epitope-surface.
        #
        # The two are named as the pair they are -- "group A as surface" and
        # "group B as surface" -- in the panel's own words for its two chain
        # lists. They were "surface on group A" against "epitope on surface",
        # which named the mechanics on one and the biology on the other, so
        # nothing in the menu said they were the same preset twice. "Epitope"
        # also presumed the antibody case, which is the presumption this
        # preset exists to avoid.
        "surface-partner-a", "Interface (group A as surface)", 1,
        requires_interface=True, group="Interface",
        shading=SURFACE_SHADING,
        geometry=Geometry(
            cartoon_xsection="oval", cartoon_thickness=0.45,
            cartoon_sides=20, cartoon_divisions=24, arrow_scale=1.4,
            sidechain_style="stick", stick_radius=0.24, stick_top=0,
            surface_side="a", surface_transparency=0,
            viewpoint="side-on",
        ),
        palette=Palette(
            body_a=ANTIGEN_WHITE, body_b=BINDER_BLUE,
            interface_a=EPITOPE_BLUE, interface_b=BINDER_BLUE,
            sidechain=CONTACT_YELLOW, sidechain_byhetero=True,
            primary=ANTIGEN_WHITE,
        ),
    ),
    "surface-translucent": Preset(
        # A surface you can see through, over a cartoon that stays readable.
        # It answers a different question from the solid one: not "what shape
        # does this partner present" but "where does the fold sit inside the
        # envelope" — which is what you want on a first look at a complex
        # nobody in the room has seen before.
        #
        # 55, not the 84 the interface halo uses. A halo frames a cartoon that
        # is the subject; here the surface *is* half the subject, and above
        # about 70 it stops reading as a surface at all.
        "surface-translucent", "Interface (translucent surface)", 1,
        requires_interface=True, group="Interface",
        shading=SURFACE_SHADING,
        geometry=Geometry(
            cartoon_xsection="oval", cartoon_thickness=0.40,
            cartoon_sides=20, cartoon_divisions=24, arrow_scale=1.4,
            sidechain_style="stick", stick_radius=0.24, stick_top=6,
            surface_side="b", surface_transparency=55,
            surface_over_cartoon=True,
            viewpoint="side-on",
        ),
        palette=Palette(
            # Not the white the solid styles use for the target. White washes
            # to white, so the envelope and the ribbon inside it would be the
            # same colour and only transparency would separate them — and a
            # light grey is barely better: seen through 55% of surface, the
            # ribbon lost most of its contrast and the first render came back
            # with the fold as a ghost. The slate is chosen for how it looks
            # *under* the surface, not on its own.
            body_a=BINDER_BLUE, body_b=SLATE_UNDER_SURFACE,
            interface_a=BINDER_BLUE, interface_b=EPITOPE_BLUE,
            # Yellow, as in the sibling surface styles, and for the same
            # reason twice over: the neutral dark grey disappeared against
            # both the blue ribbon and the shaded envelope behind it.
            sidechain=CONTACT_YELLOW, sidechain_byhetero=True,
            primary=SLATE_UNDER_SURFACE,
        ),
    ),
    "surface-epitope-map": Preset(
        # The figure a reader recognises before they read the caption: a white
        # target surface with one hot patch on it, and the binder as a ribbon
        # over the top. Same layout as epitope-surface, different question —
        # that one keeps both partners in the blue family and reads as "these
        # two are a pair"; this one puts the patch in a colour nothing else in
        # the figure uses and reads as "the epitope is *there*".
        #
        # Colours are the binder-loop family, so a plate that pairs this with
        # paratope-closeup is one figure rather than two.
        "surface-epitope-map", "Interface (epitope map)", 1,
        requires_interface=True, group="Interface",
        shading=SURFACE_SHADING,
        geometry=Geometry(
            cartoon_xsection="oval", cartoon_thickness=0.45,
            cartoon_sides=20, cartoon_divisions=24, arrow_scale=1.4,
            sidechain_style="stick", stick_radius=0.24, stick_top=0,
            surface_side="b", surface_transparency=0,
            viewpoint="side-on",
        ),
        palette=Palette(
            body_a=BINDER_LILAC, body_b=ANTIGEN_WHITE,
            interface_a=LOOP_ORANGE, interface_b=LOOP_ORANGE,
            sidechain="", sidechain_byhetero=True,
            primary=ANTIGEN_WHITE,
        ),
    ),
}


def get_preset(slug: str) -> Preset:
    try:
        return PRESETS[slug]
    except KeyError as error:
        raise ValueError(f"unknown MolCompose preset: {slug}") from error


def assign_chain_colors(chain_ids, palette=COLORBLIND_PALETTE) -> dict[str, str]:
    ordered = sorted(set(chain_ids))
    return {chain_id: palette[index % len(palette)] for index, chain_id in enumerate(ordered)}
