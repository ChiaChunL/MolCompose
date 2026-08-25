"""Per-residue MM/PBSA decomposition, as gmx_MMPBSA writes it.

Read, never produced: gmx_MMPBSA writes `FINAL_DECOMP_MMPBSA.dat`, MolCompose
loads it, exactly as it loads Pythia's mutation scan. No GROMACS dependency
and no compiled extension.

Only the DELTAS section is of interest. The file also carries the complex, the
receptor and the ligand separately, and each of those is an absolute energy of
one state — the binding contribution is the difference, which is what DELTAS
holds. A loader that took the complex section would report numbers an order of
magnitude larger that mean something else entirely.

The sign is the file's own: negative where a residue contributes favourably.
It is not normalised to match the mutational ΔΔG convention, because the number
a user reads in the panel has to be the number in their file. What MolCompose
orients instead is the colour ramp — see `core/coloring.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# `R:A:LYS:27` — group, chain, residue name, residue number. The group letter
# is gmx_MMPBSA's receptor/ligand split, not a chain: both sides can hold
# several chains, and the letter after it is the one that matters.
_RESIDUE = re.compile(r"^([RL]):([^:]+):([A-Z0-9]{1,4}):(-?\d+)$")

# The row's columns are six components of three statistics each, in the order
# the two header rows declare. TOTAL is the last component, so its average is
# column 16 counting from zero and its standard error is column 18.
_TOTAL_AVERAGE = 16
_TOTAL_STANDARD_ERROR = 18

DELTAS = "DELTAS:"
# A run configured for both solvation models writes the decomposition twice,
# each under its own heading.
# Two files, two spellings of the same fact. The decomposition announces each
# solvation model once, above its whole block:
#     Energy Decomposition Analysis (All units kcal/mol): Generalized Born model
# while FINAL_RESULTS writes a bare heading, `GENERALIZED BORN:` -- which is
# what `_SOLVATION_MODEL` below matches, for `parse_totals`.
_DECOMP_MODEL = re.compile(
    r"^Energy Decomposition Analysis .*:\s*(.+?)\s+model\s*$"
)
# What a caller may type, against what the file says. Spelled out rather than
# prefix-matched: "gb" shares no prefix with "Generalized Born".
SOLVATION_ALIASES = {
    "gb": "generalized born", "gbsa": "generalized born",
    "generalized born": "generalized born",
    "pb": "poisson boltzmann", "pbsa": "poisson boltzmann",
    "poisson boltzmann": "poisson boltzmann",
}
TOTAL_DECOMPOSITION = "Total Energy Decomposition:"


@dataclass(frozen=True)
class ResidueEnergy:
    """One residue's contribution to binding, in kcal/mol."""

    group: str
    chain: str
    residue_name: str
    number: int
    energy: float
    standard_error: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.residue_name}{self.chain}{self.number}"


class DecompositionError(ValueError):
    """The file is not a per-residue decomposition this can read."""


def parse_chain_map(text: str) -> dict[str, str]:
    """`A:A,B:D` — the file's chain letter, then the model's.

    Required rather than guessed. GROMACS relabels chains when a system is
    built, so a decomposition of PDB 1BRS arrives with chains A and B where the
    structure has A and D. Guessing by order would attach barstar's energies to
    whatever the model happens to call B, silently and plausibly.
    """
    pairs = {}
    for piece in str(text).split(","):
        piece = piece.strip()
        if not piece:
            continue
        if piece.count(":") != 1:
            raise DecompositionError(
                f"chain map entries look like FILE:MODEL, separated by commas: {piece}"
            )
        source, target = (part.strip() for part in piece.split(":"))
        if not source or not target:
            raise DecompositionError(
                f"chain map entries look like FILE:MODEL, separated by commas: {piece}"
            )
        if source in pairs:
            raise DecompositionError(f"chain {source} is mapped twice")
        pairs[source] = target
    if not pairs:
        raise DecompositionError("the chain map is empty")
    return pairs


