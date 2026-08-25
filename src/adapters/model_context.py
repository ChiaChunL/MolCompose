"""Convert current ChimeraX atomic models, chains, and residues into core data types."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..core.dockq import BACKBONE_ATOMS
from ..core.interactions import AtomRecord
from ..core.interfaces import AtomPoint, ResidueKey

CRITERIA = ("heavy", "cbeta", "vdw")
# Fallback van der Waals radii, by element, for structures whose atoms carry
# none. ChimeraX supplies `atom.radius` for anything it has parameters for;
# these cover the protein heavy atoms and keep the criterion usable rather
# than refusing on an unusual file.
_FALLBACK_RADII = {6: 1.7, 7: 1.55, 8: 1.52, 16: 1.8, 15: 1.8, 34: 1.9}


@dataclass(frozen=True)
class ChainRef:
    chain_id: str
    atomspec: str
    residue_count: int
    handle: object = field(compare=False, repr=False, default=None)


@dataclass(frozen=True)
class ModelRef:
    model_id: str
    name: str
    atomspec: str
    chains: tuple[ChainRef, ...]
    handle: object = field(compare=False, repr=False, default=None)


def _amino_residues(chain):
    from chimerax.atomic import Residue

    return [
        residue
        for residue in chain.residues
        if residue is not None and residue.polymer_type == Residue.PT_AMINO
    ]


def model_ref(model) -> ModelRef:
    chains = []
    for chain in model.chains:
        amino = _amino_residues(chain)
        if not amino:
            continue
        chains.append(
            ChainRef(
                chain_id=chain.chain_id,
                atomspec=chain.atomspec,
                residue_count=len(amino),
                handle=chain,
            )
        )
    return ModelRef(
        model_id=f"#{model.id_string}",
        name=model.name,
        atomspec=model.atomspec,
        chains=tuple(chains),
        handle=model,
    )


def _validate_chains(model_id: str, known: set[str], requested: Iterable[str]) -> list[str]:
    requested_ids = sorted(set(requested))
    unknown = [chain_id for chain_id in requested_ids if chain_id not in known]
    if not unknown:
        return requested_ids

    # Name the chains that do exist, and recognise an atomspec for what it is.
    # This message is read as often by an agent as by a person, and a bare
    # "unknown chain" leaves both to guess the syntax: a recorded session had
    # the agent try "/A" and then "#1/A" before reaching "A", two wasted calls
    # against a live structure. Saying the expected form once ends that.
    message = f"unknown protein chain(s) for {model_id}: {', '.join(unknown)}"
    stripped = {chain_id: _plain_chain_id(chain_id) for chain_id in unknown}
    recoverable = {
        chain_id: plain
        for chain_id, plain in stripped.items()
        if plain != chain_id and plain in known
    }
    if recoverable:
        pairs = ", ".join(f"{spec} -> {plain}" for spec, plain in recoverable.items())
        message += f". Give the chain identifier alone, not an atomspec: {pairs}"
    if known:
        message += f". This model has {', '.join(sorted(known))}"
    raise ValueError(message)


def _plain_chain_id(text: str) -> str:
    """Reduce an atomspec such as ``#1/A`` or ``/A`` to the chain identifier."""
    return text.rsplit("/", 1)[-1].strip() if "/" in text else text.strip()


def residue_key(model_id: str, residue) -> ResidueKey:
    """A ResidueKey for one ChimeraX residue.

    Public because whole-structure colouring needs the same key type the
    interface path produces — `compact_residue_spec` collapses these into
    per-chain ranges, and a raw `a|b|c` union over hundreds of residues
    overflows ChimeraX's recursive atomspec parser.
    """
    return ResidueKey(
        model_id=model_id,
        chain_id=residue.chain_id,
        number=residue.number,
        insertion_code=residue.insertion_code,
        name=residue.name,
        atomspec=residue.atomspec,
    )


def _radius(atom) -> float:
    """The atom's van der Waals radius, or a per-element default."""
    value = getattr(atom, "radius", None)
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return _FALLBACK_RADII.get(getattr(atom.element, "number", 0), 1.7)


