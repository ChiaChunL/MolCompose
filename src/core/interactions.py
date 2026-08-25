"""Typed non-covalent interaction detection across a protein-protein interface.

Rules follow the conventions used by PLIP (Adasme et al., NAR 2021/2025) and
Arpeggio (Jubb et al., JMB 2017). Every threshold is an explicit, adjustable
parameter so the exact rule set lands in the reproducible command recipe
rather than being hidden in the implementation.
"""

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from .interfaces import ResidueKey

KINDS = ("salt-bridge", "hydrophobic", "pi-stacking", "cation-pi", "disulfide")

# Formally charged side-chain groups (Barlow & Thornton, JMB 1983 convention).
POSITIVE_ATOMS = {
    "ARG": ("NE", "NH1", "NH2"),
    "LYS": ("NZ",),
    "HIS": ("ND1", "NE2"),
}
NEGATIVE_ATOMS = {
    "ASP": ("OD1", "OD2"),
    "GLU": ("OE1", "OE2"),
}

# Apolar side-chain carbons; curated per residue so no bond graph is needed.
HYDROPHOBIC_ATOMS = {
    "ALA": ("CB",),
    "VAL": ("CB", "CG1", "CG2"),
    "LEU": ("CB", "CG", "CD1", "CD2"),
    "ILE": ("CB", "CG1", "CG2", "CD1"),
    "MET": ("CB", "CG", "CE"),
    "PRO": ("CB", "CG", "CD"),
    "PHE": ("CB", "CG", "CD1", "CD2", "CE1", "CE2", "CZ"),
    "TRP": ("CB", "CG", "CD1", "CD2", "CE2", "CE3", "CZ2", "CZ3", "CH2"),
    "TYR": ("CB", "CG", "CD1", "CD2", "CE1", "CE2"),
}

# Aromatic rings; TRP contributes both rings of its indole system.
AROMATIC_RINGS = {
    "PHE": (("CG", "CD1", "CD2", "CE1", "CE2", "CZ"),),
    "TYR": (("CG", "CD1", "CD2", "CE1", "CE2", "CZ"),),
    "HIS": (("CG", "ND1", "CD2", "CE1", "NE2"),),
    "TRP": (
        ("CG", "CD1", "NE1", "CE2", "CD2"),
        ("CD2", "CE2", "CE3", "CZ2", "CZ3", "CH2"),
    ),
}

# Cation centres for cation-pi: guanidinium/ammonium groups.
CATION_ATOMS = {
    "ARG": ("NE", "NH1", "NH2"),
    "LYS": ("NZ",),
}


@dataclass(frozen=True)
class AtomRecord:
    residue: ResidueKey
    name: str
    element: int
    xyz: tuple[float, float, float]


@dataclass(frozen=True)
class InteractionParams:
    salt_bridge: float = 4.0
    hydrophobic: float = 4.5
    pi_stacking: float = 5.5
    pi_angle_tolerance: float = 30.0
    cation_pi: float = 6.0
    disulfide: float = 2.5


@dataclass(frozen=True, order=True)
class Interaction:
    kind: str
    a: ResidueKey
    b: ResidueKey
    distance: float
    detail: str = ""
    atom_a: str = ""
    atom_b: str = ""

    def atomspec_a(self) -> str:
        return f"{self.a.atomspec}@{self.atom_a}" if self.atom_a else self.a.atomspec

    def atomspec_b(self) -> str:
        return f"{self.b.atomspec}@{self.atom_b}" if self.atom_b else self.b.atomspec


def _by_residue(records: Iterable[AtomRecord]) -> dict[ResidueKey, list[AtomRecord]]:
    grouped: dict[ResidueKey, list[AtomRecord]] = {}
    for record in records:
        grouped.setdefault(record.residue, []).append(record)
    return grouped


def _named(atoms, names) -> list[AtomRecord]:
    wanted = set(names)
    return [atom for atom in atoms if atom.name in wanted]


def _closest(atoms_a, atoms_b) -> tuple[float, str, str] | None:
    """Nearest atom pair as (distance, name_a, name_b)."""
    best = None
    for atom_a in atoms_a:
        for atom_b in atoms_b:
            distance = float(np.linalg.norm(np.array(atom_a.xyz) - np.array(atom_b.xyz)))
            if best is None or distance < best[0]:
                best = (distance, atom_a.name, atom_b.name)
    return best


