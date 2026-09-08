"""The live-agent eval must measure tool choice, not only tool responses."""

import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

import scripts.agent_behavior_eval as agent_eval
from scripts.agent_behavior_eval import (
    DEFAULT_SCENARIOS,
    EvalScenario,
    ScenarioRestServer,
    _follow_up_turn,
    _repository_imports,
    _session_id_from_stream,
    _should_run_follow_up,
    evaluate_conversation_streams,
    evaluate_stream,
    extract_tool_calls,
    score_answer,
    score_tool_calls,
)

REPOSITORY_ROOT = Path(__file__).parents[3]


def test_codex_jsonl_extracts_each_completed_molcompose_call_once():
    lines = [
        json.dumps({
            "type": "item.started",
            "item": {
                "id": "call-1",
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "inspect_session",
                "arguments": {},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {
                "id": "call-1",
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "inspect_session",
                "arguments": {},
                "result": {"status": "completed"},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {
                "id": "call-2",
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "analyse_interface",
                "arguments": {"group_a": ["A"], "group_b": ["D"]},
                "result": {"status": "completed"},
            },
        }),
    ]

    assert extract_tool_calls(lines, "codex-jsonl") == [
        {"name": "inspect_session", "arguments": {}},
        {
            "name": "analyse_interface",
            "arguments": {"group_a": ["A"], "group_b": ["D"]},
        },
    ]


def test_claude_jsonl_extracts_only_molcompose_tool_use_blocks():
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "mcp__molcompose__inspect_session",
                        "input": {},
                    },
                    {
                        "type": "tool_use",
                        "id": "tool-2",
                        "name": "Read",
                        "input": {"file_path": "/tmp/irrelevant"},
                    },
                    {
                        "type": "tool_use",
                        "id": "tool-3",
                        "name": "mcp__molcompose__analyse_interface",
                        "input": {"group_a": ["A"], "group_b": ["D"]},
                    },
                ]
            },
        }),
    ]

    assert extract_tool_calls(lines, "claude-stream-json") == [
        {"name": "inspect_session", "arguments": {}},
        {
            "name": "analyse_interface",
            "arguments": {"group_a": ["A"], "group_b": ["D"]},
        },
    ]


def test_each_agent_stream_exposes_the_session_id_needed_for_a_follow_up_turn():
    codex = json.dumps({"type": "thread.started", "thread_id": "thread-123"})
    claude = json.dumps({"type": "system", "session_id": "session-456"})

    assert _session_id_from_stream("codex-jsonl", codex) == "thread-123"
    assert _session_id_from_stream("claude-stream-json", claude) == "session-456"
    assert _session_id_from_stream("codex-jsonl", "not json") is None


def test_multiturn_score_requires_a_resumable_session_and_scores_each_turn():
    follow_up = EvalScenario(
        name="follow-up-figure",
        prompt="把刚才那个界面做成热点图。",
        required_subsequence=(
            "compose_figure",
            "render_preview",
            "export_artifact",
        ),
        max_calls=4,
    )
    scenario = EvalScenario(
        name="multiturn-interface",
        prompt="分析 A 和 D 的界面。",
        required_subsequence=("inspect_session", "analyse_interface"),
        max_calls=3,
        follow_up=follow_up,
    )
    first = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
        json.dumps({
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "inspect_session",
                "arguments": {},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "analyse_interface",
                "arguments": {"group_a": ["A"], "group_b": ["D"]},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "分析完成。"},
        }),
    ])
    second = "\n".join([
        json.dumps({
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "compose_figure",
                "arguments": {"goal": "hotspot-map"},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "render_preview",
                "arguments": {},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "export_artifact",
                "arguments": {"path": "follow-up.png"},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "已预览并导出。"},
        }),
    ])

    passed = evaluate_conversation_streams(
        scenario,
        "codex-jsonl",
        [(first, 0), (second, 0)],
    )
    missing_session = evaluate_conversation_streams(
        scenario,
        "codex-jsonl",
        [(first.replace("thread.started", "other"), 0)],
    )

    assert passed["passed"] is True
    assert passed["session_id"] == "thread-123"
    assert len(passed["turns"]) == 2
    assert missing_session["passed"] is False
    assert missing_session["reasons"] == [
        "turn 1 did not emit a resumable session id",
        "turn 2 was not run",
    ]


