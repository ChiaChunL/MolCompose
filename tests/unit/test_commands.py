import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from chimerax.core.commands import REGISTERED
from chimerax.core.errors import UserError

import src.commands as commands
from src.commands import (
    cmd_affinity,
    cmd_buriedarea,
    cmd_capabilities,
    cmd_characterise,
    cmd_confidence,
    cmd_contacts,
    cmd_ddg,
    cmd_export,
    cmd_focus,
    cmd_hbonds,
    cmd_hotspots,
    cmd_interactions,
    cmd_interface,
    cmd_interface_all,
    cmd_ipsae,
    cmd_report,
    cmd_reset,
    cmd_style,
    parse_chain_group,
    register_command,
    resolve_model,
    state_for,
)
from src.core.interfaces import ContactPair, InterfaceResult
from src.core.interfaces import ResidueKey as Key


class FakeLogger:
    def __init__(self):
        self.infos = []
        self.warnings = []

    def info(self, message):
        self.infos.append(message)

    def warning(self, message):
        self.warnings.append(message)


@dataclass
class FakeAtom:
    element: object
    coord: tuple[float, float, float]


@dataclass
class FakeResidue:
    polymer_type: int
    chain_id: str
    number: int
    insertion_code: str
    name: str
    atomspec: str
    atoms: tuple[FakeAtom, ...]


@dataclass
class FakeChain:
    chain_id: str
    residues: tuple[FakeResidue, ...]

    @property
    def atomspec(self):
        return f"#1/{self.chain_id}"


def _amino(chain_id, number):
    carbon = SimpleNamespace(number=6)
    return FakeResidue(
        1, chain_id, number, "", "ALA", f"#1/{chain_id}:{number}",
        (FakeAtom(carbon, (0.0, 0.0, 0.0)),),
    )


@pytest.fixture
def model():
    return SimpleNamespace(
        id=(1,), id_string="1", name="fake", atomspec="#1",
        chains=(
            FakeChain("A", (_amino("A", 1),)),
            FakeChain("B", (_amino("B", 1),)),
            FakeChain("D", (_amino("D", 1),)),
        ),
    )


@pytest.fixture
def session():
    return SimpleNamespace(logger=FakeLogger())


@pytest.fixture
def canned_result():
    a_keys = tuple(Key("#1", "A", n, "", "ALA", f"#1/A:{n}") for n in (1, 2, 3))
    b_keys = tuple(Key("#1", "D", n, "", "GLY", f"#1/D:{n}") for n in (1, 2, 3, 4))
    contacts = tuple(ContactPair(a_keys[0], b_key) for b_key in b_keys)
    return InterfaceResult(a_keys, b_keys, contacts, 4.5)


def test_parse_chain_group_strips_and_deduplicates():
    assert parse_chain_group(" A , B ,A") == ("A", "B")


def test_parse_chain_group_rejects_empty_ids():
    with pytest.raises(UserError, match="empty chain"):
        parse_chain_group("A,,B")


def test_parse_chain_group_rejects_empty_input():
    with pytest.raises(UserError, match="at least one chain"):
        parse_chain_group("  ")


def test_resolve_model_prefers_explicit_model(session, model):
    assert resolve_model(session, model) is model


def test_resolve_model_requires_an_open_model(session, monkeypatch):
    monkeypatch.setattr(commands, "list_protein_models", lambda session: ())
    with pytest.raises(UserError, match="No protein model"):
        resolve_model(session, None)


def test_resolve_model_rejects_ambiguity(session, monkeypatch):
    refs = (
        SimpleNamespace(model_id="#1", handle=object()),
        SimpleNamespace(model_id="#2", handle=object()),
    )
    monkeypatch.setattr(commands, "list_protein_models", lambda session: refs)
    with pytest.raises(UserError, match=r"#1, #2"):
        resolve_model(session, None)


def test_resolve_model_returns_single_model_handle(session, monkeypatch):
    handle = object()
    refs = (SimpleNamespace(model_id="#1", handle=handle),)
    monkeypatch.setattr(commands, "list_protein_models", lambda session: refs)
    assert resolve_model(session, None) is handle


def test_interface_command_saves_result_by_model_and_logs_counts(
    session, model, monkeypatch, canned_result
):
    monkeypatch.setattr(
        commands, "atom_points", lambda m, chains, criterion="heavy": tuple(sorted(chains))
    )
    monkeypatch.setattr(
        commands, "detect_interface", lambda a, b, cutoff, criterion="heavy": canned_result
    )
    result = cmd_interface(session, "A", "D", model=model, distance=4.5)
    assert result is canned_result
    assert state_for(session).interfaces["#1"] is canned_result
    assert "Group A: 3 residues" in session.logger.infos[-1]
    assert "Group B: 4 residues" in session.logger.infos[-1]
    assert "4 contact pairs" in session.logger.infos[-1]
    assert "4.5" in session.logger.infos[-1]
    assert "criterion heavy" in session.logger.infos[-1]


def test_interface_rejects_unknown_criterion(session, model):
    with pytest.raises(UserError, match="criterion must be"):
        cmd_interface(session, "A", "D", model=model, criterion="magic")


def test_interface_all_rejects_unknown_criterion(session, model):
    with pytest.raises(UserError, match="criterion must be"):
        cmd_interface_all(session, model=model, criterion="magic")


