"""Security coverage follows the registered MCP surface, not a hand-picked builder list.

The ChimeraX REST bridge treats an unquoted semicolon, newline, or carriage
return as a command boundary.  Every public string accepted by a registered
tool therefore needs an explicit policy: reject/validate it before
interpolation, quote it as one path, or keep it outside ChimeraX entirely.
"""

import asyncio

import pytest
from molcompose_mcp import server as server_module

BREAKERS = ("; open 1crn", "\nopen 1crn", "\rclose all")

# Representative valid calls.  Values are deliberately literal rather than
# derived from production constants: a changed validator must not silently
# change the test's expected domain with it.
VALID_CALLS = {
    "list_models": {},
    "open_structure": {"path_or_id": "1brs"},
    "apply_style": {
        "preset": "design-reference",
        "model": "#1",
        "references": "#2,#3",
        "align": "A",
        "partner": "D",
    },
    "characterise_interface": {
        "group_a": ["A"], "group_b": ["D"], "model": "#1",
        "criterion": "heavy",
    },
    "detect_interface": {
        "group_a": ["A"], "group_b": ["D"], "model": "#1",
        "criterion": "heavy",
    },
    "detect_all_interfaces": {"model": "#1", "criterion": "heavy"},
    "focus": {"target": "interface", "model": "#1"},
    "show_hbonds": {"model": "#1"},
    "write_report": {"path": "/tmp/molcompose-report.json", "model": "#1", "format": "json"},
    "predict_ddg_pythiastudio": {
        "structure_path": "/tmp/model.pdb",
        "output_path": "/tmp/ddg.tsv",
        "tool": "pythia-ppi",
        "api_key": "secret",
    },
    "load_energy": {"path": "/tmp/energy.dat", "chains": "A:A,B:D", "model": "#1"},
    "list_blocks": {"model": "#1"},
    "load_flexibility": {"path": "/tmp/rmsf.xvg", "chains": "A,D", "model": "#1"},
    "load_ddg": {"path": "/tmp/ddg.tsv", "model": "#1", "format": "tabular", "statistic": "min"},
    "rank_hotspots": {"model": "#1", "metric": "dsasa"},
    "measure_buried_area": {"model": "#1"},
    "predict_affinity": {"model": "#1"},
    "analyze_interactions": {"model": "#1", "types": "salt-bridge"},
    "compute_ipsae": {"pae_file": "/tmp/pae.json", "model": "#1"},
    "score_against_reference": {"reference": "#2", "model": "#1", "chain_map": "A:A,B:D"},
    "check_capabilities": {"model": "#1", "predictor": "generic", "pae_file": "/tmp/pae.json"},
    "get_confidence": {"model": "#1"},
    "show_contacts": {"model": "#1"},
    "reset": {"model": "#1"},
    "export_figure": {"path": "/tmp/molcompose-security.png"},
    "export_sequence_coloring": {"path": "/tmp/colors.scf", "model": "#1", "source": "interface"},
    "run_native": {"command": "version"},
    "render_preview": {},
    "get_recipe": {},
    "inspect_session": {},
    "analyse_interface": {
        "group_a": ["A"], "group_b": ["D"], "model": "#1",
        "criterion": "heavy",
    },
    "compose_figure": {"goal": "interface-overview", "model": "#1"},
    "export_artifact": {"path": "/tmp/molcompose-assistant.png"},
    "load_external_evidence": {
        "kind": "ddg", "path": "/tmp/ddg.tsv", "model": "#1",
        "chains": "A:A,B:D", "format": "tabular", "statistic": "min",
        "structure_path": "/tmp/model.pdb", "tool": "pythia-ppi",
    },
}