def test_eval_runner_builds_the_follow_up_with_the_real_resume_adapter():
    (
        get_agent,
        _locate,
        _write_mcp_config,
        TurnContext,
        adapter_for,
        _redact,
        AgentConversation,
    ) = _repository_imports()
    agent = get_agent("codex")
    context = TurnContext(
        agent=agent,
        executable="/opt/bin/codex",
        server_executable="/opt/bin/molcompose-mcp",
        chimerax_url="http://127.0.0.1:3010",
        source="agent:eval-codex",
    )
    scenario = EvalScenario(
        name="two-turns",
        prompt="Analyse it.",
        required_subsequence=(),
        max_calls=0,
        follow_up=EvalScenario(
            name="follow-up",
            prompt="Make the figure.",
            required_subsequence=(),
            max_calls=0,
        ),
    )
    first_stdout = json.dumps({
        "type": "thread.started",
        "thread_id": "thread-123",
    })

    turn = _follow_up_turn(
        adapter_for(agent),
        context,
        scenario,
        first_stdout,
        AgentConversation,
    )

    assert turn is not None
    assert turn.argv[:3] == ("/opt/bin/codex", "exec", "resume")
    assert turn.argv[-2] == "thread-123"
    assert turn.argv[-1].endswith("Make the figure.")


def test_evaluation_cannot_pass_a_multiturn_scenario_when_only_turn_one_ran(
    monkeypatch,
):
    scenario = EvalScenario(
        name="two-turns",
        prompt="Analyse it.",
        required_subsequence=(),
        max_calls=0,
        follow_up=EvalScenario(
            name="follow-up",
            prompt="Make the figure.",
            required_subsequence=(),
            max_calls=0,
        ),
    )
    monkeypatch.setattr(
        agent_eval,
        "run_agent_scenario",
        lambda *_args, **_kwargs: {
            "agent": "codex",
            "scenario": "two-turns",
            "passed": True,
            "reasons": [],
            "tool_calls": [],
            "final_answer": "Turn one only.",
        },
    )

    report = agent_eval.run_evaluation(
        ["codex"],
        [scenario],
        server_executable="molcompose-mcp",
        timeout=1,
    )

    assert report["passed"] is False
    assert report["results"][0]["reasons"] == [
        "multiturn scenario did not run every turn"
    ]


def test_runner_never_spends_a_follow_up_after_the_first_process_failed():
    follow_up = EvalScenario(
        name="follow-up",
        prompt="Continue.",
        required_subsequence=(),
        max_calls=0,
    )
    current = EvalScenario(
        name="first",
        prompt="Start.",
        required_subsequence=(),
        max_calls=0,
        follow_up=follow_up,
    )

    assert _should_run_follow_up(
        current, {"returncode": 0, "timed_out": False}
    )
    assert not _should_run_follow_up(
        current, {"returncode": 1, "timed_out": False}
    )
    assert not _should_run_follow_up(
        current, {"returncode": 124, "timed_out": True}
    )
    assert not _should_run_follow_up(
        follow_up, {"returncode": 0, "timed_out": False}
    )