def _solvation_models(lines: list[str]) -> list[tuple[str, int]]:
    """(model name, line index of its DELTAS section), in file order.

    A run configured for both `gb` and `pb` writes the whole decomposition
    twice, under a GENERALIZED BORN heading and then a POISSON BOLTZMANN one.
    """
    found = []
    model = None
    for index, line in enumerate(lines):
        heading = _DECOMP_MODEL.match(line.strip())
        if heading:
            model = heading.group(1)
        elif line.strip() == DELTAS and model is not None:
            found.append((model, index))
    return found


def solvation_models(path) -> list[str]:
    """Which solvation models a decomposition file carries, in file order.

    Asked before loading rather than discovered by failing to. A run
    configured for both writes the whole decomposition twice, and `load`
    refuses to pick — correctly, since the two disagree by several kcal/mol.
    But a refusal is only useful to someone who can then choose, so the panel
    needs to know there is a choice before it makes the call.
    """
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return []
    return [name for name, _index in _solvation_models(lines)]


def file_chains(path, solvation: str | None = None) -> list[str]:
    """The chain letters the decomposition uses, receptor first.

    gmx_MMPBSA names them by group rather than by the structure's own letters
    — `R:A` and `L:B` whatever the deposited entry called them — so a chain
    map is required to load one. Reporting the file's side of that map lets
    the panel propose a pairing instead of pre-filling one structure's answer
    for every structure.
    """
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return []
    try:
        rows = _deltas_total_rows(text.splitlines(), solvation)
    except DecompositionError:
        return []
    seen = []
    for row in rows:
        fields = row.split()
        if not fields:
            continue
        parts = fields[0].split(":")
        if len(parts) >= 2 and parts[1] and parts[1] not in seen:
            seen.append(parts[1])
    return seen


def _deltas_total_rows(lines: list[str], solvation: str | None = None) -> list[str]:
    """The rows of the DELTAS section's total decomposition.

    The section repeats for the complex, the receptor and the ligand before
    DELTAS, and within each it repeats for total, sidechain and backbone. Only
    one of the nine is the binding contribution per residue.

    A file may also carry the whole thing twice, once per solvation model.
    Until 2026-08-21 this took the first DELTAS it found, which on a GB+PB
    run is the GB one and is never stated anywhere the reader can see it -- a
    figure captioned MM/PBSA painted from MM/GBSA numbers. `parse_totals` in
    this same module has always distinguished the two, and reports an eight
    kcal/mol gap between them on barnase-barstar, so the choice is not
    cosmetic. Both present and no choice made is now refused rather than
    guessed.
    """
    models = _solvation_models(lines)
    if len(models) > 1:
        names = ", ".join(name for name, _ in models)
        if solvation is None:
            raise DecompositionError(
                f"this decomposition carries {len(models)} solvation models "
                f"({names}); say which one to read. They are different "
                "numbers -- the gap between GB and PB is the error bar on the "
                "solvation treatment alone -- so reading whichever came first "
                "would put an unlabelled choice in the figure."
            )
        heading = SOLVATION_ALIASES.get(solvation.strip().lower())
        if heading is None:
            raise DecompositionError(
                f"unknown solvation model {solvation!r}; use "
                f"{' or '.join(sorted(set(SOLVATION_ALIASES.values())))}"
            )
        wanted = [i for name, i in models if name.lower() == heading]
        if not wanted:
            raise DecompositionError(
                f"no {heading} section in this decomposition; it has {names}"
            )
        start = wanted[0]
    elif models:
        if solvation is not None:
            heading = SOLVATION_ALIASES.get(solvation.strip().lower())
            if heading is not None and models[0][0].lower() != heading:
                raise DecompositionError(
                    f"no {heading} section in this decomposition; it has "
                    f"{models[0][0]}"
                )
        start = models[0][1]
    else:
        start = None
    if start is None:
        try:
            start = next(i for i, line in enumerate(lines) if line.strip() == DELTAS)
        except StopIteration:
            raise DecompositionError(
                "no DELTAS section: this looks like a decomposition of one state "
                "rather than of binding. gmx_MMPBSA writes DELTAS when the run "
                "has a receptor and a ligand to subtract."
            ) from None
    for index in range(start + 1, len(lines)):
        if lines[index].strip().startswith(TOTAL_DECOMPOSITION):
            # Two header rows: the component names, then the statistic names.
            return lines[index + 3:]
        if lines[index].strip().endswith("Energy Decomposition:"):
            break
    raise DecompositionError("the DELTAS section has no total energy decomposition")


