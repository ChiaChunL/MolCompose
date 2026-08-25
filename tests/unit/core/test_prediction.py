from pathlib import Path

import pytest

from src.core.prediction import (
    COORDINATE_METRICS,
    PAE_METRICS,
    REFERENCE_METRICS,
    STRUCTURE_METRICS,
    assess,
    find_pae_file,
)


def test_experimental_structures_support_no_confidence_metric():
    caps = assess("X-RAY DIFFRACTION", has_bfactors=True)
    assert caps.kind == "experimental"
    assert not caps.is_predicted
    assert set(caps.available) == set(STRUCTURE_METRICS)
    for metric in COORDINATE_METRICS + PAE_METRICS:
        assert "temperature factors" in caps.unavailable[metric]


def test_predicted_without_pae_supports_only_the_plddt_family():
    caps = assess(None, has_bfactors=True, plddt_scale="0-100")
    assert caps.is_predicted
    assert set(COORDINATE_METRICS) <= set(caps.available)
    assert not set(PAE_METRICS) & set(caps.available)
    for metric in PAE_METRICS:
        assert "PAE matrix" in caps.unavailable[metric]
    assert "0-100" in caps.detail


def test_predicted_with_pae_unlocks_the_pae_metrics():
    caps = assess(None, has_bfactors=True, plddt_scale="0-1", pae_file="/tmp/x.json")
    assert set(PAE_METRICS) <= set(caps.available)
    assert caps.pae_file == "/tmp/x.json"
    assert not set(PAE_METRICS) & set(caps.unavailable)


def test_matching_token_and_residue_counts_still_unlock_the_pae_metrics():
    caps = assess(
        None, has_bfactors=True, pae_file="/tmp/x.json", pae_tokens=306, residue_count=306
    )
    assert set(PAE_METRICS) <= set(caps.available)


def test_a_ligands_extra_pae_tokens_withdraw_the_pae_metrics():
    caps = assess(
        None, has_bfactors=True, pae_file="/tmp/x.json", pae_tokens=341, residue_count=306
    )
    assert not set(PAE_METRICS) & set(caps.available)
    for metric in PAE_METRICS:
        reason = caps.unavailable[metric]
        assert "341 tokens" in reason and "306 amino-acid residues" in reason
        assert "ligand" in reason
    # The file was found, and saying so is still useful.
    assert caps.pae_file == "/tmp/x.json"
    assert set(COORDINATE_METRICS) <= set(caps.available)


def test_a_file_that_is_not_a_pae_matrix_withdraws_the_pae_metrics():
    caps = assess(
        None,
        has_bfactors=True,
        pae_file="/tmp/summary.json",
        pae_error="no PAE matrix found in /tmp/summary.json (expected one of 'pae')",
    )
    assert not set(PAE_METRICS) & set(caps.available)
    for metric in PAE_METRICS:
        reason = caps.unavailable[metric]
        assert "cannot be read as a PAE matrix" in reason
        assert "/tmp/summary.json" in reason  # the loader's message names the file
    assert set(COORDINATE_METRICS) <= set(caps.available)


def test_structure_without_bfactors_is_unknown_provenance():
    caps = assess(None, has_bfactors=False)
    assert caps.kind == "unknown"
    assert "no B-factor" in caps.unavailable["pLDDT"]


def test_reference_metrics_always_explain_they_need_a_reference():
    for caps in (
        assess("X-RAY DIFFRACTION", True),
        assess(None, True),
        assess(None, False),
    ):
        for metric in REFERENCE_METRICS:
            assert "reference" in caps.unavailable[metric]


def test_structure_metrics_are_always_available():
    for caps in (assess("EM", True), assess(None, True), assess(None, False)):
        assert set(STRUCTURE_METRICS) <= set(caps.available)


