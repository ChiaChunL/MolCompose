"""Scientific values keep exact raw data and gain deterministic prose values."""

import asyncio

from molcompose_mcp import server as server_module
from molcompose_mcp.presentation import (
    display_area,
    display_energy,
    display_kd,
    present_analysis,
)


def test_scalar_formatters_are_deterministic_and_unit_bearing():
    assert display_area(937.5757528846134) == "938 Å²"
    assert display_energy(-10.634728) == "-10.63 kcal/mol"
    assert display_kd(2.3412e-9) == "2.34e-09 M"


def test_present_analysis_preserves_exact_raw_values():
    source = {
        "buried_area": 937.5757528846134,
        "affinity": {"delta_g": -10.634728, "kd": 2.3412e-9, "temperature": 25.0},
        "log": "measured live",
    }

    result = present_analysis(source)

    assert result["buried_area"] == 937.5757528846134
    assert result["affinity"]["delta_g"] == -10.634728
    assert result["raw"] == {
        "buried_area": 937.5757528846134,
        "affinity": {"delta_g": -10.634728, "kd": 2.3412e-9, "temperature": 25.0},
    }
    assert result["display"] == {
        "buried_area": "938 Å²",
        "affinity": {
            "delta_g": "-10.63 kcal/mol",
            "kd": "2.34e-09 M",
            "temperature": "25 °C",
        },
    }


def test_interface_count_display_requires_criterion_and_cutoff():
    complete = present_analysis(
        {
            "interface": {
                "residues_a": 19,
                "residues_b": 16,
                "contact_pairs": 43,
                "criterion": "heavy",
                "cutoff": 4.5,
            }
        }
    )
    assert complete["display"]["interface"] == (
        "19 + 16 interface residues; 43 contacting residue pairs "
        "(heavy criterion, 4.5 Å cutoff)"
    )

    contextless = present_analysis(
        {"interface": {"residues_a": 19, "residues_b": 16, "contact_pairs": 43}}
    )
    assert "interface" not in contextless["display"]


def test_skipped_analyses_keep_their_exact_reasons():
    skipped = {"confidence": "B-factors are not pLDDT", "interface_scores": "no PAE"}
    result = present_analysis({"skipped": skipped})
    assert result["raw"]["skipped"] == skipped
    assert result["display"]["skipped"] == skipped


def test_live_analysis_tools_publish_raw_and_display(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, command):
            if "buriedarea" in command:
                return {
                    "python values": [937.5757528846134],
                    "log messages": {"note": ["Buried area measured"]},
                }
            return {"python values": [], "log messages": {}}

    monkeypatch.setattr(server_module, "ChimeraXClient", _Client)
    monkeypatch.setattr(server_module, "bridge_is_up", lambda *args, **kwargs: True)
    monkeypatch.setattr(server_module, "bundle_is_missing", lambda run: False)
    app = server_module.create_server("http://127.0.0.1:65500", launch=False)

    result = asyncio.run(app.call_tool("measure_buried_area", {})).structured_content
    assert result["buried_area"] == 937.5757528846134
    assert result["raw"]["buried_area"] == 937.5757528846134
    assert result["display"]["buried_area"] == "938 Å²"
