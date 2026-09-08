"""Behavioural evaluations for an assistant facing realistic user intents.

These scenarios exercise the public assistant profile through the MCP server,
not the pure decision helpers.  The ChimeraX transport is deterministic so the
suite measures interaction policy without downloading structures or requiring
a running viewer.
"""

import asyncio
from dataclasses import dataclass

import pytest
from molcompose_mcp import server as server_module


def _payload(value=None, *, error=None):
    return {
        "json values": [] if value is None else [value],
        "python values": [],
        "log messages": {},
        "error": error,
    }


def _models(*specs):
    return [
        {"spec": spec, "value": f"model-{spec[1:]}.pdb", "class": "AtomicStructure"}
        for spec in specs
    ]


def _chains(model, *chain_ids):
    return [
        {
            "spec": f"{model}/{chain_id}",
            "value": chain_id,
            "polymer type": "protein",
        }
        for chain_id in chain_ids
    ]


@dataclass
class _Route:
    prefix: str
    response: object


class _ScenarioClient:
    def __init__(self, routes):
        self.routes = routes
        self.commands = []

    def run(self, command):
        self.commands.append(command)
        for route in self.routes:
            if command.startswith(route.prefix):
                if isinstance(route.response, Exception):
                    raise route.response
                return route.response
        return _payload()


@pytest.fixture
def scenario_server(monkeypatch):
    def build(*routes):
        client = _ScenarioClient(list(routes))
        monkeypatch.setattr(
            server_module, "ChimeraXClient", lambda *_args, **_kwargs: client
        )
        monkeypatch.setattr(server_module, "bridge_is_up", lambda *_a, **_k: True)
        monkeypatch.setattr(server_module, "bundle_is_missing", lambda _run: False)
        app = server_module.create_server(
            "http://127.0.0.1:65500", profile="assistant", launch=False
        )
        return app, client

    return build


def _call(app, name, arguments=None):
    return asyncio.run(app.call_tool(name, arguments or {})).structured_content


def test_two_open_models_require_a_choice_before_composing(scenario_server):
    app, _client = scenario_server(
        _Route("info models", _payload(_models("#1", "#2"))),
        _Route("info chains", _payload([])),
    )

    outcome = _call(app, "compose_figure", {"goal": "whole-complex"})

    assert outcome["status"] == "needs_input"
    assert outcome["choices"] == ["#1", "#2"]


def test_six_chain_complex_returns_contacting_pair_choices(scenario_server):
    pairs = [
        {"chain_a": "A", "chain_b": "D"},
        {"chain_a": "B", "chain_b": "E"},
        {"chain_a": "C", "chain_b": "F"},
    ]
    app, client = scenario_server(
        _Route("info models", _payload(_models("#1"))),
        _Route("info chains", _payload(_chains("#1", "A", "B", "C", "D", "E", "F"))),
        _Route("molcompose interface all", _payload(pairs)),
    )

    outcome = _call(app, "analyse_interface")

    assert outcome["status"] == "needs_input"
    assert outcome["model"] == "#1"
    assert outcome["question"] == "Which contacting chain pair should be analysed?"
    assert outcome["choices"] == ["A:D", "B:E", "C:F"]
    assert sum(command.startswith("molcompose interface all") for command in client.commands) == 1
    assert any(
        command.startswith("molcompose interface all model #1")
        for command in client.commands
    )


def test_hotspot_figure_without_an_interface_points_to_analysis(scenario_server):
    missing = {
        "type": "UserError",
        "message": "Detect an interface first with 'molcompose interface' for model #1",
    }
    app, _client = scenario_server(
        _Route("info models", _payload(_models("#1"))),
        _Route("info chains", _payload(_chains("#1", "A", "D"))),
        _Route("molcompose blocks", _payload(error=missing)),
    )
    visible_tools = {tool.name for tool in asyncio.run(app.list_tools())}

    outcome = _call(app, "compose_figure", {"goal": "hotspot-map"})

    assert "rank_hotspots" not in visible_tools
    assert outcome["status"] == "needs_input"
    assert outcome["choices"] == ["analyse_interface"]
    assert "interface" in outcome["question"].lower()


def test_experimental_structure_names_each_unavailable_confidence_metric(
    scenario_server,
):
    reason = (
        "experimental structure (X-RAY DIFFRACTION): B-factors are "
        "temperature factors, not confidence values"
    )
    unavailable = {
        metric: reason
        for metric in ("pLDDT", "ipLDDT", "pDockQ", "ipSAE", "pDockQ2", "LIS")
    }
    app, _client = scenario_server(
        _Route("info models", _payload(_models("#1"))),
        _Route("info chains", _payload(_chains("#1", "A", "D"))),
        _Route(
            "molcompose capabilities",
            _payload({
                "kind": "experimental",
                "detail": "X-RAY DIFFRACTION",
                "available": ["interface", "buried area"],
                "unavailable": unavailable,
            }),
        ),
        _Route(
            "molcompose blocks",
            _payload(error={"type": "UserError", "message": "Detect an interface first"}),
        ),
    )

    outcome = _call(app, "inspect_session")
    reported = outcome["data"]["capabilities"]["#1"]["capabilities"]["unavailable"]

    assert outcome["status"] == "completed"
    assert set(reported) == {"pLDDT", "ipLDDT", "pDockQ", "ipSAE", "pDockQ2", "LIS"}
    assert all(reported[metric] for metric in reported)


def test_predicted_structure_without_pae_keeps_the_skipped_reason(scenario_server):
    summary = {
        "model": "#1",
        "steps": ["interface", "confidence"],
        "skipped": {
            "interface_scores": (
                "no PAE file found next to prediction.pdb; ipSAE, pDockQ2 and "
                "LIS cannot be computed"
            )
        },
        "interface": {
            "chains_a": ["A"],
            "chains_b": ["D"],
            "criterion": "heavy",
            "cutoff": 4.5,
            "residues_a": 10,
            "residues_b": 9,
            "contact_pairs": 20,
        },
    }
    app, _client = scenario_server(
        _Route("info models", _payload(_models("#1"))),
        _Route("info chains", _payload(_chains("#1", "A", "D"))),
        _Route("molcompose characterise", _payload(summary)),
    )

    outcome = _call(app, "analyse_interface")

    assert outcome["status"] == "completed"
    assert "PAE" in outcome["result"]["skipped"]["interface_scores"]
    assert outcome["next_steps"] == [
        "compose_figure",
        "load_external_evidence",
        "render_preview",
        "export_artifact",
    ]
    assert all(value is not None for value in outcome.values())
    assert "message" not in outcome
    assert "error" not in outcome
    assert "data" not in outcome
    assert "compatibility" not in outcome


def test_structure_fetch_failure_is_a_recoverable_assistant_outcome(scenario_server):
    app, _client = scenario_server(
        _Route(
            'open "1brs"',
            _payload(error={
                "type": "UserError",
                "message": "PDB fetch failed: network unavailable",
            }),
        )
    )

    outcome = _call(app, "open_structure", {"path_or_id": "1brs"})

    assert outcome["status"] == "failed"
    assert outcome["error"] == "operation_failed"
    assert "network unavailable" in outcome["message"]
    assert outcome["next_action"] == (
        "Resolve the reported issue and retry open_structure."
    )