def test_sequence_score_requires_the_guided_tools_in_order_and_a_small_budget():
    scenario = EvalScenario(
        name="explicit-interface",
        prompt="1BRS 的 A 和 D 靠什么结合？",
        required_subsequence=("inspect_session", "analyse_interface"),
        max_calls=3,
    )

    passing = score_tool_calls(
        scenario,
        [
            {"name": "inspect_session", "arguments": {}},
            {"name": "analyse_interface", "arguments": {}},
        ],
    )
    wrong_order = score_tool_calls(
        scenario,
        [
            {"name": "analyse_interface", "arguments": {}},
            {"name": "inspect_session", "arguments": {}},
        ],
    )
    too_many = score_tool_calls(
        scenario,
        [
            {"name": "inspect_session", "arguments": {}},
            {"name": "list_models", "arguments": {}},
            {"name": "detect_interface", "arguments": {}},
            {"name": "analyse_interface", "arguments": {}},
        ],
    )

    assert passing == {"passed": True, "reasons": []}
    assert wrong_order == {
        "passed": False,
        "reasons": [
            "required tool order not observed: inspect_session -> analyse_interface"
        ],
    }
    assert too_many == {
        "passed": False,
        "reasons": [
            "4 MCP calls exceeded the limit of 3",
            "expert-only tools were used: detect_interface, list_models",
        ],
    }

    resource_detour = score_tool_calls(
        scenario,
        [
            {"name": "inspect_session", "arguments": {}},
            {"name": "list_mcp_resources", "arguments": {"server": "molcompose"}},
            {
                "name": "read_mcp_resource",
                "arguments": {
                    "server": "molcompose",
                    "uri": "molcompose://skill",
                },
            },
            {"name": "analyse_interface", "arguments": {}},
        ],
    )
    assert resource_detour == {
        "passed": False,
        "reasons": ["4 MCP calls exceeded the limit of 3"],
    }


def test_sequence_score_can_forbid_unsafe_progress_after_a_failed_quality_gate():
    scenario = EvalScenario(
        name="cropped-preview",
        prompt="Preview the figure and stop if it is cropped.",
        required_subsequence=("compose_figure", "render_preview"),
        max_calls=4,
        forbidden_tools=("export_artifact",),
    )

    result = score_tool_calls(
        scenario,
        [
            {"name": "compose_figure", "arguments": {}},
            {"name": "render_preview", "arguments": {}},
            {"name": "export_artifact", "arguments": {"path": "bad.png"}},
        ],
    )

    assert result == {
        "passed": False,
        "reasons": ["forbidden tools were used: export_artifact"],
    }


def test_hotspot_figure_contract_requires_preview_before_export():
    scenario = next(
        item for item in DEFAULT_SCENARIOS if item.name == "hotspot-figure"
    )

    skipped_preview = score_tool_calls(
        scenario,
        [
            {"name": "inspect_session", "arguments": {}},
            {"name": "analyse_interface", "arguments": {}},
            {"name": "compose_figure", "arguments": {"goal": "hotspot-map"}},
            {"name": "export_artifact", "arguments": {"path": "figure.png"}},
        ],
    )

    assert skipped_preview == {
        "passed": False,
        "reasons": [
            "required tool order not observed: inspect_session -> "
            "analyse_interface -> compose_figure -> render_preview -> "
            "export_artifact"
        ],
    }


def test_interface_eval_rejects_an_unrequested_non_default_cutoff():
    scenario = EvalScenario(
        name="default-interface",
        prompt="Analyse this interface.",
        required_subsequence=("analyse_interface",),
        max_calls=1,
        tool_argument_constraints=(
            ("analyse_interface", "criterion", (None, "heavy")),
            ("analyse_interface", "distance", (None, 4.5)),
        ),
    )

    result = score_tool_calls(scenario, [{
        "name": "analyse_interface",
        "arguments": {"criterion": "heavy", "distance": 5.0},
    }])

    assert result == {
        "passed": False,
        "reasons": [
            "analyse_interface.distance used 5.0; allowed: omitted or 4.5"
        ],
    }