def test_pae_discovery_finds_alphafold_server_output(tmp_path):
    (tmp_path / "fold_x_model_0.cif").write_text("x")
    target = tmp_path / "fold_x_full_data_0.json"
    target.write_text("{}")
    found = find_pae_file(tmp_path / "fold_x_model_0.cif", "alphafold-server")
    assert found == str(target)


def test_pae_discovery_finds_boltz_and_colabfold_output(tmp_path):
    (tmp_path / "cx_model_0.cif").write_text("x")
    boltz = tmp_path / "pae_cx_model_0.npz"
    boltz.write_text("x")
    assert find_pae_file(tmp_path / "cx_model_0.cif", "boltz") == str(boltz)

    other = tmp_path / "sub"
    other.mkdir()
    (other / "p.pdb").write_text("x")
    scores = other / "p_scores_rank_001.json"
    scores.write_text("{}")
    assert find_pae_file(other / "p.pdb", "colabfold") == str(scores)


def test_pae_discovery_matches_the_protenix_sample_number(tmp_path):
    # Protenix names the PAE file after a different stem than the structure,
    # and writes five samples side by side; each must find its own.
    for number in range(3):
        (tmp_path / f"cplx_sample_{number}.cif").write_text("x")
        (tmp_path / f"cplx_full_data_sample_{number}.json").write_text("{}")
    for number in range(3):
        found = find_pae_file(tmp_path / f"cplx_sample_{number}.cif", "protenix")
        assert found == str(tmp_path / f"cplx_full_data_sample_{number}.json")


def test_pae_discovery_returns_none_when_absent(tmp_path):
    (tmp_path / "lonely.pdb").write_text("x")
    assert find_pae_file(tmp_path / "lonely.pdb") is None
    assert find_pae_file(None) is None
    assert find_pae_file(tmp_path / "missing" / "x.pdb") is None


# -- companion-file discovery across predictor layouts ------------------------

def _layout(tmp_path, files):
    for name in files:
        (tmp_path / name).write_text("{}")
    return tmp_path


@pytest.mark.parametrize(
    ("structure", "files", "expected"),
    [
        # AlphaFold Server, as it comes out of the downloaded zip.
        (
            "fold_x_model_2.cif",
            ["fold_x_model_2.cif", "fold_x_full_data_0.json", "fold_x_full_data_2.json",
             "fold_x_summary_confidences_2.json"],
            "fold_x_full_data_2.json",
        ),
        # Protenix names the sample differently again.
        (
            "x_sample_4.cif",
            ["x_sample_4.cif", "x_full_data_sample_0.json", "x_full_data_sample_4.json"],
            "x_full_data_sample_4.json",
        ),
        ("x_model_3.cif", ["x_model_3.cif", "pae_x_model_3.npz"], "pae_x_model_3.npz"),
        ("x_model.cif", ["x_model.cif", "x_confidences.json"], "x_confidences.json"),
    ],
)
def test_generic_discovery_handles_every_predictor_layout(
    tmp_path, structure, files, expected
):
    """A user who unzips a download has no reason to know `predictor` exists.

    Auto-discovery therefore has to work without it, across the four layouts
    the supported predictors actually write.
    """
    folder = _layout(tmp_path, files)
    found = find_pae_file(str(folder / structure), "generic")
    assert found is not None and Path(found).name == expected


def test_discovery_matches_the_sample_index_rather_than_the_first_file():
    """The dangerous failure: right shape, wrong sample.

    Scoring model 4 against model 0's PAE raises no error and produces a
    plausible number, so index matching is asserted rather than assumed.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        for index in range(5):
            (folder / f"fold_x_model_{index}.cif").write_text("")
            (folder / f"fold_x_full_data_{index}.json").write_text("{}")
        for index in range(5):
            found = find_pae_file(str(folder / f"fold_x_model_{index}.cif"), "generic")
            assert Path(found).name == f"fold_x_full_data_{index}.json"


def test_summary_confidences_is_never_chosen():
    """It sits beside the real file and matches loose wildcards, but has no PAE."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        (folder / "fold_x_model_0.cif").write_text("")
        (folder / "fold_x_summary_confidences_0.json").write_text("{}")
        assert find_pae_file(str(folder / "fold_x_model_0.cif"), "generic") is None


