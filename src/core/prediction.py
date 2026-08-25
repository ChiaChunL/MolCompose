"""Identify a structure's provenance and which confidence metrics it supports.

Different metrics need different inputs, and silently reporting one that does
not apply is worse than reporting nothing:

* an **experimental** structure supports none of them — its B-factors are
  temperature factors, not pLDDT;
* a **predicted** structure with only coordinates supports the pLDDT family
  (pLDDT, ipLDDT, pDockQ);
* a predicted structure **with a PAE matrix** additionally supports the
  PAE-derived scores (ipSAE, pDockQ2, LIS) — but only if that matrix and the
  model describe the same things: a ligand contributes one PAE token per heavy
  atom, so a protein-ligand model has more tokens than residues and the scores
  cannot be computed until token masking exists;
* DockQ needs neither — it needs a trusted *reference* structure.

This module answers "what can I compute for this file?" before anything is
computed, so the interface can show the user what is and is not available.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Companion-file patterns per predictor. Formatted with the structure file's
# stem, plus `base` and `sample` for predictors that name the PAE file after a
# different stem than the structure (see _stem_parts).
PAE_PATTERNS = {
    "alphafold-server": ("{base}_full_data_{index}.json", "{stem}_full_data_*.json",
                         "*_full_data_*.json"),
    "alphafold3": ("{base}_confidences.json",),
    "alphafold-db": ("{stem}-predicted_aligned_error*.json", "*predicted_aligned_error*.json"),
    # `{scored}` first, and it is the only pattern here that identifies a
    # replicate. ColabFold writes five ranks into one directory and names the
    # scores file by substitution rather than by suffix, so the wildcard below
    # returned rank 001's PAE for all five — silently, since every rank has the
    # same token count. Kept as a last resort for a directory holding one rank.
    "colabfold": ("{scored}.json", "{stem}_scores*.json", "*_scores_rank_*.json",
                  "{allof}.pickle"),
    "boltz": ("pae_{stem}.npz", "pae_*.npz"),
    "protenix": ("{base}_full_data_{sample}.json", "{base}_full_data_*.json"),
    # AlphaFold2-Multimer and Chai-1 name theirs by prefix substitution:
    #   unrelaxed_model_2_multimer_v3_pred_0.cif -> pae_model_2_...pred_0.json
    #   pred.model_idx_2.cif                     -> pae_model_idx_2.npz
    # Both put five models in one directory, so both had the same silent
    # wrong-replicate failure as ColabFold before `{tag}` existed.
    # `result_{tag}.pkl` is where a *local* AlphaFold2-Multimer run keeps the
    # matrix — that directory has the pickles, the PDBs, and no JSON carrying
    # any of it, so without this pattern the native output could not be read
    # at all. The JSON forms come from exports made afterwards.
    "af2-multimer": ("result_{tag}.pkl", "pae_{tag}.json", "pae_*.json"),
    "chai": ("pae_{tag}.npz", "pae_*.npz"),
    # The fallback, and the one that matters most: someone who unzips an
    # AlphaFold Server download has no reason to know that a `predictor`
    # option exists. Ordered most specific first, and index-matched before
    # wildcards so that opening model_2 does not silently score model_0.
    #
    # `*_summary_confidences_*.json` is deliberately absent. It sits beside
    # the real file, matches any loose "confidences" wildcard, and contains
    # chain-pair summaries rather than the PAE matrix — so a careless pattern
    # here fails at load time on a file that looks right.
    "generic": (
        "{base}_full_data_{index}.json",     # AlphaFold Server
        "{base}_full_data_{sample}.json",    # Protenix
        "pae_{stem}.npz",                    # Boltz
        "{base}_confidences.json",           # AlphaFold 3, local
        "{scored}.json",                     # ColabFold
        "pae_{tag}.json",                    # AlphaFold2-Multimer, exported
        "result_{tag}.pkl",                  # AlphaFold2-Multimer, native
        "{allof}.pickle",                    # ColabFold, native
        "pae_{tag}.npz",                     # Chai-1
        "{stem}-predicted_aligned_error*.json",  # AlphaFold DB
        "{stem}_pae.json",
        "{stem}.pae.json",
        "{base}_full_data_*.json",
        # Wildcards last, and the AlphaFold DB one included because a file
        # downloaded from the database is the most likely predicted structure
        # to arrive without anyone knowing a `predictor` option exists. Its
        # name has no "pae" in it, so the two patterns below never matched it
        # and the default found nothing at all.
        "*predicted_aligned_error*.json",
        "*pae*.json",
        "*pae*.npz",
    ),
}

# A trailing sample index, however the predictor spells it:
#   fold_x_model_0  ·  x_model_0  ·  x_sample_0  ·  x_model
_SAMPLE_SUFFIX = re.compile(r"^(?P<base>.+?)_(?:(?P<kind>model|sample)_)?(?P<index>\d+)$")
_BARE_MODEL = re.compile(r"^(?P<base>.+?)_model$")

# Prefixes a predictor puts on the *structure* and not on its companion files:
#   AlphaFold2  unrelaxed_model_2_… / relaxed_model_2_…  -> pae_model_2_…
#   Chai-1      pred.model_idx_2                         -> pae_model_idx_2
_STRUCTURE_PREFIXES = ("unrelaxed_", "relaxed_", "pred.")
# ColabFold substitutes in the middle instead, and keeps everything else:
#   x_unrelaxed_rank_002_…_model_4_seed_000 -> x_scores_rank_002_…_model_4_seed_000
_SCORE_INFIXES = ("_unrelaxed_", "_relaxed_")


def _tag(stem: str) -> str:
    for prefix in _STRUCTURE_PREFIXES:
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


def _allof(stem: str) -> str:
    """ColabFold's `..._unrelaxed_rank_001_...` -> `..._all_rank_001_...`.

    The native run keeps every array in one pickle named by that substitution,
    and it is the only file in the directory carrying the PAE matrix for a
    specific rank. Substituting rather than globbing matters for the same
    reason `{scored}` does: five ranks sit in one directory and a wildcard
    returns the first for all of them.
    """
    return stem.replace("_unrelaxed_", "_all_")


def _scored(stem: str) -> str:
    for infix in _SCORE_INFIXES:
        if infix in stem:
            return stem.replace(infix, "_scores_")
    # No substitution to make. Falling back to the stem itself would turn
    # `{scored}.json` into `{stem}.json`, which can match a neighbouring file
    # that is not a PAE matrix at all; `_scores` keeps the pattern meaningful
    # and harmless when nothing is named that way.
    return f"{stem}_scores"


def _stem_parts(stem: str) -> dict[str, str]:
    """Split a structure stem into the parts predictors name companion files by.

    Predictors do not derive the PAE file name from the structure's stem by
    suffixing, so the pieces have to be recovered:

        AlphaFold Server  fold_x_model_0.cif   -> fold_x_full_data_0.json
        Boltz-2           x_model_0.cif        -> pae_x_model_0.npz
        Protenix          x_sample_0.cif       -> x_full_data_sample_0.json
        AlphaFold 3       x_model.cif          -> x_confidences.json
        AlphaFold2        unrelaxed_model_2_…  -> pae_model_2_…
        Chai-1            pred.model_idx_2     -> pae_model_idx_2
        ColabFold         x_unrelaxed_rank_002_… -> x_scores_rank_002_…

    `index` is the bare number and `sample` the Protenix-style `sample_<n>`;
    both fall back to `*` so a pattern using them still matches something.
    `tag` and `scored` are the two substitution forms, and unlike the wildcards
    they identify a replicate — which is the whole point of having them, since
    five models in one directory otherwise all resolve to the first.
    """
    fixed = {"tag": _tag(stem), "scored": _scored(stem), "allof": _allof(stem)}
    match = _SAMPLE_SUFFIX.fullmatch(stem)
    if match:
        index = match["index"]
        sample = f"sample_{index}" if match["kind"] == "sample" else "*"
        return {"base": match["base"], "sample": sample, "index": index, **fixed}
    bare = _BARE_MODEL.fullmatch(stem)
    if bare:
        return {"base": bare["base"], "sample": "*", "index": "*", **fixed}
    return {"base": stem, "sample": "*", "index": "*", **fixed}

# Metrics grouped by what they require.
COORDINATE_METRICS = ("pLDDT", "ipLDDT", "pDockQ")
PAE_METRICS = ("ipSAE", "pDockQ2", "LIS")
REFERENCE_METRICS = ("DockQ", "Fnat", "iRMSD", "LRMSD")
STRUCTURE_METRICS = ("interface", "buried area", "ΔG/Kd", "typed interactions", "hot spots")


@dataclass(frozen=True)
class Capabilities:
    kind: str                       # "experimental" | "predicted" | "unknown"
    detail: str = ""                # experimental method, or how it was recognised
    pae_file: str | None = None
    # Reported beside the PAE because they are separate files, resolved
    # separately, and either can be found while the other is not. Showing only
    # one left "Find files" unable to say which half had failed.
    summary_file: str | None = None
    available: tuple[str, ...] = ()
    unavailable: dict[str, str] = field(default_factory=dict)  # metric -> reason

    @property
    def is_predicted(self) -> bool:
        return self.kind == "predicted"


def _ranked_model_name(path: Path) -> str | None:
    """What `ranked_2.pdb` is a copy of, from AlphaFold2's own ranking file.

    A local AlphaFold2-Multimer run writes each model twice: once under its
    name and once as `ranked_N.pdb`, ordered best first. The ranked copy is
    the one a user opens, because it is the one whose name says which is best
    — and it is the only file in the directory with no companion of its own,
    since every `result_*.pkl` is named for a model rather than a rank.

    `ranking_debug.json` holds the mapping and is written by the same run, so
    the copy can be traced back to the model it came from rather than left
    unresolvable. No file, or an index past the end, gives None: a guess here
    would attach another model's PAE matrix to this one, which is the failure
    the per-replicate patterns exist to prevent.
    """
    match = re.fullmatch(r"ranked_(\d+)", path.stem)
    if not match:
        return None
    ranking = path.parent / "ranking_debug.json"
    if not ranking.is_file():
        return None
    try:
        order = json.loads(ranking.read_text()).get("order")
    except (ValueError, OSError):
        return None
    index = int(match.group(1))
    if not isinstance(order, list) or index >= len(order):
        return None
    name = order[index]
    return name if isinstance(name, str) else None


def find_pae_file(structure_path, predictor: str = "generic") -> str | None:
    """Look next to the structure for the predictor's PAE/confidence file."""
    if not structure_path:
        return None
    path = Path(structure_path)
    folder = path.parent
    if not folder.is_dir():
        return None
    stem = _ranked_model_name(path) or path.stem
    parts = _stem_parts(stem)
    patterns = PAE_PATTERNS.get(predictor, ()) + PAE_PATTERNS["generic"]
    for pattern in patterns:
        for candidate in sorted(folder.glob(pattern.format(stem=stem, **parts))):
            if candidate.is_file() and candidate != path:
                return str(candidate)
    return None