def test_answer_score_requires_measurement_context_and_limitations():
    scenario = EvalScenario(
        name="scientific-answer",
        prompt="这个界面主要靠什么结合？",
        required_subsequence=("inspect_session", "analyse_interface"),
        max_calls=3,
        required_answer_concepts=(
            ("heavy", "重原子"),
            ("4.5 Å", "4.5 A", "4.5 angstrom", "4.5 埃"),
            ("residue pair", "残基对"),
            ("skipped", "跳过", "不适用", "拒绝", "无法计算"),
        ),
        conditional_answer_concepts=(
            (
                ("ΔG", "K_d", "Kd", "affinity", "亲和力"),
                ("estimate", "estimated", "估计", "估算"),
            ),
        ),
    )
    calls = [
        {"name": "inspect_session", "arguments": {}},
        {"name": "analyse_interface", "arguments": {}},
    ]

    result = evaluate_stream(
        scenario,
        "codex-jsonl",
        "\n".join([
            json.dumps({
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "server": "molcompose",
                    "tool": call["name"],
                    "arguments": call["arguments"],
                },
            })
            for call in calls
        ] + [json.dumps({
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": "界面有 43 个接触，亲和力很好。",
            },
        })]),
        returncode=0,
    )

    assert result["passed"] is False
    assert result["reasons"] == [
        "agent answer omitted required concept: heavy | 重原子",
        "agent answer omitted required concept: 4.5 Å | 4.5 A | "
        "4.5 angstrom | 4.5 埃",
        "agent answer omitted required concept: residue pair | 残基对",
        "agent answer omitted required concept: skipped | 跳过 | 不适用 | "
        "拒绝 | 无法计算",
        "agent answer omitted required concept: estimate | estimated | 估计 | 估算",
    ]


def test_default_interface_eval_rejects_an_unsupported_short_answer():
    scenario = next(
        item for item in DEFAULT_SCENARIOS if item.name == "explicit-interface"
    )
    stdout = "\n".join([
        json.dumps({
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "inspect_session",
                "arguments": {},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "analyse_interface",
                "arguments": {"group_a": ["A"], "group_b": ["D"]},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": "这个界面主要靠氢键和疏水作用。",
            },
        }),
    ])

    result = evaluate_stream(scenario, "codex-jsonl", stdout, returncode=0)

    assert result["passed"] is False
    assert "agent answer omitted required concept: heavy | 重原子" in result["reasons"]
    assert (
        "agent answer omitted required concept: residue pair | 残基对 | 对接触残基"
        in result["reasons"]
    )


def test_default_suite_covers_multiturn_ambiguity_recovery_and_bad_preview():
    scenarios = {scenario.name: scenario for scenario in DEFAULT_SCENARIOS}

    assert {
        "multiturn-hotspot",
        "ambiguous-models",
        "recoverable-failure",
        "cropped-preview",
    } <= scenarios.keys()
    assert scenarios["multiturn-hotspot"].follow_up is not None
    assert scenarios["multiturn-hotspot"].follow_up.required_subsequence == (
        "compose_figure",
        "render_preview",
        "export_artifact",
    )
    assert scenarios["ambiguous-models"].fixture == "ambiguous-models"
    assert scenarios["recoverable-failure"].fixture == "recoverable-failure"
    assert scenarios["cropped-preview"].fixture == "cropped-preview"
    assert scenarios["cropped-preview"].forbidden_tools == ("export_artifact",)


def test_recovery_answer_accepts_a_clear_resume_after_reconnection_instruction():
    scenario = next(
        item for item in DEFAULT_SCENARIOS if item.name == "recoverable-failure"
    )
    answer = (
        "当前 bridge 暂时中断，无法确认结构内容。请重新连接；"
        "恢复后再次让我检查，我会从 inspect_session 重新开始。"
    )

    assert score_answer(scenario, answer) == []


def test_answer_score_rejects_scientific_claims_after_a_failed_inspection():
    scenario = EvalScenario(
        name="failure-no-invention",
        prompt="Inspect the session.",
        required_subsequence=("inspect_session",),
        max_calls=1,
        forbidden_answer_concepts=(
            "hydrogen bond",
            "氢键",
            "buried area",
            "埋藏面积",
        ),
    )

    assert score_answer(scenario, "连接失败，但界面有 8 个氢键。") == [
        "agent answer included forbidden concept after failure: 氢键"
    ]


def test_default_answer_does_not_require_affinity_disclosure_when_it_omits_affinity():
    scenario = next(
        item for item in DEFAULT_SCENARIOS if item.name == "explicit-interface"
    )
    answer = (
        "Heavy criterion at 4.5 Å found 43 contacting residue pairs. "
        "Prediction confidence was not applicable and was skipped."
    )

    assert score_answer(scenario, answer) == []


