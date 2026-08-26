from pathlib import Path

import pytest

from src.ui.tool import (
    MolComposeTool,
    _agent_run_status,
    _classify_structure,
    _readable_argv,
    affinity_command,
    characterise_command,
    contacts_command,
    ddg_command,
    dockq_command,
    export_command,
    focus_command,
    hbonds_command,
    hotspots_command,
    interactions_command,
    interface_command,
    report_command,
    reset_command,
    style_command,
)


def test_style_command_uses_known_preset_and_model():
    assert style_command("#1", "clean-cartoon") == "molcompose style clean-cartoon model #1"


def test_zero_bfactor_placeholders_are_not_presented_as_prediction_confidence():
    kind, detail = _classify_structure(None, ((object(), 0.0),))

    assert kind == "unknown"
    assert "uniformly zero" in detail
    assert "placeholder" in detail


def test_style_command_rejects_unknown_preset():
    with pytest.raises(ValueError, match="unknown MolCompose preset"):
        style_command("#1", "glossy-rainbow")


def test_style_command_rejects_bad_model_spec():
    with pytest.raises(ValueError, match="model spec"):
        style_command("1", "clean-cartoon")


def test_interface_command_quotes_chain_groups_and_model():
    assert interface_command("#1", ["A", "B"], ["D"], 4.5) == (
        "molcompose interface A,B D model #1 distance 4.5"
    )


def test_interface_command_rejects_invalid_chain_ids():
    with pytest.raises(ValueError, match="chain ID"):
        interface_command("#1", ["A,B"], ["D"], 4.5)
    with pytest.raises(ValueError, match="chain ID"):
        interface_command("#1", ["A "], ["D"], 4.5)


def test_interface_command_appends_non_default_criterion():
    assert interface_command("#1", ["A"], ["D"], 8.0, "cbeta") == (
        "molcompose interface A D model #1 distance 8 criterion cbeta"
    )


def test_interface_command_omits_default_criterion():
    assert "criterion" not in interface_command("#1", ["A"], ["D"], 4.5, "heavy")


def test_interface_command_rejects_unknown_criterion():
    with pytest.raises(ValueError, match="criterion must be"):
        interface_command("#1", ["A"], ["D"], 4.5, "magic")


def test_interface_command_renders_distance_deterministically():
    command = interface_command("#2", ["A"], ["B"], 6.0)
    assert command.endswith("model #2 distance 6")


def test_focus_command_targets():
    assert focus_command("#1", "interface") == "molcompose focus interface model #1"
    assert focus_command("#1", "model") == "molcompose focus model model #1"


def test_focus_command_rejects_unknown_target():
    with pytest.raises(ValueError, match="focus target must be one of"):
        focus_command("#1", "galaxy")


def test_export_command_contains_every_visible_option(tmp_path):
    assert export_command(
        tmp_path / "figure.png", 2400, 1800, 3, True, True, False, 600, True
    ) == (
        f'molcompose export "{tmp_path / "figure.png"}" width 2400 height 1800 '
        "supersample 3 transparent true saveSession true overwrite false "
        "dpi 600 saveRecipe true"
    )
    # Defaults are stated rather than left off: an export whose print
    # resolution depends on which layer filled it in is a figure whose size
    # in print nobody decided.
    assert export_command(tmp_path / "f.png", 100, 100, 1, False, False, False).endswith(
        "dpi 300 saveRecipe false"
    )


def test_contacts_command_toggles():
    assert contacts_command("#1") == "molcompose contacts model #1"
    assert contacts_command("#1", off=True) == "molcompose contacts model #1 off true"


def test_hbonds_command_toggles():
    assert hbonds_command("#1") == "molcompose hbonds model #1"
    assert hbonds_command("#1", off=True) == "molcompose hbonds model #1 off true"


def test_hotspots_command_variants():
    assert hotspots_command("#1") == "molcompose hotspots model #1"
    assert hotspots_command("#1", 25.0, 5) == (
        "molcompose hotspots model #1 minArea 25 top 5"
    )


def test_dockq_command_validates_both_specs():
    assert dockq_command("#1", "#2") == "molcompose dockq #2 model #1"
    assert dockq_command("#1", "#2", "A:C,B:D") == (
        "molcompose dockq #2 model #1 chainMap A:C,B:D"
    )
    with pytest.raises(ValueError, match="model spec"):
        dockq_command("#1", "2")


