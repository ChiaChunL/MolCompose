"""Map a per-residue metric onto a colour scale.

Used to paint interface residues by a quantity — predicted ΔΔG, buried area —
rather than by chain. The scale is chosen from the data, not from a documented
range, for a specific reason: PythiaStudio documents Pythia ΔΔG as spanning
−5 to 5, and a real export of it spans −11.7 to +36.4. Hard-coding the
documented ends would flatten every residue beyond them into one colour, and the
residues past the end are exactly the ones worth looking at.

Two scale shapes, because the metrics differ in kind:

* **diverging** for signed quantities like ΔΔG, where zero is meaningful and the
  two directions mean opposite things (stabilising versus disruptive). The
  midpoint is pinned at zero and the arms are made symmetric, so a colour means
  the same magnitude on either side.
* **sequential** for non-negative quantities like buried area, where only
  magnitude carries meaning.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# ColorBrewer RdBu, 5-class, reversed so red is the positive arm: positive ΔΔG
# means the substitution costs binding, and red for that is the convention every
# ΔΔG paper uses.
#
# The previous hand-mixed ramp had both arms too pale to separate. Its light red
# sat 70 RGB units from the interface preset's body colour, so a mildly
# destabilising residue and an ordinary stretch of chain A were the same colour;
# its dark red sat 105 from the interface colour, so the most destabilising
# residue looked like ordinary interface. Both ends are now saturated enough to
# be read as values rather than as tints, and the preset bodies have moved off
# this axis to leave it to the ramp.
# The scales a metric can be drawn on. `diverging-negative` is the same ramp
# read the other way round, for a quantity whose favourable end is negative.
SCALE_KINDS = ("diverging", "diverging-negative", "sequential")

DIVERGING = ("#2166AC", "#92C5DE", "#F7F7F7", "#F4A582", "#B2182B")
# ColorBrewer Reds, 5-class. A heat ramp: this scale carries buried area,
# where more is more, and "hot spot" is the name of the thing it is measuring.
# Reds rather than OrRd because OrRd's middle sits ~35 degrees from the
# salt-bridge line colour drawn across it, and Reds keeps its saturated end
# near hue 0, a clear 50 degrees away.
SEQUENTIAL = ("#FEE5D9", "#FCAE91", "#FB6A4A", "#DE2D26", "#A50F15")

# Clip to the 2nd/98th percentile rather than the extremes: a single outlier
# would otherwise own an entire arm of the scale and compress everything else.
DEFAULT_LOW_QUANTILE = 0.02
DEFAULT_HIGH_QUANTILE = 0.98

# The ramp is interpolated between its anchor colours rather than stepped
# through them, because every metric on it -- buried area, ddG, MM/PBSA
# contribution, RMSF -- is continuous, and five blocks claim a structure the
# data does not have. pLDDT is the exception and is drawn elsewhere: its four
# bands are AlphaFold's own and are categorical.
#
# Quantised to this many levels rather than left truly continuous, because
# `group_by_color` exists to collapse a colouring into one command per colour
# and a per-residue colour would make that one command per residue -- 586 of
# them on a whole-structure scan. At 64 levels the steps are under 1% of the
# ramp and invisible at any print size, and the command count is bounded.
RAMP_LEVELS = 64


@dataclass(frozen=True)
class ColorScale:
    kind: str            # "diverging" | "sequential"
    low: float
    high: float
    colors: tuple[str, ...]

    def position(self, value: float) -> float:
        """Where `value` falls on the ramp, clamped to [0, 1]."""
        span = self.high - self.low
        if span <= 0:
            return 0.5
        return max(0.0, min(1.0, (value - self.low) / span))

    def bucket(self, value: float) -> int:
        """The anchor colour nearest `value`.

        Retained for callers that need a discrete band -- the sequence-viewer
        export among them -- and as the definition of which anchors an
        interpolated colour sits between.
        """
        index = int(self.position(value) * len(self.colors))
        return max(0, min(len(self.colors) - 1, index))

    def color_for(self, value: float) -> str:
        """The interpolated ramp colour for `value`.

        Anchors are spread evenly across [low, high], so with five of them
        they sit at 0, 0.25, 0.5, 0.75 and 1. A value between two anchors gets
        their mix; a value at an anchor gets that anchor exactly, which is
        what keeps the key honest -- the numbers printed under the bar are
        positions a residue can actually be painted.
        """
        steps = len(self.colors) - 1
        if steps <= 0:
            return self.colors[0]
        place = round(self.position(value) * RAMP_LEVELS) / RAMP_LEVELS * steps
        lower = min(int(place), steps - 1)
        return _mix(self.colors[lower], self.colors[lower + 1], place - lower)

    @property
    def legend(self) -> tuple[tuple[str, str], ...]:
        """(colour, value label) per anchor, for the Log.

        Anchor values rather than band ranges, because the ramp interpolates:
        a band range would describe a colouring this scale no longer produces.
        """
        span = self.high - self.low
        steps = len(self.colors) - 1
        if steps <= 0:
            return ((self.colors[0], f"{self.low:+.2f}"),)
        return tuple(
            (colour, f"{self.low + span * index / steps:+.2f}")
            for index, colour in enumerate(self.colors)
        )

    @property
    def key_labels(self) -> tuple[tuple[str, str], ...]:
        """(colour, label) pairs for the colour key, one per ramp anchor.

        Each anchor is emitted once, at its own position, and the key is drawn
        with `colorTreatment blended`: ChimeraX puts a label at every stop and
        blends between them, which is the same ramp the structure is painted
        with. Until the ramp was interpolated this method emitted every colour
        twice, at both bounds of its band, so each blend ran between a colour
        and itself and the bar stayed as stepped as the structure. Both halves
        moved together; a gradient bar over a stepped structure would be the
        same lie in the other direction.

        Labels are the anchor values, not band edges. With five anchors on a
        diverging scale the middle one is zero by construction, so the neutral
        point is printed rather than inferred.
        """
        decimals = 0 if max(abs(self.low), abs(self.high)) >= 20 else 1
        sign = "+" if self.kind.startswith("diverging") else ""
        span = self.high - self.low
        steps = len(self.colors) - 1

        def label(value: float) -> str:
            text = f"{value:{sign}.{decimals}f}"
            # -0.0 and +0.0 are the same number and neither is how it is
            # written; the middle anchor of a symmetric scale hits this.
            return "0" if float(text) == 0 else text

        return tuple(
            (colour, label(self.low + span * index / steps))
            for index, colour in enumerate(self.colors)
        ) if steps > 0 else ((self.colors[0], label(self.low)),)


def _mix(start: str, end: str, fraction: float) -> str:
    """`start` and `end` blended in sRGB, as a #rrggbb string.

    sRGB rather than a perceptual space: these two ramps are ColorBrewer's,
    whose anchors were already chosen so that even steps between them read as
    even, and interpolating them anywhere else would undo that work.
    """
    if fraction <= 0:
        return start
    if fraction >= 1:
        return end
    a = tuple(int(start[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(end[i:i + 2], 16) for i in (1, 3, 5))
    blended = (round(x + (y - x) * fraction) for x, y in zip(a, b, strict=True))
    return "#" + "".join(f"{channel:02X}" for channel in blended)


def quantile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated quantile; pure Python, no numpy."""
    if not values:
        raise ValueError("no values to take a quantile of")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def build_scale(
    values: Iterable[float],
    kind: str = "diverging",
    low_quantile: float = DEFAULT_LOW_QUANTILE,
    high_quantile: float = DEFAULT_HIGH_QUANTILE,
) -> ColorScale:
    numbers = [float(value) for value in values]
    if not numbers:
        raise ValueError("cannot build a colour scale from no values")
    if kind not in SCALE_KINDS:
        raise ValueError(
            f"scale kind must be one of {', '.join(SCALE_KINDS)}: {kind}"
        )

    low = quantile(numbers, low_quantile)
    high = quantile(numbers, high_quantile)
    if kind in ("diverging", "diverging-negative"):
        # Symmetric about zero, so equal magnitudes of opposite sign read as
        # equally strong. An asymmetric scale would make a mild stabilising
        # prediction look as saturated as a severe disruptive one.
        reach = max(abs(low), abs(high))
        if reach == 0:
            reach = 1.0
        low, high = -reach, reach
        # Two metrics carry kcal/mol and mean opposite things by the same
        # sign. Mutational ΔΔG is positive where a residue matters, because
        # removing it costs; MM/PBSA decomposition is negative where a residue
        # matters, because keeping it earns. On one ramp red would mean
        # "important" on one panel and "unfavourable" on the next.
        #
        # The fix is not to flip the stored number -- what the panel prints
        # has to be what is in the user's file -- but to orient the ramp, so
        # that the end which means "matters more" is the same colour either
        # way. The key still shows the real values, signs included, which is
        # what keeps a colour being a value.
        colors = DIVERGING[::-1] if kind == "diverging-negative" else DIVERGING
    else:
        low = min(low, 0.0)
        if high <= low:
            high = low + 1.0
        colors = SEQUENTIAL
    return ColorScale(kind=kind, low=low, high=high, colors=colors)


def assign(
    entries: Iterable[tuple[str, float]], scale: ColorScale
) -> tuple[tuple[str, str], ...]:
    """[(atomspec, value)] -> [(atomspec, colour)] under `scale`."""
    return tuple((spec, scale.color_for(value)) for spec, value in entries)


def group_by_color(assignments: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """Collect atomspecs per colour, so one command can paint each band."""
    grouped: dict[str, list[str]] = {}
    for spec, color in assignments:
        grouped.setdefault(color, []).append(spec)
    return grouped
