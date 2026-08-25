"""Consume predicted mutation effects (ΔΔG) from external predictors.

MolCompose does not run ΔΔG predictors: they carry heavy dependencies
(PyTorch/CUDA for Pythia and Pythia-PPI), proprietary licences (FoldX), or
large installations (Rosetta). Instead this module parses their *output* and
maps it onto the structure, exactly as the predicted-structure workflow
consumes AlphaFold files rather than running AlphaFold.

Because different predictors disagree substantially — FoldX and Rosetta
predictions have been reported to overlap for only 12-25% of mutations — the
records carry their source so several predictors can be compared side by side.

Supported inputs:

* **tabular** (`.csv`/`.tsv`): a header naming chain/position/wild-type/mutant/
  ddG columns, under any of several common spellings.
* **pythia** (`*_pred_mask.txt`): lines of ``<WT><position><MUT> <energy>``.
  Positions are *sequential indices over the parsed structure*, not PDB residue
  numbers, so a caller-supplied index→residue map is required.
* **pythia-ppi**: PythiaStudio's binding-ΔΔG export, as either the CSV
  (`Mutation,Chain,Position,DDG`) or the workbook
  (`Mutant Name | Wildtype | Chain | Position | Mutation | ΔΔG (kcal/mol) |
  Effect`). Both carry an explicit chain, which is what makes them usable on a
  complex; see `parse_pythia_ppi`.

Sign convention, per the PythiaStudio documentation: **positive ΔΔG means
reduced binding**, with > +1 kcal/mol reported as destabilising, −0.5 to +1 as
neutral, and < −0.5 as enhanced binding. It is not inferred from the data, and
the module refuses formats whose convention it cannot state.
"""

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .xlsx import read_records

FORMATS = ("tabular", "pythia", "pythia-ppi")

# PythiaStudio's own thresholds, used to label an effect when the file does not.
PPI_DESTABILISING = 1.0
PPI_STABILISING = -0.5

# Mutant name: <wild type>_<chain>_<position>_<mutant>, e.g. H_A_102_P.
_PPI_NAME = re.compile(r"^([A-Z])_([A-Za-z0-9])_(-?\d+)_([A-Z])$")

_PYTHIA_LINE = re.compile(r"^\s*([A-Z])(\d+)([A-Z])\s+(-?[\d.eE+]+)\s*$")

# Accepted spellings for tabular columns, lower-cased.
_COLUMNS = {
    "chain": ("chain", "chain_id", "chainid"),
    "position": ("position", "pos", "resnum", "residue", "resi", "res_num"),
    "wild_type": ("wt", "wild_type", "wildtype", "from", "ref"),
    "mutant": ("mut", "mutant", "to", "alt"),
    "ddg": ("ddg", "ddG", "delta_delta_g", "score", "energy", "prediction"),
}


@dataclass(frozen=True, order=True)
class MutationEffect:
    chain: str
    position: int
    wild_type: str
    mutant: str
    ddg: float
    source: str = ""

    @property
    def label(self) -> str:
        return f"{self.wild_type}{self.chain}{self.position}{self.mutant}"


def _resolve_columns(fieldnames) -> dict[str, str]:
    lowered = {name.strip().lower(): name for name in fieldnames if name}
    resolved = {}
    for key, spellings in _COLUMNS.items():
        for spelling in spellings:
            if spelling in lowered:
                resolved[key] = lowered[spelling]
                break
    missing = [key for key in ("position", "mutant", "ddg") if key not in resolved]
    if missing:
        raise ValueError(
            f"tabular ΔΔG file is missing column(s) for {', '.join(missing)}; "
            f"found headers: {', '.join(sorted(lowered))}"
        )
    return resolved