def test_ddg_command_quotes_path_and_takes_statistic(tmp_path):
    target = tmp_path / "d.csv"
    assert ddg_command("#1", target) == f'molcompose ddg "{target}" model #1'
    assert ddg_command("#1", target, "mean").endswith("statistic mean")


def test_report_command_quotes_path_and_takes_format(tmp_path):
    target = tmp_path / "r.md"
    assert report_command(target) == f'molcompose report "{target}"'
    assert report_command(target, "json") == f'molcompose report "{target}" format json'


def test_affinity_command_variants():
    assert affinity_command("#1") == "molcompose affinity model #1"
    assert affinity_command("#1", 37.0) == "molcompose affinity model #1 temperature 37"


def test_characterise_command_variants():
    assert characterise_command("#1", ["A"], ["D"], 4.5) == (
        "molcompose characterise A D model #1 distance 4.5"
    )
    # style false is how the panel asks for the numbers without the restyle:
    # characterise clobbering an already-styled scene was an author complaint.
    assert characterise_command("#1", ["A"], ["D"], 4.5, style=False).endswith(
        " style false"
    )
    assert characterise_command("#1", ["A", "B"], ["D"], 8.0, "cbeta").endswith(
        "distance 8 criterion cbeta"
    )
    with pytest.raises(ValueError, match="criterion"):
        characterise_command("#1", ["A"], ["D"], 4.5, "magic")


def test_interactions_command_variants():
    assert interactions_command("#1") == "molcompose interactions model #1"
    assert interactions_command("#1", types="salt-bridge,hydrophobic") == (
        "molcompose interactions model #1 types salt-bridge,hydrophobic"
    )
    assert interactions_command("#1", off=True) == (
        "molcompose interactions model #1 off true"
    )


def test_reset_command_is_model_scoped():
    assert reset_command("#1") == "molcompose reset model #1"


def test_the_panel_and_the_command_layer_agree_on_focus_targets():
    """Two lists of the same four things, in two files.

    The panel's copy of the criterion list had already drifted from the
    command layer's once, and the pLDDT button raised on every click for it.
    """
    from src.commands import FOCUS_TARGETS
    from src.ui.tool import _TARGETS

    assert set(_TARGETS) == set(FOCUS_TARGETS)


def test_the_panel_and_the_command_layer_agree_on_criteria():
    from src.adapters.model_context import CRITERIA
    from src.ui.tool import _CRITERIA

    assert set(_CRITERIA) == set(CRITERIA)


def test_a_preset_that_draws_its_own_surface_is_recognised():
    """The Interface figure card must not clear a surface the preset just built.

    Its halo logic was written when no preset built one — "the preset builds no
    surface" was literally true — so the else branch hid every surface in the
    model to clear a halo left by a previous click. Once the surface styles
    existed, choosing one from that card built its surface and had it torn down
    one command later, which is why they appeared to show no surface at all.
    """
    from src.core.presets import PRESETS, get_preset

    for slug in ("epitope-surface", "surface-partner-a", "surface-translucent",
                 "surface-epitope-map", "surface-complex"):
        assert get_preset(slug).geometry.draws_surface is True
    # And the cartoon styles are not caught by it, or the halo would never work.
    for slug in ("interface-focus", "clean-cartoon", "paratope-closeup"):
        assert get_preset(slug).geometry.draws_surface is False
    # Stated as a rule so a preset added later cannot drift: exactly the styles
    # naming a surface side, or the whole structure, draw one.
    assert {slug for slug, p in PRESETS.items() if p.geometry.draws_surface} == {
        "epitope-surface", "surface-partner-a", "surface-translucent",
        "surface-epitope-map", "surface-complex",
    }


def test_seqcolor_command_carries_source_and_path(tmp_path):
    from src.ui.tool import seqcolor_command

    target = tmp_path / "figure_interface.scf"
    assert seqcolor_command("#1", "plddt", target) == (
        f'molcompose seqcolor "{target}" model #1 source plddt'
    )
    # No path: the command picks one beside the structure.
    assert seqcolor_command("#1", "interface") == (
        "molcompose seqcolor model #1 source interface"
    )
    assert seqcolor_command("#1", "ddg", None, load=False).endswith(" load false")


