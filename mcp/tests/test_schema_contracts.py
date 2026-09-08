"""The generated MCP contract should let clients choose and correct tools."""

import asyncio
import re

import pytest
from molcompose_mcp.server import create_server

LEGACY_TOOLS = {
    "list_models", "open_structure", "apply_style", "characterise_interface",
    "detect_interface", "detect_all_interfaces", "focus", "show_hbonds",
    "write_report", "predict_ddg_pythiastudio", "load_energy", "list_blocks",
    "load_flexibility", "load_ddg", "rank_hotspots", "measure_buried_area",
    "predict_affinity", "analyze_interactions", "compute_ipsae",
    "score_against_reference", "check_capabilities", "get_confidence",
    "show_contacts", "reset", "export_figure", "export_sequence_coloring",
    "run_native", "render_preview", "get_recipe",
}

ASSISTANT_TOOLS = {
    "open_structure",
    "inspect_session",
    "analyse_interface",
    "compose_figure",
    "render_preview",
    "export_artifact",
    "load_external_evidence",
}

READ_ONLY = {
    "list_models", "list_blocks", "check_capabilities", "get_confidence",
    "render_preview", "get_recipe", "inspect_session",
}
SESSION_MUTATION = {
    "apply_style", "characterise_interface", "detect_interface",
    "detect_all_interfaces", "focus", "show_hbonds", "load_energy",
    "load_flexibility", "load_ddg", "rank_hotspots", "measure_buried_area",
    "predict_affinity", "analyze_interactions", "compute_ipsae",
    "score_against_reference", "show_contacts", "reset", "run_native",
    "analyse_interface", "compose_figure",
}
LOCAL_WRITE = {
    "write_report", "export_figure", "export_sequence_coloring", "export_artifact",
}
OPEN_WORLD_MUTATION = {"open_structure"}
EXTERNAL_UPLOAD = {"predict_ddg_pythiastudio", "load_external_evidence"}


def _tools():
    app = create_server("http://127.0.0.1:65500", launch=False)
    return {tool.name: tool for tool in asyncio.run(app.list_tools())}


def _profile_tools(profile):
    app = create_server(
        "http://127.0.0.1:65500", profile=profile, launch=False
    )
    return {tool.name for tool in asyncio.run(app.list_tools())}


def _property(tool, name):
    return tool.input_schema["properties"][name]


def _branch_with(schema, key):
    if key in schema:
        return schema
    return next(branch for branch in schema.get("anyOf", ()) if key in branch)


def test_the_legacy_surface_remains_available():
    assert LEGACY_TOOLS <= set(_tools())


def test_profiles_publish_only_the_tools_their_callers_need():
    assert _profile_tools("assistant") == ASSISTANT_TOOLS
    assert _profile_tools("expert") == LEGACY_TOOLS
    assert _profile_tools("all") == LEGACY_TOOLS | ASSISTANT_TOOLS


def test_assistant_profile_does_not_publish_the_expert_methodology_resource():
    async def resources(profile):
        app = create_server(
            "http://127.0.0.1:65500", profile=profile, launch=False
        )
        return {str(resource.uri) for resource in await app.list_resources()}

    assert asyncio.run(resources("assistant")) == set()
    assert asyncio.run(resources("expert")) == {"molcompose://skill"}
    assert asyncio.run(resources("all")) == {"molcompose://skill"}


def test_assistant_profile_reduces_tool_description_context_by_over_ninety_percent():
    def description_characters(profile):
        app = create_server(
            "http://127.0.0.1:65500", profile=profile, launch=False
        )
        return sum(
            len(tool.description or "") for tool in asyncio.run(app.list_tools())
        )

    assistant = description_characters("assistant")
    complete = description_characters("all")

    assert assistant <= 1_000
    assert assistant < complete * 0.1


def test_the_default_profile_preserves_the_complete_existing_surface():
    assert set(_tools()) == _profile_tools("all")


def test_profile_instructions_never_recommend_a_hidden_tool():
    known = LEGACY_TOOLS | ASSISTANT_TOOLS
    for profile in ("assistant", "expert", "all"):
        app = create_server(
            "http://127.0.0.1:65500", profile=profile, launch=False
        )
        mentioned = set(re.findall(r"`([a-z][a-z0-9_]*)`", app.instructions or ""))
        assert mentioned & known <= _profile_tools(profile), profile


def test_assistant_instructions_require_visual_review_before_export():
    instructions = create_server(
        "http://127.0.0.1:65500", profile="assistant", launch=False
    ).instructions

    assert instructions.index("`render_preview`") < instructions.index(
        "`export_artifact`"
    )
    assert "cropped" in instructions
    assert "colour key" in instructions
    assert "cannot visually verify" in instructions