# Policy values are observable security behavior, not implementation names.
# - reject: never reaches an unquoted command position with a breaker.
# - quote: may contain a breaker, but only inside one quoted path argument.
# - local: used by Python filesystem/network code, never a ChimeraX command.
# - secret: opaque credential, never a ChimeraX command or log value.
STRING_POLICIES = {
    ("open_structure", "path_or_id"): "quote",
    ("apply_style", "preset"): "reject",
    ("apply_style", "model"): "reject",
    ("apply_style", "references"): "reject",
    ("apply_style", "align"): "reject",
    ("apply_style", "partner"): "reject",
    ("characterise_interface", "group_a"): "reject",
    ("characterise_interface", "group_b"): "reject",
    ("characterise_interface", "model"): "reject",
    ("characterise_interface", "criterion"): "reject",
    ("detect_interface", "group_a"): "reject",
    ("detect_interface", "group_b"): "reject",
    ("detect_interface", "model"): "reject",
    ("detect_interface", "criterion"): "reject",
    ("detect_all_interfaces", "model"): "reject",
    ("detect_all_interfaces", "criterion"): "reject",
    ("focus", "target"): "reject",
    ("focus", "model"): "reject",
    ("show_hbonds", "model"): "reject",
    ("write_report", "path"): "quote",
    ("write_report", "model"): "reject",
    ("write_report", "format"): "reject",
    ("predict_ddg_pythiastudio", "structure_path"): "local",
    ("predict_ddg_pythiastudio", "output_path"): "local",
    ("predict_ddg_pythiastudio", "tool"): "reject",
    ("predict_ddg_pythiastudio", "api_key"): "secret",
    ("load_energy", "path"): "quote",
    ("load_energy", "chains"): "reject",
    ("load_energy", "model"): "reject",
    ("load_energy", "solvation"): "reject",
    ("list_blocks", "model"): "reject",
    ("load_flexibility", "path"): "quote",
    ("load_flexibility", "chains"): "reject",
    ("load_flexibility", "model"): "reject",
    ("load_ddg", "path"): "quote",
    ("load_ddg", "model"): "reject",
    ("load_ddg", "format"): "reject",
    ("load_ddg", "statistic"): "reject",
    ("rank_hotspots", "model"): "reject",
    ("rank_hotspots", "metric"): "reject",
    ("measure_buried_area", "model"): "reject",
    ("predict_affinity", "model"): "reject",
    ("analyze_interactions", "model"): "reject",
    ("analyze_interactions", "types"): "reject",
    ("compute_ipsae", "pae_file"): "quote",
    ("compute_ipsae", "model"): "reject",
    ("score_against_reference", "reference"): "reject",
    ("score_against_reference", "model"): "reject",
    ("score_against_reference", "chain_map"): "reject",
    ("check_capabilities", "model"): "reject",
    ("check_capabilities", "predictor"): "reject",
    ("check_capabilities", "pae_file"): "quote",
    ("get_confidence", "model"): "reject",
    ("show_contacts", "model"): "reject",
    ("reset", "model"): "reject",
    ("export_figure", "path"): "quote",
    ("export_sequence_coloring", "path"): "quote",
    ("export_sequence_coloring", "model"): "reject",
    ("export_sequence_coloring", "source"): "reject",
    ("run_native", "command"): "reject",
    ("analyse_interface", "group_a"): "reject",
    ("analyse_interface", "group_b"): "reject",
    ("analyse_interface", "model"): "reject",
    ("analyse_interface", "criterion"): "reject",
    ("compose_figure", "goal"): "reject",
    ("compose_figure", "model"): "reject",
    ("export_artifact", "path"): "quote",
    ("load_external_evidence", "kind"): "reject",
    ("load_external_evidence", "path"): "quote",
    ("load_external_evidence", "model"): "reject",
    ("load_external_evidence", "chains"): "reject",
    ("load_external_evidence", "solvation"): "reject",
    ("load_external_evidence", "format"): "reject",
    ("load_external_evidence", "statistic"): "reject",
    ("load_external_evidence", "structure_path"): "local",
    ("load_external_evidence", "tool"): "reject",
}


class _RecordingClient:
    def __init__(self, *args, **kwargs):
        self.commands = []

    def run(self, command):
        self.commands.append(command)
        return {"json values": [], "python values": [], "log messages": {}}


def _is_string_schema(schema):
    if schema.get("type") == "string":
        return True
    if schema.get("type") == "array":
        return _is_string_schema(schema.get("items", {}))
    return any(_is_string_schema(item) for item in schema.get("anyOf", ()))


def _registered_string_parameters(tools):
    return {
        (tool.name, name)
        for tool in tools
        for name, schema in (tool.input_schema or {}).get("properties", {}).items()
        if _is_string_schema(schema)
    }


def _has_unquoted_command_boundary(command):
    quoted = False
    escaped = False
    for character in command:
        if escaped:
            escaped = False
            continue
        if character == "\\" and quoted:
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
            continue
        if not quoted and character in ";\n\r":
            return True
    return False


def _payload_arguments(tool_name, parameter, breaker):
    arguments = dict(VALID_CALLS[tool_name])
    if tool_name == "load_external_evidence":
        if parameter == "chains":
            arguments["kind"] = "energy"
        elif parameter in {"structure_path", "tool"}:
            arguments["kind"] = "pythiastudio"
            arguments["confirm_external"] = True
    representative = arguments[parameter]
    if parameter in {"group_a", "group_b"}:
        arguments[parameter] = [f"{representative[0]}{breaker}"]
    else:
        arguments[parameter] = f"{representative}{breaker}"
    return arguments


def test_every_registered_tool_and_string_parameter_has_a_security_policy(monkeypatch):
    monkeypatch.setattr(server_module, "ChimeraXClient", _RecordingClient)
    app = server_module.create_server("http://127.0.0.1:65500", launch=False)
    tools = asyncio.run(app.list_tools())

    assert {tool.name for tool in tools} == set(VALID_CALLS)
    assert _registered_string_parameters(tools) == set(STRING_POLICIES)


@pytest.mark.parametrize(
    ("tool_name", "parameter", "policy"),
    [(*key, policy) for key, policy in STRING_POLICIES.items() if policy in {"reject", "quote"}],
)
def test_no_registered_string_can_start_a_second_chimerax_command(
    monkeypatch, tool_name, parameter, policy
):
    clients = []

    def client_factory(*args, **kwargs):
        client = _RecordingClient()
        clients.append(client)
        return client

    monkeypatch.setattr(server_module, "ChimeraXClient", client_factory)
    monkeypatch.setattr(server_module, "bridge_is_up", lambda *args, **kwargs: True)
    monkeypatch.setattr(server_module, "bundle_is_missing", lambda run: False)
    app = server_module.create_server("http://127.0.0.1:65500", launch=False)

    inspected = 0
    for breaker in BREAKERS:
        try:
            asyncio.run(
                app.call_tool(tool_name, _payload_arguments(tool_name, parameter, breaker))
            )
        except Exception:  # Rejection is one correct outcome; command inspection is authoritative.
            pass

        commands = [command for client in clients for command in client.commands]
        new_commands = commands[inspected:]
        inspected = len(commands)
        unsafe = [
            command for command in new_commands
            if _has_unquoted_command_boundary(command)
        ]
        assert not unsafe, (
            f"{tool_name}.{parameter} ({policy}) emitted a second command "
            f"boundary for {breaker!r}: {unsafe}"
        )