def parse(text: str, solvation: str | None = None) -> tuple[ResidueEnergy, ...]:
    """Per-residue binding contributions, in the file's own sign convention.

    `solvation` names which model to read -- "gb" or "pb" -- and is required
    only when the file carries both.
    """
    rows = _deltas_total_rows(text.splitlines(), solvation)
    energies = []
    for line in rows:
        stripped = line.strip()
        if not stripped:
            break
        fields = stripped.split(",")
        match = _RESIDUE.match(fields[0].strip())
        if match is None:
            break
        if len(fields) <= _TOTAL_STANDARD_ERROR:
            raise DecompositionError(
                f"row for {fields[0]} has {len(fields)} columns, and the total "
                f"energy is in column {_TOTAL_STANDARD_ERROR + 1}"
            )
        group, chain, name, number = match.groups()
        try:
            energy = float(fields[_TOTAL_AVERAGE])
            error = float(fields[_TOTAL_STANDARD_ERROR])
        except ValueError as failure:
            raise DecompositionError(
                f"row for {fields[0]} does not hold numbers where the total "
                f"energy should be: {failure}"
            ) from failure
        energies.append(
            ResidueEnergy(group, chain, name, int(number), energy, error)
        )
    if not energies:
        raise DecompositionError("the DELTAS total decomposition has no residues")
    return tuple(energies)


def load(path, solvation: str | None = None) -> tuple[ResidueEnergy, ...]:
    from pathlib import Path

    return parse(Path(path).read_text(), solvation)


def remap(
    energies: tuple[ResidueEnergy, ...], chain_map: dict[str, str]
) -> tuple[ResidueEnergy, ...]:
    """Rewrite the file's chain letters as the model's.

    A chain the map does not mention is dropped rather than passed through: a
    map is a statement about which chains this file describes, and quietly
    keeping the rest would put unmapped residues into the structure under
    whatever letter the simulation happened to use.
    """
    from dataclasses import replace

    return tuple(
        replace(energy, chain=chain_map[energy.chain])
        for energy in energies
        if energy.chain in chain_map
    )


def numbering_offset(
    energies: tuple[ResidueEnergy, ...], residue_names: dict
) -> int | None:
    """A constant shift that would make the file and the structure agree.

    The signature of the repaired-versus-deposited mistake, and the reason a
    "how much disagrees" threshold misses it. Repair adds the residues a
    crystal did not resolve, so from the first gap onward every number moves
    by the same amount — and the *fraction* that disagrees then depends on
    where the gaps are, not on how wrong the pairing is. A file three residues
    out can match most of the structure by coincidence of composition.

    Returning the shift lets the error say what happened rather than how much
    of it happened. Only a shift that fixes essentially everything counts: a
    handful of accidental matches at some offset is not a numbering shift, it
    is two unrelated proteins.
    """
    if not energies:
        return None
    for shift in range(1, 26):
        for offset in (shift, -shift):
            checked = agreed = 0
            for energy in energies:
                actual = residue_names.get((energy.chain, energy.number + offset))
                if actual is None:
                    continue  # shifted off the end of the structure
                checked += 1
                if actual.upper() == energy.residue_name.upper():
                    agreed += 1
            # Both conditions matter. Requiring agreement among the residues
            # that landed somewhere is what makes a shift detectable at all,
            # since a shifted file always runs off one end of the structure;
            # requiring that most of them land is what stops a shift of 20
            # "agreeing" on the two residues it still overlaps.
            if checked >= 0.8 * len(energies) and agreed >= 0.95 * checked:
                return offset
    return None