def test_interface_rejects_overlapping_chain_groups_before_analysis(session, model, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("analysis must not run for overlapping groups")

    monkeypatch.setattr(commands, "atom_points", explode)
    with pytest.raises(UserError, match="must not overlap"):
        cmd_interface(session, "A,B", "B,D", model=model)


def test_interface_converts_value_errors(session, model, monkeypatch):
    def raise_value_error(m, chains, criterion="heavy"):
        raise ValueError("unknown protein chain(s) for #1: Z")

    monkeypatch.setattr(commands, "atom_points", raise_value_error)
    with pytest.raises(UserError, match="unknown protein chain"):
        cmd_interface(session, "Z", "D", model=model)


def test_interface_all_reports_only_contacting_pairs(session, model, monkeypatch, canned_result):
    empty = InterfaceResult((), (), (), 4.5)

    monkeypatch.setattr(
        commands, "atom_points", lambda m, chains, criterion="heavy": tuple(chains)
    )

    def fake_detect(a, b, cutoff, criterion="heavy"):
        return canned_result if (a, b) == (("A",), ("D",)) else empty

    monkeypatch.setattr(commands, "detect_interface", fake_detect)
    records = cmd_interface_all(session, model=model)
    assert [(a, b) for a, b, _ in records] == [("A", "D")]
    assert any("A-D" in message for message in session.logger.infos)


def test_style_renders_selected_preset(session, model, monkeypatch):
    rendered = {}

    def fake_render(render_session, ref, preset, interface=None, **_kwargs):
        rendered.update(ref=ref, preset=preset, interface=interface)
        return ("cmd",)

    monkeypatch.setattr(commands, "render_preset", fake_render)
    cmd_style(session, "clean-cartoon", model=model)
    assert rendered["preset"].slug == "clean-cartoon"
    assert rendered["ref"].model_id == "#1"
    assert rendered["interface"] is None


def test_design_reference_style_resolves_open_references_and_records_one_command(
    session, model, monkeypatch
):
    """Catch a comparison style that only works through a case-specific script."""
    reference_one = SimpleNamespace(
        id=(2,), id_string="2", name="crystal-one", atomspec="#2", chains=model.chains
    )
    reference_two = SimpleNamespace(
        id=(3,), id_string="3", name="crystal-two", atomspec="#3", chains=model.chains
    )
    a = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    b = Key("#1", "B", 1, "", "ALA", "#1/B:1")
    state_for(session).interfaces["#1"] = InterfaceResult(
        (a,), (b,), (ContactPair(a, b),), 4.5
    )
    monkeypatch.setattr(
        commands,
        "list_protein_models",
        lambda _session: tuple(
            commands.model_ref(item) for item in (model, reference_one, reference_two)
        ),
    )
    executed = []
    monkeypatch.setattr(commands, "_run", lambda _session, command: executed.append(command))

    cmd_style(
        session,
        "design-reference",
        model=model,
        references="#2,#3",
        align="A",
        partner="B",
    )

    assert "matchmaker #2/A to #1/A" in executed
    assert "matchmaker #3/A to #1/A" in executed
    assert state_for(session).recipe[-1].command == (
        "molcompose style design-reference model #1 references #2,#3 align A partner B"
    )


def test_predicted_structure_builds_confidence_and_logs_scale(session, model, monkeypatch):
    key = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    monkeypatch.setattr(commands, "plddt_values", lambda m: ((key, 0.95), (key, 0.30)))
    captured = {}

    def fake_render(render_session, ref, preset, interface=None, confidence=None, **_kwargs):
        captured["confidence"] = confidence
        return ()

    monkeypatch.setattr(commands, "render_preset", fake_render)
    cmd_style(session, "predicted-structure", model=model)
    assert captured["confidence"].scale == "0-1"
    assert any("pLDDT scale detected: 0-1" in message for message in session.logger.infos)


def test_predicted_structure_without_bfactors_is_a_user_error(session, model, monkeypatch):
    monkeypatch.setattr(commands, "plddt_values", lambda m: ())
    with pytest.raises(UserError, match="no B-factor/pLDDT values"):
        cmd_style(session, "predicted-structure", model=model)


def test_interface_focus_requires_saved_result(session, model):
    with pytest.raises(UserError, match="Detect an interface first"):
        cmd_style(session, "interface-focus", model=model)


def test_interface_focus_uses_saved_result(session, model, monkeypatch, canned_result):
    state_for(session).interfaces["#1"] = canned_result
    rendered = {}

    def fake_render(render_session, ref, preset, interface=None, **_kwargs):
        rendered["interface"] = interface
        return ()

    monkeypatch.setattr(commands, "render_preset", fake_render)
    cmd_style(session, "interface-focus", model=model)
    assert rendered["interface"] is canned_result


def test_unknown_preset_is_a_user_error(session, model):
    with pytest.raises(UserError, match="unknown MolCompose preset"):
        cmd_style(session, "glossy-rainbow", model=model)


def test_focus_interface_requires_saved_result(session, model):
    with pytest.raises(UserError, match="Detect an interface first"):
        cmd_focus(session, "interface", model=model)


def test_focus_runs_view_commands(session, model, monkeypatch, canned_result):
    state_for(session).interfaces["#1"] = canned_result
    executed = []
    monkeypatch.setattr(commands, "_run", lambda s, c: executed.append(c))
    cmd_focus(session, "interface", model=model)
    assert executed and executed[0].startswith("view ")


def test_focus_model_target(session, model, monkeypatch):
    executed = []
    monkeypatch.setattr(commands, "_run", lambda s, c: executed.append(c))
    cmd_focus(session, "model", model=model)
    # Read from the renderer rather than repeated here: the padding is a
    # framing decision that belongs in one place, and 0.3 left a third of the
    # figure as white margin.
    from src.adapters.renderer import VIEW_PAD

    assert executed == [f"view #1 pad {VIEW_PAD}"]
    assert VIEW_PAD < 0.15


def test_focus_rejects_unknown_target(session, model):
    with pytest.raises(UserError, match="focus target must be one of"):
        cmd_focus(session, "galaxy", model=model)


def test_export_logs_recipe_and_returns_paths(session, tmp_path, monkeypatch):
    def fake_export(export_session, options, **_kwargs):
        return options.path, None, ("save-cmd",), None

    monkeypatch.setattr(commands, "export_figure", fake_export)
    png, cxs, recipe, sidecar = cmd_export(session, str(tmp_path / "figure.png"))
    assert sidecar is None
    # Strings, not Paths: the REST bridge serialises a command's return value,
    # and a Path is not JSON-serialisable, so returning one crashed ChimeraX
    # for every agent that exported a figure.
    assert png == str(tmp_path / "figure.png")
    assert isinstance(png, str)
    assert cxs is None
    assert recipe == ("save-cmd",)
    assert any("save-cmd" in message for message in session.logger.infos)


def test_export_converts_expected_errors(session, tmp_path, monkeypatch):
    def fake_export(export_session, options, **_kwargs):
        raise FileExistsError("output file already exists: x.png")

    monkeypatch.setattr(commands, "export_figure", fake_export)
    with pytest.raises(UserError, match="already exists"):
        cmd_export(session, str(tmp_path / "figure.png"))


def test_export_rejects_invalid_dimensions_as_user_error(session, tmp_path):
    with pytest.raises(UserError, match="width and height"):
        cmd_export(session, str(tmp_path / "figure.png"), width=0)


def test_hbonds_requires_detected_interface(session, model):
    with pytest.raises(UserError, match="Detect an interface first"):
        cmd_hbonds(session, model=model)


def test_hbonds_runs_restricted_native_command(session, model, monkeypatch, canned_result):
    state_for(session).interfaces["#1"] = canned_result
    executed = []
    monkeypatch.setattr(commands, "_run", lambda s, c: executed.append(c))
    cmd_hbonds(session, model=model)
    assert executed and executed[0].startswith("hbonds ")
    assert "restrict" in executed[0]


def test_hbonds_off_clears_without_interface(session, model, monkeypatch):
    executed = []
    monkeypatch.setattr(commands, "_run", lambda s, c: executed.append(c))
    cmd_hbonds(session, model=model, off=True)
    assert executed == ["~hbonds"]


def test_capabilities_report_experimental_structures(session, model, monkeypatch):
    monkeypatch.setattr(commands, "experimental_method", lambda m: "X-RAY DIFFRACTION")
    monkeypatch.setattr(commands, "plddt_values", lambda m: ())
    monkeypatch.setattr(commands, "structure_path", lambda m: None)
    caps = cmd_capabilities(session, model=model)
    assert caps.kind == "experimental"
    assert "pLDDT" in caps.unavailable
    assert any("experimental" in line for line in session.logger.infos)


def test_capabilities_unlock_pae_metrics_when_a_matrix_is_found(
    session, model, monkeypatch, tmp_path
):
    key = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    monkeypatch.setattr(commands, "experimental_method", lambda m: None)
    monkeypatch.setattr(commands, "plddt_values", lambda m: ((key, 90.0),))
    monkeypatch.setattr(commands, "structure_path", lambda m: None)
    # Square, and as wide as the fixture's three amino-acid residues.
    pae = tmp_path / "pae.json"
    pae.write_text(json.dumps({"pae": [[0.0] * 3 for _ in range(3)]}))
    caps = cmd_capabilities(session, model=model, paeFile=str(pae))
    assert caps.is_predicted
    assert "ipSAE" in caps.available and "pDockQ2" in caps.available
    assert any("PAE matrix found" in line for line in session.logger.infos)


def test_capabilities_withhold_pae_metrics_when_the_matrix_counts_ligand_tokens(
    session, model, monkeypatch, tmp_path
):
    key = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    monkeypatch.setattr(commands, "experimental_method", lambda m: None)
    monkeypatch.setattr(commands, "plddt_values", lambda m: ((key, 90.0),))
    monkeypatch.setattr(commands, "structure_path", lambda m: None)
    # The model fixture has three amino-acid residues; a bound ligand would add
    # one PAE token per heavy atom, here two.
    pae = tmp_path / "confidences.json"
    pae.write_text(json.dumps({"pae": [[0.0] * 5 for _ in range(5)]}))
    caps = cmd_capabilities(session, model=model, paeFile=str(pae))
    assert not {"ipSAE", "pDockQ2", "LIS"} & set(caps.available)
    assert "5 tokens" in caps.unavailable["ipSAE"]
    assert "3 amino-acid residues" in caps.unavailable["ipSAE"]
    assert any("unavailable — ipSAE" in line for line in session.logger.infos)


def test_capabilities_withhold_pae_metrics_when_the_file_is_not_a_matrix(
    session, model, monkeypatch, tmp_path
):
    key = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    monkeypatch.setattr(commands, "experimental_method", lambda m: None)
    monkeypatch.setattr(commands, "plddt_values", lambda m: ((key, 90.0),))
    monkeypatch.setattr(commands, "structure_path", lambda m: None)
    # Shaped like AlphaFold's *_summary_confidences.json: real JSON, chain-pair
    # summaries, no matrix.
    summary = tmp_path / "summary_confidences.json"
    summary.write_text(json.dumps({"chain_pair_iptm": [[0.8]]}))
    caps = cmd_capabilities(session, model=model, paeFile=str(summary))
    assert not {"ipSAE", "pDockQ2", "LIS"} & set(caps.available)
    assert "cannot be read as a PAE matrix" in caps.unavailable["ipSAE"]
    assert summary.name in caps.unavailable["ipSAE"]


def test_capabilities_explain_a_missing_pae_matrix(session, model, monkeypatch):
    key = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    monkeypatch.setattr(commands, "experimental_method", lambda m: None)
    monkeypatch.setattr(commands, "plddt_values", lambda m: ((key, 0.9),))
    monkeypatch.setattr(commands, "structure_path", lambda m: None)
    caps = cmd_capabilities(session, model=model)
    assert "pLDDT" in caps.available
    assert "PAE matrix" in caps.unavailable["ipSAE"]


def test_capabilities_withhold_confidence_for_uniform_zero_bfactors(
    session, model, monkeypatch
):
    key = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    monkeypatch.setattr(commands, "experimental_method", lambda m: None)
    monkeypatch.setattr(commands, "plddt_values", lambda m: ((key, 0.0),))
    monkeypatch.setattr(commands, "structure_path", lambda m: None)

    caps = cmd_capabilities(session, model=model)

    assert caps.kind == "unknown"
    assert "pLDDT" in caps.unavailable
    assert "uniformly zero" in caps.detail
    assert "placeholder" in caps.unavailable["pLDDT"]


def test_confidence_refuses_experimental_structures(session, model, monkeypatch):
    monkeypatch.setattr(commands, "experimental_method", lambda m: "X-RAY DIFFRACTION")
    with pytest.raises(UserError, match="temperature factors, not pLDDT"):
        cmd_confidence(session, model=model)


def test_predicted_structure_preset_refuses_experimental_structures(
    session, model, monkeypatch
):
    monkeypatch.setattr(commands, "experimental_method", lambda m: "X-RAY DIFFRACTION")
    with pytest.raises(UserError, match="applies only to predicted models"):
        cmd_style(session, "predicted-structure", model=model)


def test_confidence_reports_pdockq_with_interface(session, model, monkeypatch, canned_result):
    keys = tuple(canned_result.group_a) + tuple(canned_result.group_b)
    monkeypatch.setattr(
        commands, "plddt_values", lambda m: tuple((key, 90.0) for key in keys)
    )
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    # Both are set together by `cmd_interface`; pDockQ needs the parameters to
    # know whether the detected interface is already its own definition.
    state.interface_params["#1"] = (("A",), ("B",), "cbeta", 8.0)
    metrics = cmd_confidence(session, model=model)
    assert metrics["scale"] == "0-100"
    assert metrics["iplddt"] == pytest.approx(90.0)
    assert metrics["contact_pairs"] == 4
    assert metrics["pdockq"] is not None
    assert any("pDockQ" in line for line in session.logger.infos)


def test_pdockq_is_measured_at_its_own_definition_not_the_displayed_one(
    session, model, monkeypatch, canned_result
):
    """A metric named after a paper should be the number that paper defines.

    pDockQ averages over a Cβ 8 Å interface. Taking whichever interface is on
    screen made it depend on a cutoff chosen for looking at figures: the
    worked example reads 0.443 on the 4.5 Å heavy-atom default and 0.521 at the
    published definition. `affinity` already fixes its own 5.5 Å contacts for
    the same reason.
    """
    keys = tuple(canned_result.group_a) + tuple(canned_result.group_b)
    monkeypatch.setattr(
        commands, "plddt_values", lambda m: tuple((key, 90.0) for key in keys)
    )
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("B",), "heavy", 4.5)

    measured = {}

    def fake_detect(points_a, points_b, cutoff=4.5, criterion="heavy"):
        measured["cutoff"] = cutoff
        measured["criterion"] = criterion
        return canned_result

    monkeypatch.setattr(commands, "detect_interface", fake_detect)
    monkeypatch.setattr(commands, "atom_points", lambda *a, **k: ())
    cmd_confidence(session, model=model)
    # Re-measured, and at the published definition rather than the shown one.
    assert measured == {"cutoff": 8.0, "criterion": "cbeta"}