def test_style_command_can_override_the_label_count():
    """The count was a property of the preset and nothing else.

    Two panels of one plate then disagreed about how many residues are named —
    panel-c.cxc draws its ΔΔG view with paratope-closeup (two labels) beside an
    interactions view with licorice-chain (three) — a difference nobody chose.
    """
    from src.ui.tool import style_command

    assert style_command("#1", "interface-focus") == (
        "molcompose style interface-focus model #1"
    )
    assert style_command("#1", "paratope-closeup", 3) == (
        "molcompose style paratope-closeup model #1 labels 3"
    )
    # 0 is a real value — labels off — and must not be read as "no override".
    assert style_command("#1", "licorice-chain", 0).endswith(" labels 0")
    with pytest.raises(ValueError, match="0 or more"):
        style_command("#1", "licorice-chain", -1)


class _ChatStub:
    """Enough of the panel to exercise the chat footer, without Qt.

    The method is called unbound: building a MolComposeTool needs a live
    ChimeraX session and a widget tree, and what is worth pinning here is
    which recipe lines the footer selects, not how they are painted.
    """

    def __init__(self, entries, mark):
        self._entries = tuple(entries)
        self._recipe_before_turn = mark
        self.written = []

    def _recipe_log(self):
        return self._entries

    def _append_chat(self, text):
        self.written.append(text)


def _entry(command, source):
    return {"command": command, "timestamp": "", "source": source}


def test_chat_footer_reports_only_what_the_agent_ran_this_turn():
    """The user's own earlier commands are not the agent's work.

    The recipe is one list for the whole session, so without the mark the
    footer would credit the agent with everything typed before it started.
    """
    stub = _ChatStub(
        [
            _entry("molcompose style clean-cartoon model #1", "panel"),
            _entry("molcompose interface A D model #1", "agent"),
            _entry("molcompose buriedarea model #1", "agent"),
        ],
        mark=1,
    )
    MolComposeTool._report_agent_commands(stub)
    body = "\n".join(stub.written)
    assert "✓ 2 MolCompose operation(s) verified" in body
    assert "molcompose interface A D model #1" in body
    assert "molcompose buriedarea model #1" in body
    assert "clean-cartoon" not in body


def test_chat_footer_warns_when_the_agent_ran_no_live_analysis():
    """A prose-only answer must not look verified against the open window."""
    stub = _ChatStub([_entry("molcompose interface A D model #1", "session")], mark=0)
    commands = MolComposeTool._report_agent_commands(stub)
    assert commands == ()
    assert "No live MolCompose analysis was recorded" in "\n".join(stub.written)


def test_successful_process_without_live_analysis_is_not_marked_complete():
    assert _agent_run_status(0, 0) == "Answer returned · live analysis not verified"
    assert _agent_run_status(0, 2) == "Analysis complete  ✓"
    assert _agent_run_status(1, 0) == "Agent failed · exit code 1"


class _ProcessOutput:
    def __init__(self, output):
        self.output = output

    def readAllStandardOutput(self):  # noqa: N802 - Qt API spelling
        return self.output


class _WidgetState:
    def __init__(self):
        self.text = None
        self.enabled = None

    def setText(self, text):  # noqa: N802 - Qt API spelling
        self.text = text

    def setEnabled(self, enabled):  # noqa: N802 - Qt API spelling
        self.enabled = enabled


class _CleanupState:
    def __init__(self):
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True


class _FinishedTurnStub:
    def __init__(self, answer_path, raw_output, commands):
        self._agent_answer_path = answer_path
        self._agent_raw_output = raw_output
        self._commands = commands
        self._agent_output_directory = _CleanupState()
        self.cleanup_state = self._agent_output_directory
        self._active_agent = object()
        self._agent_process = object()
        self._chat_run_status = _WidgetState()
        self._chat_send = _WidgetState()
        self._chat_stop = _WidgetState()
        self.chat = []
        self.details_visibility = []
        # Recorded so the test can see the lock lift. The agent choice is
        # disabled for the length of a turn, and a turn that ends without
        # restoring it would leave the panel unable to change agent at all.
        self.choice_enabled = []

    def _set_agent_choice_enabled(self, enabled):
        self.choice_enabled.append(enabled)

    def _append_chat(self, text):
        self.chat.append(text)

    def _report_agent_commands(self):
        return self._commands

    def _set_chat_details_visible(self, visible):
        self.details_visibility.append(visible)