def test_affinity_disclosure_is_required_only_when_affinity_is_reported():
    scenario = EvalScenario(
        name="conditional-affinity",
        prompt="Summarise the interface.",
        required_subsequence=(),
        max_calls=0,
        conditional_answer_concepts=((
            ("ΔG", "K_d", "Kd", "affinity", "亲和力"),
            ("estimate", "estimated", "估计", "估算"),
        ),),
    )

    assert score_answer(scenario, "The interface is compact.") == []
    assert score_answer(scenario, "ΔG is -12.4 kcal/mol.") == [
        "agent answer omitted required concept: estimate | estimated | 估计 | 估算"
    ]


def test_residue_pair_concept_accepts_equivalent_chinese_word_order():
    scenario = next(
        item for item in DEFAULT_SCENARIOS if item.name == "explicit-interface"
    )
    answer = "重原子 4.5 Å：界面共有 43 对接触残基；置信度项目被跳过。"

    assert score_answer(scenario, answer) == []


def test_figure_answer_does_not_have_to_repeat_unavailable_analyses():
    scenario = next(
        item for item in DEFAULT_SCENARIOS if item.name == "hotspot-figure"
    )
    answer = (
        "PNG exported after preview: heavy criterion at 4.5 Å found "
        "43 contacting residue pairs."
    )

    assert score_answer(scenario, answer) == []


def test_scenario_rest_server_exposes_one_model_and_tracks_interface_state(tmp_path):
    with ScenarioRestServer() as server:
        def run(command):
            url = f"{server.url}/run?{urlencode({'command': command})}"
            with urlopen(url, timeout=2) as response:  # noqa: S310 - localhost fixture
                return json.loads(response.read())

        models = run("info models")["json values"][0]
        chains = run("info chains")["json values"][0]
        before = run("molcompose blocks model #1")
        analysis = run("molcompose characterise A D model #1")
        after = run("molcompose blocks model #1")
        preview = tmp_path / "preview.png"
        saved = run(f'save "{preview}" width 640 height 640')
        export = tmp_path / "interface.png"
        exported = run(
            f'molcompose export "{export}" width 1200 height 900 '
            "supersample 1 transparent false saveSession true saveRecipe true"
        )

        assert saved["error"] is None
        preview_bytes = preview.read_bytes()
        assert preview_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", preview_bytes[16:24]) == (640, 640)
        assert exported["error"] is None
        export_bytes = export.read_bytes()
        assert struct.unpack(">II", export_bytes[16:24]) == (1200, 900)
        assert export.with_suffix(".cxc").is_file()
        assert export.with_suffix(".cxs").is_file()

    assert models == [
        {"spec": "#1", "value": "1brs.pdb", "class": "AtomicStructure"}
    ]
    assert [row["value"] for row in chains] == ["A", "D"]
    assert before["error"]["message"].startswith("Detect an interface first")
    assert analysis["json values"][0]["interface"]["chains_a"] == ["A"]
    assert [row["kind"] for row in after["json values"][0]] == [
        "groupA", "groupB", "ifaceA", "ifaceB"
    ]
    assert not preview.exists()
    assert not export.exists()
    assert not export.with_suffix(".cxc").exists()
    assert not export.with_suffix(".cxs").exists()


def test_ambiguous_model_fixture_exposes_two_complete_candidates():
    with ScenarioRestServer(fixture="ambiguous-models") as server:
        def run(command):
            url = f"{server.url}/run?{urlencode({'command': command})}"
            with urlopen(url, timeout=2) as response:  # noqa: S310 - local fixture
                return json.loads(response.read())

        models = run("info models")["json values"][0]
        chains = run("info chains")["json values"][0]

    assert [model["spec"] for model in models] == ["#1", "#2"]
    assert [(chain["spec"], chain["value"]) for chain in chains] == [
        ("#1/A", "A"),
        ("#1/D", "D"),
        ("#2/A", "A"),
        ("#2/D", "D"),
    ]