def test_pdockq_is_absent_rather_than_wrong_when_it_cannot_be_measured(
    session, model, monkeypatch, canned_result
):
    """Reporting a differently-defined number under the same name is worse."""
    keys = tuple(canned_result.group_a) + tuple(canned_result.group_b)
    monkeypatch.setattr(
        commands, "plddt_values", lambda m: tuple((key, 90.0) for key in keys)
    )
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("B",), "heavy", 4.5)
    monkeypatch.setattr(commands, "atom_points",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("no chain")))
    metrics = cmd_confidence(session, model=model)
    assert metrics["pdockq"] is None
    # ipLDDT still stands: it is defined over the interface you asked for.
    assert metrics["iplddt"] == pytest.approx(90.0)


def test_confidence_without_interface_reports_mean_only(session, model, monkeypatch):
    key = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    monkeypatch.setattr(commands, "plddt_values", lambda m: ((key, 0.8),))
    metrics = cmd_confidence(session, model=model)
    assert metrics["pdockq"] is None
    assert any("no detected interface" in line for line in session.logger.infos)


def test_confidence_rejects_missing_bfactors(session, model, monkeypatch):
    monkeypatch.setattr(commands, "plddt_values", lambda m: ())
    with pytest.raises(UserError, match="no B-factor/pLDDT values"):
        cmd_confidence(session, model=model)


def test_ddg_loads_tabular_and_ranks_residues(session, model, tmp_path):
    target = tmp_path / "foldx.csv"
    target.write_text("chain,position,wt,mut,ddG\nA,59,R,A,2.0\nA,27,K,A,-3.0\n")
    rows = cmd_ddg(session, str(target), model=model)
    assert rows[0][0] == ("A", 27)
    assert state_for(session).ddg["#1"]
    assert any("K A:27" in line for line in session.logger.infos)


def test_ddg_rejects_missing_file_and_bad_format(session, model, tmp_path):
    with pytest.raises(UserError, match="does not exist"):
        cmd_ddg(session, str(tmp_path / "nope.csv"), model=model)
    target = tmp_path / "x.csv"
    target.write_text("chain,position,wt,mut,ddG\nA,1,R,A,1.0\n")
    with pytest.raises(UserError, match="format must be"):
        cmd_ddg(session, str(target), model=model, format="magic")


def test_ddg_pythia_format_uses_the_sequential_index_map(session, model, tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "sequential_index_map", lambda m: {1: ("A", 27)})
    target = tmp_path / "x_pred_mask.txt"
    target.write_text("A1G 0.5\nA1V -1.25\n")
    rows = cmd_ddg(session, str(target), model=model)
    assert rows[0][0] == ("A", 27)
    assert rows[0][2] == pytest.approx(-1.25)


def test_hotspots_require_detected_interface(session, model):
    with pytest.raises(UserError, match="Detect an interface first"):
        cmd_hotspots(session, model=model)


def test_hotspots_rank_and_filter_by_buried_area(session, model, monkeypatch, canned_result):
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    rows = (
        (("A", 59, ""), "ARG", 200.0, 20.0, 180.0),
        (("A", 27, ""), "LYS", 150.0, 100.0, 50.0),
        (("D", 39, ""), "ASP", 120.0, 115.0, 5.0),
    )
    monkeypatch.setattr(commands, "delta_sasa", lambda *a, **k: rows)
    kept = cmd_hotspots(session, model=model, minArea=10.0)
    assert [row[0][1] for row in kept] == [59, 27]  # 5 Å² row filtered out
    assert any("ARG A:59" in line for line in session.logger.infos)
    assert cmd_hotspots(session, model=model, minArea=0.0, top=1) == rows[:1]


def test_characterise_runs_the_whole_workflow_in_one_call(
    session, model, monkeypatch, canned_result
):
    monkeypatch.setattr(commands, "cmd_interface", lambda *a, **k: canned_result)
    state = state_for(session)
    state.interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    monkeypatch.setattr(commands, "cmd_interactions", lambda *a, **k: ())
    monkeypatch.setattr(commands, "cmd_buriedarea", lambda *a, **k: 1129.4)

    class FakeAffinity:
        delta_g, kd, temperature = -10.63, 1.6e-08, 25.0

    monkeypatch.setattr(commands, "cmd_affinity", lambda *a, **k: FakeAffinity())
    monkeypatch.setattr(
        commands, "cmd_hotspots",
        lambda *a, **k: ((("A", 59, ""), "ARG", 200.0, 80.0, 120.7),),
    )
    monkeypatch.setattr(commands, "cmd_confidence", lambda *a, **k: {"pdockq": None})
    monkeypatch.setattr(commands, "cmd_style", lambda *a, **k: ())

    summary = cmd_characterise(session, "A", "D", model=model)
    assert summary["interface"]["contact_pairs"] == 4
    assert summary["buried_area"] == pytest.approx(1129.4)
    assert summary["affinity"]["delta_g"] == pytest.approx(-10.63)
    assert summary["hotspots"][0]["residue"] == "ARG A:59"
    assert {"interface", "buried_area", "affinity", "hotspots", "figure"} <= set(
        summary["steps"]
    )


def test_characterise_records_why_a_step_was_skipped(
    session, model, monkeypatch, canned_result
):
    monkeypatch.setattr(commands, "cmd_interface", lambda *a, **k: canned_result)
    state_for(session).interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    monkeypatch.setattr(commands, "cmd_interactions", lambda *a, **k: ())
    monkeypatch.setattr(commands, "cmd_buriedarea", lambda *a, **k: 1129.4)
    monkeypatch.setattr(commands, "cmd_affinity", lambda *a, **k: None)
    monkeypatch.setattr(commands, "cmd_hotspots", lambda *a, **k: ())
    monkeypatch.setattr(commands, "cmd_style", lambda *a, **k: ())

    def refuse(*args, **kwargs):
        raise UserError("experimental structure: B-factors are temperature factors")

    monkeypatch.setattr(commands, "cmd_confidence", refuse)
    summary = cmd_characterise(session, "A", "D", model=model)
    # A step that does not apply is reported, not raised.
    assert "temperature factors" in summary["skipped"]["confidence"]
    assert "confidence" not in summary["steps"]


def test_report_requires_detected_interface(session, model, tmp_path):
    with pytest.raises(UserError, match="Detect an interface first"):
        cmd_report(session, str(tmp_path / "r.md"), model=model)