def ring_geometry(atoms) -> tuple[np.ndarray, np.ndarray] | None:
    """Centroid and unit normal of a planar ring, or None if underdetermined."""
    if len(atoms) < 3:
        return None
    coords = np.array([atom.xyz for atom in atoms], dtype=float)
    centroid = coords.mean(axis=0)
    # Best-fit plane normal = smallest singular vector of the centred coordinates.
    _, _, vectors = np.linalg.svd(coords - centroid)
    normal = vectors[-1]
    norm = np.linalg.norm(normal)
    if norm == 0:
        return None
    return centroid, normal / norm


def _ring_atoms(residue: ResidueKey, atoms) -> list[AtomRecord]:
    names = {name for ring in AROMATIC_RINGS.get(residue.name, ()) for name in ring}
    return _named(atoms, names)


def _rings(residue: ResidueKey, atoms) -> list[tuple[np.ndarray, np.ndarray]]:
    found = []
    for names in AROMATIC_RINGS.get(residue.name, ()):
        ring_atoms = _named(atoms, names)
        if len(ring_atoms) < len(names):
            continue  # incomplete ring (e.g. truncated side chain)
        geometry = ring_geometry(ring_atoms)
        if geometry is not None:
            found.append(geometry)
    return found


def ring_angle(normal_a, normal_b) -> float:
    """Angle in degrees between two ring planes (0 = coplanar, 90 = perpendicular)."""
    cosine = float(np.clip(abs(np.dot(normal_a, normal_b)), 0.0, 1.0))
    return float(np.degrees(np.arccos(cosine)))


def _salt_bridges(residues_a, residues_b, params) -> list[Interaction]:
    found = []
    for key_a, atoms_a in residues_a.items():
        for key_b, atoms_b in residues_b.items():
            for donor, acceptor in (
                (POSITIVE_ATOMS.get(key_a.name), NEGATIVE_ATOMS.get(key_b.name)),
                (NEGATIVE_ATOMS.get(key_a.name), POSITIVE_ATOMS.get(key_b.name)),
            ):
                if not donor or not acceptor:
                    continue
                closest = _closest(_named(atoms_a, donor), _named(atoms_b, acceptor))
                if closest and closest[0] <= params.salt_bridge:
                    distance, name_a, name_b = closest
                    found.append(
                        Interaction(
                            "salt-bridge", key_a, key_b, distance,
                            f"{name_a}–{name_b}", name_a, name_b,
                        )
                    )
                    break
    return found


def _hydrophobic(residues_a, residues_b, params) -> list[Interaction]:
    found = []
    for key_a, atoms_a in residues_a.items():
        names_a = HYDROPHOBIC_ATOMS.get(key_a.name)
        if not names_a:
            continue
        for key_b, atoms_b in residues_b.items():
            names_b = HYDROPHOBIC_ATOMS.get(key_b.name)
            if not names_b:
                continue
            closest = _closest(_named(atoms_a, names_a), _named(atoms_b, names_b))
            if closest and closest[0] <= params.hydrophobic:
                distance, name_a, name_b = closest
                found.append(
                    Interaction(
                        "hydrophobic", key_a, key_b, distance,
                        f"{name_a}–{name_b}", name_a, name_b,
                    )
                )
    return found


def _pi_stacking(residues_a, residues_b, params) -> list[Interaction]:
    found = []
    for key_a, atoms_a in residues_a.items():
        rings_a = _rings(key_a, atoms_a)
        if not rings_a:
            continue
        for key_b, atoms_b in residues_b.items():
            rings_b = _rings(key_b, atoms_b)
            if not rings_b:
                continue
            best = None
            for centroid_a, normal_a in rings_a:
                for centroid_b, normal_b in rings_b:
                    distance = float(np.linalg.norm(centroid_a - centroid_b))
                    if distance > params.pi_stacking:
                        continue
                    angle = ring_angle(normal_a, normal_b)
                    if angle <= params.pi_angle_tolerance:
                        geometry = "parallel"
                    elif angle >= 90.0 - params.pi_angle_tolerance:
                        geometry = "T-shaped"
                    else:
                        continue  # intermediate geometry: not a defined stack
                    if best is None or distance < best[0]:
                        best = (distance, f"{geometry} ({angle:.0f}°)")
            if best:
                # Anchor the display line on the nearest ring-atom pair.
                anchor = _closest(
                    _ring_atoms(key_a, atoms_a), _ring_atoms(key_b, atoms_b)
                )
                found.append(
                    Interaction(
                        "pi-stacking", key_a, key_b, best[0], best[1],
                        anchor[1] if anchor else "", anchor[2] if anchor else "",
                    )
                )
    return found


