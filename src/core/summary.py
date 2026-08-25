"""Per-prediction confidence summaries: ipTM, pTM, and the per-chain-pair form.

The PAE matrix and the summary scores live in different files, and the eight
engines this toolkit reads agree on almost nothing about either:

    AlphaFold 3     {base}_summary_confidences.json      chain_pair_iptm
    AlphaFold Server{base}_summary_confidences_{i}.json  chain_pair_iptm
    Protenix        {base}_summary_confidence_sample_{i}.json   chain_pair_iptm
                    -- note the singular "confidence"
    Boltz-2         confidence_{stem}.json               global iptm only
    AF2-Multimer    iptm_ptm.json                        global iptm only,
                    one file covering every model, keyed by model name
    ColabFold       {scored}.json                        global iptm only,
                    in the same file as the PAE matrix
    Chai-1          scores.{tag}.npz                     per_chain_pair_iptm,
                    and the only one that is not JSON

Several of them give only a whole-complex ipTM. That distinction has to
survive to the surface: a global ipTM is not the ipTM of the interface being
characterised, and reporting it as though it were would be the same class of
error as scoring one sample's structure against another's PAE.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Ordered most specific first, index-matched before wildcards, for the same
# reason the PAE patterns are: opening sample_4 must not pick up sample_0.
SUMMARY_PATTERNS = {
    "alphafold3": ("{base}_summary_confidences.json",),
    "alphafold-server": ("{base}_summary_confidences_{index}.json",
                         "{stem}_summary_confidences_*.json"),
    "protenix": ("{base}_summary_confidence_{sample}.json",
                 "{base}_summary_confidence_sample_*.json"),
    "boltz": ("confidence_{stem}.json",),
    # Two shapes. A local AF2-Multimer run writes one `iptm_ptm.json` for the
    # whole run, keyed by model name. A single model exported on its own
    # carries its scores beside it, and that is what the packaged example is —
    # the pattern for it was missing, so the file this project ships could not
    # be found by the software that ships with it.
    # `result_{tag}.pkl` again: for a native run the same file is both the PAE
    # matrix and the only place ipTM and pTM exist.
    "af2-multimer": ("result_{tag}.pkl", "iptm_ptm.json", "{stem}_summary.json"),
    # ColabFold puts ipTM and pTM in the same file as the PAE matrix, so the
    # replicate-exact name is the one to use here too. It reports no chain-pair
    # breakdown, which `parse` records as None rather than substituting the
    # whole-complex figure.
    "colabfold": ("{scored}.json", "{allof}.pickle"),
    # Chai-1 writes one npz per model, named off the same `{tag}` its PAE file
    # uses: pred.model_idx_2.cif -> scores.model_idx_2.npz.
    # `scores.<tag>.npz` is the native name; `{stem}_ranking.json` is the one
    # a single exported model carries, and holds the same numbers under
    # `ptm_scores`.
    "chai": ("scores.{tag}.npz", "{stem}_scores.npz", "{stem}_ranking.json"),
    "generic": (
        "{base}_summary_confidences.json",
        "{base}_summary_confidences_{index}.json",
        "{base}_summary_confidence_{sample}.json",
        "confidence_{stem}.json",
        "scores.{tag}.npz",                  # Chai-1
        "{scored}.json",                     # ColabFold
        "iptm_ptm.json",
        "{stem}_summary.json",               # AlphaFold2-Multimer, one model
        "result_{tag}.pkl",                  # AlphaFold2-Multimer, native
        "{allof}.pickle",                    # ColabFold, native
        "{stem}_scores.npz",                 # Chai-1, one model
        "{stem}_ranking.json",               # Chai-1, one model
        "*_summary_confidence*.json",
    ),
}

_MODEL_KEY = re.compile(r"model_\d+.*")


@dataclass(frozen=True)
class Summary:
    """What a prediction says about itself, beyond the PAE matrix.

    `chain_pair_iptm` is None for engines that only report a whole-complex
    value. Callers must not substitute `iptm` for it: the global number
    averages over every chain pair in the model, so on anything larger than a
    dimer it is not a statement about any one interface.
    """

    iptm: float | None
    ptm: float | None
    chain_pair_iptm: tuple[tuple[float, ...], ...] | None
    source: Path
    engine: str

    @property
    def has_pairwise(self) -> bool:
        return self.chain_pair_iptm is not None

    def pair(self, index_a: int, index_b: int) -> float | None:
        """ipTM for one chain pair, by the chains' order in the model.

        The larger of the two directions, which is a no-op for every engine
        whose matrix is symmetric — AlphaFold 3 and Protenix both are — and is
        Chai-1's own convention where it is not: its `per_chain_pair_iptm` has
        two different off-diagonal values, and its own whole-complex `iptm`
        equals the larger of them on all five samples of the reference panel.
        Without this, the number reported would depend on which chain the
        caller happened to name first.
        """
        matrix = self.chain_pair_iptm
        if matrix is None:
            return None
        try:
            return max(float(matrix[index_a][index_b]),
                       float(matrix[index_b][index_a]))
        except (IndexError, TypeError, ValueError):
            return None


def _matrix(value) -> tuple[tuple[float, ...], ...] | None:
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(row, list) for row in value):
        return None
    try:
        return tuple(tuple(float(x) for x in row) for row in value)
    except (TypeError, ValueError):
        return None


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse(path, model_stem: str = "") -> Summary:
    """Read whichever summary layout `path` holds.

    `model_stem` matters only for AF2-Multimer, whose single `iptm_ptm.json`
    covers every model in the run and is keyed by model name. Passing the
    wrong stem there would report another model's score, so an unmatched stem
    is an error rather than a fallback to the first entry.
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"summary file does not exist: {path}")
    if path.suffix == ".npz":
        return _parse_npz(path)
    if path.suffix in (".pkl", ".pickle"):
        # A local AlphaFold2-Multimer run writes ipTM and pTM nowhere else.
        # Read through the restricted loader for the same reason as the PAE
        # matrix: the file was found by searching, and unpickling runs code.
        from .pickled import load_arrays

        arrays = load_arrays(path)
        data = {
            key: float(arrays[key])
            for key in ("iptm", "ptm")
            if key in arrays
        }
        if not data:
            raise ValueError(
                f"{path.name} holds no ipTM or pTM; it may be an AlphaFold "
                "features pickle rather than a result"
            )
        return Summary(
            data.get("iptm"), data.get("ptm"), None, path, "alphafold2-multimer"
        )
    try:
        data = json.loads(path.read_text())
    except ValueError as error:
        raise ValueError(f"{path.name} is not readable JSON: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} does not hold a confidence summary")

    # AF2-Multimer: one file, keyed by model name, each value {iptm, ptm}.
    if data and all(isinstance(v, dict) and "iptm" in v for v in data.values()):
        return _parse_af2_multimer(data, path, model_stem)

    # Chai-1's per-model `ranking.json` nests the same two numbers under
    # `ptm_scores`, as one-element lists carrying the batch axis every array in
    # that engine's output has.
    scores = data.get("ptm_scores")
    if isinstance(scores, dict):
        data = {
            **data,
            "iptm": scores.get("interface_ptm", data.get("iptm")),
            "ptm": scores.get("complex_ptm", data.get("ptm")),
            "chain_pair_iptm": scores.get(
                "per_chain_pair_iptm", data.get("chain_pair_iptm")
            ),
        }

    pairwise = _matrix(data.get("chain_pair_iptm"))
    iptm = _number(data.get("iptm"))
    if iptm is None:
        # Boltz-2 reports the protein-only figure separately; when a ligand is
        # present the two differ and the protein one is what an interface
        # between two protein chains is about.
        iptm = _number(data.get("protein_iptm"))
    ptm = _number(data.get("ptm"))
    if iptm is None and ptm is None and pairwise is None:
        raise ValueError(
            f"{path.name} holds no ipTM, pTM or chain-pair ipTM; "
            "it may be a PAE file rather than a summary"
        )
    return Summary(iptm, ptm, pairwise, path, _engine_of(data))


