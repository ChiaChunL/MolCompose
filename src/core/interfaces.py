"""Immutable interface-analysis data types and spatial-bin contact algorithm."""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import product
from math import floor


@dataclass(frozen=True, order=True)
class ResidueKey:
    model_id: str
    chain_id: str
    number: int
    insertion_code: str
    name: str
    atomspec: str


@dataclass(frozen=True)
class AtomPoint:
    residue: ResidueKey
    xyz: tuple[float, float, float]
    # Van der Waals radius, carried only for the `vdw` criterion. Zero means
    # "not supplied", which the distance criteria never look at.
    radius: float = 0.0


@dataclass(frozen=True, order=True)
class ContactPair:
    a: ResidueKey
    b: ResidueKey


@dataclass(frozen=True)
class InterfaceResult:
    group_a: tuple[ResidueKey, ...]
    group_b: tuple[ResidueKey, ...]
    contacts: tuple[ContactPair, ...]
    cutoff: float


def _cell(xyz, cell_size):
    return tuple(floor(value / cell_size) for value in xyz)


# ChimeraX's own contact default, and the convention this follows: two atoms
# touch when their van der Waals spheres come within 0.4 A of overlapping.
DEFAULT_VDW_OVERLAP = -0.4
# The widest pair of van der Waals radii among protein heavy atoms is about
# 2 x 1.9 A, so no contact can span more than this however the overlap is set.
# It is the spatial-binning cell size, not a criterion.
_VDW_SEARCH_LIMIT = 5.0


def _detect_by_overlap(
    group_a: Iterable[AtomPoint],
    group_b: Iterable[AtomPoint],
    overlap: float,
) -> InterfaceResult:
    """Contact when r_a + r_b - distance >= overlap.

    Binning uses a fixed cell rather than the cutoff, because the reach of a
    pair depends on the two radii and not on `overlap` alone.
    """
    if not -2.0 <= overlap <= 2.0:
        raise ValueError("VDW overlap must be between -2.0 and 2.0 Å")
    a_points, b_points = tuple(group_a), tuple(group_b)
    a_residues = {point.residue for point in a_points}
    b_residues = {point.residue for point in b_points}
    if a_residues & b_residues:
        raise ValueError("Group A and Group B must not overlap")
    if any(point.radius <= 0 for point in a_points + b_points):
        raise ValueError(
            "the VDW criterion needs van der Waals radii, which this structure "
            "did not supply"
        )

    bins = {}
    for point_b in b_points:
        bins.setdefault(_cell(point_b.xyz, _VDW_SEARCH_LIMIT), []).append(point_b)

    contacts = set()
    offsets = tuple(product((-1, 0, 1), repeat=3))
    for point_a in a_points:
        base = _cell(point_a.xyz, _VDW_SEARCH_LIMIT)
        for offset in offsets:
            neighbor = tuple(base[index] + offset[index] for index in range(3))
            for point_b in bins.get(neighbor, ()):
                reach = point_a.radius + point_b.radius - overlap
                distance_squared = sum(
                    (point_a.xyz[index] - point_b.xyz[index]) ** 2 for index in range(3)
                )
                if distance_squared <= reach * reach:
                    contacts.add(ContactPair(point_a.residue, point_b.residue))

    ordered = tuple(sorted(contacts))
    return InterfaceResult(
        group_a=tuple(sorted({pair.a for pair in ordered})),
        group_b=tuple(sorted({pair.b for pair in ordered})),
        contacts=ordered,
        cutoff=overlap,
    )


def detect_interface(
    group_a: Iterable[AtomPoint],
    group_b: Iterable[AtomPoint],
    cutoff: float = 4.5,
    criterion: str = "heavy",
) -> InterfaceResult:
    """Residue pairs in contact across two groups.

    `heavy` and `cbeta` compare centre-to-centre distance against `cutoff`.
    `vdw` compares the *overlap* of the two atoms' van der Waals spheres
    against `cutoff`, which is then an overlap in angstroms and normally
    negative: -0.4 means "within 0.4 A of touching". A fixed distance treats a
    sulphur and a carbon alike, and they are not alike.
    """
    if criterion == "vdw":
        return _detect_by_overlap(group_a, group_b, cutoff)
    if not 2.0 <= cutoff <= 10.0:
        raise ValueError("distance cutoff must be between 2.0 and 10.0 Å")
    a_points, b_points = tuple(group_a), tuple(group_b)
    a_residues = {point.residue for point in a_points}
    b_residues = {point.residue for point in b_points}
    if a_residues & b_residues:
        raise ValueError("Group A and Group B must not overlap")

    bins = {}
    for point_b in b_points:
        bins.setdefault(_cell(point_b.xyz, cutoff), []).append(point_b)

    cutoff_squared = cutoff * cutoff
    contacts = set()
    offsets = tuple(product((-1, 0, 1), repeat=3))
    for point_a in a_points:
        base = _cell(point_a.xyz, cutoff)
        for offset in offsets:
            neighbor = tuple(base[index] + offset[index] for index in range(3))
            for point_b in bins.get(neighbor, ()):
                distance_squared = sum(
                    (point_a.xyz[index] - point_b.xyz[index]) ** 2 for index in range(3)
                )
                if distance_squared <= cutoff_squared:
                    contacts.add(ContactPair(point_a.residue, point_b.residue))

    ordered_contacts = tuple(sorted(contacts))
    return InterfaceResult(
        group_a=tuple(sorted({pair.a for pair in ordered_contacts})),
        group_b=tuple(sorted({pair.b for pair in ordered_contacts})),
        contacts=ordered_contacts,
        cutoff=cutoff,
    )