def _cation_pi(residues_a, residues_b, params) -> list[Interaction]:
    found = []
    for first, second, flipped in (
        (residues_a, residues_b, False),
        (residues_b, residues_a, True),
    ):
        for cation_key, cation_atoms in first.items():
            names = CATION_ATOMS.get(cation_key.name)
            if not names:
                continue
            charged = _named(cation_atoms, names)
            if not charged:
                continue
            centre = np.array([atom.xyz for atom in charged], dtype=float).mean(axis=0)
            for ring_key, ring_atoms in second.items():
                best = None
                for centroid, _normal in _rings(ring_key, ring_atoms):
                    distance = float(np.linalg.norm(centre - centroid))
                    if distance <= params.cation_pi and (best is None or distance < best):
                        best = distance
                if best is not None:
                    anchor = _closest(charged, _ring_atoms(ring_key, ring_atoms))
                    cation_atom = anchor[1] if anchor else ""
                    ring_atom = anchor[2] if anchor else ""
                    if flipped:
                        key_a, key_b = ring_key, cation_key
                        atom_a, atom_b = ring_atom, cation_atom
                    else:
                        key_a, key_b = cation_key, ring_key
                        atom_a, atom_b = cation_atom, ring_atom
                    found.append(
                        Interaction(
                            "cation-pi", key_a, key_b, best,
                            f"{cation_key.name}{cation_key.number}→{ring_key.name}"
                            f"{ring_key.number}", atom_a, atom_b,
                        )
                    )
    return found


def _disulfides(residues_a, residues_b, params) -> list[Interaction]:
    found = []
    for key_a, atoms_a in residues_a.items():
        if key_a.name != "CYS":
            continue
        for key_b, atoms_b in residues_b.items():
            if key_b.name != "CYS":
                continue
            closest = _closest(_named(atoms_a, ("SG",)), _named(atoms_b, ("SG",)))
            if closest and closest[0] <= params.disulfide:
                distance, name_a, name_b = closest
                found.append(
                    Interaction(
                        "disulfide", key_a, key_b, distance,
                        f"{name_a}–{name_b}", name_a, name_b,
                    )
                )
    return found


_DETECTORS = {
    "salt-bridge": _salt_bridges,
    "hydrophobic": _hydrophobic,
    "pi-stacking": _pi_stacking,
    "cation-pi": _cation_pi,
    "disulfide": _disulfides,
}


def detect_interactions(
    group_a: Iterable[AtomRecord],
    group_b: Iterable[AtomRecord],
    kinds: Iterable[str] = KINDS,
    params: InteractionParams | None = None,
) -> tuple[Interaction, ...]:
    """Typed interactions between two disjoint interface groups, stably ordered."""
    requested = tuple(kinds)
    unknown = [kind for kind in requested if kind not in _DETECTORS]
    if unknown:
        raise ValueError(
            f"unknown interaction type(s): {', '.join(sorted(unknown))}; "
            f"choose from {', '.join(KINDS)}"
        )
    params = params or InteractionParams()
    residues_a = _by_residue(group_a)
    residues_b = _by_residue(group_b)
    if set(residues_a) & set(residues_b):
        raise ValueError("interaction groups must not overlap")

    found: list[Interaction] = []
    for kind in requested:
        found.extend(_DETECTORS[kind](residues_a, residues_b, params))
    return tuple(sorted(found))


def summarize(interactions: Iterable[Interaction]) -> dict[str, int]:
    """Counts per interaction type, always covering every known kind."""
    counts = dict.fromkeys(KINDS, 0)
    for interaction in interactions:
        counts[interaction.kind] += 1
    return counts


def describe(interactions: Iterable[Interaction]) -> list[dict]:
    """One record per interaction, naming the residues on both sides.

    ``summarize`` answers "how many of each kind", which is what a caption
    needs; this answers "between which residues", which is what anyone
    reasoning about the interface needs. Reporting only the counts left the
    identities recoverable solely from the display commands' atom specs — a
    recorded agent session read ``/A:27@NZ`` and called it Arg27, when 1BRS
    has Lys27 there. Naming the residues removes the guess.
    """
    return [
        {
            "kind": interaction.kind,
            "a": f"{interaction.a.name} {interaction.a.chain_id}:{interaction.a.number}",
            "b": f"{interaction.b.name} {interaction.b.chain_id}:{interaction.b.number}",
            "distance": round(interaction.distance, 2),
            **({"detail": interaction.detail} if interaction.detail else {}),
        }
        for interaction in sorted(interactions)
    ]
