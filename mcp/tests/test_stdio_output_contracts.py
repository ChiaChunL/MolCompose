"""Successful typed results survive the normal MCP client over real stdio.

The host double replaces only ChimeraX transport; SDK output validation stays
enabled. Based on the release audit's stdio_contract_repro.py reproduction.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from mcp import ClientSession, StdioServerParameters, stdio_client


def _prohibit_connections(event, _args):
    if event == "socket.connect":
        raise PermissionError("Output contract tests are offline")


class _Host:
    def __init__(self, *_args, **_kwargs):
        pass

    def run(self, command):
        value = None
        if command == "info models":
            value = [{"spec": "#1", "class": "AtomicStructure", "value": "fixture"}]
        elif command == "info chains":
            value = [{"spec": f"#1/{c}", "value": c, "polymer type": "protein"}
                     for c in ("A", "B")]
        elif command.startswith("molcompose characterise "):
            if "model #1" in command:
                value = {"steps": ["interface"]}
            elif "model #2" in command:
                value = {"interface_scores": [{"chains": "A-B", "ipsae": 0.71}]}
            elif "model #4" in command:
                value = {"steps": {"interface": True}}
            elif "model #5" in command:
                value = {"buried_area": "976.8443517193655"}
            else:
                value = json.loads((Path(__file__).parent / "fixtures" /
                                    "characterise-1brs-python-values.json").read_text())
        elif command.startswith("molcompose ipsae"):
            value = {"A-B": {"ipsae": 0.71}}
        elif command.startswith("molcompose style "):
            value = ["show #1 cartoon"]
        elif command.startswith("molcompose buriedarea"):
            value = 976.8443517193655
        elif command.startswith("molcompose report "):
            target = Path(sys.argv[1])
            target.write_text('{"fixture": "written"}\n')
            value = str(target)
        return {"json values": [None], "python values": [value],
                "log messages": {}, "error": None}


def _call(tmp_path, name, arguments):
    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).resolve()), str(tmp_path / "report.json")],
            env={"PYTHONDONTWRITEBYTECODE": "1"},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(name, arguments)
    return asyncio.run(run())


def test_stdio_characterise_preserves_steps_list(tmp_path):
    result = _call(tmp_path, "characterise_interface", {
        "group_a": ["A"], "group_b": ["B"], "model": "#1", "style": False,
    })
    assert not result.is_error
    assert result.structured_content["steps"] == ["interface"]


def test_stdio_characterise_preserves_pair_score_rows(tmp_path):
    result = _call(tmp_path, "characterise_interface", {
        "group_a": ["A"], "group_b": ["B"], "model": "#2", "style": False,
    })
    assert not result.is_error
    assert result.structured_content["interface_scores"][0]["chains"] == "A-B"


def test_stdio_real_characterise_fixture(tmp_path):
    result = _call(tmp_path, "characterise_interface", {
        "group_a": ["A"], "group_b": ["D"], "model": "#3", "style": False,
    })
    assert not result.is_error
    data = result.structured_content
    assert data["steps"] == ["interface", "interactions", "buried_area",
                             "affinity", "hotspots", "figure"]
    assert data["interface"]["contact_pairs"] == 43
    assert "confidence" in data["skipped"]


@pytest.mark.parametrize(("name", "arguments"), [
    ("list_models", {}),
    ("apply_style", {"preset": "clean-cartoon", "model": "#1"}),
    ("measure_buried_area", {"model": "#1"}),
    ("write_report", {}),
])
def test_stdio_omits_absent_optional_fields(tmp_path, name, arguments):
    if name == "write_report":
        arguments = {"path": str(tmp_path / "report.json")}
    result = _call(tmp_path, name, arguments)
    assert not result.is_error
    assert "warnings" not in result.structured_content
    assert "value_available" not in result.structured_content
    if name == "write_report":
        assert (tmp_path / "report.json").is_file()


def test_stdio_area_preserves_exact_scientific_float(tmp_path):
    result = _call(tmp_path, "measure_buried_area", {"model": "#1"})
    assert not result.is_error
    assert result.structured_content["buried_area"] == 976.8443517193655


def test_stdio_standalone_ipsae_preserves_pair_map(tmp_path):
    result = _call(tmp_path, "compute_ipsae", {"model": "#1", "pae_file": "/tmp/pae.json"})
    assert not result.is_error
    assert result.structured_content["interface_scores"]["A-B"]["ipsae"] == 0.71


def test_stdio_wrong_output_still_fails_validation(tmp_path):
    result = _call(tmp_path, "characterise_interface", {
        "group_a": ["A"], "group_b": ["B"], "model": "#4", "style": False,
    })
    assert result.is_error
    assert "steps" in str(result.content)


def test_stdio_invalid_numeric_string_is_a_tool_error_not_client_failure(tmp_path):
    result = _call(tmp_path, "characterise_interface", {
        "group_a": ["A"], "group_b": ["B"], "model": "#5", "style": False,
    })
    assert result.is_error
    assert "buried_area" in str(result.content)


def test_stdio_assistant_retains_internal_dictionary(tmp_path):
    result = _call(tmp_path, "analyse_interface", {
        "group_a": ["A"], "group_b": ["B"], "model": "#1", "style": False,
    })
    assert not result.is_error
    assert result.structured_content["status"] == "completed"
    assert result.structured_content["result"]["steps"] == ["interface"]


if __name__ == "__main__":
    sys.addaudithook(_prohibit_connections)
    from molcompose_mcp import server

    server.ChimeraXClient = _Host
    server.bridge_is_up = lambda *_a, **_kw: True
    server.bundle_is_missing = lambda _run: False
    server.create_server(launch=False).run()