def test_codex_raw_output_goes_to_details_not_the_answer():
    from src.core.agent_cli import get_agent

    stub = _FinishedTurnStub(None, "", ())
    stub._agent_process = _ProcessOutput(b"startup diagnostic\n")
    stub._active_agent = get_agent("codex")
    stub.details = []
    stub._append_chat_detail = stub.details.append

    MolComposeTool._on_chat_output(stub)

    assert stub._agent_raw_output == "startup diagnostic\n"
    assert stub.details == ["startup diagnostic\n"]
    assert stub.chat == []


def test_claude_raw_output_remains_visible_as_the_answer():
    from src.core.agent_cli import get_agent

    stub = _FinishedTurnStub(None, "", ())
    stub._agent_process = _ProcessOutput(b"Claude answer\n")
    stub._active_agent = get_agent("claude")
    stub.details = []
    stub._append_chat_detail = stub.details.append

    MolComposeTool._on_chat_output(stub)

    assert stub.details == ["Claude answer\n"]
    assert stub.chat == ["Claude answer\n"]


def test_agent_finish_uses_final_answer_and_cleans_temporary_state(tmp_path):
    answer = tmp_path / "answer.md"
    answer.write_text("Contacting chains: E–I\n")
    stub = _FinishedTurnStub(str(answer), "startup diagnostic", ("command",))

    MolComposeTool._on_chat_finished(stub, 0)

    assert stub.chat == ["Contacting chains: E–I"]
    assert stub._chat_run_status.text == "Analysis complete  ✓"
    assert stub.cleanup_state.cleaned is True
    assert stub._agent_output_directory is None
    assert stub._agent_answer_path is None
    assert stub._active_agent is None
    assert stub._agent_process is None
    assert stub._chat_send.enabled is True
    assert stub._chat_stop.enabled is False
    assert stub.details_visibility == []


def test_agent_failure_expands_run_details_and_resets_buttons():
    stub = _FinishedTurnStub(None, "failure diagnostic", ())

    MolComposeTool._on_chat_finished(stub, 1)

    assert stub._chat_run_status.text == "Agent failed · exit code 1"
    assert stub.details_visibility == [True]
    assert stub._chat_send.enabled is True
    assert stub._chat_stop.enabled is False


def test_readable_argv_keeps_the_flags_and_drops_the_paths():
    """`--allowedTools mcp__molcompose` is the confinement claim; the temp
    directory's random suffix is noise that lands in every screenshot."""
    line = _readable_argv([
        "/opt/homebrew/bin/claude",
        "--print",
        "--allowedTools",
        "mcp__molcompose",
        "--mcp-config",
        "/var/folders/7d/kzgvwmhx/T/molcompose-agent-ur8b3n97/mcp.json",
    ])
    assert line == "claude --print --allowedTools mcp__molcompose --mcp-config mcp.json"


def test_readable_argv_leaves_a_relative_executable_alone():
    """A CLI invoked by name was never a path, and shortening it would be a lie."""
    assert _readable_argv(["codex", "exec", "characterise it"]) == (
        "codex exec characterise it"
    )


# Rules that style a widget which never draws text of its own: containers,
# frames, and the parts of a control that are only a box.
NO_TEXT_OF_ITS_OWN = {
    "QScrollArea", "QTabWidget::pane", "QTabBar", "QWidget#content",
    "QWidget#card", "QWidget#tile", "QWidget#tileActive", "QWidget#tileMuted",
    "QHeaderView", "QComboBox::drop-down", "QPushButton#swatch",
    "QTableCornerButton::section",
    # Its colour is set per chip, from the interaction type's own hue.
    "QLabel#chipClickable",
}


