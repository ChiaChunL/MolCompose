"""DockQ and its CAPRI components for scoring a predicted complex against a reference.

Implements the measure of Basu & Wallner (PLoS ONE 2016, 10.1371/journal.pone.0161879),
as extended in DockQ v2 (Bioinformatics 2024, 10.1093/bioinformatics/btae586):

    DockQ = (Fnat + 1/(1 + (iRMSD/1.5)^2) + 1/(1 + (LRMSD/8.5)^2)) / 3

Fnat is the fraction of reference interface residue contacts reproduced by the
model, iRMSD the backbone RMSD over reference interface residues after optimal
superposition, and LRMSD the backbone RMSD of the smaller ("ligand") chain
group after superposing the larger ("receptor") group.

These are *reference-based* scores: unlike pLDDT, pDockQ or ipSAE they need an
experimental or otherwise trusted structure to compare against.
"""

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

BACKBONE_ATOMS = ("N", "CA", "C", "O")
FNAT_CUTOFF = 5.0        # Å, heavy-atom contact distance defining native contacts
INTERFACE_CUTOFF = 10.0  # Å, residue distance defining the interface for iRMSD
CLASH_CUTOFF = 2.0       # Å, below which an inter-chain residue pair is a clash

# How much of the reference interface the model-to-reference residue mapping has
# to cover before a DockQ score means anything. Below MINIMUM_COVERAGE the score
# is computed from so few residues that it says more about the mapping than
# about the model, and scoring is refused; between there and FULL_COVERAGE it is
# reported with the shortfall named. A correct alignment against a reference of
# the same construct covers essentially all of it, so anything under 90% is
# already worth showing the user.
MINIMUM_COVERAGE = 0.30
FULL_COVERAGE = 0.90

# Aligned-residue identity below which two chains are not the same protein, and
# the chain pairing itself — not the numbering — is what is wrong.
MINIMUM_IDENTITY = 0.30

# CAPRI quality bands (DockQ paper, Table 1).
CAPRI_BANDS = (
    (0.80, "High"),
    (0.49, "Medium"),
    (0.23, "Acceptable"),
)


@dataclass(frozen=True)
class DockQResult:
    dockq: float
    fnat: float
    fnonnat: float
    irmsd: float
    lrmsd: float
    native_contacts: int
    shared_contacts: int
    interface_residues: int
    capri_class: str
    # Reported alongside the DockQ terms so the output lines up with the
    # reference implementation's, which prints both. Neither enters the score.
    f1: float = 0.0
    clashes: int = 0


def f1_score(fnat: float, fnonnat: float) -> float:
    """Harmonic mean of precision and recall over interface contacts.

    Fnat is recall — the fraction of native contacts recovered. Fnonnat is the
    fraction of predicted contacts that are not native, so precision is its
    complement. F1 therefore costs nothing beyond the two terms DockQ already
    computes, and it penalises a model that recovers native contacts by
    predicting far too many, which Fnat alone rewards.
    """
    precision = 1.0 - fnonnat
    recall = fnat
    if precision + recall == 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def count_clashes(residues_a: dict, residues_b: dict, cutoff: float = CLASH_CUTOFF) -> int:
    """Inter-chain residue pairs closer than `cutoff` — steric clashes in a model.

    A quality flag rather than a score term: a predicted complex can reproduce
    native contacts and still be physically impossible, and DockQ itself does
    not notice.
    """
    limit = cutoff * cutoff
    clashes = 0
    for points_a in residues_a.values():
        if not points_a:
            continue
        coords_a = np.asarray(points_a, dtype=float)
        for points_b in residues_b.values():
            if not points_b:
                continue
            coords_b = np.asarray(points_b, dtype=float)
            deltas = coords_a[:, None, :] - coords_b[None, :, :]
            if (np.einsum("ijk,ijk->ij", deltas, deltas) <= limit).any():
                clashes += 1
    return clashes