def _selects_atom(atom, residue, criterion: str) -> bool:
    if atom.element.number == 1:
        return False
    if criterion in ("heavy", "vdw"):
        return True
    # cbeta: one point per residue — CB, with CA as the conventional glycine fallback.
    return atom.name == "CB" or (residue.name == "GLY" and atom.name == "CA")


def atom_points(model, chain_ids: Iterable[str], criterion: str = "heavy") -> tuple[AtomPoint, ...]:
    if criterion not in CRITERIA:
        raise ValueError(f"interface criterion must be one of {', '.join(CRITERIA)}: {criterion}")
    ref = model_ref(model)
    known = {chain.chain_id for chain in ref.chains}
    requested = _validate_chains(ref.model_id, known, chain_ids)

    points = []
    for chain in model.chains:
        if chain.chain_id not in requested:
            continue
        for residue in _amino_residues(chain):
            key = residue_key(ref.model_id, residue)
            for atom in residue.atoms:
                if not _selects_atom(atom, residue, criterion):
                    continue
                x, y, z = atom.coord
                points.append(
                    AtomPoint(key, (float(x), float(y), float(z)), _radius(atom))
                )
    return tuple(points)


# PDB/mmCIF metadata keys that mark an experimentally determined structure.
_EXPERIMENTAL_KEYS = ("EXPDTA", "expdta", "_exptl.method", "exptl")


def experimental_method(model) -> str | None:
    """The experimental method if this is a determined (not predicted) structure."""
    metadata = getattr(model, "metadata", None) or {}
    for key in _EXPERIMENTAL_KEYS:
        value = metadata.get(key)
        if not value:
            continue
        text = value[0] if isinstance(value, (list, tuple)) and value else value
        text = str(text).replace("EXPDTA", "").strip()
        if text:
            return text
    return None


def plddt_values(model) -> tuple[tuple[ResidueKey, float], ...]:
    """Per-residue mean heavy-atom B-factor, read as pLDDT for predicted models."""
    ref = model_ref(model)
    values = []
    for chain in model.chains:
        for residue in _amino_residues(chain):
            atom_values = [
                atom.bfactor
                for atom in residue.atoms
                if atom.element.number != 1 and getattr(atom, "bfactor", None) is not None
            ]
            if not atom_values:
                continue
            values.append(
                (residue_key(ref.model_id, residue), sum(atom_values) / len(atom_values))
            )
    return tuple(values)


def interaction_atoms(model, residue_keys: Iterable[ResidueKey]) -> tuple[AtomRecord, ...]:
    """All heavy atoms (with names) of the given residues, for interaction typing."""
    wanted = {(key.chain_id, key.number, key.insertion_code) for key in residue_keys}
    ref = model_ref(model)
    records = []
    for chain in model.chains:
        for residue in _amino_residues(chain):
            ident = (residue.chain_id, residue.number, residue.insertion_code)
            if ident not in wanted:
                continue
            key = residue_key(ref.model_id, residue)
            for atom in residue.atoms:
                if atom.element.number == 1:
                    continue
                x, y, z = atom.coord
                records.append(
                    AtomRecord(key, atom.name, atom.element.number, (float(x), float(y), float(z)))
                )
    return tuple(records)


def buried_area_specs(ref: ModelRef, chains_a, chains_b) -> tuple[str, str]:
    """Validated atomspecs for the two sides of a buried-area measurement."""
    overlap = sorted(set(chains_a) & set(chains_b))
    if overlap:
        raise ValueError(f"chain groups must be disjoint (shared: {', '.join(overlap)})")
    return chain_group_atomspec(ref, chains_a), chain_group_atomspec(ref, chains_b)


def buried_area(session, model, chains_a, chains_b, probe_radius: float = 1.4) -> float:
    """Buried solvent-accessible area (Å²) between two chain groups.

    Calls the same routine as `measure buriedarea` (which returns the value,
    unlike the command, which only logs it) on atoms resolved from the same
    atomspecs, so the number matches the native command exactly.
    """
    from chimerax.atomic import AtomsArg
    from chimerax.atomic import buried_area as chimerax_buried_area

    spec_a, spec_b = buried_area_specs(model_ref(model), chains_a, chains_b)
    atoms_a, _, _ = AtomsArg.parse(spec_a, session)
    atoms_b, _, _ = AtomsArg.parse(spec_b, session)
    area, *_ = chimerax_buried_area(atoms_a, atoms_b, probe_radius)
    return float(area)