def test_report_rejects_unknown_format(session, model, tmp_path, monkeypatch, canned_result):
    state_for(session).interfaces["#1"] = canned_result
    state_for(session).interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    with pytest.raises(UserError, match="report format must be"):
        cmd_report(session, str(tmp_path / "r.pdf"), model=model)


def _stub_report_analyses(monkeypatch):
    """Make the optional analyses unavailable so the report degrades gracefully."""
    def unavailable(*args, **kwargs):
        raise UserError("not available")

    monkeypatch.setattr(commands, "cmd_buriedarea", unavailable)
    monkeypatch.setattr(commands, "cmd_affinity", unavailable)
    monkeypatch.setattr(commands, "cmd_confidence", unavailable)


def test_report_writes_markdown_with_methods(
    session, model, tmp_path, monkeypatch, canned_result
):
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    state.recipe.append(
        commands.RecipeEntry(
            "molcompose interface A D model #1 distance 4.5 criterion heavy",
            "2026-08-14T00:00:00+00:00",
            "session",
        )
    )
    _stub_report_analyses(monkeypatch)
    target = tmp_path / "report.md"
    # A string for the same reason as cmd_export: Path is not JSON-serialisable
    # and the REST bridge serialises whatever a command returns.
    assert cmd_report(session, str(target), model=model) == str(target)
    text = target.read_text()
    assert "# Interface report" in text
    assert "## Methods" in text
    assert "chains A and D" in text
    assert "molcompose interface A D model #1 distance 4.5 criterion heavy" in text


def test_report_format_follows_suffix_and_override(
    session, model, tmp_path, monkeypatch, canned_result
):
    import json as json_module

    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    _stub_report_analyses(monkeypatch)
    target = tmp_path / "report.json"
    cmd_report(session, str(target), model=model)
    assert json_module.loads(target.read_text())["interface"]["residues_a"] == 3
    override = tmp_path / "report.txt"
    cmd_report(session, str(override), model=model, format="csv")
    assert override.read_text().startswith("section,key,value")


def test_report_rejects_missing_directory(session, model, tmp_path, canned_result):
    state_for(session).interfaces["#1"] = canned_result
    state_for(session).interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    with pytest.raises(UserError, match="output directory does not exist"):
        cmd_report(session, str(tmp_path / "nope" / "r.md"), model=model)


def test_buriedarea_requires_detected_interface(session, model):
    with pytest.raises(UserError, match="Detect an interface first"):
        cmd_buriedarea(session, model=model)


def test_interactions_require_detected_interface(session, model):
    with pytest.raises(UserError, match="Detect an interface first"):
        cmd_interactions(session, model=model)


def test_interactions_detect_display_and_log_counts(
    session, model, monkeypatch, canned_result
):
    from src.core.interactions import AtomRecord

    state_for(session).interfaces["#1"] = canned_result
    arg = Key("#1", "A", 1, "", "ARG", "#1/A:1")
    asp = Key("#1", "D", 1, "", "ASP", "#1/D:1")

    def fake_atoms(m, keys):
        keys = tuple(keys)
        if keys and keys[0].chain_id == "A":
            return (AtomRecord(arg, "NH1", 7, (0.0, 0.0, 0.0)),)
        return (AtomRecord(asp, "OD1", 8, (3.0, 0.0, 0.0)),)

    executed = []
    monkeypatch.setattr(commands, "interaction_atoms", fake_atoms)
    monkeypatch.setattr(commands, "_run", lambda s, c: executed.append(c))
    found = cmd_interactions(session, model=model, types="salt-bridge")
    assert len(found) == 1
    assert executed and executed[0].startswith("pbond ")
    assert any("salt-bridge 1" in line for line in session.logger.infos)
    assert state_for(session).interactions["#1"] == found


def test_interactions_off_closes_the_groups_rather_than_each_bond(
    session, model, monkeypatch
):
    """Hiding must not fail because there is less to hide than expected.

    The per-pair form asked ChimeraX to delete one specific pseudobond for
    every interaction recorded, so any that had already gone — a preset hid
    it, the interface was redetected, the button was pressed twice — aborted
    the run with "No pseudobond between /A ALA 23 CB and /B TYR 83 CD2 found
    for mc-hydrophobic". Closing the groups removes each whole, and a group
    that is not there is not in the list.
    """
    from src.core.interactions import Interaction

    arg = Key("#1", "A", 1, "", "ARG", "#1/A:1")
    asp = Key("#1", "D", 1, "", "ASP", "#1/D:1")
    stored = (Interaction("salt-bridge", arg, asp, 3.0, "NH1–OD1", "NH1", "OD1"),)
    state_for(session).interactions["#1"] = stored
    executed = []
    monkeypatch.setattr(commands, "_run", lambda s, c: executed.append(c))
    monkeypatch.setattr(
        commands, "_interaction_group_commands", lambda s, r: ("close #1.1",)
    )
    cmd_interactions(session, model=model, off=True)
    assert executed == ["close #1.1"]
    assert "#1" not in state_for(session).interactions


def test_only_molcompose_pseudobond_groups_are_closed(session, monkeypatch):
    """ChimeraX's own hydrogen bonds and contacts are separate groups."""
    from types import SimpleNamespace

    groups = [
        SimpleNamespace(name="mc-hydrophobic", atomspec="#1.1", id_string="1.1"),
        SimpleNamespace(name="hydrogen bonds", atomspec="#1.2", id_string="1.2"),
        SimpleNamespace(name="contacts", atomspec="#1.3", id_string="1.3"),
        SimpleNamespace(name="mc-salt-bridge", atomspec="#1.4", id_string="1.4"),
    ]
    import sys

    stub = SimpleNamespace(all_pseudobond_groups=lambda _s: groups)
    monkeypatch.setitem(sys.modules, "chimerax.atomic", stub)
    assert commands._interaction_group_commands(session, None) == (
        "close #1.1",
        "close #1.4",
    )


def test_interactions_reject_unknown_type(session, model, monkeypatch, canned_result):
    state_for(session).interfaces["#1"] = canned_result
    monkeypatch.setattr(commands, "interaction_atoms", lambda m, k: ())
    with pytest.raises(UserError, match="unknown interaction type"):
        cmd_interactions(session, model=model, types="magnetism")


def test_ipsae_scores_pairs_from_pae_file(session, model, tmp_path, monkeypatch):
    import json as json_module

    monkeypatch.setattr(
        commands, "cbeta_and_plddt",
        lambda m: (((0.0, 0, 0), (5.0, 0, 0), (10.0, 0, 0)), (90.0, 85.0, 80.0)),
    )
    pae_path = tmp_path / "pae.json"
    pae_path.write_text(json_module.dumps({"pae": [[0.0, 4.0, 4.0]] * 3}))
    scores = cmd_ipsae(session, str(pae_path), model=model)
    assert set(scores) == {"A-B", "A-D", "B-D"}
    assert all({"pdockq2", "lis"} <= set(v) for v in scores.values())
    assert any("pDockQ2" in line and "LIS" in line for line in session.logger.infos)
    # ipSAE is asymmetric, so the two directions have to name the chains they
    # describe. These were hardcoded "A→B"/"B→A", which mislabelled every pair
    # not called A and B — including the B-D pair of this very model, and every
    # AlphaFold2-Multimer model, whose chains come out B and C.
    lines = "\n".join(session.logger.infos)
    assert "B→D" in lines and "D→B" in lines
    assert "A→D" in lines and "D→A" in lines


def test_ipsae_token_mismatch_is_a_user_error(session, model, tmp_path, monkeypatch):
    import json as json_module

    monkeypatch.setattr(
        commands, "cbeta_and_plddt", lambda m: (((0.0, 0, 0),) * 3, (90.0,) * 3)
    )
    pae_path = tmp_path / "pae.json"
    pae_path.write_text(json_module.dumps({"pae": [[0.0, 4.0], [4.0, 0.0]]}))
    with pytest.raises(UserError, match="same residues"):
        cmd_ipsae(session, str(pae_path), model=model)


def test_contacts_requires_detected_interface(session, model):
    with pytest.raises(UserError, match="Detect an interface first"):
        cmd_contacts(session, model=model)


def test_contacts_runs_restricted_native_command(session, model, monkeypatch, canned_result):
    state_for(session).interfaces["#1"] = canned_result
    executed = []
    monkeypatch.setattr(commands, "_run", lambda s, c: executed.append(c))
    cmd_contacts(session, model=model)
    assert executed and executed[0].startswith("contacts ")
    assert "restrict" in executed[0]


def test_contacts_off_clears_without_interface(session, model, monkeypatch):
    executed = []
    monkeypatch.setattr(commands, "_run", lambda s, c: executed.append(c))
    cmd_contacts(session, model=model, off=True)
    assert executed == ["~contacts"]


def test_reset_runs_baseline_commands(session, model, monkeypatch):
    executed = []
    monkeypatch.setattr(commands, "_run", lambda s, c: executed.append(c))
    cmd_reset(session, model=model)
    assert executed == [
        "hide #1 atoms",
        "hide #1 surfaces",
        "show #1 cartoons",
        "color #1 #BBBBBB target c",
        "label delete #1 residues",
        "label missing #1 0",
        "~hbonds #1",
        "key delete",
    ]


