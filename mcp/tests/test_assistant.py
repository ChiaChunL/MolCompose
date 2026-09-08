"""Intent-level planning composes expert tools without guessing science."""

import asyncio
import shlex
from pathlib import Path

from molcompose_mcp.assistant import (
    artifact_quality,
    choose_interface,
    compatibility_status,
    export_decision,
    external_evidence_decision,
    figure_plan,
)
from molcompose_mcp.server import create_server

MODELS = [{"spec": "#1", "name": "complex.pdb", "class": "AtomicStructure"}]
TWO_CHAINS = [
    {"model_spec": "#1", "chain_id": "A", "polymer_type": "protein"},
    {"model_spec": "#1", "chain_id": "D", "polymer_type": "protein"},
]


def test_one_two_chain_model_is_the_only_safe_automatic_interface_choice():
    decision = choose_interface(MODELS, TWO_CHAINS)
    assert decision == {
        "status": "completed",
        "model": "#1",
        "group_a": ["A"],
        "group_b": ["D"],
    }


def test_multiple_models_require_a_model_choice_instead_of_guessing():
    decision = choose_interface(
        [*MODELS, {"spec": "#2", "name": "other.pdb", "class": "AtomicStructure"}],
        TWO_CHAINS,
    )
    assert decision["status"] == "needs_input"
    assert decision["question"] == "Which open model should be analysed?"
    assert decision["choices"] == ["#1", "#2"]


def test_multiple_contacting_pairs_require_a_pair_choice():
    chains = [
        *TWO_CHAINS,
        {"model_spec": "#1", "chain_id": "B", "polymer_type": "protein"},
    ]
    pairs = [{"chain_a": "A", "chain_b": "D"}, {"chain_a": "B", "chain_b": "D"}]
    decision = choose_interface(MODELS, chains, contacting_pairs=pairs)
    assert decision["status"] == "needs_input"
    assert decision["question"] == "Which contacting chain pair should be analysed?"
    assert decision["choices"] == ["A:D", "B:D"]


def test_explicit_groups_are_kept_when_the_model_is_unambiguous():
    decision = choose_interface(MODELS, TWO_CHAINS, group_a=["A"], group_b=["D"])
    assert decision["status"] == "completed"
    assert decision["group_a"] == ["A"]
    assert decision["group_b"] == ["D"]


def test_missing_models_is_a_recoverable_failure():
    decision = choose_interface([], [])
    assert decision == {
        "status": "failed",
        "error": "no_structure",
        "message": "No atomic structure is open in the live ChimeraX session.",
    }


def test_figure_goals_map_only_to_existing_presets():
    assert figure_plan("interface-overview", interface_ready=True) == {
        "status": "completed",
        "preset": "interface-focus",
        "operations": ["apply_style"],
    }
    assert figure_plan("hotspot-map", interface_ready=True)["preset"] == "hotspot-focus"
    assert figure_plan("whole-complex", interface_ready=False)["preset"] == "complex-by-chain"


def test_interface_figure_goal_names_its_missing_prerequisite():
    decision = figure_plan("binder-closeup", interface_ready=False)
    assert decision == {
        "status": "needs_input",
        "question": "An interface must be analysed before this figure can be composed.",
        "choices": ["analyse_interface"],
    }


def test_file_overwrite_and_external_upload_require_explicit_confirmation():
    assert export_decision("/tmp/existing.png", exists=True, confirmed=False) == {
        "status": "needs_confirmation",
        "confirmation": "overwrite_local_file",
        "target": "/tmp/existing.png",
    }
    confirmed = export_decision("/tmp/existing.png", exists=True, confirmed=True)
    assert confirmed["status"] == "completed"
    assert external_evidence_decision("pythiastudio", confirmed=False) == {
        "status": "needs_confirmation",
        "confirmation": "upload_structure_to_pythiastudio",
    }
    assert external_evidence_decision("ddg", confirmed=False)["status"] == "completed"


