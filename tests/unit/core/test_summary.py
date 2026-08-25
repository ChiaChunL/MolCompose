"""Reading ipTM out of five engines that agree on almost nothing.

The five layouts are not variations on a theme — the file name, the key names
and the shape of the answer all differ, and two of the five cannot answer the
question being asked at all. These tests use the exact structures the engines
write, transcribed from the panel in fixtures/predictions/.
"""

import json

import pytest

from src.core.summary import parse

AF3 = {
    "chain_iptm": [0.93, 0.93], "chain_pair_iptm": [[0.92, 0.93], [0.93, 0.9]],
    "chain_pair_pae_min": [[0.76, 0.79], [0.79, 0.76]], "chain_ptm": [0.92, 0.9],
    "fraction_disordered": 0.0, "has_clash": 0.0,
    "iptm": 0.93, "ptm": 0.94, "ranking_score": 0.93,
}
AF_SERVER = dict(AF3, chain_ids=["A"] * 110 + ["D"] * 89)
PROTENIX = {
    "plddt": 95.78, "gpde": 0.33, "ptm": 0.964, "iptm": 0.958,
    "chain_gpde": [0.32, 0.34], "chain_pair_gpde": [[0.0, 0.35], [0.35, 0.0]],
    "chain_ptm": [0.955, 0.942], "chain_iptm": [0.958, 0.958],
    "chain_pair_iptm": [[0.0, 0.958], [0.958, 0.0]],
    "chain_pair_iptm_global": [[0.0, 0.958], [0.958, 0.0]],
}
BOLTZ = {
    "confidence_score": 0.965, "ptm": 0.9647, "iptm": 0.9574, "ligand_iptm": 0.0,
    "protein_iptm": 0.9574, "complex_plddt": 0.967, "complex_iplddt": 0.971,
}
AF2MM = {
    "model_1_multimer_v3_pred_0": {"iptm": 0.9369, "ptm": 0.9},
    "model_2_multimer_v3_pred_0": {"iptm": 0.9341, "ptm": 0.89},
    "model_3_multimer_v3_pred_0": {"iptm": 0.9307, "ptm": 0.88},
}


def write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


@pytest.mark.parametrize(
    ("name", "payload", "engine"),
    [
        ("x_summary_confidences.json", AF3, "alphafold3"),
        ("x_summary_confidences_0.json", AF_SERVER, "alphafold-server"),
        ("x_summary_confidence_sample_0.json", PROTENIX, "protenix"),
    ],
)
def test_the_three_engines_that_report_per_pair_do(tmp_path, name, payload, engine):
    summary = parse(write(tmp_path, name, payload))
    assert summary.engine == engine
    assert summary.has_pairwise
    assert summary.pair(0, 1) == pytest.approx(payload["chain_pair_iptm"][0][1])


def test_boltz_reports_only_a_whole_complex_figure(tmp_path):
    """Which must not be passed off as an interface score."""
    summary = parse(write(tmp_path, "confidence_x_model_0.json", BOLTZ))
    assert summary.engine == "boltz"
    assert not summary.has_pairwise
    assert summary.pair(0, 1) is None
    assert summary.iptm == pytest.approx(0.9574)


def test_boltz_falls_back_to_the_protein_only_figure(tmp_path):
    """With a ligand present the two differ, and a protein interface wants this one."""
    payload = dict(BOLTZ)
    del payload["iptm"]
    payload["protein_iptm"] = 0.81
    assert parse(write(tmp_path, "confidence_x.json", payload)).iptm == pytest.approx(0.81)


def test_af2_multimer_indexes_one_file_by_model_name(tmp_path):
    """One file covers the whole run, so the stem picks the entry."""
    path = write(tmp_path, "iptm_ptm.json", AF2MM)
    assert parse(path, "pae_model_2_multimer_v3_pred_0").iptm == pytest.approx(0.9341)
    assert parse(path, "pae_model_3_multimer_v3_pred_0").iptm == pytest.approx(0.9307)


def test_af2_multimer_refuses_rather_than_guess(tmp_path):
    """Falling back to the first entry would report another model's score."""
    path = write(tmp_path, "iptm_ptm.json", AF2MM)
    with pytest.raises(ValueError, match="keyed by model name"):
        parse(path, "some_unrelated_structure")