def test_every_rule_that_draws_text_sets_its_own_colour():
    """The panel paints its own backgrounds, so it must paint its own text.

    `QCheckBox` set spacing and nothing else, so its label took the system
    palette's colour while the card behind it stayed white. On macOS in dark
    mode that is white on white: four checkbox labels were invisible after
    dark and readable again in the morning. A rule that leaves the colour to
    the platform is the same omission that once painted the QLineEdits as
    black bars.
    """
    import re

    from src.ui.tool import _PANEL_QSS

    stylesheet = re.sub(r"/\*.*?\*/", "", _PANEL_QSS, flags=re.S)
    missing = []
    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", stylesheet):
        selector = " ".join(selector.split())
        if not selector or selector in NO_TEXT_OF_ITS_OWN:
            continue
        # A state rule modifies the base rule, which already set the colour;
        # only the base selector has to declare one.
        if any(state in selector for state in (":hover", ":pressed", ":focus")):
            continue
        if not re.search(r"(^|;)\s*color\s*:", body):
            missing.append(selector)
    assert not missing, (
        "these paint a background but leave the text colour to the platform, "
        "which is white on white in dark mode: " + "; ".join(missing)
    )


def test_energy_command_carries_the_chain_map():
    """It is not optional and not defaulted: the wrong map attaches one
    partner's energies to the other with no error anywhere."""
    from src.ui.tool import energy_command

    assert energy_command("#1", "/tmp/FINAL_DECOMP_MMPBSA.dat", "A:A,B:D") == (
        'molcompose energy "/tmp/FINAL_DECOMP_MMPBSA.dat" chains A:A,B:D model #1'
    )


def test_the_panel_offers_every_metric_the_command_layer_has():
    """The Files card grew a row; this is the drift test for it."""
    from src.ui.tool import COLOR_METRICS, METRIC_LABELS

    assert "mmpbsa" in COLOR_METRICS
    assert set(METRIC_LABELS) == set(COLOR_METRICS)
    # Named for the quantity, not the method: it sits beside ΔΔG in the panel
    # and the two are opposite in sign.
    assert "kcal/mol" in METRIC_LABELS["mmpbsa"]


# The names ChimeraX registers, which are not always the ones on the window
# titles: "Render by Attribute" is titled that and registered as
# "Render/Select by Attribute", so the button raised "No running or installed
# tool named ..." and did nothing. Verified against ChimeraX 1.12's own
# registry on 2026-08-20.
NATIVE_TOOL_NAMES = ("Distances", "Model Panel", "Render/Select by Attribute")


def test_the_panel_asks_for_native_tools_by_their_registered_names():
    """A wrong name here is silent: the button clicks and nothing opens."""
    import re

    source = (Path(__file__).parents[3] / "src/ui/tool.py").read_text()
    asked = set(re.findall(r'_on_show_tool\(\s*"([^"]+)"', source))
    unknown = sorted(asked - set(NATIVE_TOOL_NAMES))
    assert not unknown, (
        "the panel asks ChimeraX for tools by these names, and they are not "
        "the ones it registers: " + ", ".join(unknown)
    )


def test_flexibility_command_carries_the_ordered_chains():
    """One per block, in order: gmx restarts its numbering at each chain, so
    the wrong order puts the second chain's motion on the first."""
    from src.ui.tool import flexibility_command

    assert flexibility_command("#1", "/tmp/Complex_CA.xvg", "A,D") == (
        'molcompose flexibility "/tmp/Complex_CA.xvg" chains A,D model #1'
    )


def test_the_help_button_opens_the_page_that_shipped():
    """`help:` is ChimeraX's scheme for bundle documentation, so it finds the
    page beside the running code rather than a URL that can go stale."""
    from src.ui.tool import HELP_PAGE

    assert HELP_PAGE.startswith("help:")
    assert HELP_PAGE.endswith("user/tools/molcompose.html")
    page = Path(__file__).parents[3] / "src/docs/user/tools/molcompose.html"
    assert page.is_file(), "the help button would open a page that is not shipped"


class TestKeyFontControl:
    """The key's font is in pixels of the exported image, so what it comes out
    as in print depends on how wide the figure is placed."""

    def test_the_shipped_value_sends_nothing(self):
        """An untouched panel has to export exactly as it did before."""
        from src.ui.tool import DEFAULT_KEY_FONT, export_command

        command = export_command("/tmp/f.png", 2400, 1800, 3, False, False,
                                 True, 300, False, None)
        assert "keyFontSize" not in command
        assert DEFAULT_KEY_FONT == 42

    def test_a_changed_value_is_sent(self):
        from src.ui.tool import export_command

        command = export_command("/tmp/f.png", 2400, 1800, 3, False, False,
                                 True, 300, False, 96)
        assert command.endswith("keyFontSize 96")


# -- the agent bridge --------------------------------------------------------