def verify_residue_names(
    energies: tuple[ResidueEnergy, ...], residue_names: dict
) -> tuple[str, ...]:
    """Where the file and the structure disagree about what a residue is.

    `residue_names` is keyed by (chain, number) and holds three-letter codes,
    the same shape `core/ddg.py` verifies wild types against. A mismatch means
    the chain map is wrong or the trajectory is not this structure, and both
    produce a figure that is confidently mislabelled.
    """
    problems = []
    for energy in energies:
        actual = residue_names.get((energy.chain, energy.number))
        if actual is None:
            problems.append(
                f"{energy.chain}:{energy.number} is not in the structure"
            )
        elif actual.upper() != energy.residue_name.upper():
            problems.append(
                f"{energy.chain}:{energy.number} is {actual.upper()} in the "
                f"structure and {energy.residue_name.upper()} in the file"
            )
    return tuple(problems)


def by_residue(energies: tuple[ResidueEnergy, ...]) -> dict[tuple[str, int], float]:
    """Keyed the way the colouring and the sequence exporter want it."""
    return {(energy.chain, energy.number): energy.energy for energy in energies}


def ranked(
    energies: tuple[ResidueEnergy, ...], top: int = 0
) -> tuple[ResidueEnergy, ...]:
    """Most favourable contribution first — most negative, in this convention."""
    order = sorted(energies, key=lambda energy: energy.energy)
    return tuple(order[:top] if top else order)

# The overall binding energy lives in a sibling file, not in the decomposition.
RESULTS_FILE = "FINAL_RESULTS_MMPBSA.dat"

_SOLVATION_MODEL = re.compile(r"^(GENERALIZED BORN|POISSON BOLTZMANN):\s*$")

_DELTA_TOTAL = re.compile(r"^\s*[\u0394\u2206]TOTAL\s+(-?\d+\.?\d*)\s+")


@dataclass(frozen=True)
class BindingTotal:
    """One solvation model's overall ΔTOTAL, in kcal/mol."""

    model: str
    total: float

    @property
    def label(self) -> str:
        return "MM/GBSA" if self.model.startswith("GENERALIZED") else "MM/PBSA"


def parse_totals(text: str) -> tuple[BindingTotal, ...]:
    """Each solvation model's ΔTOTAL, in the order the file reports them.

    Read only to be *reported*, never to be used as the interface's ΔG. An
    MM/PBSA total carries no entropy term and moves with the internal
    dielectric and the salt model: on barnase-barstar this run gives -80.75
    (GB) and -72.93 (PB) against an experimental -19, and the eight kcal/mol
    between the two models is the honest error bar on the solvation treatment
    alone. Printing both, with the caveat, is more use than printing neither.
    """
    totals = []
    model = None
    for line in text.splitlines():
        heading = _SOLVATION_MODEL.match(line)
        if heading:
            model = heading.group(1)
            continue
        # The complex, receptor and ligand sections each end in a TOTAL; only
        # the delta -- written with a Δ -- is the binding energy.
        match = _DELTA_TOTAL.match(line)
        if match and model:
            totals.append(BindingTotal(model, float(match.group(1))))
            model = None
    return tuple(totals)


def totals_beside(path) -> tuple[BindingTotal, ...]:
    """The overall energies from the results file next to a decomposition."""
    from pathlib import Path as _Path

    results = _Path(path).parent / RESULTS_FILE
    if not results.is_file():
        return ()
    try:
        return parse_totals(results.read_text())
    except (OSError, ValueError):
        return ()