def test_assistant_instructions_explain_metric_scope_without_magic_thresholds():
    instructions = create_server(
        "http://127.0.0.1:65500", profile="assistant", launch=False
    ).instructions

    assert "ipTM is a whole-complex" in instructions
    assert "pDockQ2 and ipSAE are chain-pair" in instructions
    assert "predictor and oligomeric state" in instructions
    assert "do not average or silently choose one" in instructions
    assert "Interface size alone cannot identify crystal packing" in instructions
    assert "keep the default heavy criterion and 4.5 Å cutoff" in instructions


def test_an_unknown_profile_is_rejected_before_server_registration():
    with pytest.raises(ValueError, match="unknown MCP profile"):
        create_server("http://127.0.0.1:65500", profile="tiny", launch=False)


def test_assistant_outcome_schema_names_machine_readable_next_steps():
    tools = {
        tool.name: tool
        for tool in asyncio.run(
            create_server(
                "http://127.0.0.1:65500", profile="assistant", launch=False
            ).list_tools()
        )
    }
    schema = tools["analyse_interface"].output_schema
    assert "next_steps" in schema["properties"]
    assert schema["properties"]["next_steps"]["items"]["enum"] == [
        "open_structure",
        "analyse_interface",
        "compose_figure",
        "render_preview",
        "export_artifact",
        "load_external_evidence",
    ]


def test_export_artifact_schema_describes_each_file_quality_check():
    tools = {
        tool.name: tool
        for tool in asyncio.run(
            create_server(
                "http://127.0.0.1:65500", profile="assistant", launch=False
            ).list_tools()
        )
    }
    schema = tools["export_artifact"].output_schema
    qa_field = schema["properties"]["qa"]
    qa = schema["$defs"][qa_field["$ref"].rsplit("/", 1)[-1]]

    assert {"passed", "artifacts"} <= set(qa["properties"])
    artifact_field = qa["properties"]["artifacts"]["additionalProperties"]
    artifact = schema["$defs"][artifact_field["$ref"].rsplit("/", 1)[-1]]
    assert {"path", "exists", "non_empty", "bytes"} <= set(
        artifact["properties"]
    )


def test_finite_choices_are_machine_readable_enums():
    tools = _tools()
    expected = {
        ("apply_style", "preset"): {
            "clean-cartoon", "complex-by-chain", "interface-focus", "flat-outline",
            "licorice-closeup", "licorice-chain", "surface-complex",
            "epitope-surface", "surface-partner-a", "surface-translucent",
            "surface-epitope-map", "paratope-closeup", "hotspot-focus",
            "predicted-structure", "metric-map", "design-reference",
        },
        ("characterise_interface", "criterion"): {"heavy", "cbeta", "vdw"},
        ("detect_interface", "criterion"): {"heavy", "cbeta", "vdw"},
        ("detect_all_interfaces", "criterion"): {"heavy", "cbeta", "vdw"},
        ("focus", "target"): {"model", "interface"},
        ("write_report", "format"): {"json", "csv", "md"},
        ("predict_ddg_pythiastudio", "tool"): {"pythia", "pythia-ppi"},
        ("load_ddg", "format"): {"tabular", "pythia", "pythia-ppi"},
        ("load_ddg", "statistic"): {"min", "max", "mean"},
        ("rank_hotspots", "metric"): {"dsasa", "energy"},
        ("check_capabilities", "predictor"): {
            "generic", "alphafold3", "alphafold-server", "alphafold-db",
            "af2-multimer", "protenix", "boltz", "colabfold", "chai",
        },
        ("export_sequence_coloring", "source"): {
            "interface", "plddt", "ddg", "dsasa", "bfactor", "mmpbsa",
        },
        ("analyse_interface", "criterion"): {"heavy", "cbeta", "vdw"},
        ("compose_figure", "goal"): {
            "interface-overview", "interaction-closeup", "binder-closeup",
            "epitope-surface", "hotspot-map", "confidence", "whole-complex",
            "metric-map",
        },
        ("load_external_evidence", "kind"): {
            "ddg", "energy", "flexibility", "pythiastudio",
        },
        ("load_external_evidence", "format"): {"tabular", "pythia", "pythia-ppi"},
        ("load_external_evidence", "statistic"): {"min", "max", "mean"},
        ("load_external_evidence", "tool"): {"pythia", "pythia-ppi"},
    }
    for (tool_name, parameter), allowed in expected.items():
        enum_schema = _branch_with(_property(tools[tool_name], parameter), "enum")
        assert set(enum_schema["enum"]) == allowed, f"{tool_name}.{parameter}"


