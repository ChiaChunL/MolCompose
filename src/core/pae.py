"""Chain-pair ipSAE scoring from predicted aligned error (PAE) matrices.

ipSAE (Dunbrack, bioRxiv 2025, 10.1101/2025.02.10.637595) aggregates
PAE-derived pTM terms over PAE-validated interchain residue pairs, with d0
scaled per aligned residue by its number of PAE-valid partners ("d0res", the
paper's recommended variant). This implementation follows the reference
ipsae.py (v4, MIT, Roland Dunbrack) for the protein-chain case; models with
ligands or modified residues (extra PAE tokens) are rejected explicitly.
"""

import json
from pathlib import Path

import numpy as np


def ptm_term(pae, d0):
    return 1.0 / (1.0 + (np.asarray(pae, dtype=float) / d0) ** 2)


def d0_array(counts):
    lengths = np.maximum(26.0, np.asarray(counts, dtype=float))
    return np.maximum(1.0, 1.24 * (lengths - 15.0) ** (1.0 / 3.0) - 1.8)


PAE_JSON_KEYS = ("pae", "predicted_aligned_error", "token_pair_pae")


def load_pae_matrix(path) -> np.ndarray:
    """Load a PAE matrix from JSON, NPZ, or an AlphaFold result pickle."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"PAE file does not exist: {path}")
    if path.suffix in (".pkl", ".pickle"):
        # AlphaFold2-Multimer and ColabFold keep the matrix only here. Read
        # through the restricted loader, which allows numpy's three
        # reconstruction globals and refuses everything else — unpickling is
        # code execution, and this file was found by searching a directory.
        from .pickled import load_arrays

        data = load_arrays(path)
        for key in PAE_JSON_KEYS:
            if key in data:
                return np.asarray(data[key], dtype=float)
        raise ValueError(
            f"no PAE matrix in {path.name} "
            f"(expected one of {', '.join(repr(key) for key in PAE_JSON_KEYS)})"
        )
    if path.suffix == ".npz":
        data = np.load(path)
        if "pae" in data:
            return np.asarray(data["pae"], dtype=float)
        raise ValueError(f"no 'pae' array in NPZ file: {path}")
    data = json.loads(path.read_text())
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]  # ColabFold wraps the dict in a list
    for key in PAE_JSON_KEYS:
        if isinstance(data, dict) and key in data:
            return np.asarray(data[key], dtype=float)
    raise ValueError(
        f"no PAE matrix found in {path} "
        f"(expected one of {', '.join(repr(key) for key in PAE_JSON_KEYS)})"
    )


# pDockQ2 sigmoid fit (Zhu, Shenoy, Kundrotas & Elofsson, Bioinformatics 2023,
# 10.1093/bioinformatics/btad424). Interface defined at 8 A between Cbeta atoms.
_PDOCKQ2_L, _PDOCKQ2_X0, _PDOCKQ2_K, _PDOCKQ2_B = 1.31, 84.733, 0.075, 0.005
PDOCKQ2_CUTOFF = 8.0
PDOCKQ2_D0 = 10.0

# LIS (Local Interaction Score; Kim et al., bioRxiv 2024, 10.1101/2024.02.19.580970)
# averages (cutoff - PAE)/cutoff over interchain pairs below the cutoff.
LIS_PAE_CUTOFF = 12.0


def pdockq2_score(mean_plddt: float, mean_ptm: float) -> float:
    """pDockQ2 from mean interface pLDDT (0-100) and mean PAE-derived pTM."""
    x = mean_plddt * mean_ptm
    return _PDOCKQ2_L / (1 + np.exp(-_PDOCKQ2_K * (x - _PDOCKQ2_X0))) + _PDOCKQ2_B


def lis_score(pae_block, cutoff: float = LIS_PAE_CUTOFF) -> float:
    """Local Interaction Score over one directed chain block of the PAE matrix."""
    values = np.asarray(pae_block, dtype=float).ravel()
    if values.size == 0:
        return 0.0
    valid = values[values < cutoff]
    if valid.size == 0:
        return 0.0
    return float(((cutoff - valid) / cutoff).mean())


def pair_scores(
    pae_matrix,
    residue_chains,
    cb_coords,
    plddt,
    pae_cutoff: float = 10.0,
) -> dict:
    """Per chain-pair ipSAE, pDockQ2 and LIS from PAE, Cbeta geometry and pLDDT.

    `cb_coords` are per-residue Cbeta (Calpha for glycine) coordinates and
    `plddt` per-residue confidence on the 0-100 scale, both in PAE row order.
    """
    pae = np.asarray(pae_matrix, dtype=float)
    chains = np.asarray(residue_chains)
    coords = np.asarray(cb_coords, dtype=float)
    confidence = np.asarray(plddt, dtype=float)
    if not (pae.shape[0] == len(chains) == len(coords) == len(confidence)):
        raise ValueError(
            f"PAE ({pae.shape[0]}), chains ({len(chains)}), coordinates "
            f"({len(coords)}) and pLDDT ({len(confidence)}) must describe the "
            "same residues"
        )
    ipsae = ipsae_scores(pae, chains, pae_cutoff)
    distances = np.sqrt(
        ((coords[:, None, :] - coords[None, :, :]) ** 2).sum(axis=2)
    )
    unique = list(dict.fromkeys(chains.tolist()))

    scores = {}
    for index_1, chain_1 in enumerate(unique):
        for chain_2 in unique[index_1 + 1 :]:
            rows = chains == chain_1
            cols = chains == chain_2
            close = np.outer(rows, cols) & (distances <= PDOCKQ2_CUTOFF)
            pair_key = f"{chain_1}-{chain_2}"
            entry = dict(ipsae.get(pair_key, {}))
            if close.any():
                interface = np.unique(np.concatenate(np.where(close)))
                mean_plddt = float(confidence[interface].mean())
                mean_ptm = float(ptm_term(pae[close], PDOCKQ2_D0).mean())
                entry["pdockq2"] = float(pdockq2_score(mean_plddt, mean_ptm))
                entry["interface_plddt"] = mean_plddt
            else:
                entry["pdockq2"] = 0.0
                entry["interface_plddt"] = None
            forward = lis_score(pae[np.outer(rows, cols)])
            backward = lis_score(pae[np.outer(cols, rows)])
            entry["lis"] = (forward + backward) / 2.0
            scores[pair_key] = entry
    return scores


def ipsae_scores(pae_matrix, residue_chains, pae_cutoff: float = 10.0) -> dict:
    """Per chain-pair ipSAE (d0res variant): both asymmetric values and the max."""
    pae = np.asarray(pae_matrix, dtype=float)
    chains = np.asarray(residue_chains)
    if pae.ndim != 2 or pae.shape[0] != pae.shape[1]:
        raise ValueError(f"PAE matrix must be square, got shape {pae.shape}")
    if pae.shape[0] != len(chains):
        raise ValueError(
            f"PAE matrix has {pae.shape[0]} tokens but the model has "
            f"{len(chains)} amino-acid residues; models with ligands, nucleic "
            "acids, or modified residues are not yet supported"
        )
    unique = list(dict.fromkeys(chains.tolist()))
    if len(unique) < 2:
        raise ValueError("ipSAE needs at least two protein chains")

    asym: dict = {}
    for chain_1 in unique:
        for chain_2 in unique:
            if chain_1 == chain_2:
                continue
            rows = chains == chain_1
            cols = chains == chain_2
            valid = np.outer(rows, cols) & (pae < pae_cutoff)
            d0_per_residue = d0_array(valid.sum(axis=1))
            best = 0.0
            for index in np.where(rows)[0]:
                row_valid = valid[index]
                if not row_valid.any():
                    continue
                score = float(ptm_term(pae[index, row_valid], d0_per_residue[index]).mean())
                best = max(best, score)
            asym[(chain_1, chain_2)] = best

    scores = {}
    for chain_1 in unique:
        for chain_2 in unique:
            if chain_1 >= chain_2:
                continue
            forward = asym[(chain_1, chain_2)]
            backward = asym[(chain_2, chain_1)]
            scores[f"{chain_1}-{chain_2}"] = {
                "asym_ab": forward,
                "asym_ba": backward,
                "max": max(forward, backward),
            }
    return scores