ALL_COMMANDS = (
    "molcompose style",
    "molcompose interface",
    "molcompose interface all",
    "molcompose focus",
    "molcompose export",
    "molcompose capabilities",
    "molcompose confidence",
    "molcompose contacts",
    "molcompose ipsae",
    "molcompose hbonds",
    "molcompose reset",
)


@pytest.mark.parametrize("name", ALL_COMMANDS)
def test_register_command_registers_each_public_name(name):
    register_command(name, logger=None)
    assert name in REGISTERED


def test_register_command_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown MolCompose command: molcompose bogus"):
        register_command("molcompose bogus", logger=None)


# -- characterise reports the PAE-based scores too -----------------------------


def test_scores_for_pair_keeps_only_the_characterised_interface():
    """`ipsae` scores every chain pair; `characterise` asked about one.

    Until 2026-08-15 "Characterise Everything" ran no PAE step at all, so it
    returned every geometric quantity and none of the three scores that say
    whether a predicted interface should be believed. Adding the step raised
    the opposite problem: a six-chain crystal form scores fifteen pairs, and
    the one being described would be buried among them.
    """
    from src.commands import _scores_for_pair

    scores = {
        "A-D": {"max": 0.89, "pdockq2": 0.93, "lis": 0.77},
        "A-B": {"max": 0.02, "pdockq2": 0.01, "lis": 0.00},
        "B-E": {"max": 0.85, "pdockq2": 0.91, "lis": 0.74},
    }
    rows = _scores_for_pair(scores, ["A"], ["D"])
    assert [row["chains"] for row in rows] == ["A-D"]
    assert rows[0]["ipsae"] == 0.89 and rows[0]["lis"] == 0.77


def test_scores_for_pair_keeps_the_two_kinds_of_iptm_apart():
    """A whole-complex ipTM is not this interface's ipTM.

    Four of the five engines put ipTM in a different file from the PAE, and
    two of those report only a figure averaged over every chain pair in the
    model. Flattening the two would overstate what is known about one
    interface, so they travel in separate fields and the log says which it is.
    """
    from src.commands import _scores_for_pair

    pairwise = {"A-D": {"max": 0.89, "pdockq2": 0.93, "lis": 0.77, "iptm": 0.93}}
    (row,) = _scores_for_pair(pairwise, ["A"], ["D"])
    assert row["iptm"] == 0.93 and row["iptm_global"] is None

    global_only = {"A-D": {"max": 0.89, "pdockq2": 0.93, "lis": 0.77,
                           "iptm_global": 0.957}}
    (row,) = _scores_for_pair(global_only, ["A"], ["D"])
    assert row["iptm"] is None and row["iptm_global"] == 0.957


def test_scores_for_pair_matches_a_pair_written_either_way_round():
    from src.commands import _scores_for_pair

    scores = {"D-A": {"max": 0.89, "pdockq2": 0.93, "lis": 0.77}}
    assert _scores_for_pair(scores, ["A"], ["D"])[0]["chains"] == "D-A"


def test_scores_for_pair_covers_every_cross_pair_of_multi_chain_groups():
    """An antibody is H+L against one antigen chain: two pairs, not one."""
    from src.commands import _scores_for_pair

    scores = {
        "H-G": {"max": 0.7, "pdockq2": 0.8, "lis": 0.6},
        "L-G": {"max": 0.5, "pdockq2": 0.6, "lis": 0.4},
        "H-L": {"max": 0.9, "pdockq2": 0.9, "lis": 0.9},  # within group A
    }
    rows = _scores_for_pair(scores, ["H", "L"], ["G"])
    assert {row["chains"] for row in rows} == {"H-G", "L-G"}


# --- return_json: values for out-of-process callers ----------------------
#
# The REST bridge asks for JSON by passing return_json=True; nothing in
# process does. These check both halves of that bargain — the in-process
# answer is untouched, and the JSON answer is data rather than a repr.


def _json_of(value):
    """The JSON half of a JSONResult, proven to survive json.dumps."""
    assert hasattr(value, "json_value"), f"expected JSONResult, got {type(value).__name__}"
    json.dumps(value.json_value)  # a dataclass here would raise
    return value.json_value


def test_interface_returns_the_dataclass_unchanged_without_return_json(
    session, model, monkeypatch, canned_result
):
    monkeypatch.setattr(
        commands, "atom_points", lambda m, chains, criterion="heavy": tuple(sorted(chains))
    )
    monkeypatch.setattr(
        commands, "detect_interface", lambda a, b, cutoff, criterion="heavy": canned_result
    )
    assert cmd_interface(session, "A", "D", model=model) is canned_result


def test_interface_returns_named_counts_and_residues_as_json(
    session, model, monkeypatch, canned_result
):
    monkeypatch.setattr(
        commands, "atom_points", lambda m, chains, criterion="heavy": tuple(sorted(chains))
    )
    monkeypatch.setattr(
        commands, "detect_interface", lambda a, b, cutoff, criterion="heavy": canned_result
    )
    result = cmd_interface(session, "A", "D", model=model, return_json=True)

    # The in-process value is still the dataclass, for the panel and the CLI.
    assert result.python_value is canned_result

    payload = _json_of(result)
    assert payload["residues_a"] == 3
    assert payload["residues_b"] == 4
    assert payload["contact_pairs"] == 4
    assert payload["cutoff"] == 4.5
    assert payload["chains_a"] == ["A"]
    assert payload["criterion"] == "heavy"
    # Residues are named, not positional, and not a repr string.
    assert payload["group_a"][0]["chain_id"] == "A"
    assert payload["group_a"][0]["name"] == "ALA"
    assert payload["contacts"][0]["b"]["chain_id"] == "D"


def test_affinity_returns_named_fields_as_json(session, model, monkeypatch, canned_result):
    from src.core.affinity import AffinityResult

    canned = AffinityResult(
        delta_g=-10.63,
        kd=1.6e-08,
        temperature=25.0,
        bins={"CC": 11, "AC": 25, "PP": 2, "AP": 11},
        nis_apolar=33.3,
        nis_charged=34.3,
        contact_pairs=68,
    )
    state_for(session).interfaces["#1"] = canned_result
    state_for(session).interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    monkeypatch.setattr(commands, "predict_affinity", lambda *a, **k: canned)
    monkeypatch.setattr(
        commands, "atom_points", lambda m, chains, criterion="heavy": tuple(sorted(chains))
    )
    monkeypatch.setattr(
        commands, "detect_interface", lambda a, b, cutoff, criterion="heavy": canned_result
    )

    assert cmd_affinity(session, model=model) is canned

    payload = _json_of(cmd_affinity(session, model=model, return_json=True))
    assert payload["delta_g"] == -10.63
    assert payload["kd"] == 1.6e-08
    assert payload["contact_pairs"] == 68
    assert payload["bins"] == {"CC": 11, "AC": 25, "PP": 2, "AP": 11}


def test_capabilities_reports_its_refusals_as_json(session, model, monkeypatch):
    monkeypatch.setattr(commands, "experimental_method", lambda m: "X-RAY DIFFRACTION")
    monkeypatch.setattr(commands, "find_pae_file", lambda *a, **k: None)

    caps = cmd_capabilities(session, model=model)
    assert not hasattr(caps, "json_value")  # untouched in process

    payload = _json_of(cmd_capabilities(session, model=model, return_json=True))
    assert payload["kind"] == "experimental"
    assert isinstance(payload["unavailable"], dict)
    # The reasons are the point: each unsupported metric says why.
    assert all(isinstance(reason, str) and reason for reason in payload["unavailable"].values())


def test_af2_multimer_iptm_is_looked_up_by_the_structures_stem(
    session, model, tmp_path, monkeypatch
):
    """AF2-Multimer keys one iptm_ptm.json by model name, so the stem matters.

    This passed the *summary file's* stem — "iptm_ptm" — which matches no key,
    so the parser refused (correctly) and no AF2-Multimer model ever got an
    ipTM. The refusal is what hid it: the output was never wrong, a number was
    just always missing.
    """
    import json as json_module

    structure = tmp_path / "unrelaxed_model_5_multimer_v3_pred_0.cif"
    structure.write_text("x")
    (tmp_path / "iptm_ptm.json").write_text(json_module.dumps({
        "model_1_multimer_v3_pred_0": {"iptm": 0.11, "ptm": 0.5},
        "model_5_multimer_v3_pred_0": {"iptm": 0.93, "ptm": 0.94},
    }))
    monkeypatch.setattr(commands, "structure_path", lambda m: str(structure))

    scores = {"A-B": {"max": 0.8, "pdockq2": 0.9, "lis": 0.7}}
    commands._attach_iptm(session, model, commands.model_ref(model), scores)
    # Whole-complex, because AF2-Multimer reports no per-chain-pair value —
    # and it is model 5's number, not the first entry in the file.
    assert scores["A-B"]["iptm_global"] == 0.93
    assert "iptm" not in scores["A-B"]
    assert not any("could not read the summary" in line
                   for line in session.logger.infos)