def _squeeze(array) -> np.ndarray:
    """Drop Chai-1's leading batch axis, whatever the array's rank.

    Every array in the file carries it: `iptm` is (1,), `per_chain_ptm` is
    (1, N) and `per_chain_pair_iptm` is (1, N, N). Indexing [0] blindly would
    turn a scalar score into a crash on a file written without the batch axis,
    so the axis is removed only when it is there to remove.
    """
    values = np.asarray(array, dtype=float)
    if values.ndim and values.shape[0] == 1:
        return values[0]
    return values


def _parse_npz(path: Path) -> Summary:
    """Chai-1's `scores.<model>.npz`.

    The diagonal of `per_chain_pair_iptm` is not ipTM — it holds each chain's
    own pTM, verified equal to `per_chain_ptm` on all five samples of the
    reference panel. Nothing here reads the diagonal, because a chain paired
    with itself is not an interface, but a future caller that indexed it
    expecting ipTM would get a systematically higher number.
    """
    try:
        data = np.load(path)
    except (OSError, ValueError) as error:
        raise ValueError(f"{path.name} is not a readable NPZ file: {error}") from error
    with data:
        available = set(data.files)
        if not available & {"iptm", "ptm", "per_chain_pair_iptm"}:
            raise ValueError(
                f"{path.name} holds no ipTM, pTM or chain-pair ipTM "
                f"(found {', '.join(sorted(available)) or 'nothing'}); "
                "it may be a PAE file rather than a summary"
            )
        pairwise = None
        if "per_chain_pair_iptm" in available:
            matrix = _squeeze(data["per_chain_pair_iptm"])
            if matrix.ndim == 2 and matrix.shape[0] == matrix.shape[1]:
                pairwise = tuple(tuple(float(x) for x in row) for row in matrix)
        iptm = _scalar(data, available, "iptm")
        ptm = _scalar(data, available, "ptm")
    return Summary(iptm, ptm, pairwise, path, "chai")