def find_summary_file(structure_path, predictor: str = "generic") -> str | None:
    """Look next to the structure for the predictor's ipTM/pTM summary file.

    A separate search from `find_pae_file` because they are separate files
    everywhere except Boltz-2, and because the two sit side by side with
    names a wildcard cannot safely tell apart: AlphaFold 3 writes
    `x_confidences.json` for the matrix and `x_summary_confidences.json` for
    the scores, and Protenix spells its summary with the singular
    "confidence" while AlphaFold spells it plural.
    """
    from .summary import SUMMARY_PATTERNS

    if not structure_path:
        return None
    path = Path(structure_path)
    folder = path.parent
    if not folder.is_dir():
        return None
    stem = _ranked_model_name(path) or path.stem
    parts = _stem_parts(stem)
    patterns = SUMMARY_PATTERNS.get(predictor, ()) + SUMMARY_PATTERNS["generic"]
    for pattern in patterns:
        for candidate in sorted(folder.glob(pattern.format(stem=stem, **parts))):
            if candidate.is_file() and candidate != path:
                return str(candidate)
    return None


def expected_names(structure_path, predictor: str = "generic", kind: str = "pae"):
    """The filenames a lookup would accept, most specific first.

    So a "not found" can say what it wanted. Reporting only the absence sends
    the reader looking for a wrong setting when the honest answer is usually
    that the file was never copied out of the prediction's output folder —
    AlphaFold 3 splits its numbers across two files and it is the *summary* one
    that carries ipTM and pTM.

    Wildcards are dropped: they are how the search works, not something a user
    can go and look for.
    """
    from .summary import SUMMARY_PATTERNS

    path = Path(structure_path) if structure_path else None
    if path is None:
        return ()
    table = PAE_PATTERNS if kind == "pae" else SUMMARY_PATTERNS
    patterns = table.get(predictor, ()) + table["generic"]
    parts = _stem_parts(path.stem)
    names, seen = [], set()
    for pattern in patterns:
        name = pattern.format(stem=path.stem, **parts)
        if "*" in name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return tuple(names)


