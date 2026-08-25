"""Host-light tests for the pure parts of molcompose-mcp."""

import json
from pathlib import Path

import pytest
from molcompose_mcp import __version__
from molcompose_mcp.chimerax import NO_VALUE, command_value, log_text
from molcompose_mcp.recipe import RecipeLog, build_provenance, disclosure_text
from molcompose_mcp.server import (
    CRITERIA,
    PRESETS,
    REFERENCE_PRESETS,
    build_export_command,
    build_flexibility_command,
    build_hotspots_command,
    build_interface_command,
    build_style_command,
    command_list,
    name_hotspot_rows,
    native_allowed,
    normalise_model_listing,
    parse_bundle_version,
    parse_interface_counts,
    with_log,
)


def test_the_packaged_version_and_the_reported_version_are_the_same():
    """The bundle has guarded this since August; the server did not.

    `mcp/pyproject.toml` decides what PyPI serves and what `pip install
    molcompose-mcp` puts on a machine. `__version__` is what
    `build_provenance` writes into the agent-side record of every figure.
    They are one fact in two files, and a record naming a version that was
    never published is the failure the record exists to prevent.
    """
    import re
    import tomllib

    root = Path(__file__).resolve().parents[1]
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    source = (root / "molcompose_mcp" / "__init__.py").read_text()
    reported = re.search(r'^__version__ = "([^"]+)"', source, re.M)
    assert reported is not None, "molcompose_mcp/__init__.py must declare __version__"
    assert reported.group(1) == declared, (
        f"pyproject says {declared}, the server reports {reported.group(1)}"
    )


def test_presets_and_criteria_stay_in_lockstep_with_bundle():
    from src.adapters.model_context import CRITERIA as BUNDLE_CRITERIA
    from src.core.presets import PRESETS as BUNDLE_PRESETS

    assert set(PRESETS) == set(BUNDLE_PRESETS)
    assert tuple(CRITERIA) == tuple(BUNDLE_CRITERIA)


def test_reference_presets_stay_in_lockstep_with_bundle():
    """Name parity is not enough; the arguments have to come across too.

    `design-reference` was added to PRESETS on its own once. An agent could
    then name a preset whose command it had no way to complete, and the only
    reachable outcome was the bundle's "needs references, align and partner"
    error. Matching the bundle's own flag here means a future preset with
    extra requirements cannot be advertised without them.
    """
    from src.core.presets import PRESETS as BUNDLE_PRESETS

    bundle = {slug for slug, preset in BUNDLE_PRESETS.items()
              if preset.reference_comparison}
    assert set(REFERENCE_PRESETS) == bundle


def test_reference_preset_requires_all_three_arguments():
    assert build_style_command(
        "design-reference", "#1", references="#2,#3", align="A", partner="B"
    ) == (
        "molcompose style design-reference model #1 "
        "references #2,#3 align A partner B"
    )
    with pytest.raises(ValueError, match="missing align, partner"):
        build_style_command("design-reference", "#1", references="#2")
    with pytest.raises(ValueError, match="does not take references"):
        build_style_command("interface-focus", "#1", references="#2")


def test_style_command_validates_preset():
    assert build_style_command("clean-cartoon", "#1") == (
        "molcompose style clean-cartoon model #1"
    )
    with pytest.raises(ValueError, match="unknown MolCompose preset"):
        build_style_command("glossy-rainbow")


def test_interface_command_matches_bundle_grammar():
    assert build_interface_command(["A"], ["D"], "#1", 4.5) == (
        "molcompose interface A D model #1 distance 4.5"
    )
    assert build_interface_command(["A", "B"], ["D"], None, 8.0, "cbeta") == (
        "molcompose interface A,B D distance 8 criterion cbeta"
    )


def test_interface_command_validates_inputs():
    with pytest.raises(ValueError, match="criterion"):
        build_interface_command(["A"], ["D"], criterion="magic")
    with pytest.raises(ValueError, match="distance"):
        build_interface_command(["A"], ["D"], distance=12.0)
    with pytest.raises(ValueError, match="chain"):
        build_interface_command([], ["D"])


def test_export_command_contains_every_option(tmp_path):
    command = build_export_command(tmp_path / "fig.png", save_session=True)
    assert command == (
        f'molcompose export "{tmp_path / "fig.png"}" width 2400 height 1800 '
        "supersample 3 transparent false saveSession true overwrite false "
        "dpi 300 saveRecipe false"
    )


@pytest.mark.parametrize(
    "command",
    ["view #1", "info models", "select clear", "hide #1 atoms", "turn y 90"],
)
def test_whitelist_accepts_display_commands(command):
    assert native_allowed(command)