def parse_tabular(text: str, source: str = "") -> tuple[MutationEffect, ...]:
    sample = text[:2048]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("tabular ΔΔG file has no header row")
    columns = _resolve_columns(reader.fieldnames)
    effects = []
    for row in reader:
        try:
            effects.append(
                MutationEffect(
                    chain=(row.get(columns.get("chain", ""), "") or "").strip(),
                    position=int(str(row[columns["position"]]).strip()),
                    wild_type=(row.get(columns.get("wild_type", ""), "") or "").strip().upper(),
                    mutant=str(row[columns["mutant"]]).strip().upper(),
                    ddg=float(row[columns["ddg"]]),
                    source=source,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed rows rather than failing the whole file
    if not effects:
        raise ValueError("no usable rows found in the tabular ΔΔG file")
    return tuple(effects)


def parse_pythia(
    text: str, index_map: dict[int, tuple[str, int]], source: str = "pythia"
) -> tuple[MutationEffect, ...]:
    """Parse Pythia `*_pred_mask.txt`; `index_map` is 1-based index → (chain, resnum)."""
    effects = []
    unmapped = set()
    for line in text.splitlines():
        match = _PYTHIA_LINE.match(line)
        if not match:
            continue
        wild_type, index, mutant, value = match.groups()
        located = index_map.get(int(index))
        if located is None:
            unmapped.add(int(index))
            continue
        chain, number = located
        effects.append(
            MutationEffect(chain, number, wild_type, mutant, float(value), source)
        )
    if not effects:
        raise ValueError(
            "no Pythia predictions could be mapped onto the structure; Pythia "
            "positions are sequential indices, so the model must match the PDB "
            "file that was scored"
        )
    return tuple(effects)


def _ppi_row(row: dict, source: str) -> MutationEffect | None:
    """One PythiaStudio row, from either the CSV or the workbook layout."""
    # The CSV calls the mutant *name* "Mutation"; the workbook uses that header
    # for the substituted residue and names the identifier "Mutant Name". Read
    # the identifier first and fall back, so neither layout needs its own path.
    name = (row.get("Mutant Name") or row.get("Mutation") or "").strip()
    match = _PPI_NAME.match(name)
    chain = (row.get("Chain") or "").strip()
    position = (row.get("Position") or "").strip()

    if match:
        wild_type, name_chain, name_position, mutant = match.groups()
        chain = chain or name_chain
        position = position or name_position
    else:
        # No parsable identifier: fall back to the workbook's explicit columns.
        wild_type = (row.get("Wildtype") or row.get("Wild Type") or "").strip().upper()
        mutant = (row.get("Mutation") or "").strip().upper()
        if len(wild_type) != 1 or len(mutant) != 1:
            return None

    value = ""
    for key in ("DDG", "ddG", "ΔΔG (kcal/mol)", "ddg"):
        if row.get(key):
            value = row[key]
            break
    if not value or not chain or not position:
        return None
    try:
        return MutationEffect(
            chain=chain,
            position=int(position),
            wild_type=wild_type.upper(),
            mutant=mutant.upper(),
            ddg=float(value),
            source=source,
        )
    except ValueError:
        return None


def parse_pythia_ppi(rows: Iterable[dict], source: str = "pythia-ppi") -> tuple:
    """PythiaStudio binding-ΔΔG records, from CSV rows or workbook records.

    A chain is mandatory. PythiaStudio's *stability* export omits it, and a
    stability file fed to this parser would otherwise be silently attributed to
    whichever chain happened to be first — inverting nothing but relocating
    every prediction. It is also a different quantity in a different unit
    (Pythia Energy Units, not kcal/mol), so the two must never be merged.
    """
    effects = []
    rows = list(rows)
    for row in rows:
        effect = _ppi_row(row, source)
        if effect is not None:
            effects.append(effect)
    if not effects:
        headers = sorted({key for row in rows[:5] for key in row})
        if headers and not any(key.strip().lower() == "chain" for key in headers):
            raise ValueError(
                "this file has no Chain column, so its predictions cannot be "
                "placed on a complex. PythiaStudio's stability export looks like "
                "this; it reports folding ΔΔG in Pythia Energy Units, which is a "
                f"different quantity from binding ΔΔG. Headers found: "
                f"{', '.join(headers)}"
            )
        raise ValueError(
            "no usable Pythia-PPI rows found; expected a Mutation or Mutant Name "
            "column of the form H_A_102_P together with Chain, Position and DDG"
        )
    return tuple(effects)


THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}

# Below this fraction of matching wild-type residues, the file is taken to
# describe a different structure. Left low enough to tolerate a few modified or
# non-standard residues, high enough that a wrong file cannot pass.
IDENTITY_THRESHOLD = 0.8


@dataclass(frozen=True)
class WildTypeCheck:
    matched: int
    mismatched: int
    examples: tuple[str, ...]      # "chain:pos file=X structure=Y"

    @property
    def total(self) -> int:
        return self.matched + self.mismatched

    @property
    def rate(self) -> float:
        return self.matched / self.total if self.total else 0.0


def verify_wild_types(effects: Iterable[MutationEffect], residue_names: dict) -> WildTypeCheck:
    """Check the file's wild-type residues against the structure's own.

    A ΔΔG file carries the residue it thinks is at each position, and that is
    the only thing tying it to a structure. Without checking it, a file computed
    on one complex loads silently onto another whenever the chain letters happen
    to coincide — 1BRS has a chain E, and so does 1ACB, so barstar's predictions
    were attributed to chymotrypsin's catalytic residues and reported as if they
    belonged there.

    `residue_names` maps (chain, position) to a three-letter residue name.
    """
    matched = mismatched = 0
    examples: list[str] = []
    seen: set[tuple[str, int]] = set()
    for effect in effects:
        actual = residue_names.get((effect.chain, effect.position))
        if actual is None:
            continue  # position absent from the structure: not a mismatch
        expected = THREE_TO_ONE.get(actual.upper())
        if expected is None:
            continue  # non-standard residue: no one-letter code to compare
        if expected == effect.wild_type.upper():
            matched += 1
            continue
        mismatched += 1
        # A saturation scan carries ~19 substitutions per residue, so collect
        # examples per position rather than per row — otherwise the message
        # names one residue four times.
        position = (effect.chain, effect.position)
        if position not in seen and len(examples) < 3:
            seen.add(position)
            examples.append(
                f"{effect.chain}:{effect.position} "
                f"file={effect.wild_type} structure={actual}"
            )
    return WildTypeCheck(matched, mismatched, tuple(examples))


def classify_ppi(value: float) -> str:
    """PythiaStudio's own effect labels. Positive ΔΔG means reduced binding."""
    if value >= PPI_DESTABILISING:
        return "destabilising"
    if value <= PPI_STABILISING:
        return "stabilising"
    return "neutral"


def detect_format(path) -> str:
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    if suffix == ".xlsx":
        return "pythia-ppi"
    if "pred_mask" in name:
        return "pythia"
    if suffix in (".csv", ".tsv"):
        # PythiaStudio's CSV header is exactly these four columns; the generic
        # tabular reader would take "Mutation" for the substituted residue and
        # store the whole identifier as the mutant.
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                header = handle.readline().strip().lower()
        except OSError:
            return "tabular"
        if header.replace(" ", "") == "mutation,chain,position,ddg":
            return "pythia-ppi"
        return "tabular"
    return "tabular"


def load(path, fmt: str, index_map=None) -> tuple:
    """Read a ΔΔG file in `fmt`, returning MutationEffect records."""
    source = Path(path).stem
    if fmt == "pythia-ppi":
        if Path(path).suffix.lower() == ".xlsx":
            _, records = read_records(path)
            return parse_pythia_ppi(records, source)
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        return parse_pythia_ppi(csv.DictReader(text.splitlines()), source)
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if fmt == "pythia":
        if index_map is None:
            raise ValueError("the pythia format needs a sequential index map")
        return parse_pythia(text, index_map, source)
    return parse_tabular(text, source)


def summarize_by_residue(
    effects: Iterable[MutationEffect], statistic: str = "min"
) -> tuple[tuple[tuple[str, int], str, float, int], ...]:
    """Per-residue summary: ((chain, position), wild_type, value, n_mutations).

    `min` reports the most stabilising substitution, `max` the most
    destabilising, and `mean` the average over all scored substitutions.

    Ordering follows the statistic, so that the residues the caller asked about
    come first: `max` sorts most positive first, `min` and `mean` most negative
    first. Sorting `max` ascending — as this did until 2026-08-15 — ranks the
    *most tolerant* residues at the top, which is the exact opposite of a
    hot-spot list and reads as plausible while being backwards.

    This assumes the convention MolCompose's supported formats use, in which a
    positive ΔΔG is the disruptive direction (see `classify_ppi`).
    """
    if statistic not in ("min", "max", "mean"):
        raise ValueError(f"statistic must be min, max or mean: {statistic}")
    grouped: dict[tuple[str, int], list[MutationEffect]] = {}
    for effect in effects:
        grouped.setdefault((effect.chain, effect.position), []).append(effect)
    rows = []
    for key, items in grouped.items():
        values = [item.ddg for item in items]
        if statistic == "min":
            value = min(values)
        elif statistic == "max":
            value = max(values)
        else:
            value = sum(values) / len(values)
        rows.append((key, items[0].wild_type, value, len(items)))
    rows.sort(key=lambda row: row[2], reverse=(statistic == "max"))
    return tuple(rows)


def restrict_to(effects: Iterable[MutationEffect], residues: Iterable[tuple[str, int]]):
    """Keep only effects at the given (chain, position) residues.

    A saturation scan covers every chain of the deposited file — for 1BRS that
    is three copies of each partner, 586 residues — so ranking the whole file
    against one interface drowns the interface in residues that are not part of
    it. The caller passes the interface it actually detected.
    """
    wanted = {(chain, int(position)) for chain, position in residues}
    return tuple(
        effect for effect in effects if (effect.chain, effect.position) in wanted
    )