def test_a_single_entry_needs_no_matching(tmp_path):
    path = write(tmp_path, "iptm_ptm.json", {"model_1": {"iptm": 0.5, "ptm": 0.6}})
    assert parse(path, "").iptm == pytest.approx(0.5)


def test_a_pae_file_handed_here_by_mistake_says_so(tmp_path):
    """The PAE and the summary sit side by side with confusable names."""
    path = write(tmp_path, "x_confidences.json", {"pae": [[0, 1], [1, 0]],
                                                 "token_chain_ids": ["A", "B"]})
    with pytest.raises(ValueError, match="may be a PAE file"):
        parse(path)


def test_a_missing_file_is_named(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        parse(tmp_path / "nothing.json")


def test_protenix_zero_diagonal_is_not_mistaken_for_a_score(tmp_path):
    """Protenix writes 0.0 on the diagonal where AF3 writes the self-ipTM."""
    summary = parse(write(tmp_path, "x_summary_confidence_sample_0.json", PROTENIX))
    assert summary.pair(0, 0) == 0.0
    assert summary.pair(0, 1) == pytest.approx(0.958)


def test_colabfold_scores_file_doubles_as_the_summary(tmp_path):
    """ColabFold puts ipTM, pTM and the PAE matrix in one file.

    It reports no per-chain-pair breakdown, and `chain_pair_iptm` must stay
    None rather than borrowing the whole-complex figure: on more than two
    chains the global number is not a statement about any one interface.
    """
    from src.core.prediction import find_pae_file, find_summary_file
    from src.core.summary import parse

    tail = "rank_002_alphafold2_multimer_v3_model_4_seed_000"
    (tmp_path / f"cplx_unrelaxed_{tail}.pdb").write_text("x")
    scores = tmp_path / f"cplx_scores_{tail}.json"
    scores.write_text('{"ptm": 0.93, "iptm": 0.92, "pae": [[0.5, 1.0], [1.0, 0.5]]}')

    structure = tmp_path / f"cplx_unrelaxed_{tail}.pdb"
    assert find_summary_file(structure, "colabfold") == str(scores)
    # And with no predictor named, which is the only way `molcompose ipsae`
    # ever asks: it has no idea which engine produced the open model. Testing
    # only the named form is what let the ColabFold ipTM stay unreported after
    # the pattern was added.
    assert find_summary_file(structure) == str(scores)
    # Same file serves both roles, which is ColabFold's layout, not an error.
    assert find_pae_file(structure, "colabfold") == str(scores)

    summary = parse(scores)
    assert summary.iptm == 0.92
    assert summary.ptm == 0.93
    assert summary.chain_pair_iptm is None
    assert summary.has_pairwise is False


def _chai_npz(path, iptm=0.9363, ptm=0.9709, off=(0.8960, 0.9363),
              diagonal=(0.9559, 0.9582)):
    """Chai-1's layout: every array carries a leading batch axis of 1."""
    import numpy as np

    matrix = [[diagonal[0], off[0]], [off[1], diagonal[1]]]
    np.savez(
        path,
        aggregate_score=np.array([0.9432], dtype="float32"),
        ptm=np.array([ptm], dtype="float32"),
        iptm=np.array([iptm], dtype="float32"),
        per_chain_ptm=np.array([list(diagonal)], dtype="float32"),
        per_chain_pair_iptm=np.array([matrix], dtype="float32"),
        has_inter_chain_clashes=np.array([False]),
    )
    return path


def test_chai_scores_npz_is_read_as_a_summary(tmp_path):
    """The only non-JSON summary of the eight engines.

    Its per-chain-pair ipTM was sitting unread because the parser was
    JSON-only, so a Chai-1 model reported no ipTM at all.
    """
    from src.core.summary import parse

    npz = _chai_npz(tmp_path / "scores.model_idx_2.npz")
    summary = parse(npz)
    assert summary.engine == "chai"
    assert summary.iptm == pytest.approx(0.9363, abs=1e-4)
    assert summary.ptm == pytest.approx(0.9709, abs=1e-4)
    assert summary.has_pairwise is True


def test_chai_pair_ipTM_does_not_depend_on_chain_order(tmp_path):
    """Chai's matrix is asymmetric, unlike AlphaFold 3's and Protenix's.

    Its two off-diagonal values differ, so indexing one of them would report
    a number that depends on which chain the caller named first. Taking the
    larger reproduces Chai's own convention: its whole-complex ipTM equals the
    larger of the two on all five samples of the reference panel.
    """
    from src.core.summary import parse

    summary = parse(_chai_npz(tmp_path / "scores.model_idx_0.npz"))
    assert summary.pair(0, 1) == summary.pair(1, 0)
    assert summary.pair(0, 1) == pytest.approx(summary.iptm, abs=1e-4)
    # The raw matrix is kept as the file wrote it, asymmetry included; only
    # the accessor resolves the direction.
    assert summary.chain_pair_iptm[0][1] != summary.chain_pair_iptm[1][0]


def test_a_symmetric_matrix_is_unaffected_by_the_direction_rule():
    """AlphaFold 3 and Protenix are symmetric, so max() must change nothing."""
    from pathlib import Path

    from src.core.summary import Summary

    matrix = ((0.92, 0.93), (0.93, 0.90))
    summary = Summary(0.93, 0.94, matrix, Path("x.json"), "alphafold3")
    assert summary.pair(0, 1) == 0.93
    assert summary.pair(1, 0) == 0.93


def test_chai_npz_without_any_score_is_rejected(tmp_path):
    """A PAE npz sits beside the summary and must not be mistaken for one."""
    import numpy as np

    from src.core.summary import parse

    path = tmp_path / "pae_model_idx_0.npz"
    np.savez(path, pae=np.zeros((3, 3), dtype="float32"))
    with pytest.raises(ValueError, match="holds no ipTM"):
        parse(path)


def test_a_corrupt_npz_is_a_readable_error(tmp_path):
    from src.core.summary import parse

    path = tmp_path / "scores.model_idx_0.npz"
    path.write_bytes(b"not an npz at all")
    with pytest.raises(ValueError, match="not a readable NPZ"):
        parse(path)


def test_chai_summary_is_found_per_replicate(tmp_path):
    """Five models in one directory; each must find its own scores file."""
    from src.core.prediction import find_summary_file

    for number in range(5):
        (tmp_path / f"pred.model_idx_{number}.cif").write_text("x")
        _chai_npz(tmp_path / f"scores.model_idx_{number}.npz")
    for number in range(5):
        structure = tmp_path / f"pred.model_idx_{number}.cif"
        expected = str(tmp_path / f"scores.model_idx_{number}.npz")
        assert find_summary_file(structure, "chai") == expected
        # And with no predictor named, which is how `molcompose ipsae` asks.
        assert find_summary_file(structure) == expected


# -- the engines this project actually ships ---------------------------------


def test_every_packaged_engine_yields_iptm_and_ptm():
    """The examples and the finders have to agree with each other.

    Each engine's native confidence file was renamed to one scheme when the
    examples were packaged — `<case>_seed-N_model-M_<kind>` — and two of the
    patterns still described only the native names. AlphaFold2-Multimer's
    `_summary.json` and Chai-1's `_ranking.json` were therefore invisible to
    the software that ships beside them: the panel offered "Detect
    automatically", found no summary, and reported no ipTM or pTM for a file
    sitting in the same directory as the model.

    Chai-1 needed the parser too, not just the pattern: its per-model ranking
    file nests the two numbers under `ptm_scores`.
    """
    from pathlib import Path

    from src.core.prediction import find_pae_file, find_summary_file
    from src.core.summary import parse as parse_summary

    root = Path(__file__).parents[3] / "examples/data/1brs/predictions"
    if not root.is_dir():  # the examples are not beside every checkout
        return
    engines = sorted(path.name for path in root.iterdir() if path.is_dir())
    assert engines, "no packaged predictions to check"
    for engine in engines:
        folder = root / engine
        # `ranked_N.pdb` is AlphaFold2-Multimer's copy of a model it also
        # writes under its own name, and only `ranking_debug.json` says which
        # one — so it has no companion file of its own to find. The named
        # models are what a pattern can resolve.
        model = next(
            (
                p
                for p in sorted(folder.iterdir())
                if p.suffix in (".cif", ".pdb") and not p.name.startswith("ranked_")
            ),
            None,
        )
        assert model is not None, f"{engine} packages no model"
        assert find_pae_file(str(model)), f"{engine}: no PAE file found"
        found = find_summary_file(str(model))
        assert found, f"{engine}: no summary file found"
        result = parse_summary(found)
        assert result.iptm is not None, f"{engine}: summary carries no ipTM"
        assert result.ptm is not None, f"{engine}: summary carries no pTM"