def test_recoverable_failure_fixture_returns_a_user_facing_error_not_a_traceback():
    with ScenarioRestServer(fixture="recoverable-failure") as server:
        url = f"{server.url}/run?{urlencode({'command': 'info models'})}"
        with urlopen(url, timeout=2) as response:  # noqa: S310 - local fixture
            payload = json.loads(response.read())

    assert payload["error"] == {
        "type": "UserError",
        "message": "Temporary ChimeraX bridge interruption; retry inspect_session.",
    }
    assert "Traceback" not in json.dumps(payload)


def _png_pixels(payload):
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", payload[16:24])
    offset = 8
    compressed = bytearray()
    while offset < len(payload):
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        kind = payload[offset + 4:offset + 8]
        data = payload[offset + 8:offset + 8 + length]
        checksum = struct.unpack(">I", payload[offset + 8 + length:offset + 12 + length])[0]
        assert checksum == zlib.crc32(kind + data)
        if kind == b"IDAT":
            compressed.extend(data)
        offset += 12 + length
    rows = zlib.decompress(bytes(compressed))
    assert len(rows) == height * (1 + width * 3)

    def pixel(x, y):
        start = y * (1 + width * 3)
        assert rows[start] == 0
        index = start + 1 + x * 3
        return tuple(rows[index:index + 3])

    return width, height, pixel


def test_preview_png_preserves_shape_boundaries_overlap_and_hotspot_priority():
    width, height, pixel = _png_pixels(agent_eval._preview_png(120, 90))

    assert (width, height) == (120, 90)
    for point, colour in [
        ((0, 0), (246, 247, 250)),
        ((17, 45), (246, 247, 250)),
        ((18, 45), (66, 133, 244)),
        ((30, 45), (66, 133, 244)),
        ((60, 40), (126, 87, 194)),
        ((90, 45), (255, 167, 38)),
        ((102, 45), (255, 167, 38)),
        ((103, 45), (246, 247, 250)),
        ((48, 14), (246, 247, 250)),
        ((48, 15), (66, 133, 244)),
        ((40, 16), (246, 247, 250)),
        ((41, 16), (66, 133, 244)),
        ((48, 75), (66, 133, 244)),
        ((48, 76), (246, 247, 250)),
        ((60, 24), (211, 47, 47)),
        ((60, 23), (126, 87, 194)),
        ((62, 25), (211, 47, 47)),
        ((63, 25), (126, 87, 194)),
        ((60, 45), (211, 47, 47)),
    ]:
        assert pixel(*point) == colour, point


@pytest.mark.parametrize(
    ("width", "height", "edge_x", "edge_y"),
    [(120, 120, 42, 21), (120, 60, 39, 11), (127, 103, 43, 18)],
)
def test_preview_png_respects_ellipse_aspect_ratio(width, height, edge_x, edge_y):
    _, _, pixel = _png_pixels(agent_eval._preview_png(width, height))

    assert pixel(edge_x - 1, edge_y) == (246, 247, 250)
    assert pixel(edge_x, edge_y) == (66, 133, 244)


@pytest.mark.parametrize(
    ("width", "height", "cropped", "expected_rows"),
    [
        (1, 1, False, [[(211, 47, 47)]]),
        (1, 1, True, [[(126, 87, 194)]]),
        (2, 3, True, [
            [(246, 247, 250), (246, 247, 250)],
            [(246, 247, 250), (66, 133, 244)],
            [(246, 247, 250), (246, 247, 250)],
        ]),
    ],
)
def test_preview_png_clips_shapes_to_small_images(width, height, cropped, expected_rows):
    actual_width, actual_height, pixel = _png_pixels(
        agent_eval._preview_png(width, height, cropped=cropped)
    )

    assert (actual_width, actual_height) == (width, height)
    assert [[pixel(x, y) for x in range(width)] for y in range(height)] == expected_rows