def measure_residue_sasa(session, model, chain_ids, runner=None):
    """Per-residue (name, SASA) for the given chains, measured in complex state."""
    if runner is None:
        from chimerax.core.commands import run as runner
    ref = model_ref(model)
    wanted = set(chain_ids)
    _validate_chains(ref.model_id, {c.chain_id for c in ref.chains}, wanted)
    spec = chain_group_atomspec(ref, wanted)
    runner(session, f"measure sasa {spec} setAttribute true")
    values = []
    for chain in model.chains:
        if chain.chain_id not in wanted:
            continue
        for residue in _amino_residues(chain):
            area = getattr(residue, "area", None)
            if area is not None:
                values.append((residue.name, float(area)))
    return tuple(values)


def backbone_atoms(model, chain_ids: Iterable[str]) -> dict[tuple, dict[str, tuple]]:
    """{(chain, resnum, icode): {atom_name: xyz}} for backbone atoms of the chains."""
    wanted = set(chain_ids)
    residues: dict[tuple, dict[str, tuple]] = {}
    for chain in model.chains:
        if chain.chain_id not in wanted:
            continue
        for residue in _amino_residues(chain):
            key = (residue.chain_id, residue.number, residue.insertion_code)
            entry = residues.setdefault(key, {})
            for atom in residue.atoms:
                if atom.name in BACKBONE_ATOMS:
                    x, y, z = atom.coord
                    entry[atom.name] = (float(x), float(y), float(z))
    return residues


def residue_sequences(model, chain_ids: Iterable[str]) -> dict[str, tuple]:
    """{chain: ((chain, resnum, icode), residue name), ...} in sequence order.

    The input a sequence alignment needs: residues in chain order, each carrying
    the key the coordinate dicts are keyed by, so an alignment can be turned back
    into a mapping between those dicts. Order comes from the chain's residue
    list rather than from sorting by number, because numbering is exactly what
    cannot be trusted here.
    """
    wanted = set(chain_ids)
    sequences: dict[str, list] = {}
    for chain in model.chains:
        if chain.chain_id not in wanted:
            continue
        entries = sequences.setdefault(chain.chain_id, [])
        for residue in _amino_residues(chain):
            entries.append(
                ((residue.chain_id, residue.number, residue.insertion_code), residue.name)
            )
    return {chain: tuple(entries) for chain, entries in sequences.items()}


def heavy_atoms_by_residue(model, chain_ids: Iterable[str]) -> dict[tuple, list[tuple]]:
    """{(chain, resnum, icode): [xyz, ...]} heavy atoms, for contact detection."""
    wanted = set(chain_ids)
    residues: dict[tuple, list[tuple]] = {}
    for chain in model.chains:
        if chain.chain_id not in wanted:
            continue
        for residue in _amino_residues(chain):
            key = (residue.chain_id, residue.number, residue.insertion_code)
            entry = residues.setdefault(key, [])
            for atom in residue.atoms:
                if atom.element.number != 1:
                    x, y, z = atom.coord
                    entry.append((float(x), float(y), float(z)))
    return residues


def residue_sasa_map(session, model, chain_ids, runner=None) -> dict[tuple, tuple[str, float]]:
    """{(chain, resnum, icode): (resname, SASA)} for the given chains as specified."""
    if runner is None:
        from chimerax.core.commands import run as runner
    ref = model_ref(model)
    wanted = set(chain_ids)
    _validate_chains(ref.model_id, {c.chain_id for c in ref.chains}, wanted)
    runner(session, f"measure sasa {chain_group_atomspec(ref, wanted)} setAttribute true")
    values = {}
    for chain in model.chains:
        if chain.chain_id not in wanted:
            continue
        for residue in _amino_residues(chain):
            area = getattr(residue, "area", None)
            if area is not None:
                key = (residue.chain_id, residue.number, residue.insertion_code)
                values[key] = (residue.name, float(area))
    return values


