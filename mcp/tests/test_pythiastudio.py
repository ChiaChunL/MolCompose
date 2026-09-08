import json

import pytest
from molcompose_mcp.pythiastudio import (
    ENDPOINTS,
    PythiaStudioError,
    api_key,
    request_prediction,
    to_tabular,
)


def test_api_key_prefers_environment_and_keeps_explicit_as_legacy_fallback(monkeypatch):
    monkeypatch.delenv("PYTHIASTUDIO_API_KEY", raising=False)
    assert api_key("explicit") == "explicit"
    monkeypatch.setenv("PYTHIASTUDIO_API_KEY", "from-env")
    assert api_key() == "from-env"
    assert api_key("legacy-explicit") == "from-env"


def test_missing_api_key_explains_how_to_set_one(monkeypatch):
    monkeypatch.delenv("PYTHIASTUDIO_API_KEY", raising=False)
    with pytest.raises(PythiaStudioError, match="PYTHIASTUDIO_API_KEY"):
        api_key()


def test_unknown_tool_is_rejected_before_any_network_call(tmp_path):
    with pytest.raises(PythiaStudioError, match="tool must be one of"):
        request_prediction(str(tmp_path / "x.pdb"), tool="magic", key="k")


def test_missing_structure_file_is_reported(tmp_path):
    with pytest.raises(PythiaStudioError, match="cannot read structure"):
        request_prediction(str(tmp_path / "absent.pdb"), key="k")


def test_endpoints_cover_both_documented_tools():
    assert set(ENDPOINTS) == {"pythia", "pythia-ppi"}


def test_response_is_flattened_to_the_tabular_ddg_format():
    payload = {
        "mutations": [
            {"chain": "A", "position": 59, "wt": "R", "mut": "A", "ddg": 1.85},
            {"chain": "A", "pos": 27, "wild_type": "K", "mutant": "A", "score": -0.5},
        ]
    }
    text = to_tabular(payload)
    lines = text.strip().splitlines()
    assert lines[0] == "chain,position,wt,mut,ddG"
    assert lines[1] == "A,59,R,A,1.85"
    assert lines[2] == "A,27,K,A,-0.5"


def test_flattened_output_is_readable_by_the_bundle_parser():
    from src.core.ddg import parse_tabular

    payload = {"results": [{"chain": "B", "position": 12, "wt": "G", "mut": "D",
                            "prediction": -1.5}]}
    (effect,) = parse_tabular(to_tabular(payload))
    assert (effect.chain, effect.position, effect.ddg) == ("B", 12, -1.5)


def test_unrecognised_response_names_the_keys_it_saw():
    with pytest.raises(PythiaStudioError, match="top-level keys were: job_id, status"):
        to_tabular({"status": "queued", "job_id": "abc"})


def test_response_without_usable_records_is_reported():
    with pytest.raises(PythiaStudioError, match="no usable mutation records"):
        to_tabular({"mutations": [{"note": "nothing here"}]})


def test_payload_round_trips_as_json():
    payload = json.loads(json.dumps({"mutations": [
        {"chain": "A", "position": 1, "wt": "M", "mut": "A", "ddg": 0.1}
    ]}))
    assert "A,1,M,A,0.1" in to_tabular(payload)