def test_export_artifact_confirms_before_overwriting_any_sidecar(tmp_path):
    target = tmp_path / "figure.png"
    provenance = target.with_suffix(".provenance.json")
    provenance.write_text("do not replace")
    app = create_server("http://127.0.0.1:65500", launch=False)

    outcome = asyncio.run(app.call_tool("export_artifact", {"path": str(target)}))
    result = outcome.structured_content

    assert result["status"] == "needs_confirmation"
    assert str(provenance) in result["choices"]
    assert provenance.read_text() == "do not replace"


def test_artifact_quality_reports_each_required_file_and_rejects_empty_output(
    tmp_path,
):
    png = tmp_path / "figure.png"
    recipe = tmp_path / "figure.cxc"
    provenance = tmp_path / "figure.provenance.json"
    png.write_bytes(b"png")
    recipe.write_text("molcompose style interface-focus\n")
    provenance.write_text("{}")

    complete = artifact_quality({
        "png": str(png),
        "recipe": str(recipe),
        "provenance": str(provenance),
        "session": None,
    })

    assert complete == {
        "passed": True,
        "artifacts": {
            "png": {
                "path": str(png),
                "exists": True,
                "non_empty": True,
                "bytes": 3,
            },
            "recipe": {
                "path": str(recipe),
                "exists": True,
                "non_empty": True,
                "bytes": recipe.stat().st_size,
            },
            "provenance": {
                "path": str(provenance),
                "exists": True,
                "non_empty": True,
                "bytes": 2,
            },
        },
    }

    recipe.write_bytes(b"")

    incomplete = artifact_quality({
        "png": str(png),
        "recipe": str(recipe),
        "provenance": str(provenance),
    })
    assert incomplete["passed"] is False
    assert incomplete["artifacts"]["recipe"] == {
        "path": str(recipe),
        "exists": True,
        "non_empty": False,
        "bytes": 0,
    }


def test_export_artifact_returns_file_quality_for_every_claimed_sidecar(
    tmp_path, monkeypatch
):
    from molcompose_mcp import server as server_module

    class WritingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, command):
            if command.startswith("molcompose export "):
                words = shlex.split(command)
                target = Path(words[2])
                target.write_bytes(b"PNG bytes")
                target.with_suffix(".cxc").write_text(
                    "molcompose style interface-focus model #1\n"
                )
                if "saveSession" in words and words[words.index("saveSession") + 1] == "true":
                    target.with_suffix(".cxs").write_bytes(b"session")
            return {
                "json values": [],
                "python values": [],
                "log messages": {},
                "error": "",
            }

    monkeypatch.setattr(server_module, "ChimeraXClient", WritingClient)
    monkeypatch.setattr(server_module, "bridge_is_up", lambda *_a, **_k: True)
    monkeypatch.setattr(server_module, "bundle_is_missing", lambda _run: False)
    app = server_module.create_server(
        "http://127.0.0.1:65500", profile="assistant", launch=False
    )
    target = tmp_path / "figure.png"

    outcome = asyncio.run(app.call_tool("export_artifact", {
        "path": str(target),
        "save_session": True,
    })).structured_content

    assert outcome["status"] == "completed"
    assert outcome["qa"]["passed"] is True
    assert set(outcome["qa"]["artifacts"]) == {
        "png", "session", "recipe", "provenance"
    }
    assert all(
        check["exists"] and check["non_empty"]
        for check in outcome["qa"]["artifacts"].values()
    )


def test_export_artifact_fails_when_chimerax_omits_a_claimed_session_sidecar(
    tmp_path, monkeypatch
):
    from molcompose_mcp import server as server_module

    class MissingSessionClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, command):
            if command.startswith("molcompose export "):
                target = Path(shlex.split(command)[2])
                target.write_bytes(b"PNG bytes")
                target.with_suffix(".cxc").write_text(
                    "molcompose style interface-focus model #1\n"
                )
            return {
                "json values": [],
                "python values": [],
                "log messages": {},
                "error": "",
            }

    monkeypatch.setattr(server_module, "ChimeraXClient", MissingSessionClient)
    monkeypatch.setattr(server_module, "bridge_is_up", lambda *_a, **_k: True)
    monkeypatch.setattr(server_module, "bundle_is_missing", lambda _run: False)
    app = server_module.create_server(
        "http://127.0.0.1:65500", profile="assistant", launch=False
    )

    outcome = asyncio.run(app.call_tool("export_artifact", {
        "path": str(tmp_path / "figure.png"),
        "save_session": True,
    })).structured_content

    assert outcome["status"] == "failed"
    assert outcome["error"] == "operation_failed"
    assert "session" in outcome["message"]