def assess(
    experimental_method: str | None,
    has_bfactors: bool,
    plddt_scale: str | None = None,
    pae_file: str | None = None,
    summary_file: str | None = None,
    pae_tokens: int | None = None,
    residue_count: int | None = None,
    pae_error: str | None = None,
    bfactor_issue: str | None = None,
) -> Capabilities:
    """Decide which metrics apply, and give a reason for each that does not.

    A PAE file only earns the PAE-derived metrics if it can actually deliver
    them, which takes two things beyond existing. `pae_error` carries the
    loader's complaint when the file is not a PAE matrix at all; `pae_tokens`
    is the matrix's dimension and `residue_count` the model's amino-acid
    residue count, which disagree whenever the model holds a ligand. Either
    way the metrics are reported unavailable here rather than promised and then
    refused by :mod:`molcompose.core.pae`.
    """
    available: list[str] = list(STRUCTURE_METRICS)
    unavailable: dict[str, str] = {}

    if experimental_method:
        for metric in COORDINATE_METRICS + PAE_METRICS:
            unavailable[metric] = (
                f"experimental structure ({experimental_method}): B-factors are "
                "temperature factors, not confidence values"
            )
        for metric in REFERENCE_METRICS:
            unavailable[metric] = (
                "this structure can serve as the reference; run molcompose dockq "
                "on the predicted model instead"
            )
        return Capabilities(
            kind="experimental",
            detail=experimental_method,
            available=tuple(available),
            unavailable=unavailable,
        )

    if not has_bfactors:
        reason = bfactor_issue or "the file carries no B-factor/pLDDT column"
        for metric in COORDINATE_METRICS + PAE_METRICS:
            unavailable[metric] = reason
        for metric in REFERENCE_METRICS:
            unavailable[metric] = "needs a reference structure (use molcompose dockq)"
        return Capabilities(
            kind="unknown",
            detail=bfactor_issue or "no B-factor column",
            available=tuple(available),
            unavailable=unavailable,
        )

    available.extend(COORDINATE_METRICS)
    mismatch = (
        pae_file
        and pae_tokens is not None
        and residue_count is not None
        and pae_tokens != residue_count
    )
    if pae_file and pae_error:
        for metric in PAE_METRICS:
            unavailable[metric] = f"the file cannot be read as a PAE matrix: {pae_error}"
    elif mismatch:
        for metric in PAE_METRICS:
            unavailable[metric] = (
                f"the PAE covers {pae_tokens} tokens but the model has "
                f"{residue_count} amino-acid residues — a ligand contributes one "
                "token per heavy atom, and ligand/modified-residue token masking "
                "is not supported"
            )
    elif pae_file:
        available.extend(PAE_METRICS)
    else:
        for metric in PAE_METRICS:
            unavailable[metric] = (
                "needs the prediction's PAE matrix (AlphaFold *_full_data_*.json, "
                "ColabFold *_scores*.json or Boltz pae_*.npz) — pass it to "
                "molcompose ipsae"
            )
    for metric in REFERENCE_METRICS:
        unavailable[metric] = "needs a reference structure (use molcompose dockq)"

    detail = f"pLDDT on the {plddt_scale} scale" if plddt_scale else "B-factors look like pLDDT"
    return Capabilities(
        kind="predicted",
        detail=detail,
        pae_file=pae_file,
        summary_file=summary_file,
        available=tuple(available),
        unavailable=unavailable,
    )