def test_state_notification_cannot_fail_the_command_that_sends_it(session):
    """A view refreshing itself must not be able to lose an analysis.

    The alternative is a broken listener turning a working `molcompose
    interface` into an error, which trades a stale list for a lost result.
    """
    class ExplodingTriggers:
        def has_trigger(self, name):
            return True

        def activate_trigger(self, name, data):
            raise RuntimeError("a listener blew up")

    session.triggers = ExplodingTriggers()
    commands.notify_state_changed(session, "#1")  # must not raise
    assert any("failed to refresh" in line for line in session.logger.infos)


def test_a_session_without_triggers_is_not_an_error(session):
    """The MCP server and the tests drive commands on a bare session."""
    assert not hasattr(session, "triggers")
    commands.notify_state_changed(session, "#1")
    assert commands.ensure_state_trigger(session) is None


def test_the_trigger_is_registered_once(session):
    class Triggers:
        def __init__(self):
            self.names = []

        def has_trigger(self, name):
            return name in self.names

        def add_trigger(self, name):
            self.names.append(name)

    session.triggers = Triggers()
    commands.ensure_state_trigger(session)
    commands.ensure_state_trigger(session)
    assert session.triggers.names == [commands.STATE_CHANGED]


def test_detecting_an_interface_announces_it(session, model, monkeypatch):
    """The notification is what lets a view learn about work it did not do."""
    announced = []
    monkeypatch.setattr(
        commands, "notify_state_changed",
        lambda s, model_id=None: announced.append(model_id),
    )
    monkeypatch.setattr(commands, "_define_blocks", lambda *a, **k: None)
    cmd_interface(session, "A", "B", model=model)
    assert announced == ["#1"]


def test_a_declared_source_applies_to_one_command_and_then_reverts(
    session, model, monkeypatch
):
    """The agent bridge declares itself; the user's next command is not it.

    ChimeraX's REST control carries no identity, so a command sent by the agent
    is indistinguishable from one the user typed. Before this, every agent
    command was recorded as "session" and the report's provenance sentence said
    the user had issued them.
    """
    monkeypatch.setattr(commands, "_define_blocks", lambda *a, **k: None)
    monkeypatch.setattr(commands, "notify_state_changed", lambda *a, **k: None)

    commands.cmd_source(session, "agent")
    cmd_interface(session, "A", "B", model=model)
    # A second, undeclared command must not inherit it.
    cmd_interface(session, "A", "D", model=model)

    sources = [entry["source"] for entry in commands.recipe_log(session)]
    assert sources == ["agent", "session"]


def test_a_declared_source_is_not_recorded_as_a_command_itself(session, model, monkeypatch):
    """It is bookkeeping, not analysis, so it stays out of the replayable recipe."""
    monkeypatch.setattr(commands, "_define_blocks", lambda *a, **k: None)
    monkeypatch.setattr(commands, "notify_state_changed", lambda *a, **k: None)
    commands.cmd_source(session, "agent")
    cmd_interface(session, "A", "B", model=model)
    assert [entry["command"] for entry in commands.recipe_log(session)] == [
        "molcompose interface A B model #1 distance 4.5 criterion heavy"
    ]


def test_an_empty_source_is_refused(session):
    with pytest.raises(UserError, match="cannot be empty"):
        commands.cmd_source(session, "   ")


def test_the_panel_still_wins_for_its_own_clicks(session, model, monkeypatch):
    """`recording_source` is a scoped block; a declaration is for the bridge.

    Nothing arriving over REST is inside the panel's block, so the two cannot
    contend in practice — but if they did, the click that is actually happening
    is the truth.
    """
    monkeypatch.setattr(commands, "_define_blocks", lambda *a, **k: None)
    monkeypatch.setattr(commands, "notify_state_changed", lambda *a, **k: None)
    with commands.recording_source(session, "panel"):
        cmd_interface(session, "A", "B", model=model)
    assert [e["source"] for e in commands.recipe_log(session)] == ["panel"]


def test_computed_numbers_are_kept_for_views_that_did_not_run_them(
    session, model, monkeypatch, tmp_path
):
    """A command's return value is seen only by the caller that ran it.

    So a panel sitting beside a structure an agent has just characterised had
    nothing to show. The numbers now live in session state, keyed by model.
    """
    monkeypatch.setattr(commands, "_define_blocks", lambda *a, **k: None)
    monkeypatch.setattr(commands, "notify_state_changed", lambda *a, **k: None)
    monkeypatch.setattr(commands, "buried_area", lambda *a, **k: 812.4)
    monkeypatch.setattr(commands, "measure_residue_sasa", lambda *a, **k: ())
    cmd_interface(session, "A", "B", model=model)
    commands.cmd_buriedarea(session, model=model)
    assert state_for(session).metrics["#1"]["bsa"] == 812.4


def test_re_detecting_an_interface_drops_numbers_derived_from_the_old_one(
    session, model, monkeypatch
):
    """Buried area for a 4.5 A interface is not buried area for an 8.0 A one.

    Keeping it would let a view show a number for a cutoff nobody asked for.
    """
    monkeypatch.setattr(commands, "_define_blocks", lambda *a, **k: None)
    monkeypatch.setattr(commands, "notify_state_changed", lambda *a, **k: None)
    monkeypatch.setattr(commands, "buried_area", lambda *a, **k: 812.4)
    cmd_interface(session, "A", "B", model=model)
    commands.cmd_buriedarea(session, model=model)
    assert "bsa" in state_for(session).metrics["#1"]
    cmd_interface(session, "A", "B", model=model, distance=8.0)
    assert state_for(session).metrics.get("#1", {}) == {}


def test_remembering_ignores_a_missing_value(session, model):
    """A metric that came back None is not a metric, and must not be stored."""
    ref = commands.model_ref(model)
    commands.remember_metric(session, ref, "dockq", None)
    assert state_for(session).metrics.get("#1", {}) == {}


def test_a_nested_command_does_not_notify_but_its_caller_does(session, model, monkeypatch):
    """`characterise` runs six analyses; a view wants one refresh, at the end.

    The first nested notification arrives when only the interface exists, which
    is how the result tiles came to be read before the buried area and affinity
    behind them had been stored.
    """
    announced = []
    triggers = SimpleNamespace(
        has_trigger=lambda name: True,
        activate_trigger=lambda name, data: announced.append(data),
    )
    session.triggers = triggers
    monkeypatch.setattr(commands, "_define_blocks", lambda *a, **k: None)

    with commands._nested(session):
        cmd_interface(session, "A", "B", model=model)
    assert announced == [], "a nested command must stay quiet"

    cmd_interface(session, "A", "D", model=model)
    assert announced == ["#1"]


def test_characterise_notifies_from_outside_its_own_nesting(session, model, monkeypatch):
    """The notification has to come from `cmd_characterise`, not from its steps.

    Every step runs inside `with _nested(...)`, and a notification sent from in
    there is suppressed by the same rule that keeps the recipe to one line. That
    is where it was: the panel refreshed only on the incidental model-add
    triggers the styling step happens to fire, and read the result tiles before
    the buried area and affinity behind them had been stored.

    The steps are stubbed rather than run — the point under test is where the
    notification is sent from, and what state holds by then.
    """
    seen = []
    session.triggers = SimpleNamespace(
        has_trigger=lambda name: True,
        activate_trigger=lambda name, data: seen.append(
            dict(state_for(session).metrics.get("#1", {}))
        ),
    )

    def fake_steps(sess, summary, mdl, ref, *args, **kwargs):
        # What the real steps do that matters here: they run nested, they store
        # numbers, and any notification of their own is swallowed.
        assert state_for(sess)._nesting > 0, "steps must run nested"
        commands.notify_state_changed(sess, ref.model_id)
        commands.remember_metric(sess, ref, "bsa", 812.4)
        return summary

    monkeypatch.setattr(commands, "_characterise_steps", fake_steps)
    commands.cmd_characterise(session, "A", "B", model=model, style=False)

    assert len(seen) == 1, "exactly one notification for the whole sequence"
    # And it carries the numbers the steps stored, which is the whole point.
    assert seen[0].get("bsa") == 812.4


def test_the_survey_makes_the_next_refusal_useful(session, model, monkeypatch):
    """"interface all" then "buriedarea" answered four pairs with "detect one".

    Technically true and reasonably infuriating. The survey deliberately makes
    no pair active — choosing for the user would replace an interface they had
    set on purpose — so the refusal has to say that, and name a pair to try.
    """
    monkeypatch.setattr(commands, "_define_blocks", lambda *a, **k: None)
    monkeypatch.setattr(commands, "notify_state_changed", lambda *a, **k: None)

    plain = commands._detect_interface_missing(session, "#1")
    assert "interface all" not in str(plain)

    commands.cmd_interface_all(session, model=model)
    surveyed = state_for(session).surveys["#1"]
    assert surveyed, "the survey has to be remembered to be mentioned"
    message = str(commands._detect_interface_missing(session, "#1"))
    assert "does not choose one" in message
    # The suggestion is the pair with the most contacts, not the first found.
    best = max(surveyed, key=lambda row: row[2])
    assert f"molcompose interface {best[0]} {best[1]}" in message