def test_pythiastudio_evidence_confirms_before_overwriting_local_output(tmp_path):
    target = tmp_path / "prediction.tsv"
    target.write_text("do not replace")
    app = create_server("http://127.0.0.1:65500", launch=False)

    outcome = asyncio.run(app.call_tool("load_external_evidence", {
        "kind": "pythiastudio",
        "path": str(target),
        "structure_path": str(tmp_path / "model.pdb"),
        "confirm_external": True,
    }))
    result = outcome.structured_content

    assert result["status"] == "needs_confirmation"
    assert result["confirmation"] == "overwrite_local_file"
    assert result["target"] == str(target)
    assert target.read_text() == "do not replace"


def test_inspect_session_reports_current_interface_state(monkeypatch):
    from molcompose_mcp import server as server_module

    class EmptyClient:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, command):
            return {"json values": [], "python values": [], "log messages": {}}

    monkeypatch.setattr(server_module, "ChimeraXClient", EmptyClient)
    app = server_module.create_server("http://127.0.0.1:65500", launch=False)

    outcome = asyncio.run(app.call_tool("inspect_session", {})).structured_content

    assert outcome["status"] == "completed"
    assert outcome["data"]["interfaces"] == {}


def test_inspect_session_treats_expected_missing_interface_as_not_ready(monkeypatch):
    from molcompose_mcp import server as server_module

    class NoInterfaceClient:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, command):
            if command == "info models":
                return {
                    "json values": [[{
                        "spec": "#1",
                        "value": "complex.pdb",
                        "class": "AtomicStructure",
                    }]],
                    "log messages": {},
                    "error": "",
                }
            if command == "info chains":
                return {"json values": [[]], "log messages": {}, "error": ""}
            if command.startswith("molcompose blocks"):
                return {
                    "json values": [],
                    "log messages": {},
                    "error": {
                        "type": "UserError",
                        "message": (
                            "Detect an interface first with 'molcompose interface' "
                            "for model #1"
                        ),
                    },
                }
            return {"json values": [], "log messages": {}, "error": ""}

    monkeypatch.setattr(server_module, "ChimeraXClient", NoInterfaceClient)
    monkeypatch.setattr(server_module, "bridge_is_up", lambda *args, **kwargs: True)
    monkeypatch.setattr(server_module, "bundle_is_missing", lambda run: False)
    app = server_module.create_server("http://127.0.0.1:65500", launch=False)

    outcome = asyncio.run(app.call_tool("inspect_session", {})).structured_content

    assert outcome["status"] == "completed"
    assert outcome["data"]["interfaces"]["#1"] == {
        "ready": False,
        "blocks": [],
    }


def test_assistant_boundary_returns_a_recoverable_failed_outcome(monkeypatch):
    from molcompose_mcp import server as server_module

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, command):
            raise server_module.ChimeraXUnavailable("bridge unavailable")

    monkeypatch.setattr(server_module, "ChimeraXClient", FailingClient)
    app = server_module.create_server("http://127.0.0.1:65500", launch=False)

    outcome = asyncio.run(app.call_tool("inspect_session", {})).structured_content

    assert outcome["status"] == "failed"
    assert outcome["error"] == "chimerax_operation_failed"
    assert outcome["message"] == "bridge unavailable"
    assert outcome["next_action"] == (
        "Start the MolCompose bridge and retry inspect_session."
    )


