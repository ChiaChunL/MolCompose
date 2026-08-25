"""pLDDT confidence handling for predicted-structure figures.

Different prediction tools write pLDDT into the B-factor column on different
scales (AlphaFold Server / AFDB / ColabFold: 0-100; ESMFold API output: 0-1).
Applying a 0-100 palette to a 0-1 file silently paints the whole model as
"very low confidence" — this module makes the scale decision explicit,
logged, and machine-checkable.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass

from .interfaces import ResidueKey

# AlphaFold Database confidence colors (very low < 50 <= low < 70 <= confident
# < 90 <= very high), expressed as ChimeraX value:color palette stops.
#
# The bands are discrete, and each colour is repeated to keep them that way.
# ChimeraX interpolates linearly between palette stops, so the four-stop form
# this used until 2026-08-16 —
#
#     0,#FF7D45:50,#FFDB13:70,#65CBF3:90,#0053D6
#
# — painted a continuous ramp rather than AlphaFold's four bands. A residue at
# pLDDT 60 came out #B2D383, half way from yellow to cyan, where the
# convention says plain yellow; on the 1BRS example the whole 50-70
# stretch simply disappeared into the gradient. Anyone who knows the AlphaFold
# colours reads such a figure wrong, and reads it confidently, which is worse
# than an obviously broken one.
#
# The epsilon before each boundary is the standard way to spell a step in a
# palette that only knows how to interpolate: it leaves a ramp one hundredth
# of a unit wide, far narrower than any pLDDT value's precision. It has to
# scale with the axis, so 0.01 on the 0-100 scale is 0.0001 on 0-1.
_AF_BANDS = ((50, "#FF7D45"), (70, "#FFDB13"), (90, "#65CBF3"), (None, "#0053D6"))


def _banded_palette(top: float, epsilon: float) -> str:
    """AlphaFold's bands as stops that interpolate only inside each epsilon."""
    scale = top / 100.0
    stops, low = [], 0.0
    for boundary, colour in _AF_BANDS:
        high = top if boundary is None else boundary * scale
        stops.append(f"{low:g},{colour}")
        stops.append(f"{high - epsilon if boundary is not None else high:g},{colour}")
        low = high
    return ":".join(stops)


AF_PALETTE_SPECS = {
    "0-100": _banded_palette(100.0, 0.01),
    "0-1": _banded_palette(1.0, 0.0001),
}


def key_stops(scale: str) -> tuple[tuple[str, str], ...]:
    """`(colour, label)` pairs for the colour key, built from `_AF_BANDS`.

    Derived from the same table as the palette rather than written out beside
    it. A key is only useful if it is the scale the figure was actually
    painted with, and a second hand-maintained copy of four colours is a
    promise to eventually disagree — which is the worse failure of the two,
    because a wrong key is read confidently.

    Each colour is emitted **twice**, carrying its lower and upper bound, so
    four bands produce eight stops labelled 0, 50, 50, 70, 70, 90, 90, 100.
    Drawn with `colorTreatment blended` this puts a number at every band
    boundary, which is how the AlphaFold bands are defined and how AFDB itself
    states them.

    The doubling is what makes blending safe. ChimeraX blends between
    consecutive stops, and both stops of a band are the same colour, so each
    band is flat; consecutive bands share a position, so the change between
    them is a hard edge. The bar stays as discrete as the structure.

    Read `chimerax/color_key/model.py`: with `blended` the labels are drawn at
    the stop positions, and only with `distinct` are they centred on blocks.
    That is the whole reason this shape exists. Two earlier attempts at
    boundary labels failed because they kept `distinct`:

      key #FF7D45:0 #FFDB13:50 #65CBF3:70 #0053D6:90 :100   -> "Expected a
          keyword". A bare `:label` is legal only after a palette *name*.
      key alphafold :0 :50 :70 :90 :100                     -> parses, but
          ChimeraX's built-in `alphafold` colormap is FF0000, FFA500, FFFF00,
          6495ED, 0000FF, not the AFDB colours painted here.

    From those two this module concluded on 2026-08-18 that boundary labels
    were impossible and labelled each band with its range instead. That was
    wrong: the constraint was never "one label per block", it was `distinct`.

    Band widths become proportional to their value ranges, so 0-50 takes half
    the bar and 90-100 a tenth. That is a consequence of numeric labels, and
    it is honest: the bar reads as the linear axis it is.
    """
    top = 100.0 if scale == "0-100" else 1.0
    factor = top / 100.0
    pairs, low = [], 0.0
    for boundary, colour in _AF_BANDS:
        high = top if boundary is None else boundary * factor
        pairs.append((colour, f"{low:g}"))
        pairs.append((colour, f"{high:g}"))
        low = high
    return tuple(pairs)