def test_the_survey_does_not_become_the_active_interface(session, model, monkeypatch):
    """It reports; it does not decide. Downstream commands must still refuse."""
    monkeypatch.setattr(commands, "_define_blocks", lambda *a, **k: None)
    monkeypatch.setattr(commands, "notify_state_changed", lambda *a, **k: None)
    commands.cmd_interface_all(session, model=model)
    assert state_for(session).interfaces == {}
    with pytest.raises(UserError, match="Detect an interface first"):
        commands.cmd_contacts(session, model=model)


def test_a_reused_model_id_takes_the_stored_numbers_with_it(session, model, monkeypatch):
    """Model ids are reused, and metrics are keyed by id like every other cache.

    Without this, closing #1 and opening a different structure that becomes #1
    left the previous structure's buried area and ΔG for a view to read back —
    the same failure `_drop_cache_from_another_structure` was written for, in a
    cache added after it.
    """
    monkeypatch.setattr(commands, "notify_state_changed", lambda *a, **k: None)

    # A real class, not SimpleNamespace: the owner is held by weak reference and
    # SimpleNamespace cannot be weak-referenced, so a namespace double silently
    # skips the very mechanism under test.
    class Structure:
        def __init__(self, name):
            self.id, self.id_string, self.atomspec = (1,), "1", "#1"
            self.name, self.chains = name, ()

    first = Structure("first")
    ref = commands.model_ref(first)
    commands.remember_metric(session, ref, "bsa", 812.4)
    state_for(session).surveys["#1"] = (("A", "B", 12),)
    commands.resolve_model(session, first)          # first owner registered
    assert state_for(session).owners.get("#1") is not None

    commands.resolve_model(session, Structure("second"))   # #1 means another one
    assert state_for(session).metrics.get("#1") is None
    assert state_for(session).surveys.get("#1") is None


def test_metric_colouring_reaches_surfaces():
    """Every colour `color by` paints must name surfaces in its target.

    Without the `s` the metric paints atoms and cartoons and leaves any
    surface holding whatever colour the preset gave it. On surface-translucent
    that is EPITOPE_BLUE, sitting beside a diverging key whose most-negative
    block is #2166AC — three degrees apart in hue. A figure went out with a
    large blue patch reading "strongly stabilising" over a dataset whose every
    value is positive, and the colour was not a value at all.

    Asserted against the source rather than a rendered figure because the
    defect is invisible in every test that does not draw a surface, which was
    all of them. On a figure whose whole content is a scale, a colour is
    either a value or the no-data colour; a surface is not a third category.
    """
    import inspect
    import re

    targets = re.findall(r"target ([a-z]+)", inspect.getsource(commands.cmd_color_by))
    assert targets, "cmd_color_by no longer names its colour targets explicitly"
    assert all("s" in target for target in targets), targets


def test_the_label_override_reaches_the_renderer_and_the_recipe(
    session, model, monkeypatch, canned_result
):
    """Replaying the recipe has to produce the same figure, labels included."""
    state_for(session).interfaces["#1"] = canned_result
    monkeypatch.setattr(commands, "_run", lambda *a, **k: None)
    monkeypatch.setattr(commands, "notify_state_changed", lambda *a, **k: None)
    seen = {}

    def fake_render(session, ref, preset, interface=None, **kwargs):
        seen["label_top"] = preset.geometry.label_top
        return ()

    monkeypatch.setattr(commands, "render_preset", fake_render)
    commands.cmd_style(session, "paratope-closeup", model=model, labels=5)
    assert seen["label_top"] == 5
    assert commands.recipe_commands(session)[-1].endswith(" labels 5")

    # The preset itself is untouched: the override is per call.
    from src.core.presets import PRESETS
    assert PRESETS["paratope-closeup"].geometry.label_top == 2


def test_confidence_keeps_the_three_numbers_that_had_no_home(
    session, model, monkeypatch, canned_result
):
    """mean pLDDT, ipLDDT and pDockQ reached the Log and stopped there."""
    key = Key("#1", "A", 1, "", "ALA", "#1/A:1")
    monkeypatch.setattr(commands, "experimental_method", lambda m: None)
    monkeypatch.setattr(commands, "plddt_values", lambda m: ((key, 90.0),))
    monkeypatch.setattr(commands, "notify_state_changed", lambda *a, **k: None)
    state_for(session).interfaces["#1"] = canned_result
    commands.cmd_confidence(session, model=model)
    stored = state_for(session).metrics["#1"]
    assert stored["plddt"] == 90.0
    assert "iplddt" in stored


# --- MM/PBSA -----------------------------------------------------------------

def _decomposition(rows) -> str:
    """A minimal DELTAS section in gmx_MMPBSA's shape."""
    header = ["DELTAS:", "Total Energy Decomposition:",
              "Residue,Internal,,,van der Waals,,,Electrostatic,,,"
              "Polar Solvation,,,Non-Polar Solv.,,,TOTAL,,",
              ",Avg.,Std. Dev.,Std. Err. of Mean" * 6]
    for key, energy in rows:
        columns = ["0.0"] * 19
        columns[0] = key
        columns[16] = str(energy)
        columns[18] = "0.1"
        header.append(",".join(columns))
    return "\n".join(header)


def test_energy_requires_a_chain_map(session, model, tmp_path):
    """Guessing by order attaches one partner's energies to the other."""
    target = tmp_path / "decomp.dat"
    target.write_text(_decomposition([("R:A:ALA:1", -5.0)]))
    with pytest.raises(UserError, match="'chains' is required"):
        commands.cmd_energy(session, str(target), model=model)


def test_energy_loads_and_renames_the_chains(session, model, tmp_path):
    target = tmp_path / "decomp.dat"
    target.write_text(_decomposition([("R:A:ALA:1", -5.0), ("L:B:ALA:1", -2.0)]))
    loaded = commands.cmd_energy(session, str(target), chains="A:A,B:D", model=model)
    assert sorted(e.chain for e in loaded) == ["A", "D"]
    assert state_for(session).energies["#1"]
    assert any("negative is favourable" in line for line in session.logger.infos)


def test_energy_says_it_is_not_the_interface_dg(session, model, tmp_path):
    """−80 kcal/mol beside PRODIGY's −10.6 would read as the same quantity."""
    target = tmp_path / "decomp.dat"
    target.write_text(_decomposition([("R:A:ALA:1", -5.0)]))
    commands.cmd_energy(session, str(target), chains="A:A", model=model)
    assert any("not the interface's ΔG" in line for line in session.logger.infos)


def test_energy_refuses_a_chain_map_the_structure_contradicts(session, model, tmp_path):
    """The file's residue names are the only thing tying it to a structure."""
    target = tmp_path / "decomp.dat"
    target.write_text(_decomposition([("R:A:TRP:1", -5.0)]))
    with pytest.raises(UserError, match="does not describe"):
        commands.cmd_energy(session, str(target), chains="A:A", model=model)


def test_energy_refuses_a_map_that_selects_nothing(session, model, tmp_path):
    target = tmp_path / "decomp.dat"
    target.write_text(_decomposition([("R:A:ALA:1", -5.0)]))
    with pytest.raises(UserError, match="no residue"):
        commands.cmd_energy(session, str(target), chains="Z:A", model=model)


def test_hotspots_by_energy_needs_the_decomposition(session, model, canned_result):
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    with pytest.raises(UserError, match="no MM/PBSA decomposition"):
        commands.cmd_hotspots(session, model=model, metric="energy")


def test_hotspots_rejects_an_unknown_metric(session, model, canned_result):
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    with pytest.raises(UserError, match="hot-spot metric"):
        commands.cmd_hotspots(session, model=model, metric="vibes")


def test_hotspots_by_energy_ranks_and_says_what_it_ranked_by(
    session, model, canned_result, tmp_path
):
    """Two hot-spot figures that disagree are only confusing if neither says
    what it ranked by."""
    target = tmp_path / "decomp.dat"
    target.write_text(_decomposition([("R:A:ALA:1", -2.0), ("L:B:ALA:1", -9.0)]))
    commands.cmd_energy(session, str(target), chains="A:A,B:D", model=model)
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    rows = commands.cmd_hotspots(session, model=model, metric="energy")
    assert [row[0][:2] for row in rows] == [("D", 1), ("A", 1)]
    assert any("by MM/PBSA contribution" in line for line in session.logger.infos)
    assert any("metric energy" in entry.command
               for entry in state_for(session).recipe)


