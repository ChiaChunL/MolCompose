import json

import numpy as np
import pytest

from src.core.pae import d0_array, ipsae_scores, load_pae_matrix, ptm_term


def test_ptm_term_matches_reference_formula():
    assert ptm_term(4.0, 1.0) == pytest.approx(1.0 / 17.0)
    assert ptm_term(0.0, 2.0) == pytest.approx(1.0)


def test_d0_clamps_small_counts_to_one():
    assert d0_array([0, 5, 26]).tolist() == pytest.approx([1.0, 1.0, 1.0], abs=1e-6)
    # L=100: 1.24*(85)^(1/3) - 1.8
    assert d0_array([100])[0] == pytest.approx(1.24 * 85 ** (1 / 3) - 1.8)


def test_ipsae_hand_computed_two_chain_case():
    chains = ["A", "A", "B", "B"]
    pae = np.full((4, 4), 30.0)
    pae[0, 2], pae[0, 3] = 4.0, 20.0   # A res0 -> B: one valid pair
    pae[1, 2], pae[1, 3] = 6.0, 8.0    # A res1 -> B: two valid pairs
    pae[2, 0], pae[2, 1] = 3.0, 30.0   # B res0 -> A: one valid pair
    scores = ipsae_scores(pae, chains, pae_cutoff=10.0)
    pair = scores["A-B"]
    # d0 clamps to 1.0 at these sizes: row0 = ptm(4)=1/17; row1 = mean(1/37, 1/65)
    assert pair["asym_ab"] == pytest.approx(1.0 / 17.0)
    assert pair["asym_ba"] == pytest.approx(1.0 / 10.0)
    assert pair["max"] == pytest.approx(0.1)


def test_ipsae_rejects_token_mismatch():
    with pytest.raises(ValueError, match="amino-acid residues"):
        ipsae_scores(np.zeros((3, 3)), ["A", "B"])


def test_ipsae_rejects_single_chain():
    with pytest.raises(ValueError, match="two protein chains"):
        ipsae_scores(np.zeros((2, 2)), ["A", "A"])


def test_load_pae_from_json_variants(tmp_path):
    direct = tmp_path / "a.json"
    direct.write_text(json.dumps({"pae": [[0, 1], [1, 0]]}))
    assert load_pae_matrix(direct).shape == (2, 2)
    colabfold = tmp_path / "b.json"
    colabfold.write_text(json.dumps([{"predicted_aligned_error": [[0, 2], [2, 0]]}]))
    assert load_pae_matrix(colabfold)[0, 1] == 2.0
    protenix = tmp_path / "c.json"
    protenix.write_text(json.dumps({"token_pair_pae": [[0, 3], [3, 0]]}))
    assert load_pae_matrix(protenix)[0, 1] == 3.0


def test_load_pae_from_npz(tmp_path):
    target = tmp_path / "pae.npz"
    np.savez(target, pae=np.ones((3, 3)))
    assert load_pae_matrix(target).sum() == 9.0


def test_load_pae_reports_missing_key(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"plddt": [1, 2]}))
    with pytest.raises(ValueError, match="no PAE matrix"):
        load_pae_matrix(bad)


def test_pdockq2_matches_the_published_sigmoid():
    from src.core.pae import pdockq2_score

    # x = 90 * 0.8 = 72 -> 1.31/(1+exp(-0.075*(72-84.733))) + 0.005
    expected = 1.31 / (1 + np.exp(-0.075 * (72 - 84.733))) + 0.005
    assert pdockq2_score(90.0, 0.8) == pytest.approx(expected)


def test_lis_averages_scaled_low_pae_values():
    from src.core.pae import lis_score

    # Values below 12 contribute (12-v)/12; 15 is ignored.
    assert lis_score([[0.0, 6.0, 15.0]]) == pytest.approx((1.0 + 0.5) / 2)
    assert lis_score([[20.0, 30.0]]) == 0.0
    assert lis_score([]) == 0.0


def test_pair_scores_bundle_ipsae_pdockq2_and_lis():
    from src.core.pae import pair_scores

    chains = ["A", "A", "B", "B"]
    pae = np.full((4, 4), 30.0)
    pae[0, 2] = pae[2, 0] = 3.0
    pae[1, 3] = pae[3, 1] = 5.0
    coords = [(0, 0, 0), (0, 3, 0), (5, 0, 0), (5, 3, 0)]  # A-B pairs within 8 A
    plddt = [90.0, 85.0, 80.0, 75.0]
    scores = pair_scores(pae, chains, coords, plddt)
    entry = scores["A-B"]
    assert set(entry) >= {"asym_ab", "asym_ba", "max", "pdockq2", "lis", "interface_plddt"}
    assert 0.0 < entry["pdockq2"] < 1.4
    assert 0.0 < entry["lis"] <= 1.0
    assert entry["interface_plddt"] == pytest.approx(82.5)


def test_pair_scores_reject_mismatched_inputs():
    from src.core.pae import pair_scores

    with pytest.raises(ValueError, match="same residues"):
        pair_scores(np.zeros((3, 3)), ["A", "B"], [(0, 0, 0)] * 3, [90.0] * 3)