@pytest.mark.parametrize(
    "command",
    [
        "open 1brs",           # `open` runs a .cxc or .py as readily as a .pdb
        "open evil.cxc",
        "close all",           # ends the session the agent was asked to describe
        "turn y 90 models #1",  # rotates coordinates, not the camera
        "roll y 1 models #1",
        "info models saveFile /tmp/anything",
    ],
)
def test_whitelist_rejects_the_display_verbs_that_were_not_display_only(command):
    """All accepted until 2026-08-21, under a comment calling the list
    display-state-only. Opening a structure is still available -- as
    `open_structure`, which validates what it is handed."""
    assert not native_allowed(command)


@pytest.mark.parametrize(
    "command",
    [
        "delete #1",
        "build start",
        "swapaa #1/A:1 ALA",
        "open 1brs; delete #1",  # chaining
        "save /tmp/x.png",  # exports must go through export_figure
        "",
    ],
)
def test_whitelist_rejects_everything_else(command):
    assert not native_allowed(command)


def test_parse_interface_counts_reads_molcompose_log():
    text = (
        "MolCompose interface #1 A=(A) B=(D) cutoff 4.5 Å criterion heavy — "
        "Group A: 19 residues, Group B: 16 residues, 43 contact pairs"
    )
    assert parse_interface_counts(text) == {
        "group_a_residues": 19,
        "group_b_residues": 16,
        "contact_pairs": 43,
    }
    assert parse_interface_counts("no counts here") is None


def test_log_text_flattens_rest_payload_shapes():
    assert log_text({"raw": "plain"}) == "plain"
    payload = {"log messages": {"info": ["line one", "line two"]}, "error": ""}
    assert "line one" in log_text(payload)
    assert "line two" in log_text(payload)


def test_model_listing_uses_info_values_when_native_info_logs_are_empty():
    """ChimeraX 1.12 returns `info` rows as JSON strings, not log text."""
    models = json.dumps([
        {
            "spec": "#1",
            "class": "AtomicStructure",
            "attribute": "name",
            "present": True,
            "value": "1acb.pdb",
        },
        {
            "spec": "#1.1",
            "class": "PseudobondGroup",
            "attribute": "name",
            "present": True,
            "value": "missing structure",
        },
    ])
    chains = json.dumps([
        {
            "spec": "/E",
            "attribute": "chain_id",
            "sequence": "CGVP",
            "residues": ["/E:1"],
            "polymer type": "protein",
            "present": True,
            "value": "E",
        },
        {
            "spec": "/I",
            "attribute": "chain_id",
            "sequence": "TEFG",
            "residues": ["/I:8"],
            "polymer type": "protein",
            "present": True,
            "value": "I",
        },
    ])

    listing = normalise_model_listing(models, chains, "", "")

    assert listing == {
        "models": [
            {"spec": "#1", "name": "1acb.pdb", "class": "AtomicStructure"}
        ],
        "chains": [
            {
                "spec": "/E",
                "model_spec": "#1",
                "chain_id": "E",
                "polymer_type": "protein",
                "residue_count": 1,
            },
            {
                "spec": "/I",
                "model_spec": "#1",
                "chain_id": "I",
                "polymer_type": "protein",
                "residue_count": 1,
            },
        ],
    }


def test_model_listing_associates_chains_with_each_model():
    models = [
        {"spec": "#1", "class": "AtomicStructure", "value": "first.pdb"},
        {"spec": "#2", "class": "AtomicStructure", "value": "second.pdb"},
    ]
    chains = [
        {
            "spec": "#1/A",
            "value": "A",
            "polymer type": "protein",
            "residues": ["#1/A:1", "#1/A:2"],
        },
        {
            "spec": "#2/B",
            "value": "B",
            "polymer type": "protein",
            "sequence": "GLY",
        },
    ]

    listing = normalise_model_listing(models, chains)

    assert listing["chains"] == [
        {
            "spec": "#1/A",
            "model_spec": "#1",
            "chain_id": "A",
            "polymer_type": "protein",
            "residue_count": 2,
        },
        {
            "spec": "#2/B",
            "model_spec": "#2",
            "chain_id": "B",
            "polymer_type": "protein",
            "residue_count": 3,
        },
    ]


def test_model_listing_falls_back_to_logs_without_json_values():
    listing = normalise_model_listing(
        NO_VALUE,
        "not-json",
        "model #1: 1acb.pdb",
        "chain E\nchain I",
    )

    assert listing == {
        "models_text": "model #1: 1acb.pdb",
        "chains_text": "chain E\nchain I",
        "log": "model #1: 1acb.pdb\nchain E\nchain I",
    }


def test_model_listing_returns_empty_mapping_when_discovery_returns_nothing():
    assert normalise_model_listing(NO_VALUE, NO_VALUE) == {}


# --- return values, not formatted text -----------------------------------


