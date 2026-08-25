"""Minimal PDB reader for structure-level golden tests.

The bundle's own tests must run without ChimeraX, so a real structure cannot be
loaded through the adapters. This reader produces the same core-layer inputs the
adapters produce, following the same selection rules as
``adapters/model_context.py``:

- ATOM records only, so waters, ions and non-polymer ligands are excluded;
- hydrogens and deuteriums dropped;
- first altloc kept (blank or ``A``), matching ChimeraX's default;
- first model only.

It is deliberately independent of the production code path: it shares no module
with ``src/``, so a golden test failing here means the science changed, not that
one shared helper drifted.
"""

from pathlib import Path

from src.core.interactions import AtomRecord
from src.core.interfaces import AtomPoint, ResidueKey

FIXTURES = Path(__file__).parent / "fixtures"

# Element symbol -> atomic number, for the elements a protein ATOM record holds.
_ELEMENTS = {"C": 6, "N": 7, "O": 8, "S": 16, "SE": 34, "P": 15}


def _atom_lines(path: Path):
    seen = set()
    for line in path.read_text().splitlines():
        if line.startswith("ENDMDL"):
            break
        if not line.startswith("ATOM"):
            continue
        element = line[76:78].strip().upper()
        if element in ("H", "D"):
            continue
        altloc = line[16]
        if altloc not in (" ", "A"):
            continue
        name = line[12:16].strip()
        chain = line[21]
        number = int(line[22:26])
        icode = line[26].strip()
        identity = (chain, number, icode, name)
        if identity in seen:
            continue
        seen.add(identity)
        yield {
            "chain": chain,
            "number": number,
            "icode": icode,
            "resname": line[17:20].strip(),
            "name": name,
            "element": _ELEMENTS.get(element, 0),
            "xyz": (float(line[30:38]), float(line[38:46]), float(line[46:54])),
        }


def _key(model_id: str, atom) -> ResidueKey:
    chain, number, icode = atom["chain"], atom["number"], atom["icode"]
    return ResidueKey(
        model_id=model_id,
        chain_id=chain,
        number=number,
        insertion_code=icode,
        name=atom["resname"],
        atomspec=f"{model_id}/{chain}:{number}{icode}",
    )


def _select(name: str, chains, criterion: str):
    path = FIXTURES / name
    wanted = set(chains)
    for atom in _atom_lines(path):
        if atom["chain"] not in wanted:
            continue
        if criterion == "cbeta" and not (
            atom["name"] == "CB" or (atom["resname"] == "GLY" and atom["name"] == "CA")
        ):
            continue
        yield atom


def atom_points(name, chains, criterion="heavy", model_id="#1") -> tuple[AtomPoint, ...]:
    """Interface-detection input: one point per selected atom."""
    return tuple(
        AtomPoint(residue=_key(model_id, atom), xyz=atom["xyz"])
        for atom in _select(name, chains, criterion)
    )


def atom_records(name, chains, model_id="#1") -> tuple[AtomRecord, ...]:
    """Interaction-typing input: heavy atoms with names and elements."""
    return tuple(
        AtomRecord(
            residue=_key(model_id, atom),
            name=atom["name"],
            element=atom["element"],
            xyz=atom["xyz"],
        )
        for atom in _select(name, chains, "heavy")
    )


def residue_names(name, chains, model_id="#1") -> dict:
    """{ResidueKey: residue name} for every selected residue."""
    return {_key(model_id, atom): atom["resname"] for atom in _select(name, chains, "heavy")}


def heavy_atoms_by_residue(name, chains) -> dict:
    """{(chain, number, icode): [xyz, ...]} — DockQ contact input."""
    grouped: dict = {}
    for atom in _select(name, chains, "heavy"):
        grouped.setdefault((atom["chain"], atom["number"], atom["icode"]), []).append(atom["xyz"])
    return grouped


def backbone_by_residue(name, chains) -> dict:
    """{(chain, number, icode): {atom name: xyz}} — DockQ superposition input."""
    grouped: dict = {}
    for atom in _select(name, chains, "heavy"):
        if atom["name"] not in ("N", "CA", "C", "O"):
            continue
        key = (atom["chain"], atom["number"], atom["icode"])
        grouped.setdefault(key, {})[atom["name"]] = atom["xyz"]
    return grouped


def residue_sequences(name, chains) -> dict:
    """{chain: (((chain, number, icode), resname), ...)} -- sequence-alignment input.

    Mirrors `adapters.model_context.residue_sequences`: residues in file order,
    each carrying the key the coordinate dicts above are keyed by.
    """
    sequences: dict = {}
    seen = set()
    for atom in _select(name, chains, "heavy"):
        key = (atom["chain"], atom["number"], atom["icode"])
        if key in seen:
            continue
        seen.add(key)
        sequences.setdefault(atom["chain"], []).append((key, atom["resname"]))
    return {chain: tuple(entries) for chain, entries in sequences.items()}


def remap_chains(grouped: dict, mapping: dict) -> dict:
    """Relabel chain IDs so a second copy can be compared against the first."""
    return {
        (mapping.get(key[0], key[0]),) + key[1:]: value for key, value in grouped.items()
    }