def test_state_survives_the_bundle_being_reloaded(session):
    """The state lives on the session and outlives this module.

    ChimeraX re-imports a bundle on its own, and `toolshed reload` or an
    update mid-session does it deliberately, leaving an instance of the
    previous class behind. It looks fine until a command reaches a field the
    old class never had — `energies` did exactly this the morning after it was
    added — and then raises AttributeError from deep inside a command.
    """
    from dataclasses import dataclass, field

    @dataclass
    class OlderState:
        """What the class looked like before `energies` existed."""

        interfaces: dict = field(default_factory=dict)
        ddg: dict = field(default_factory=dict)

    older = OlderState()
    older.interfaces["#1"] = "an interface the user already detected"
    session._molcompose_state = older

    state = state_for(session)
    assert type(state) is commands.MolComposeState
    assert hasattr(state, "energies")
    # And the work done before the reload is still there.
    assert state.interfaces["#1"] == "an interface the user already detected"


def test_a_current_state_is_left_alone(session):
    state = state_for(session)
    assert state_for(session) is state


def test_style_ranks_by_buried_area_unless_told_otherwise(
    session, model, canned_result, monkeypatch
):
    """Unchanged default: every figure drawn so far used buried area."""
    seen = {}
    monkeypatch.setattr(commands, "cmd_hotspots",
                        lambda s, **kw: seen.update(kw) or ())
    monkeypatch.setattr(commands, "render_preset", lambda *a, **kw: ())
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    commands.cmd_style(session, "licorice-closeup", model=model)
    assert seen.get("metric") == "dsasa"


def test_style_can_rank_by_the_metric_the_figure_is_coloured_with(
    session, model, canned_result, monkeypatch
):
    """Sticks, frames and labels followed buried area whatever the colour said.

    A panel painted with MM/PBSA could leave the residues the colour calls
    strongest unnamed: on barnase–barstar Arg83 and Arg87 came out deep red
    and unlabelled while Asp35 was named.
    """
    seen = {}
    monkeypatch.setattr(commands, "cmd_hotspots",
                        lambda s, **kw: seen.update(kw) or ())
    monkeypatch.setattr(commands, "render_preset", lambda *a, **kw: ())
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    commands.cmd_style(session, "licorice-closeup", model=model, rankBy="energy")
    assert seen.get("metric") == "energy"
    assert any("rankBy energy" in entry.command for entry in state_for(session).recipe)


def test_style_refuses_a_ranking_it_cannot_do(session, model):
    with pytest.raises(UserError, match="rankBy"):
        commands.cmd_style(session, "clean-cartoon", model=model, rankBy="vibes")


def test_bare_molcompose_lists_the_subcommands(session):
    """It is the first thing someone types after installing, and ChimeraX's
    own answer — "Incomplete command" — is accurate and useless."""
    listed = commands.cmd_overview(session)
    assert "molcompose characterise" in listed
    assert "molcompose" not in listed  # it does not list itself
    printed = "\n".join(session.logger.infos)
    assert "Tools → Structure Analysis" in printed
    # Every command carries its synopsis, so the list says what each one is for.
    assert "Detect every contacting protein chain pair" in printed


def test_residue_keyed_returns_are_json_serialisable():
    """A command's return crosses the REST bridge as JSON.

    `molcompose flexibility` returned `dict[(chain, number)] -> float`. JSON has
    no tuple keys and ChimeraX wedges on the attempt rather than raising, so
    the whole session stopped answering and it read as a hung analysis. Export
    and report had the same shape once, when they returned Path.
    """
    import json

    from src.commands import residue_keys_as_text

    placed = {("A", 12): 1.83, ("B", 7): 0.42}
    text = residue_keys_as_text(placed)
    assert text == {"A:12": 1.83, "B:7": 0.42}
    assert json.loads(json.dumps(text)) == text
    with pytest.raises(TypeError):
        json.dumps(placed)


# -- pointing at the repaired structure --------------------------------------


def test_the_repaired_structure_is_named_when_it_is_there(tmp_path):
    """The file someone needs next is usually beside the one they just chose."""
    (tmp_path / "FINAL_DECOMP_MMPBSA.dat").write_text("")
    (tmp_path / "1brs_AD_repaired.pdb").write_text("")
    hint = commands._repaired_structure_hint(tmp_path / "FINAL_DECOMP_MMPBSA.dat")
    assert "1brs_AD_repaired.pdb" in hint


def test_nothing_is_claimed_when_there_is_no_repaired_structure(tmp_path):
    """Silence beats a hint that sends someone looking for a file they lack.

    Not everyone has one. A run someone did themselves keeps it beside the
    results; a decomposition that arrived on its own may have nothing of the
    sort, and telling that person to find a repaired structure would be
    advice with no object.
    """
    (tmp_path / "FINAL_DECOMP_MMPBSA.dat").write_text("")
    (tmp_path / "1brs.pdb").write_text("")
    assert commands._repaired_structure_hint(tmp_path / "FINAL_DECOMP_MMPBSA.dat") == ""


def test_a_missing_directory_is_not_an_error(tmp_path):
    assert commands._repaired_structure_hint(tmp_path / "gone" / "x.dat") == ""


def test_a_matching_model_that_is_already_open_is_named(session, monkeypatch):
    """The step people miss after being told the structure is wrong.

    They open the right one, and the panel goes on acting on the first: its
    selector keeps whatever was chosen when a model is added rather than
    following the newest. Pressing the button again repeats the same error
    about a structure they no longer mean.

    Auto-selecting the newest model would break the other flow in this panel —
    a DockQ reference is opened the same way and the analysis would jump to it
    — so the selection is left alone and the message says where to point it.
    """
    from types import SimpleNamespace

    from src.core.mmpbsa import ResidueEnergy

    energies = (ResidueEnergy("R", "A", "LYS", 27, -1.0),)
    monkeypatch.setattr(commands, "verify_residue_names", lambda e, n: ())
    monkeypatch.setattr(
        commands, "residue_sequences", lambda m, c: {"A": ((("A", 27, ""), "LYS"),)}
    )
    monkeypatch.setattr(
        commands, "model_ref",
        lambda m: SimpleNamespace(model_id="#2", name="repaired.pdb",
                                  chains=(SimpleNamespace(chain_id="A"),)),
    )

    class Structure:
        pass

    import sys

    monkeypatch.setitem(
        sys.modules, "chimerax.atomic",
        SimpleNamespace(AtomicStructure=Structure),
    )
    session.models = SimpleNamespace(list=lambda: [Structure()])
    hint = commands._matching_open_model(session, energies, "#1")
    assert "repaired.pdb (#2) is already open" in hint

    # The panel needs the model, not the sentence: it switches to it and
    # loads again rather than leaving the last step to the reader.
    assert commands.matching_open_model(session, energies, "#1") is not None

    # The model being acted on is never proposed as the answer to itself.
    assert commands._matching_open_model(session, energies, "#2") == ""
    assert commands.matching_open_model(session, energies, "#2") is None


def test_rmsf_matches_a_structure_by_block_lengths(session, monkeypatch, tmp_path):
    """A different question from the decomposition's, asked differently.

    `gmx rmsf -res` carries no residue names — one value per residue per
    chain and nothing else — so all a structure can be checked against is how
    many residues each named chain has. Weaker evidence, and it is the whole
    of what the file says. It catches the case it exists for: 1BRS repaired
    is 110 and 89 residues where the deposited entry is 108 and 87.
    """
    from types import SimpleNamespace

    xvg = tmp_path / "rmsf.xvg"
    xvg.write_text(
        '@    xaxis  label "Residue"\n@    yaxis  label "(nm)"\n'
        + "".join(f"{n} 0.1\n" for n in range(1, 4))
        + "".join(f"{n} 0.1\n" for n in range(1, 3))
    )

    class Structure:
        pass

    wrong, right = Structure(), Structure()
    refs = {
        id(wrong): SimpleNamespace(model_id="#1", name="deposited.pdb",
                                   chains=(SimpleNamespace(chain_id="A"),
                                           SimpleNamespace(chain_id="D"))),
        id(right): SimpleNamespace(model_id="#2", name="repaired.pdb",
                                   chains=(SimpleNamespace(chain_id="A"),
                                           SimpleNamespace(chain_id="D"))),
    }
    lengths = {"#1": {"A": 2, "D": 1}, "#2": {"A": 3, "D": 2}}

    def sequences(model, chains):
        counts = lengths[refs[id(model)].model_id]
        return {c: tuple(((c, n, ""), "ALA") for n in range(counts[c]))
                for c in chains}

    import sys

    monkeypatch.setitem(sys.modules, "chimerax.atomic",
                        SimpleNamespace(AtomicStructure=Structure))
    monkeypatch.setattr(commands, "model_ref", lambda m: refs[id(m)])
    monkeypatch.setattr(commands, "residue_sequences", sequences)
    session.models = SimpleNamespace(list=lambda: [wrong, right])

    found = commands.matching_open_model_for_blocks(session, xvg, "A,D", "#1")
    assert found is right
    # Nothing to move to when the structure in hand already fits.
    assert commands.matching_open_model_for_blocks(session, xvg, "A,D", "#2") is None