def delta_sasa(session, model, chains_a, chains_b, runner=None):
    """Per-residue buried area: SASA alone minus SASA in the complex.

    Returns ((chain, resnum, icode), resname, sasa_alone, sasa_complex, delta)
    sorted by decreasing delta — the interface hot-spot ranking.
    """
    alone = {
        **residue_sasa_map(session, model, chains_a, runner),
        **residue_sasa_map(session, model, chains_b, runner),
    }
    complexed = residue_sasa_map(
        session, model, tuple(chains_a) + tuple(chains_b), runner
    )
    rows = []
    for key, (name, area_complex) in complexed.items():
        entry = alone.get(key)
        if entry is None:
            continue
        area_alone = entry[1]
        delta = area_alone - area_complex
        if delta > 0.0:
            rows.append((key, name, area_alone, area_complex, delta))
    rows.sort(key=lambda row: row[4], reverse=True)
    return tuple(rows)


def structure_path(model) -> str | None:
    """Filesystem path the model was opened from, when there is one."""
    for attribute in ("filename", "path"):
        value = getattr(model, attribute, None)
        if value:
            return str(value)
    metadata = getattr(model, "metadata", None) or {}
    value = metadata.get("_source_file") or metadata.get("filename")
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    return str(value) if value else None


# Everything ChimeraX will open as a structure, plus the compressed forms.
# A model opened from a file is named after that file, extension included, so
# without this every derived filename carried it: `1brs.cif_interface.scf`,
# `1brs.cif_clean-cartoon.png`.
_STRUCTURE_SUFFIXES = (
    ".cif", ".mmcif", ".pdb", ".pdb1", ".ent", ".bcif", ".mol2", ".sdf", ".mol",
)


def structure_stem(model, fallback: str = "figure") -> str:
    """The model's name with any structure extension and unsafe characters gone.

    Used for every filename this bundle suggests, so an SCF, a report and a
    figure exported from one structure agree on what that structure is called.
    """
    import re

    name = str(getattr(model, "name", "") or "") if model is not None else ""
    lowered = name.lower()
    for compressed in (".gz", ".bz2", ".xz", ".zst"):
        if lowered.endswith(compressed):
            name, lowered = name[: -len(compressed)], lowered[: -len(compressed)]
    for suffix in _STRUCTURE_SUFFIXES:
        if lowered.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or fallback


def sequential_index_map(model) -> dict[int, tuple[str, int]]:
    """1-based sequential residue index -> (chain, residue number), Pythia's ordering."""
    mapping = {}
    index = 0
    for chain in model.chains:
        for residue in _amino_residues(chain):
            index += 1
            mapping[index] = (residue.chain_id, residue.number)
    return mapping


def cbeta_and_plddt(model) -> tuple[tuple, tuple]:
    """Per-residue (Cbeta-or-Calpha xyz, mean heavy-atom B-factor) in model order."""
    coords, values = [], []
    for chain in model.chains:
        for residue in _amino_residues(chain):
            anchor = None
            fallback = None
            bfactors = []
            for atom in residue.atoms:
                if atom.element.number == 1:
                    continue
                if getattr(atom, "bfactor", None) is not None:
                    bfactors.append(atom.bfactor)
                if atom.name == "CB":
                    anchor = atom.coord
                elif atom.name == "CA":
                    fallback = atom.coord
            point = anchor if anchor is not None else fallback
            if point is None:
                continue
            x, y, z = point
            coords.append((float(x), float(y), float(z)))
            values.append(sum(bfactors) / len(bfactors) if bfactors else 0.0)
    return tuple(coords), tuple(values)


def amino_chain_sequence(model) -> tuple[str, ...]:
    """Chain ID per amino-acid residue in model order (PAE matrix row order)."""
    return tuple(
        residue.chain_id
        for chain in model.chains
        for residue in _amino_residues(chain)
    )


def chain_group_atomspec(ref: ModelRef, chain_ids: Iterable[str]) -> str:
    known = {chain.chain_id: chain for chain in ref.chains}
    requested = _validate_chains(ref.model_id, set(known), chain_ids)
    return "|".join(known[chain_id].atomspec for chain_id in requested)


def list_protein_models(session) -> tuple[ModelRef, ...]:
    from chimerax.atomic import AtomicStructure

    refs = []
    for model in session.models.list():
        if not isinstance(model, AtomicStructure):
            continue
        ref = model_ref(model)
        if ref.chains:
            refs.append((model.id, ref))
    refs.sort(key=lambda item: item[0])
    return tuple(ref for _, ref in refs)