def kabsch_rotation(mobile: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Optimal rotation superposing centred `mobile` onto centred `target`."""
    covariance = mobile.T @ target
    u, _, vt = np.linalg.svd(covariance)
    # Correct for a reflection so the result is a proper rotation.
    sign = np.sign(np.linalg.det(vt.T @ u.T))
    correction = np.diag([1.0, 1.0, sign])
    return vt.T @ correction @ u.T


def superpose(mobile: np.ndarray, target: np.ndarray):
    """Return (rotation, mobile_centre, target_centre) superposing mobile→target."""
    mobile = np.asarray(mobile, dtype=float)
    target = np.asarray(target, dtype=float)
    if mobile.shape != target.shape:
        raise ValueError(
            f"superposition needs matched point sets, got {mobile.shape} and {target.shape}"
        )
    if len(mobile) < 3:
        raise ValueError("superposition needs at least three matched atoms")
    mobile_centre = mobile.mean(axis=0)
    target_centre = target.mean(axis=0)
    rotation = kabsch_rotation(mobile - mobile_centre, target - target_centre)
    return rotation, mobile_centre, target_centre


def apply_superposition(points, rotation, mobile_centre, target_centre) -> np.ndarray:
    return (np.asarray(points, dtype=float) - mobile_centre) @ rotation.T + target_centre


def rmsd(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"RMSD needs matched point sets, got {a.shape} and {b.shape}")
    return float(np.sqrt(((a - b) ** 2).sum(axis=1).mean()))


def superposed_rmsd(mobile, target) -> float:
    """RMSD after optimal superposition of `mobile` onto `target`."""
    rotation, mobile_centre, target_centre = superpose(mobile, target)
    return rmsd(apply_superposition(mobile, rotation, mobile_centre, target_centre), target)


def fnat_scores(
    native_contacts: Iterable[tuple], model_contacts: Iterable[tuple]
) -> tuple[float, float, int, int]:
    """(Fnat, Fnonnat, native count, shared count) from two contact-pair sets."""
    native = set(native_contacts)
    model = set(model_contacts)
    if not native:
        raise ValueError(
            "the reference structure has no interface contacts; check the chain groups"
        )
    shared = native & model
    fnat = len(shared) / len(native)
    fnonnat = (len(model - native) / len(model)) if model else 0.0
    return fnat, fnonnat, len(native), len(shared)


def scale_rmsd(value: float, scale: float) -> float:
    return 1.0 / (1.0 + (value / scale) ** 2)


def dockq_score(fnat: float, irmsd: float, lrmsd: float) -> float:
    return (fnat + scale_rmsd(irmsd, 1.5) + scale_rmsd(lrmsd, 8.5)) / 3.0


def capri_class(dockq: float) -> str:
    for threshold, label in CAPRI_BANDS:
        if dockq >= threshold:
            return label
    return "Incorrect"


def evaluate(
    fnat: float,
    fnonnat: float,
    irmsd: float,
    lrmsd: float,
    native_contacts: int,
    shared_contacts: int,
    interface_residues: int,
    clashes: int = 0,
) -> DockQResult:
    score = dockq_score(fnat, irmsd, lrmsd)
    return DockQResult(
        dockq=score,
        fnat=fnat,
        fnonnat=fnonnat,
        irmsd=irmsd,
        lrmsd=lrmsd,
        native_contacts=native_contacts,
        shared_contacts=shared_contacts,
        interface_residues=interface_residues,
        capri_class=capri_class(score),
        f1=f1_score(fnat, fnonnat),
        clashes=clashes,
    )


def residue_contacts(
    residues_a: dict, residues_b: dict, cutoff: float = FNAT_CUTOFF
) -> set[tuple]:
    """Residue-pair contacts between two {key: [xyz, ...]} groups."""
    limit = cutoff * cutoff
    contacts = set()
    for key_a, points_a in residues_a.items():
        if not points_a:
            continue
        coords_a = np.asarray(points_a, dtype=float)
        for key_b, points_b in residues_b.items():
            if not points_b:
                continue
            coords_b = np.asarray(points_b, dtype=float)
            deltas = coords_a[:, None, :] - coords_b[None, :, :]
            if (np.einsum("ijk,ijk->ij", deltas, deltas) <= limit).any():
                contacts.add((key_a, key_b))
    return contacts


def interface_keys(
    residues_a: dict, residues_b: dict, cutoff: float = INTERFACE_CUTOFF
) -> tuple[set, set]:
    """Residues of each group within `cutoff` of the other group."""
    contacts = residue_contacts(residues_a, residues_b, cutoff)
    return {pair[0] for pair in contacts}, {pair[1] for pair in contacts}


@dataclass(frozen=True)
class Coverage:
    """How much of the reference interface the residue mapping actually reached."""

    mapped: int
    total: int

    @property
    def fraction(self) -> float:
        return self.mapped / self.total if self.total else 0.0

    @property
    def is_scorable(self) -> bool:
        return self.total > 0 and self.fraction >= MINIMUM_COVERAGE

    @property
    def is_complete(self) -> bool:
        return self.fraction >= FULL_COVERAGE


def interface_coverage(interface_keys_wanted, model_residues: dict) -> Coverage:
    """Reference interface residues that the mapped model actually provides.

    `model_residues` is expected to be keyed in the reference's key space, i.e.
    already relabelled through the sequence alignment.
    """
    wanted = set(interface_keys_wanted)
    return Coverage(
        mapped=sum(1 for key in wanted if key in model_residues), total=len(wanted)
    )


def coverage_report(coverage: Coverage) -> str:
    """One line naming how many reference interface residues the model supplied."""
    return (
        f"{coverage.mapped}/{coverage.total} reference interface residues "
        f"({coverage.fraction:.0%}) have an aligned counterpart in the model"
    )


def matched_backbone(reference: dict, model: dict, keys) -> tuple[np.ndarray, np.ndarray]:
    """Paired backbone coordinates for residues present in both structures."""
    reference_points, model_points = [], []
    for key in sorted(keys):
        ref_atoms = reference.get(key)
        model_atoms = model.get(key)
        if not ref_atoms or not model_atoms:
            continue
        for name in BACKBONE_ATOMS:
            if name in ref_atoms and name in model_atoms:
                reference_points.append(ref_atoms[name])
                model_points.append(model_atoms[name])
    if len(reference_points) < 3:
        raise ValueError(
            "fewer than three backbone atoms could be matched between the reference "
            "and the model; check that chain IDs and residue numbering correspond"
        )
    return np.asarray(model_points, dtype=float), np.asarray(reference_points, dtype=float)