def test_compound_string_domains_publish_patterns():
    tools = _tools()
    assert "pattern" in _branch_with(
        _property(tools["analyze_interactions"], "types"), "pattern"
    )
    for tool_name in ("characterise_interface", "detect_interface"):
        for parameter in ("group_a", "group_b"):
            items = _property(tools[tool_name], parameter)["items"]
            assert items["pattern"] == "^[A-Za-z0-9]{1,4}$"


def test_numeric_constraints_match_the_bundle_contract():
    tools = _tools()
    for tool_name in ("characterise_interface", "detect_interface", "detect_all_interfaces"):
        distance = _property(tools[tool_name], "distance")
        assert (distance["minimum"], distance["maximum"]) == (2.0, 10.0)

    labels = _branch_with(_property(tools["apply_style"], "labels"), "minimum")
    assert labels["minimum"] == 0
    for name in ("width", "height"):
        dimension = _property(tools["export_figure"], name)
        assert (dimension["minimum"], dimension["maximum"]) == (1, 16384)
    supersample = _property(tools["export_figure"], "supersample")
    assert (supersample["minimum"], supersample["maximum"]) == (1, 8)
    key_font = _branch_with(
        _property(tools["export_figure"], "key_font_size"), "minimum"
    )
    assert (key_font["minimum"], key_font["maximum"]) == (4, 400)
    temperature = _property(tools["predict_affinity"], "temperature")
    assert (temperature["exclusiveMinimum"], temperature["maximum"]) == (
        -273.15, 1000.0
    )
    pae_cutoff = _property(tools["compute_ipsae"], "pae_cutoff")
    assert (pae_cutoff["exclusiveMinimum"], pae_cutoff["maximum"]) == (0.0, 100.0)

    api_key = _branch_with(
        _property(tools["predict_ddg_pythiastudio"], "api_key"), "writeOnly"
    )
    assert api_key["writeOnly"] is True
    assert _property(tools["predict_ddg_pythiastudio"], "api_key")["deprecated"] is True


def test_structured_tools_publish_output_schemas():
    tools = _tools()
    without_schema = {
        name for name, tool in tools.items()
        if name != "render_preview" and tool.output_schema is None
    }
    assert not without_schema

    expected_properties = {
        "list_models": {"models", "chains", "log"},
        "apply_style": {"commands", "log"},
        "characterise_interface": {"interface", "skipped", "log"},
        "export_figure": {"png", "session", "recipe", "provenance", "log"},
    }
    for name, properties in expected_properties.items():
        assert properties <= set(tools[name].output_schema["properties"]), name
        required = set(tools[name].output_schema.get("required", ()))
        assert "log" in required, name
    assert "commands" in tools["apply_style"].output_schema.get("required", ())
    assert {"png", "session", "recipe", "provenance"} <= set(
        tools["export_figure"].output_schema.get("required", ())
    )
    assert {"models", "chains"} <= set(
        tools["list_models"].output_schema.get("required", ())
    )


def test_render_preview_uses_native_image_content_instead_of_structured_json():
    tool = _tools()["render_preview"]
    assert tool.output_schema is None
    assert "PNG preview" in tool.description


def test_every_tool_declares_accurate_side_effect_metadata():
    tools = _tools()
    categories = READ_ONLY | SESSION_MUTATION | LOCAL_WRITE | OPEN_WORLD_MUTATION | EXTERNAL_UPLOAD
    assert categories == set(tools)

    for name, tool in tools.items():
        annotation = tool.annotations
        assert annotation is not None, name
        if name in READ_ONLY:
            assert annotation.read_only_hint is True
            assert annotation.destructive_hint is False
            assert annotation.idempotent_hint is True
            assert annotation.open_world_hint is False
        elif name in LOCAL_WRITE:
            assert annotation.read_only_hint is False
            assert annotation.destructive_hint is True
            assert annotation.idempotent_hint is False
            assert annotation.open_world_hint is False
        elif name in EXTERNAL_UPLOAD:
            assert annotation.read_only_hint is False
            assert annotation.destructive_hint is False
            assert annotation.idempotent_hint is False
            assert annotation.open_world_hint is True
        elif name in OPEN_WORLD_MUTATION:
            assert annotation.read_only_hint is False
            assert annotation.destructive_hint is False
            assert annotation.idempotent_hint is False
            assert annotation.open_world_hint is True
        else:
            assert annotation.read_only_hint is False
            assert annotation.destructive_hint is False
            assert annotation.idempotent_hint is False
            assert annotation.open_world_hint is False