def _colabfold_run(folder):
    """Five ranks side by side, as ColabFold writes them.

    The rank number and the model number move independently — rank 002 is
    model 4 here — so a pattern that matched only one of them would still
    cross-match.
    """
    ranks = {"001": "3", "002": "4", "003": "1", "004": "2", "005": "5"}
    for rank, model in ranks.items():
        tail = f"rank_{rank}_alphafold2_multimer_v3_model_{model}_seed_000"
        (folder / f"cplx_unrelaxed_{tail}.pdb").write_text("x")
        (folder / f"cplx_scores_{tail}.json").write_text("{}")
    return ranks


def test_each_colabfold_rank_finds_its_own_scores_file(tmp_path):
    """The failure this prevents is silent, which is why it is worth a test.

    Every rank in a ColabFold run has the same token count, so the wrong
    file loads without complaint and ipSAE, pDockQ2 and LIS come back for a
    model the user is not looking at. Before `{scored}` existed, all five
    resolved to rank 001.
    """
    ranks = _colabfold_run(tmp_path)
    for rank, model in ranks.items():
        tail = f"rank_{rank}_alphafold2_multimer_v3_model_{model}_seed_000"
        found = find_pae_file(tmp_path / f"cplx_unrelaxed_{tail}.pdb", "colabfold")
        assert found == str(tmp_path / f"cplx_scores_{tail}.json")
        # And without the predictor named, which is how most people open one.
        assert find_pae_file(tmp_path / f"cplx_unrelaxed_{tail}.pdb") == found


def test_relaxed_colabfold_output_resolves_too(tmp_path):
    """ColabFold names the file `relaxed_` once amber relaxation has run."""
    tail = "rank_001_alphafold2_multimer_v3_model_3_seed_000"
    (tmp_path / f"cplx_relaxed_{tail}.pdb").write_text("x")
    scores = tmp_path / f"cplx_scores_{tail}.json"
    scores.write_text("{}")
    assert find_pae_file(tmp_path / f"cplx_relaxed_{tail}.pdb") == str(scores)


def test_each_af2_multimer_model_finds_its_own_pae(tmp_path):
    """AlphaFold2 drops the `unrelaxed_` prefix on companion files."""
    for number in range(1, 6):
        tail = f"model_{number}_multimer_v3_pred_0"
        (tmp_path / f"unrelaxed_{tail}.cif").write_text("x")
        (tmp_path / f"pae_{tail}.json").write_text("{}")
    for number in range(1, 6):
        tail = f"model_{number}_multimer_v3_pred_0"
        found = find_pae_file(tmp_path / f"unrelaxed_{tail}.cif", "af2-multimer")
        assert found == str(tmp_path / f"pae_{tail}.json")
        assert find_pae_file(tmp_path / f"unrelaxed_{tail}.cif") == found


def test_each_chai_model_finds_its_own_pae(tmp_path):
    """Chai-1 prefixes the structure with `pred.` and the matrix with `pae_`."""
    for number in range(5):
        (tmp_path / f"pred.model_idx_{number}.cif").write_text("x")
        (tmp_path / f"pae_model_idx_{number}.npz").write_text("x")
    for number in range(5):
        found = find_pae_file(tmp_path / f"pred.model_idx_{number}.cif", "chai")
        assert found == str(tmp_path / f"pae_model_idx_{number}.npz")
        assert find_pae_file(tmp_path / f"pred.model_idx_{number}.cif") == found