def test_the_return_value_comes_back_as_data_not_appended_to_the_log():
    """The whole point: a caller reads the value, not a repr inside the log."""
    payload = {
        "json values": [None],
        "python values": [{"buried_area": 1129.4, "skipped": {}}],
        "log messages": {"info": ["MolCompose buried area #1: 1129.4 Å²"]},
        "error": None,
    }
    assert command_value(payload) == {"buried_area": 1129.4, "skipped": {}}
    text = log_text(payload)
    assert "1129.4 Å²" in text
    assert "buried_area" not in text  # the dict is not stringified into the log


def test_json_values_wins_over_python_values():
    payload = {"json values": [{"named": 1}], "python values": ["Repr(named=1)"]}
    assert command_value(payload) == {"named": 1}


def test_a_bridge_without_json_mode_reports_no_value_rather_than_inventing_one():
    assert command_value({"raw": "plain text reply"}) is NO_VALUE
    assert command_value({"json values": [None], "python values": [None]}) is NO_VALUE
    assert command_value({}) is NO_VALUE


def test_a_command_returning_none_is_not_confused_with_an_absent_value():
    """`None` from a command and "no value available" are different facts."""
    assert command_value({"python values": [0]}) == 0
    assert command_value({"python values": [False]}) is False
    assert command_value({"python values": []}) is NO_VALUE


def test_with_log_puts_values_at_the_top_level_and_the_log_beside_them():
    result = with_log("some log", {"a": 1}, buried_area=1129.4)
    assert result == {"buried_area": 1129.4, "log": "some log"}
    assert "note" not in result


def test_with_log_says_so_when_the_bridge_could_not_supply_a_value():
    result = with_log("some log", NO_VALUE, buried_area=None)
    assert result["log"] == "some log"
    assert "buried_area" not in result
    assert "json true" in result["note"]


def test_hotspot_rows_get_their_field_names_back():
    value = [[["A", 59, ""], "ARG", 131.73, 10.99, 120.73]]
    assert name_hotspot_rows(value) == [
        {
            "residue": "ARG A:59",
            "chain": "A",
            "number": 59,
            "insertion_code": "",
            "name": "ARG",
            "sasa_alone": 131.73,
            "sasa_complexed": 10.99,
            "buried_area": 120.73,
        }
    ]


def test_hotspot_rows_refuse_a_shape_they_do_not_recognise():
    """A repr string or a short row yields None, never a half-filled record."""
    assert name_hotspot_rows("HotspotRow(chain='A')") is None
    assert name_hotspot_rows([["A", 59, ""], "ARG"]) is None
    assert name_hotspot_rows(NO_VALUE) is None


def test_command_list_reads_the_commands_a_display_tool_issued():
    assert command_list(["hide #1 atoms", "show #1 cartoons"]) == [
        "hide #1 atoms",
        "show #1 cartoons",
    ]
    assert command_list("not a list") is None


def test_characterise_summary_carries_every_field_figure_1c_shows():
    """Locked against a real 1BRS run through the bridge's own serialiser.

    The public interface summary includes this field, and `skipped` is the reason it
    exists: it shows that a step which could not run says why, rather than
    being silently omitted. Regenerate with mcp/tests/fixtures/README if the
    summary shape changes on purpose.
    """
    fixture = Path(__file__).parent / "fixtures" / "characterise-1brs-python-values.json"
    summary = json.loads(fixture.read_text(encoding="utf-8"))

    # Arrives as data through the same extraction the tools use.
    value = command_value({"json values": [None], "python values": [summary]})
    assert value == summary

    assert value["interface"]["residues_a"] == 19
    assert value["interface"]["residues_b"] == 16
    assert value["interface"]["contact_pairs"] == 43
    assert value["interface"]["cutoff"] == 4.5
    assert value["interactions"]["salt-bridge"] == 4
    assert round(value["buried_area"]) == 1129
    assert round(value["affinity"]["delta_g"], 2) == -10.63

    # The field the panel is for: named steps, each with its reason.
    assert set(value["skipped"]) == {"confidence", "interface_scores"}
    assert "not pLDDT confidence values" in value["skipped"]["confidence"]
    assert "no PAE file found" in value["skipped"]["interface_scores"]
    assert "confidence" not in value["steps"]


def test_provenance_contains_recipe_and_disclosure():
    recipe = RecipeLog(client_name="claude-code")
    recipe.add("open 1brs")
    recipe.add("molcompose style clean-cartoon")
    record = build_provenance(recipe, "0.1.0", __version__)
    assert record["generated_by"]["kind"] == "agent"
    assert record["generated_by"]["client"] == "claude-code"
    assert [entry["command"] for entry in record["commands"]] == [
        "open 1brs",
        "molcompose style clean-cartoon",
    ]
    text = disclosure_text(recipe, "0.1.0")
    assert "claude-code" in text
    assert "2 commands" in text