LOW_CONFIDENCE_CUTOFF = {"0-100": 50.0, "0-1": 0.5}


class NotAPredictedStructure(ValueError):
    """Raised when B-factors are temperature factors, not pLDDT."""


def detect_plddt_scale(values: Iterable[float]) -> str:
    observed = tuple(values)
    if not observed:
        raise ValueError("no B-factor/pLDDT values found in the model")
    if all(value == 0.0 for value in observed):
        raise NotAPredictedStructure(
            "B-factor/pLDDT values are uniformly zero; this is a placeholder "
            "field, not prediction confidence"
        )
    maximum = max(observed)
    if maximum <= 1.0:
        return "0-1"
    if maximum <= 100.0:
        return "0-100"
    raise ValueError(
        f"B-factor column does not look like pLDDT (maximum {maximum:.1f} > 100); "
        "this may be an experimental structure with true temperature factors"
    )


def band_color(value: float, scale: str = "0-100") -> str:
    """The AlphaFold band a pLDDT value falls in, as a hex colour.

    From `_AF_BANDS`, the same table the palette is generated from, because a
    second copy of four colours is a promise to eventually disagree — and the
    figure and its key disagreeing is the failure this file already documents
    twice. The palette's epsilon-repeated stops make ChimeraX paint these
    bands flat, so what this returns is what the structure shows.

    Bands are half-open: 70 is "confident", not "low". The boundary belongs to
    the band above it, as AlphaFold defines them.
    """
    factor = 100.0 if scale == "0-1" else 1.0
    normalised = value * factor
    for boundary, colour in _AF_BANDS:
        if boundary is None or normalised < boundary:
            return colour
    return _AF_BANDS[-1][1]


def band_label(value: float, scale: str = "0-100") -> str:
    """A name for the band, for anything that lists regions rather than paints."""
    factor = 100.0 if scale == "0-1" else 1.0
    normalised = value * factor
    low = 0
    for boundary, _colour in _AF_BANDS:
        if boundary is None:
            return f"pLDDT {low}-100"
        if normalised < boundary:
            return f"pLDDT {low}-{boundary}"
        low = boundary
    return "pLDDT"


def palette_spec(scale: str) -> str:
    return AF_PALETTE_SPECS[scale]


@dataclass(frozen=True)
class ConfidenceReport:
    scale: str
    residues: tuple[tuple[ResidueKey, float], ...]

    @property
    def normalized_mean(self) -> float:
        factor = 100.0 if self.scale == "0-1" else 1.0
        return sum(value for _, value in self.residues) * factor / len(self.residues)

    def low_confidence_keys(self) -> tuple[ResidueKey, ...]:
        cutoff = LOW_CONFIDENCE_CUTOFF[self.scale]
        return tuple(key for key, value in self.residues if value < cutoff)


def build_report(residue_values) -> ConfidenceReport:
    residues = tuple(residue_values)
    scale = detect_plddt_scale(tuple(value for _, value in residues))
    return ConfidenceReport(scale=scale, residues=residues)


# pDockQ sigmoid fit from Bryant, Pozzati & Elofsson, Nat Commun 13, 1265 (2022).
# Canonical protocol: interface residues by Cβ–Cβ <= 8 Å (Cα for Gly).
_PDOCKQ_L, _PDOCKQ_X0, _PDOCKQ_K, _PDOCKQ_B = 0.724, 152.611, 0.052, 0.018


def interface_plddt(report: ConfidenceReport, interface_keys) -> float | None:
    """Mean pLDDT (0-100 scale) over the given interface residues."""
    wanted = set(interface_keys)
    factor = 100.0 if report.scale == "0-1" else 1.0
    values = [value * factor for key, value in report.residues if key in wanted]
    if not values:
        return None
    return sum(values) / len(values)


def pdockq_score(mean_interface_plddt: float, contact_pairs: int) -> float | None:
    """pDockQ from mean interface pLDDT (0-100) and residue contact-pair count."""
    if contact_pairs <= 0:
        return None
    x = mean_interface_plddt * math.log10(contact_pairs)
    return _PDOCKQ_L / (1 + math.exp(-_PDOCKQ_K * (x - _PDOCKQ_X0))) + _PDOCKQ_B