def test_an_alphafold_db_download_is_found_without_naming_the_predictor(tmp_path):
    """The likeliest predicted structure to arrive with no options given.

    Its companion is `…-predicted_aligned_error_v6.json`, which contains no
    "pae" — so every generic pattern missed it and the default reported that
    the model had no PAE at all.
    """
    structure = tmp_path / "AF-P04637-F1-model_v6.cif"
    structure.write_text("x")
    matrix = tmp_path / "AF-P04637-F1-predicted_aligned_error_v6.json"
    matrix.write_text("{}")
    assert find_pae_file(structure) == str(matrix)
    assert find_pae_file(structure, "alphafold-db") == str(matrix)


def test_the_scored_fallback_cannot_grab_an_unrelated_neighbour(tmp_path):
    """`{scored}` degrades to `<stem>_scores`, never to `<stem>`.

    Falling back to the stem itself would make `{scored}.json` match any
    same-named JSON sitting beside the structure — a ranking file, a config —
    and that file would then fail to load as a matrix.
    """
    (tmp_path / "plain.cif").write_text("x")
    (tmp_path / "plain.json").write_text("{}")
    assert find_pae_file(tmp_path / "plain.cif") is None


def test_a_missing_companion_can_name_what_it_wanted(tmp_path):
    """"not found" alone sends the reader hunting for a wrong setting.

    The usual cause is that the file was never copied out of the prediction's
    output folder. AlphaFold 3 splits its numbers in two — the PAE lives in
    <name>_confidences.json and ipTM/pTM in <name>_summary_confidences.json —
    so a folder holding only the first has the matrix and can never have the
    scores, however the predictor is set.
    """
    from src.core.prediction import expected_names

    structure = tmp_path / "predicted_complex.cif"
    structure.write_text("x")
    summary = expected_names(structure, "alphafold3", "summary")
    assert summary[0] == "predicted_complex_summary_confidences.json"
    pae = expected_names(structure, "alphafold3", "pae")
    assert pae[0] == "predicted_complex_confidences.json"
    # Wildcards are how the search works, not something anyone can go and look
    # for, so they are not offered as an answer.
    assert not any("*" in name for name in summary + pae)
    assert expected_names(None, "alphafold3", "summary") == ()


def test_a_ranked_copy_resolves_to_the_model_it_is_a_copy_of(tmp_path):
    """`ranked_0.pdb` has no companion of its own; the ranking file says whose.

    A local AlphaFold2-Multimer run writes each model twice, once under its
    name and once as `ranked_N.pdb` ordered best first. The ranked copy is the
    one a user opens — its name is the only one that says which model is best
    — and every `result_*.pkl` beside it is named for a model rather than a
    rank, so nothing paired with it.
    """
    import json

    from src.core.prediction import find_pae_file

    (tmp_path / "ranking_debug.json").write_text(
        json.dumps({"order": ["model_4_multimer_v3_pred_0",
                              "model_1_multimer_v3_pred_0"]})
    )
    for name in ("model_4_multimer_v3_pred_0", "model_1_multimer_v3_pred_0"):
        (tmp_path / f"result_{name}.pkl").write_bytes(b"")
        (tmp_path / f"unrelaxed_{name}.pdb").write_text("")
    for index in (0, 1):
        (tmp_path / f"ranked_{index}.pdb").write_text("")

    assert find_pae_file(str(tmp_path / "ranked_0.pdb")).endswith(
        "result_model_4_multimer_v3_pred_0.pkl"
    )
    assert find_pae_file(str(tmp_path / "ranked_1.pdb")).endswith(
        "result_model_1_multimer_v3_pred_0.pkl"
    )


def test_a_ranked_copy_with_no_ranking_file_resolves_to_nothing(tmp_path):
    """Guessing would attach another model's matrix to this one."""
    from src.core.prediction import find_pae_file

    (tmp_path / "result_model_1_multimer_v3_pred_0.pkl").write_bytes(b"")
    (tmp_path / "ranked_0.pdb").write_text("")
    assert find_pae_file(str(tmp_path / "ranked_0.pdb")) is None
