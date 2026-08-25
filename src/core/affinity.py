"""Binding-affinity prediction for protein-protein complexes (PRODIGY IC-NIS model).

Implements the contacts-based predictor of Vangone & Bonvin (eLife 2015,
10.7554/eLife.07454), as served by PRODIGY (Xue et al., Bioinformatics 2016,
10.1093/bioinformatics/btw514). Coefficients, residue-class tables and the
reference maximum-accessibility values are taken from the reference
implementation (`prodigy-prot`) and cross-checked numerically against it —
see tests/unit/core/test_affinity.py and the molfig-bench cross-validation.

Model in one line:

    dG = -0.09459*CC - 0.10007*AC + 0.19577*PP - 0.22671*AP
         + 0.18681*%NIS_apolar + 0.13810*%NIS_charged - 15.9433

where the four terms are counts of intermolecular residue-residue contacts
(any heavy-atom pair within 5.5 A) binned by residue class, and %NIS are the
class percentages among solvent-accessible residues of the complex
(relative SASA >= 5%).

Method note — SASA engine: the contact terms reproduce the reference exactly,
but %NIS depends on the solvent-accessibility engine. MolCompose uses the
native ChimeraX `measure sasa`, whereas the reference implementation uses
freesasa with ProtOr radii. Measured across three benchmark complexes this
shifts %NIS by roughly 2-4 percentage points and dG by 0.1-0.6 kcal/mol,
well inside the model's own reported RMSE of 1.89 kcal/mol. The predicted
value is therefore comparable to, but not bit-identical with, PRODIGY.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass

# Residue classes for contact binning (apolar / charged / polar).
IC_CLASS = {
    "ALA": "A", "ARG": "C", "ASN": "P", "ASP": "C", "CYS": "A",
    "GLN": "P", "GLU": "C", "GLY": "A", "HIS": "C", "ILE": "A",
    "LEU": "A", "LYS": "C", "MET": "A", "PHE": "A", "PRO": "A",
    "SER": "P", "THR": "P", "TRP": "A", "TYR": "A", "VAL": "A",
}

# Residue classes for the non-interacting surface (ProtorP convention).
NIS_CLASS = {
    "ALA": "A", "ARG": "C", "ASN": "P", "ASP": "C", "CYS": "P",
    "GLN": "P", "GLU": "C", "GLY": "A", "HIS": "P", "ILE": "A",
    "LEU": "A", "LYS": "C", "MET": "A", "PHE": "A", "PRO": "A",
    "SER": "P", "THR": "P", "TRP": "P", "TYR": "P", "VAL": "A",
}

# Reference maximum solvent accessibility per residue type (A^2).
MAX_ASA = {
    "ALA": 107.95, "ARG": 238.76, "ASN": 143.94, "ASP": 140.39, "CYS": 134.28,
    "GLN": 178.50, "GLU": 172.25, "GLY": 80.10, "HIS": 182.88, "ILE": 175.12,
    "LEU": 178.63, "LYS": 200.81, "MET": 194.15, "PHE": 199.48, "PRO": 136.13,
    "SER": 116.50, "THR": 139.27, "TRP": 249.36, "TYR": 212.76, "VAL": 151.44,
}

CONTACT_CUTOFF = 5.5
ACCESSIBILITY_THRESHOLD = 0.05
GAS_CONSTANT = 0.0019858775  # kcal / (mol K)

BINS = ("AA", "AC", "AP", "CC", "CP", "PP")


@dataclass(frozen=True)
class AffinityResult:
    delta_g: float           # kcal/mol
    kd: float                # M, at `temperature`
    temperature: float       # degrees Celsius
    bins: dict[str, int]
    nis_apolar: float        # percent
    nis_charged: float       # percent
    contact_pairs: int


def classify_contacts(residue_pairs: Iterable[tuple[str, str]]) -> dict[str, int]:
    """Bin intermolecular residue-residue contacts by residue class pair."""
    bins = dict.fromkeys(BINS, 0)
    for name_a, name_b in residue_pairs:
        class_a = IC_CLASS.get(name_a)
        class_b = IC_CLASS.get(name_b)
        if class_a is None or class_b is None:
            continue  # non-standard residue: outside the model's training set
        bins["".join(sorted((class_a, class_b)))] += 1
    return bins


def relative_accessibility(residue_name: str, sasa: float) -> float | None:
    """SASA as a fraction of the residue type's reference maximum."""
    maximum = MAX_ASA.get(residue_name)
    if maximum is None:
        return None
    return sasa / maximum


def nis_percentages(
    residue_sasa: Iterable[tuple[str, float]],
    threshold: float = ACCESSIBILITY_THRESHOLD,
) -> tuple[float, float]:
    """Percent apolar and percent charged among solvent-accessible residues."""
    counts = {"A": 0, "C": 0, "P": 0}
    for name, sasa in residue_sasa:
        rsa = relative_accessibility(name, sasa)
        if rsa is None or rsa < threshold:
            continue
        residue_class = NIS_CLASS.get(name)
        if residue_class is not None:
            counts[residue_class] += 1
    total = sum(counts.values())
    if total == 0:
        raise ValueError(
            "no solvent-accessible standard residues found; cannot compute the "
            "non-interacting surface composition"
        )
    return 100.0 * counts["A"] / total, 100.0 * counts["C"] / total


def binding_free_energy(bins: dict[str, int], nis_apolar: float, nis_charged: float) -> float:
    """PRODIGY IC-NIS regression (kcal/mol)."""
    return (
        -0.09459 * bins.get("CC", 0)
        + -0.10007 * bins.get("AC", 0)
        + 0.19577 * bins.get("PP", 0)
        + -0.22671 * bins.get("AP", 0)
        + 0.18681 * nis_apolar
        + 0.13810 * nis_charged
        + -15.9433
    )


def dg_to_kd(delta_g: float, temperature: float = 25.0) -> float:
    """Dissociation constant (M) from binding free energy at `temperature` (C)."""
    return math.exp(delta_g / (GAS_CONSTANT * (temperature + 273.15)))


def predict_affinity(
    residue_pairs: Iterable[tuple[str, str]],
    residue_sasa: Iterable[tuple[str, float]],
    temperature: float = 25.0,
) -> AffinityResult:
    """Full IC-NIS prediction from contacts and complex-state residue SASA."""
    pairs = list(residue_pairs)
    if not pairs:
        raise ValueError(
            "no intermolecular contacts found; binding affinity needs a contacting "
            f"interface (contacts are counted within {CONTACT_CUTOFF} Å)"
        )
    bins = classify_contacts(pairs)
    nis_apolar, nis_charged = nis_percentages(residue_sasa)
    delta_g = binding_free_energy(bins, nis_apolar, nis_charged)
    return AffinityResult(
        delta_g=delta_g,
        kd=dg_to_kd(delta_g, temperature),
        temperature=temperature,
        bins=bins,
        nis_apolar=nis_apolar,
        nis_charged=nis_charged,
        contact_pairs=len(pairs),
    )