class _Address:
    """Stand-in for ChimeraX's RESTServer, which exposes `server_address`."""

    def __init__(self, port):
        self.server_address = ("127.0.0.1", port) if port else None


def _bridge_port(server):
    """`MolComposePanel._bridge_port` without a Qt panel to build.

    The method reads one attribute off ChimeraX's REST server object, and that
    read is the whole fix, so it is exercised directly rather than through a
    widget tree the host-light suite cannot construct.
    """
    address = getattr(server, "server_address", None) if server else None
    return address[1] if address else None


def test_the_bridge_is_found_on_whatever_port_it_is_on():
    """Probing 3000 reported a running bridge as down, with no way out.

    A session that already had `remotecontrol rest start port 3010` left the
    panel probing a port nothing was listening on. It then offered to start the
    bridge; ChimeraX answers `rest start` with success and no second listener
    when a server is already running, so the next probe found 3000 empty again
    and the panel asked again. Reproduced on 2026-08-25: REST up on 3020, the
    panel insisting it was down, the button doing nothing each time.
    """
    assert _bridge_port(_Address(3010)) == 3010
    assert _bridge_port(_Address(3000)) == 3000
    assert _bridge_port(_Address(None)) is None
    assert _bridge_port(None) is None


# -- long names in the header ------------------------------------------------


def test_a_colabfold_name_keeps_the_parts_that_identify_the_model():
    """The header stretched the panel to fit a 68-character file name.

    ColabFold's naming carries the rank at the front and the model and seed at
    the back, and those are what tell one of five predictions from another —
    the engine and version in the middle are identical across all five. So the
    middle is what goes.
    """
    from src.ui.tool import _short_name

    name = "1brs_unrelaxed_rank_001_alphafold2_multimer_v3_model_1_seed_2066.pdb"
    short = _short_name(name)
    assert len(short) <= 48
    assert "rank_001" in short
    assert "model_1_seed_2066" in short
    assert "…" in short


def test_a_name_that_fits_is_left_alone():
    from src.ui.tool import _short_name

    assert _short_name("DerF7_b2.pdb") == "DerF7_b2.pdb"


# -- the file dialogs -------------------------------------------------------


def test_the_choosers_offer_every_format_the_loaders_read():
    """A filter narrower than the loader hides files that would have worked.

    `.pkl` support was added to discovery and to both loaders, and the two
    dialogs kept a `*.json *.npz` filter — so a native AlphaFold2-Multimer
    run, whose PAE and ipTM exist only inside `result_<model>.pkl`, showed an
    empty directory to anyone trying to point at it by hand. The reader had
    the format and the way in did not.
    """
    from pathlib import Path

    source = (Path(__file__).parents[3] / "src/ui/tool.py").read_text()
    # Only the two confidence choosers. The RMSF, MM/PBSA, ΔΔG and structure
    # dialogs have their own formats and would fail a blanket check for
    # reasons that are correct.
    filters = [
        line
        for line in source.splitlines()
        if ";;All files (*)" in line
        and ("PAE matrices" in line or "Confidence summaries" in line)
    ]
    assert len(filters) == 2, "expected a PAE chooser and a summary chooser"
    for line in filters:
        for suffix in ("*.json", "*.npz", "*.pkl", "*.pickle"):
            assert suffix in line, f"{suffix} missing from {line.strip()}"


def test_characterise_carries_a_file_the_user_chose_by_hand():
    """Pressing Characterise again after choosing a file has to use it.

    The panel found the file, showed it in the table, and characterised
    without it — so a user who pointed at a PAE matrix and a summary, then
    pressed the button to see the numbers change, saw them not change. The
    files were reaching the capabilities card and nothing else.
    """
    from src.ui.tool import characterise_command

    plain = characterise_command("#1", ["A"], ["B"], 4.5, style=False)
    assert "paeFile" not in plain
    assert "summaryFile" not in plain

    carried = characterise_command(
        "#1", ["A"], ["B"], 4.5, style=False,
        pae_file="/runs/result_model_1.pkl",
        summary_file="/runs/result_model_1.pkl",
    )
    assert "paeFile" in carried
    assert "summaryFile" in carried
    assert "result_model_1.pkl" in carried