def test_assistant_boundary_classifies_non_bridge_failures_as_operation_errors(
    tmp_path,
):
    app = create_server("http://127.0.0.1:65500", launch=False)

    outcome = asyncio.run(app.call_tool("load_external_evidence", {
        "kind": "pythiastudio",
        "path": str(tmp_path / "prediction.tsv"),
        "structure_path": str(tmp_path / "missing-model.pdb"),
        "confirm_external": True,
    })).structured_content

    assert outcome["status"] == "failed"
    assert outcome["error"] == "operation_failed"
    assert outcome["next_action"] == (
        "Resolve the reported issue and retry load_external_evidence."
    )


def test_assistant_boundary_rejects_chimerax_error_payloads(monkeypatch):
    from molcompose_mcp import server as server_module

    class ErrorPayloadClient:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, command):
            if command == "info models":
                return {
                    "json values": [[{
                        "spec": "#1",
                        "value": "complex.pdb",
                        "class": "AtomicStructure",
                    }]],
                    "log messages": {},
                    "error": "",
                }
            if command == "info chains":
                return {
                    "json values": [[
                        {"spec": "#1/A", "value": "A", "polymer type": "protein"},
                        {"spec": "#1/D", "value": "D", "polymer type": "protein"},
                    ]],
                    "log messages": {},
                    "error": "",
                }
            if command.startswith("molcompose characterise"):
                return {
                    "json values": [],
                    "log messages": {"error": ["simulated command failure"]},
                    "error": "simulated command failure",
                }
            return {"json values": [], "log messages": {}, "error": ""}

    monkeypatch.setattr(server_module, "ChimeraXClient", ErrorPayloadClient)
    monkeypatch.setattr(server_module, "bridge_is_up", lambda *args, **kwargs: True)
    monkeypatch.setattr(server_module, "bundle_is_missing", lambda run: False)
    app = server_module.create_server("http://127.0.0.1:65500", launch=False)

    outcome = asyncio.run(app.call_tool("analyse_interface", {})).structured_content

    assert outcome["status"] == "failed"
    assert outcome["error"] == "operation_failed"
    assert "simulated command failure" in outcome["message"]
    recipe = asyncio.run(app.call_tool("get_recipe", {}))
    commands = [block.text for block in recipe.content]
    assert not any("characterise" in command for command in commands)


def test_version_handshake_is_explicit_when_a_bundle_version_is_unknown_or_incompatible():
    assert compatibility_status("0.1.1", "0.1.2")["compatible"] is True
    unknown = compatibility_status("0.1.1", "")
    assert unknown["compatible"] is False
    assert "could not be read" in unknown["warning"]
    incompatible = compatibility_status("0.1.1", "0.2.0")
    assert incompatible["compatible"] is False
    assert "0.1.x" in incompatible["warning"]


def test_assistant_tools_are_additive_and_publish_outcome_schemas():
    app = create_server("http://127.0.0.1:65500", launch=False)
    tools = {tool.name: tool for tool in asyncio.run(app.list_tools())}
    assistant_names = {
        "inspect_session", "analyse_interface", "compose_figure",
        "export_artifact", "load_external_evidence",
    }
    assert assistant_names <= set(tools)
    for name in assistant_names:
        schema = tools[name].output_schema
        assert schema is not None
        assert "status" in schema["properties"]


def test_local_ddg_evidence_is_loaded_exactly_once(monkeypatch):
    from molcompose_mcp import server as server_module

    class Client:
        def __init__(self, *args, **kwargs):
            self.commands = []

        def run(self, command):
            self.commands.append(command)
            return {"json values": [], "python values": [], "log messages": {}}

    clients = []

    def client_factory(*args, **kwargs):
        client = Client()
        clients.append(client)
        return client

    monkeypatch.setattr(server_module, "ChimeraXClient", client_factory)
    app = server_module.create_server("http://127.0.0.1:65500", launch=False)

    asyncio.run(app.call_tool("load_external_evidence", {
        "kind": "ddg",
        "path": "/tmp/ddg.tsv",
        "format": "tabular",
    }))

    issued = [command for client in clients for command in client.commands]
    assert len([command for command in issued if command.startswith("molcompose ddg")]) == 1