class TestMDCommands:
    """The MM/PBSA and fluctuation loaders, whose whole risk is in the
    arguments: both refuse to guess which chain is which, and an agent that
    quietly dropped the mapping would attach one partner's numbers to the
    other."""

    def test_flexibility_carries_the_ordered_chains(self):
        assert build_flexibility_command("/tmp/Complex_CA.xvg", "A,D") == (
            'molcompose flexibility "/tmp/Complex_CA.xvg" chains A,D'
        )

    def test_flexibility_takes_a_model(self):
        assert build_flexibility_command("/tmp/f.xvg", "A,D", "#2").endswith(
            "chains A,D model #2"
        )

    def test_flexibility_quotes_a_path_with_spaces(self):
        """gmx output lands in run directories people name freely."""
        command = build_flexibility_command("/tmp/my run/Complex_CA.xvg", "A,D")
        assert '"/tmp/my run/Complex_CA.xvg"' in command

    def test_export_passes_the_key_font_size_only_when_asked(self):
        plain = build_export_command("/tmp/f.png")
        assert "keyFontSize" not in plain
        sized = build_export_command("/tmp/f.png", key_font_size=96)
        assert sized.endswith("keyFontSize 96")


class TestHotspotMetric:
    """`hotspots` answers a different question per metric, so the command has
    to say which — two figures that disagree about the top residue are only
    confusing if neither states what it ranked by."""

    def test_the_default_says_nothing_extra(self):
        """Unchanged behaviour: every figure drawn so far ranked by area."""
        assert build_hotspots_command() == "molcompose hotspots"

    def test_energy_is_named(self):
        assert build_hotspots_command(metric="energy") == (
            "molcompose hotspots metric energy"
        )

    def test_min_area_is_dropped_when_ranking_by_energy(self):
        """It is a ΔSASA threshold; sent with an energy ranking it would read
        as a filter that silently did nothing."""
        command = build_hotspots_command(min_area=25.0, metric="energy")
        assert "minArea" not in command
        assert command.endswith("metric energy")

    def test_min_area_survives_the_area_ranking(self):
        assert "minArea 25" in build_hotspots_command(min_area=25.0)

    def test_top_and_model_come_through_either_way(self):
        for metric in ("dsasa", "energy"):
            command = build_hotspots_command(model="#2", top=5, metric=metric)
            assert "model #2" in command
            assert "top 5" in command


class TestBlockRows:
    """`blocks` names the four ChimeraX selections detection creates. Without
    them an agent has to guess the names or rebuild the same selections from
    residue lists it already has."""

    def test_records_rather_than_tuples(self):
        from molcompose_mcp.server import name_block_rows

        rows = name_block_rows([("groupA", "mc1_groupA", "Group A chains", 1)])
        assert rows == [{"kind": "groupA", "name": "mc1_groupA",
                         "label": "Group A chains", "count": 1}]

    def test_dicts_pass_through(self):
        from molcompose_mcp.server import name_block_rows

        given = [{"kind": "ifaceA", "name": "mc1_ifaceA"}]
        assert name_block_rows(given) == given

    def test_nothing_useful_is_none(self):
        from molcompose_mcp.server import name_block_rows

        assert name_block_rows(None) is None
        assert name_block_rows([]) is None


TOOLSHED_LISTING = (
    "  * **[MolCompose]"
    "(https://cxtoolshed.rbvi.ucsf.edu/apps/chimeraxmolcompose)** (0.1.1): "
    "_Interface analysis and publication-ready figures_"
)


def test_the_bundle_version_is_read_from_chimerax_not_hardcoded():
    """It was the literal "0.1.0" while the bundle shipped 0.1.1, so every
    provenance record named a version that had not produced it."""
    assert parse_bundle_version(TOOLSHED_LISTING) == "0.1.1"


def test_a_listing_without_molcompose_gives_no_version_rather_than_a_guess():
    """An absent version is a gap a reader can see; a stale one reads as fact."""
    assert parse_bundle_version("  * **[Some Other Bundle]()** (9.9.9): _x_") == ""
    assert parse_bundle_version("") == ""


def test_export_refuses_to_write_provenance_for_a_figure_that_does_not_exist(
    tmp_path, monkeypatch
):
    """A failed export used to leave a record attesting to the commands that
    made a figure nobody had -- the one failure this server exists to prevent."""
    from molcompose_mcp import server as server_module

    class RefusingChimeraX:
        def run(self, command):
            return {"log messages": {"note": ["file exists; use overwrite true"]}}

    monkeypatch.setattr(server_module, "ChimeraXClient", lambda url: RefusingChimeraX())
    app = server_module.create_server("http://127.0.0.1:9")
    export = app._tool_manager._tools["export_figure"].fn
    target = tmp_path / "never-written.png"

    with pytest.raises(RuntimeError, match="did not write"):
        export(path=str(target), ctx=None)
    assert not target.with_suffix(".provenance.json").exists()