def test_energy_command_states_the_solvation_model_when_asked_to():
    """Loading a two-model decomposition failed with no way to resolve it.

    gmx_MMPBSA run for both GB and PB writes the decomposition twice, and the
    loader refuses to pick — correctly, since the two disagree by several
    kcal/mol. But the panel offered a chain-map prompt and nothing else, so
    the refusal was the end of the road: the message said "say which one to
    read" and the panel had no control that said it.
    """
    from src.ui.tool import energy_command

    plain = energy_command("#1", "/runs/decomp.dat", "A:A,B:D")
    assert "solvation" not in plain

    chosen = energy_command("#1", "/runs/decomp.dat", "A:A,B:D", "gb")
    assert chosen.endswith("solvation gb")


def test_a_finished_turn_gives_the_agent_choice_back():
    """A lock that does not lift is worse than no lock.

    The dropdown is disabled for the length of a turn, because it was live
    throughout and the panel could show one agent while another was still
    executing. If a finished turn did not restore it, the panel would be
    stuck on whichever agent ran first.
    """
    from src.ui.tool import MolComposeTool

    stub = _FinishedTurnStub(None, "", ())
    MolComposeTool._on_chat_finished(stub, 0, None)
    assert stub.choice_enabled == [True]


def test_the_setup_prompt_names_the_port_the_bridge_is_on():
    """The README's version hard-codes 3000.

    That is the assumption that had this panel telling people to start a
    bridge already running on another port; a prompt carrying it would hand
    an agent an address with nothing behind it.
    """
    from src.ui.tool import MolComposeTool

    class Stub:
        _bridge_port = staticmethod(lambda: 3010)

    text = MolComposeTool._setup_prompt_text(Stub())
    assert "http://127.0.0.1:3010" in text
    assert "port 3010 json true" in text
    assert "3000" not in text


def test_the_footer_recognises_an_agent_that_named_itself():
    """The panel showed nothing after a turn that had in fact run commands.

    Both CLIs, immediately after the bridge started naming the client it was
    launched by. The footer's filter asked `source == "agent"` and
    "agent:codex" is not that, so a turn full of real analysis reported "No
    live MolCompose analysis was recorded" — the panel telling the user not to
    trust an answer that was, in this respect, exactly what it claimed to be.
    """
    stub = _ChatStub(
        [
            _entry("molcompose style clean-cartoon model #1", "panel"),
            _entry("molcompose interface A L model #1", "agent:claude"),
            _entry("molcompose buriedarea model #1", "agent:codex"),
            _entry("molcompose interface A D model #1", "agent"),
        ],
        mark=1,
    )
    MolComposeTool._report_agent_commands(stub)
    body = "\n".join(stub.written)
    assert "✓ 3 MolCompose operation(s) verified" in body
    assert "No live MolCompose analysis" not in body
    assert "clean-cartoon" not in body


def test_the_setup_prompt_does_not_ask_the_agent_to_do_what_it_cannot():
    """`toolshed install` and `remotecontrol rest start` are not the agent's.

    The first version of this prompt read as one paragraph and told the agent
    to run both. Neither is in the bridge's whitelist, and the second is the
    command that *creates* the bridge, so it could not work from the other
    side of one however the whitelist read. An agent given that tries, fails,
    and improvises — which is worse than being told plainly whose step it is.

    The prompt now numbers its steps and marks each one. This checks the two
    commands the human has to run are attributed to the human, and that the
    agent is warned it may not have its tools until it restarts.
    """
    from src.ui.tool import MolComposeTool

    class _Stub:
        def _bridge_port(self):
            return 3010

    text = MolComposeTool._setup_prompt_text(_Stub())

    for command in ("toolshed install", "remotecontrol rest start"):
        assert command in text, command
        # The step carrying it has to be one of the human's.
        step = next(s for s in text.split("\n\n") if command in s)
        # The human's steps say "I run"; the agent's are imperative. The voice
        # is the only marker, so it has to be there.
        assert "I run" in step, f"{command}: {step[:60]}"

    assert "Step 3." in text and "molcompose-mcp" in text
    assert "restart" in text.lower()
    # The client launches the server in its own environment, not the shell that
    # installed it, so a bare `pip install` into an unactivated venv leaves the
    # command unfindable. The prompt has to say where to put it.
    assert "pipx" in text or "absolute path" in text
    # The real port, not the default.
    assert "3010" in text and "127.0.0.1:3010" in text