def _scalar(data, available: set, key: str) -> float | None:
    if key not in available:
        return None
    values = _squeeze(data[key])
    try:
        return float(values if values.ndim == 0 else values.reshape(-1)[0])
    except (IndexError, TypeError, ValueError):
        return None


def _parse_af2_multimer(data: dict, path: Path, model_stem: str) -> Summary:
    key = _match_model_key(data, model_stem)
    if key is None:
        raise ValueError(
            f"{path.name} covers {len(data)} models and none matches "
            f"{model_stem or 'the open structure'}; it is keyed by model name, "
            f"so the wrong key would report another model's score. "
            f"Available: {', '.join(sorted(data)[:4])}…"
        )
    entry = data[key]
    return Summary(
        _number(entry.get("iptm")), _number(entry.get("ptm")), None, path, "af2-multimer"
    )


def _match_model_key(data: dict, model_stem: str) -> str | None:
    """Find the entry for a structure whose file stem embeds the model name.

    `pae_model_1_multimer_v3_pred_0.json` and the key
    `model_1_multimer_v3_pred_0` share a tail, so the longest key contained in
    the stem wins. One model in the file needs no matching.
    """
    if len(data) == 1:
        return next(iter(data))
    if not model_stem:
        return None
    matches = [key for key in data if key in model_stem]
    if not matches:
        found = _MODEL_KEY.search(model_stem)
        matches = [key for key in data if found and key == found.group(0)]
    return max(matches, key=len) if matches else None


def _engine_of(data: dict) -> str:
    if "chain_pair_gpde" in data or "chain_pair_iptm_global" in data:
        return "protenix"
    if "chain_ids" in data and "chain_pair_iptm" in data:
        return "alphafold-server"
    if "chain_pair_iptm" in data:
        return "alphafold3"
    if "complex_plddt" in data or "protein_iptm" in data:
        return "boltz"
    # ColabFold puts the matrix, the per-residue pLDDT and the scores in one
    # file, which no other engine does — and the log line names the engine, so
    # calling it "generic" was a small lie about a file we recognise exactly.
    if {"max_pae", "plddt", "pae"} <= set(data):
        return "colabfold"
    return "generic"