def test_cropped_preview_fixture_places_only_a_subject_sliver_at_the_right_edge(
    tmp_path,
):
    with ScenarioRestServer(fixture="cropped-preview") as server:
        preview = tmp_path / "cropped.png"
        command = f'save "{preview}" width 120 height 90'
        url = f"{server.url}/run?{urlencode({'command': command})}"
        with urlopen(url, timeout=2) as response:  # noqa: S310 - local fixture
            assert json.loads(response.read())["error"] is None
        payload = preview.read_bytes()

    width, height, pixel = _png_pixels(payload)
    background = (246, 247, 250)
    assert pixel(width // 2, height // 2) == background
    assert pixel(width - 1, height // 2) != background
    assert pixel(89, 45) == background
    assert pixel(90, 45) == (66, 133, 244)
    assert pixel(105, 25) == background
    assert pixel(106, 25) == (66, 133, 244)


def test_stream_evaluation_combines_real_call_order_exit_and_final_answer():
    scenario = EvalScenario(
        name="explicit-interface",
        prompt="1BRS 的 A 和 D 靠什么结合？",
        required_subsequence=("inspect_session", "analyse_interface"),
        max_calls=3,
    )
    stdout = "\n".join([
        json.dumps({
            "type": "item.completed",
            "item": {
                "id": "call-1",
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "inspect_session",
                "arguments": {},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {
                "id": "call-2",
                "type": "mcp_tool_call",
                "server": "molcompose",
                "tool": "analyse_interface",
                "arguments": {"group_a": ["A"], "group_b": ["D"]},
            },
        }),
        json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "界面由氢键等作用稳定。"},
        }),
    ])

    result = evaluate_stream(scenario, "codex-jsonl", stdout, returncode=0)
    failed = evaluate_stream(scenario, "codex-jsonl", "", returncode=2)

    assert result == {
        "passed": True,
        "reasons": [],
        "tool_calls": [
            {"name": "inspect_session", "arguments": {}},
            {
                "name": "analyse_interface",
                "arguments": {"group_a": ["A"], "group_b": ["D"]},
            },
        ],
        "final_answer": "界面由氢键等作用稳定。",
    }
    assert failed == {
        "passed": False,
        "reasons": [
            "agent process exited with code 2",
            "agent returned no final answer",
            "required tool order not observed: inspect_session -> analyse_interface",
        ],
        "tool_calls": [],
        "final_answer": "",
    }


def test_stream_evaluation_fails_when_the_client_received_a_tool_error():
    scenario = EvalScenario(
        name="inspect",
        prompt="分析当前结构",
        required_subsequence=("inspect_session",),
        max_calls=2,
    )
    stdout = "\n".join([
        json.dumps({
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "mcp__molcompose__inspect_session",
                    "input": {},
                }]
            },
        }),
        json.dumps({
            "type": "user",
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "is_error": True,
                    "content": "Structured content does not match the output schema",
                }]
            },
        }),
        json.dumps({
            "type": "result",
            "result": "无法回答。",
        }),
    ])

    result = evaluate_stream(
        scenario, "claude-stream-json", stdout, returncode=0
    )

    assert result["passed"] is False
    assert result["reasons"] == [
        "tool error: Structured content does not match the output schema",
        "agent answer indicates refusal: 无法回答",
    ]


def test_stream_evaluation_reports_account_limits_without_rubric_noise():
    scenario = next(
        item for item in DEFAULT_SCENARIOS if item.name == "explicit-interface"
    )
    stdout = json.dumps({
        "type": "result",
        "result": "You've hit your session limit · resets at noon",
    })

    result = evaluate_stream(
        scenario,
        "claude-stream-json",
        stdout,
        returncode=1,
    )

    assert result["passed"] is False
    assert result["reasons"] == [
        "agent process exited with code 1",
        "agent unavailable: session limit",
    ]


def test_eval_runner_loads_panel_adapters_in_plain_python_without_chimerax():
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from scripts.agent_behavior_eval import _repository_imports; "
                "get_agent, *_ = _repository_imports(); "
                "assert get_agent('codex').key == 'codex'"
            ),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr
