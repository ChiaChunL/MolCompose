"""Per-residue fluctuation from an MD trajectory, as `gmx rmsf` writes it.

Read, never produced, like the MM/PBSA decomposition beside it. What it adds is
the one thing every other metric here is blind to: all of them describe a
single conformation, and this describes how much that conformation moves.

The file is Grace's `.xvg` — comment lines beginning `#`, formatting commands
beginning `@`, then two columns. The first is not a residue number and not a
running index either: `gmx rmsf -res` restarts its numbering at each chain, so
a two-chain selection reads 1..110 then 1..89. Taken as one sequence, the
second chain's fluctuations land on the first chain's opening residues — a
figure that is entirely plausible and entirely wrong. `blocks` splits on the
restart and the caller names one chain per block.
"""

from __future__ import annotations

from dataclasses import dataclass

# The unit gmx writes. Ångström is what every other length in this tool is in,
# and a B-factor column is Å² by convention, so the values are converted once
# on the way in rather than in each place that draws them.
NM_TO_ANGSTROM = 10.0


@dataclass(frozen=True)
class Fluctuation:
    """One residue's RMS fluctuation, in Ångström."""

    index: int
    rmsf: float


class FluctuationError(ValueError):
    """The file is not an `.xvg` this can read."""


def parse(text: str) -> tuple[Fluctuation, ...]:
    """Fluctuations in Å, indexed as the file indexes them.

    The y-axis label is checked rather than assumed: `gmx` writes RMSD, radius
    of gyration and half a dozen other quantities into files of exactly this
    shape, and a fluctuation scale painted from an RMSD curve would look
    entirely plausible and mean nothing.
    """
    unit = None
    is_residue_axis = None
    values = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("@"):
            lowered = stripped.lower()
            if "yaxis" in lowered and "label" in lowered:
                unit = "nm" if "(nm)" in lowered else lowered.split("label", 1)[1]
            if "xaxis" in lowered and "label" in lowered:
                is_residue_axis = "residue" in lowered or "atom" in lowered
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        try:
            values.append(Fluctuation(int(float(parts[0])), float(parts[1])))
        except ValueError:
            continue
    if not values:
        raise FluctuationError("no two-column data rows in the .xvg file")
    if is_residue_axis is False:
        raise FluctuationError(
            "this .xvg is indexed by something other than residue or atom; "
            "run 'gmx rmsf -res' so there is one value per residue"
        )
    if unit is None or "nm" not in str(unit):
        raise FluctuationError(
            f"expected an RMS fluctuation in nm and the y axis says {unit!r}; "
            "gmx writes RMSD and other curves in this same format, and one of "
            "those painted as fluctuation would look plausible and mean nothing"
        )
    return tuple(
        Fluctuation(value.index, value.rmsf * NM_TO_ANGSTROM) for value in values
    )


def load(path) -> tuple[Fluctuation, ...]:
    from pathlib import Path

    return parse(Path(path).read_text())


def blocks(values: tuple[Fluctuation, ...]) -> tuple[tuple[Fluctuation, ...], ...]:
    """Split where the index restarts — one block per chain.

    `gmx rmsf -res` numbers residues within each chain, so a two-chain
    selection comes out 1..110 then 1..89 rather than 1..199. Read as one
    sequence, barstar's fluctuations land on barnase's first 89 residues: a
    figure that is entirely plausible and entirely wrong, which is why this
    splits rather than concatenating.
    """
    found: list[list[Fluctuation]] = []
    for value in values:
        if not found or value.index <= found[-1][-1].index:
            found.append([value])
        else:
            found[-1].append(value)
    return tuple(tuple(block) for block in found)


def by_residue(
    values: tuple[Fluctuation, ...],
    chain_residues: tuple[tuple[str, tuple[int, ...]], ...],
) -> dict[tuple[str, int], float]:
    """Keyed by (chain, residue number), against the structure's own chains.

    `chain_residues` is an ordered `(chain_id, residue_numbers)` per block, in
    the order the selection was written — the caller states it, the way the
    MM/PBSA chain map is stated, because nothing in the file says which chain
    is which. Every block has to match its chain's length: a file whose blocks
    do not line up is refused rather than trimmed, since a fluctuation on the
    wrong residue is worse than no fluctuation.
    """
    found = blocks(values)
    if len(found) != len(chain_residues):
        raise FluctuationError(
            f"the file holds {len(found)} chain(s) and {len(chain_residues)} "
            "were named; `gmx rmsf -res` restarts its numbering per chain, so "
            "name one chain per block, in the order the selection was written"
        )
    placed = {}
    for block, (chain_id, numbers) in zip(found, chain_residues, strict=True):
        if len(block) != len(numbers):
            raise FluctuationError(
                f"chain {chain_id} has {len(numbers)} residues and its block "
                f"of the file has {len(block)}. Usually this means MD repaired "
                "the structure before it ran and the file is being loaded onto "
                "the deposited one instead: load it onto the structure the "
                "simulation used. If that is not it, the chains were named in "
                "another order."
            )
        for value, number in zip(block, numbers, strict=True):
            placed[(chain_id, number)] = value.rmsf
    return placed
