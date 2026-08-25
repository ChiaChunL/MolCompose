"""The reproducible command recipe.

The recipe is the artefact the manuscript claims makes an analysis replayable
("the entire analysis is replayable from the record alone"), so what it does and
does not contain is a scientific claim, not a formatting detail.

Until this suite existed, only `molcompose interface` recorded itself: a report
listed one line no matter how many analyses had produced its numbers, and a
`characterise` call after an `interface` call recorded the interface twice while
recording none of the six analyses it ran.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

import src.commands as commands
from src.commands import (
    cmd_buriedarea,
    cmd_characterise,
    cmd_contacts,
    cmd_interface,
    cmd_report,
    cmd_reset,
    cmd_style,
    state_for,
)
from src.core.interfaces import ContactPair, InterfaceResult
from src.core.interfaces import ResidueKey as Key


class FakeLogger:
    def info(self, message):
        pass

    def warning(self, message):
        pass


@pytest.fixture
def session():
    return SimpleNamespace(logger=FakeLogger())


@pytest.fixture
def model():
    return SimpleNamespace(id=(1,), id_string="1", name="fake", atomspec="#1", chains=())


@pytest.fixture
def canned_result():
    a_keys = tuple(Key("#1", "A", n, "", "ALA", f"#1/A:{n}") for n in (1, 2, 3))
    b_keys = tuple(Key("#1", "D", n, "", "GLY", f"#1/D:{n}") for n in (1, 2, 3, 4))
    return InterfaceResult(
        a_keys, b_keys, tuple(ContactPair(a_keys[0], key) for key in b_keys), 4.5
    )


@pytest.fixture
def stub_session(monkeypatch, session, model, canned_result):
    """A session where every adapter-backed command succeeds with canned data."""
    monkeypatch.setattr(
        commands, "model_ref",
        lambda _model: SimpleNamespace(model_id="#1", name="fake", atomspec="#1", chains=()),
    )
    monkeypatch.setattr(commands, "resolve_model", lambda _session, _model=None: model)
    state = state_for(session)
    state.interfaces["#1"] = canned_result
    state.interface_params["#1"] = (("A",), ("D",), "heavy", 4.5)
    return session


def recipe(session):
    """The recipe as plain replayable strings."""
    return list(commands.recipe_commands(session))


# -- every command contributes -----------------------------------------------


def test_analysis_commands_record_themselves(stub_session, model, monkeypatch):
    monkeypatch.setattr(commands, "buried_area", lambda *a, **k: 1129.0)
    monkeypatch.setattr(commands, "reset_commands", lambda _ref: ())
    monkeypatch.setattr(commands, "contact_commands", lambda *a, **k: ())
    monkeypatch.setattr(commands, "_run", lambda *a, **k: None)

    cmd_buriedarea(stub_session, model=model)
    cmd_contacts(stub_session, model=model)
    cmd_reset(stub_session, model=model)

    assert recipe(stub_session) == [
        "molcompose buriedarea model #1",
        "molcompose contacts model #1",
        "molcompose reset model #1",
    ]


def test_non_default_arguments_are_preserved(stub_session, model, monkeypatch):
    monkeypatch.setattr(commands, "atom_points", lambda *a, **k: ())
    monkeypatch.setattr(
        commands, "detect_interface",
        lambda *a, **k: InterfaceResult((), (), (), 6.0),
    )
    cmd_interface(stub_session, "A", "D", model=model, distance=6.0, criterion="cbeta")
    assert recipe(stub_session) == [
        "molcompose interface A D model #1 distance 6 criterion cbeta"
    ]


def test_the_recipe_states_the_criterion_and_the_cutoff(
    stub_session, model, monkeypatch
):
    """Both, even when both are today's defaults.

    This test used to be called `test_defaults_are_omitted_so_the_recipe_stays
    _readable` and asserted a line carrying `distance 4.5` — a default — while
    omitting `criterion heavy`. One default written and the other dropped was
    not a readability rule, it was an inconsistency with a name on it. The
    recipe is what replays a published figure on a later version, and this
    default is the one the project has discussed moving.
    """
    monkeypatch.setattr(commands, "atom_points", lambda *a, **k: ())
    monkeypatch.setattr(
        commands, "detect_interface", lambda *a, **k: InterfaceResult((), (), (), 4.5)
    )
    cmd_interface(stub_session, "A", "D", model=model)
    assert recipe(stub_session) == [
        "molcompose interface A D model #1 distance 4.5 criterion heavy"
    ]


class WrapperStructure:
    """Two Python objects for one structure, as a C-pointer layer can produce.

    ChimeraX resolves `model #1` through `AtomicStructureArg`, which turns a C
    pointer into a Python instance. Today that instance is the one the session
    holds, so `handle` is the session's own object — this class exists to pin
    the behaviour if that ever stops being true, because the symptom is a
    silently empty recipe rather than an error.
    """

    def __init__(self, name, pointer):
        self.name = name
        self.cpp_pointer = pointer


def test_an_open_structure_keeps_its_commands_across_a_collection(session):
    """The line must outlive any garbage collection while the structure is open.

    Forced rather than hoped for: a `gc.collect()` that happens not to run is
    how the recipe filter passed its tests and still dropped live lines in
    ChimeraX.
    """
    import gc

    handle = FakeStructure("open throughout")
    session.models = SimpleNamespace(list=lambda: [handle])
    commands._record(session, "molcompose characterise A D model #1",
                     _ref_with_handle(handle))

    for _ in range(3):
        gc.collect()
    assert recipe(session) == ["molcompose characterise A D model #1"]


def test_a_line_is_tied_to_the_structure_not_to_the_wrapper_it_was_given(session):
    """A second wrapper for an open structure must not cost the line.

    The recipe holds its target weakly, and `_live_entries` asks whether that
    target is still in `session.models.list()`. Both questions answer "gone"
    for a per-call wrapper the moment it is collected, even though the
    structure is still open — so the line is tied to the object the session
    holds, matched on the underlying structure.
    """
    import gc

    held = WrapperStructure("the session's own object", pointer=0xBEEF)
    session.models = SimpleNamespace(list=lambda: [held])

    # The command is handed its own wrapper for the same structure.
    passing_wrapper = WrapperStructure("handed to the command", pointer=0xBEEF)
    commands._record(session, "molcompose characterise A D model #1",
                     _ref_with_handle(passing_wrapper))

    del passing_wrapper
    for _ in range(3):
        gc.collect()
    assert recipe(session) == ["molcompose characterise A D model #1"]

    # ...and closing the structure still takes the line with it.
    session.models = SimpleNamespace(list=lambda: [])
    assert recipe(session) == []


# -- nesting ------------------------------------------------------------------


def test_characterise_records_one_line_not_the_steps_it_runs(
    stub_session, model, monkeypatch, canned_result
):
    """The user typed one command; the recipe must say one command.

    Recording the six internal calls would describe a workflow that was never
    issued, and replaying it would not be equivalent -- `characterise` skips
    steps that cannot run, which a flat list of steps cannot express.
    """
    monkeypatch.setattr(commands, "cmd_interface", lambda *a, **k: canned_result)
    monkeypatch.setattr(commands, "cmd_interactions", lambda *a, **k: ())
    monkeypatch.setattr(commands, "cmd_buriedarea", lambda *a, **k: 1129.0)
    monkeypatch.setattr(commands, "cmd_hotspots", lambda *a, **k: ())
    monkeypatch.setattr(commands, "cmd_style", lambda *a, **k: ())

    class FakeAffinity:
        delta_g, kd, temperature = -10.63, 1.6e-08, 25.0

    monkeypatch.setattr(commands, "cmd_affinity", lambda *a, **k: FakeAffinity())
    monkeypatch.setattr(commands, "cmd_confidence", lambda *a, **k: {"pdockq": None})

    cmd_characterise(stub_session, "A", "D", model=model)
    assert recipe(stub_session) == [
        "molcompose characterise A D model #1 distance 4.5 criterion heavy"
    ]


def test_nested_commands_that_really_run_are_still_suppressed(
    stub_session, model, monkeypatch
):
    """Suppression must hold for real inner commands, not only monkeypatched ones."""
    monkeypatch.setattr(commands, "buried_area", lambda *a, **k: 1129.0)
    monkeypatch.setattr(commands, "_run", lambda *a, **k: None)
    monkeypatch.setattr(commands, "contact_commands", lambda *a, **k: ())

    with commands._nested(stub_session):
        cmd_buriedarea(stub_session, model=model)
        cmd_contacts(stub_session, model=model)
    assert recipe(stub_session) == []

    # ...and recording resumes once the block exits.
    cmd_buriedarea(stub_session, model=model)
    assert recipe(stub_session) == ["molcompose buriedarea model #1"]


def test_report_does_not_record_the_analyses_it_backfills(
    stub_session, model, monkeypatch, tmp_path
):
    """A report fills in missing analyses; those are not commands the user ran."""
    monkeypatch.setattr(commands, "buried_area", lambda *a, **k: 1129.0)
    monkeypatch.setattr(
        commands, "cmd_affinity",
        lambda *a, **k: (_ for _ in ()).throw(commands.UserError("no")),
    )
    monkeypatch.setattr(
        commands, "cmd_confidence",
        lambda *a, **k: (_ for _ in ()).throw(commands.UserError("x-ray")),
    )
    monkeypatch.setattr(commands, "_version", lambda: "0.1.0")
    monkeypatch.setattr(commands, "_chimerax_version", lambda _session: "1.12")

    target = tmp_path / "report.md"
    cmd_report(stub_session, str(target), model=model)

    assert recipe(stub_session) == [f"molcompose report {target} model #1 format md"]
    # The buried-area call the report made internally left no trace.
    assert not any("buriedarea" in line for line in recipe(stub_session))


def test_report_recipe_excludes_the_report_command_itself(
    stub_session, model, monkeypatch, tmp_path
):
    """What the file lists is the analysis that produced it."""
    monkeypatch.setattr(commands, "buried_area", lambda *a, **k: 1129.0)
    monkeypatch.setattr(
        commands, "cmd_affinity",
        lambda *a, **k: (_ for _ in ()).throw(commands.UserError("no")),
    )
    monkeypatch.setattr(
        commands, "cmd_confidence",
        lambda *a, **k: (_ for _ in ()).throw(commands.UserError("x-ray")),
    )
    monkeypatch.setattr(commands, "_version", lambda: "0.1.0")
    monkeypatch.setattr(commands, "_chimerax_version", lambda _session: "1.12")
    monkeypatch.setattr(commands, "_run", lambda *a, **k: None)
    monkeypatch.setattr(commands, "render_preset", lambda *a, **k: ())

    cmd_style(stub_session, "clean-cartoon", model=model)
    target = tmp_path / "report.md"
    cmd_report(stub_session, str(target), model=model)

    text = target.read_text()
    assert "molcompose style clean-cartoon model #1" in text
    assert "molcompose report" not in text


# -- duplicate suppression ----------------------------------------------------


def test_identical_consecutive_commands_are_not_repeated(
    stub_session, model, monkeypatch
):
    """Re-running a command to refresh a result must not inflate the record."""
    monkeypatch.setattr(commands, "buried_area", lambda *a, **k: 1129.0)
    for _ in range(3):
        cmd_buriedarea(stub_session, model=model)
    assert recipe(stub_session) == ["molcompose buriedarea model #1"]


def test_a_repeat_after_a_different_command_is_kept(stub_session, model, monkeypatch):
    """Only *consecutive* duplicates collapse; order still carries meaning."""
    monkeypatch.setattr(commands, "buried_area", lambda *a, **k: 1129.0)
    monkeypatch.setattr(commands, "reset_commands", lambda _ref: ())
    monkeypatch.setattr(commands, "_run", lambda *a, **k: None)

    cmd_buriedarea(stub_session, model=model)
    cmd_reset(stub_session, model=model)
    cmd_buriedarea(stub_session, model=model)
    assert recipe(stub_session) == [
        "molcompose buriedarea model #1",
        "molcompose reset model #1",
        "molcompose buriedarea model #1",
    ]


def test_a_failed_command_records_nothing(stub_session, model, monkeypatch):
    """A command that raised did not happen, and must not appear in the recipe."""
    state = state_for(stub_session)
    state.interface_params.pop("#1")
    with pytest.raises(commands.UserError):
        cmd_buriedarea(stub_session, model=model)
    assert recipe(stub_session) == []


# -- timestamps and source attribution ---------------------------------------


def test_each_entry_carries_a_timestamp_and_a_source(stub_session, model, monkeypatch):
    monkeypatch.setattr(commands, "buried_area", lambda *a, **k: 1129.0)
    cmd_buriedarea(stub_session, model=model)

    (entry,) = commands.recipe_log(stub_session)
    assert entry["command"] == "molcompose buriedarea model #1"
    assert entry["source"] == "session"
    # ISO-8601 UTC, to the second.
    datetime.fromisoformat(entry["timestamp"])
    assert entry["timestamp"].endswith("+00:00")


def test_source_attribution_follows_the_calling_surface(
    stub_session, model, monkeypatch
):
    """A click and a typed command are both the user, but not the same act."""
    monkeypatch.setattr(commands, "buried_area", lambda *a, **k: 1129.0)
    monkeypatch.setattr(commands, "reset_commands", lambda _ref: ())
    monkeypatch.setattr(commands, "_run", lambda *a, **k: None)

    with commands.recording_source(stub_session, "panel"):
        cmd_buriedarea(stub_session, model=model)
    cmd_reset(stub_session, model=model)

    assert [entry["source"] for entry in commands.recipe_log(stub_session)] == [
        "panel",
        "session",
    ]


def test_source_is_restored_even_if_the_command_fails(stub_session, model):
    state = state_for(stub_session)
    state.interface_params.pop("#1")
    with pytest.raises(commands.UserError), commands.recording_source(stub_session, "panel"):
        cmd_buriedarea(stub_session, model=model)
    assert state.source == "session"


# -- a closed structure takes its commands with it ----------------------------


class FakeStructure:
    """Stands in for a ChimeraX model.

    A plain class, deliberately: `SimpleNamespace` cannot be weakly referenced,
    so using one here would exercise the fallback path in `_model_token` and
    quietly assert nothing. ChimeraX's AtomicStructure is an ordinary class.
    """

    def __init__(self, name):
        self.name = name


def _ref_with_handle(handle, model_id="#1"):
    """A ModelRef-alike whose `handle` is the object the recipe weakly holds."""
    return SimpleNamespace(model_id=model_id, name="fake", atomspec=model_id,
                           chains=(), handle=handle)


def test_a_closed_structure_drops_its_commands(session):
    """The bug: a report on one structure listing another structure's analysis.

    Model IDs are reused — close #1, open something else, and it is #1 too —
    so a flat per-session recipe carried the previous analysis forward. A 1ACB
    report came out listing nine commands from a predicted barnase-barstar
    complex, naming a PAE file and a ΔΔG file describing neither of its
    chains, under the sentence "the complete command recipe ... reproduces
    every value reported here". Replaying it would have failed at once.
    """
    import gc

    handle = FakeStructure("first structure")
    commands._record(session, "molcompose characterise A D model #1",
                     _ref_with_handle(handle))
    commands._record(session, "molcompose ipsae pae.json model #1",
                     _ref_with_handle(handle))
    assert len(recipe(session)) == 2

    del handle
    gc.collect()
    assert recipe(session) == []


def test_a_second_analysis_keeps_only_its_own(session):
    import gc

    first = FakeStructure("closed later")
    second = FakeStructure("still open")
    commands._record(session, "molcompose dockq #2 model #1", _ref_with_handle(first))
    commands._record(session, "molcompose characterise E I model #1",
                     _ref_with_handle(second))

    del first
    gc.collect()
    assert recipe(session) == ["molcompose characterise E I model #1"]


def test_a_command_with_no_structure_survives():
    """Session-level lines belong to the session, not to any one structure."""
    plain = SimpleNamespace(logger=FakeLogger())
    commands._record(plain, "molcompose reset", None)
    assert recipe(plain) == ["molcompose reset"]


def test_a_handle_that_cannot_be_weakly_referenced_is_kept(session):
    """Test doubles and slotted objects must not silently lose their lines."""
    commands._record(session, "molcompose confidence model #1",
                     _ref_with_handle(object()))
    assert recipe(session) == ["molcompose confidence model #1"]


def test_the_source_attribution_survives_pruning(session):
    import gc

    kept = FakeStructure("open")
    gone = FakeStructure("closed")
    with commands.recording_source(session, "agent"):
        commands._record(session, "molcompose characterise A D model #1",
                         _ref_with_handle(gone))
        commands._record(session, "molcompose confidence model #1",
                         _ref_with_handle(kept))
    del gone
    gc.collect()
    log = commands.recipe_log(session)
    assert [entry["command"] for entry in log] == ["molcompose confidence model #1"]
    assert log[0]["source"] == "agent"


def test_a_closed_structure_drops_its_commands_before_gc_runs(session):
    """Collection is not prompt enough to rely on, and the report cannot wait.

    ChimeraX models sit in reference cycles, so `close all` leaves the object
    alive until the cycle collector next runs. Testing liveness by the weak
    reference alone therefore passed under an explicit `gc.collect()` and
    failed in ChimeraX, where the stale commands reached a real report.
    """
    handle = FakeStructure("closed but not yet collected")
    session.models = SimpleNamespace(list=lambda: [handle])
    commands._record(session, "molcompose characterise A D model #1",
                     _ref_with_handle(handle))
    assert recipe(session) == ["molcompose characterise A D model #1"]

    # Closed: gone from the model list, but still referenced by `handle`.
    session.models = SimpleNamespace(list=lambda: [])
    assert recipe(session) == []


def test_a_session_that_cannot_list_models_keeps_everything(session):
    """Never drop a line because liveness could not be established."""
    handle = FakeStructure("unknowable")
    commands._record(session, "molcompose confidence model #1",
                     _ref_with_handle(handle))
    assert recipe(session) == ["molcompose confidence model #1"]


# -- cached analyses do not outlive their structure ---------------------------


def test_a_reused_model_id_does_not_inherit_the_previous_analysis(monkeypatch):
    """The bug: `confidence` reporting an interface the structure does not have.

    ChimeraX reuses model IDs — close #1, open something else, and it is #1
    again — so everything MolCompose caches under an ID outlived its subject.
    `characterise A B` on one complex, `close all`, a different structure, and
    `confidence` reported "32 contact pairs, ipLDDT 98.2, pDockQ 0.335" for a
    structure with one protein chain and no interface. Commands that
    re-resolve chains failed honestly; the ones reading the cache did not.
    """
    session = SimpleNamespace(logger=FakeLogger())
    first = FakeStructure("first complex")
    first.id_string = "1"
    state = state_for(session)

    commands.resolve_model(session, first)
    state.interfaces["#1"] = "the first structure's interface"
    state.interface_params["#1"] = (("A",), ("B",), "heavy", 4.5)
    state.interactions["#1"] = ("a salt bridge",)
    state.ddg["#1"] = ("some effects",)

    # A different structure, opened into the same ID.
    second = FakeStructure("second complex")
    second.id_string = "1"
    commands.resolve_model(session, second)

    assert state.interfaces == {}
    assert state.interface_params == {}
    assert state.interactions == {}
    assert state.ddg == {}


def test_the_same_structure_keeps_its_analysis():
    """Invalidation must not fire on every command, only on a real change."""
    session = SimpleNamespace(logger=FakeLogger())
    model = FakeStructure("one complex")
    model.id_string = "1"
    state = state_for(session)

    commands.resolve_model(session, model)
    state.interfaces["#1"] = "an interface"
    commands.resolve_model(session, model)
    commands.resolve_model(session, model)

    assert state.interfaces == {"#1": "an interface"}


def test_a_second_model_does_not_disturb_the_first():
    session = SimpleNamespace(logger=FakeLogger())
    one, two = FakeStructure("one"), FakeStructure("two")
    one.id_string, two.id_string = "1", "2"
    state = state_for(session)

    commands.resolve_model(session, one)
    state.interfaces["#1"] = "first"
    commands.resolve_model(session, two)
    state.interfaces["#2"] = "second"
    commands.resolve_model(session, one)

    assert state.interfaces == {"#1": "first", "#2": "second"}


def test_blocks_are_dropped_with_the_structure_that_defined_them():
    """The panel reads them through resolve_model for exactly this reason.

    ChimeraX reuses model ids, so blocks defined on one structure were still
    in state under "#1" after `close all` and a fresh open — and the panel's
    first version of the block rows read state directly by id, so it showed
    the previous structure's residue counts for the new one.
    """
    session = SimpleNamespace(logger=FakeLogger())
    first = FakeStructure("first")
    first.id_string = "1"
    state = state_for(session)

    commands.resolve_model(session, first)
    state.blocks["#1"] = ("four blocks from the first structure",)

    second = FakeStructure("second")
    second.id_string = "1"
    commands.resolve_model(session, second)
    assert state.blocks == {}


# -- the log echo follows the same rule as the recipe --------------------------


def test_only_the_outermost_command_is_echoed_to_the_log(session, monkeypatch):
    """One `characterise` used to put 55 raw commands in the ChimeraX log.

    ChimeraX echoes every command it runs, which is how a user sees what a
    tool did and learns the command to retype — worth having for a single
    `molcompose style`, and noise for anything that fans out into colours,
    pseudobonds and names. So the echo follows the recipe's rule: a command
    issued *by* another MolCompose command is internal.

    Note this cannot be observed from `--nogui` stdout, which echoes
    regardless; `log` controls the Log window.
    """
    logged = []
    monkeypatch.setattr(
        commands, "run",
        lambda s, command, log=True: logged.append((command, log)),
        raising=False,
    )

    import sys
    from types import ModuleType

    fake = ModuleType("chimerax.core.commands")
    fake.run = lambda s, command, log=True: logged.append((command, log))
    monkeypatch.setitem(sys.modules, "chimerax.core.commands", fake)

    commands._run(session, "color red")
    with commands._nested(session):
        commands._run(session, "color blue")
        with commands._nested(session):
            commands._run(session, "color green")
    commands._run(session, "color white")

    assert logged == [
        ("color red", True),
        ("color blue", False),
        ("color green", False),
        ("color white", True),
    ]


def test_the_same_command_on_a_new_structure_is_not_a_repeat(session):
    """ChimeraX reuses model ids, so identical text is not proof of a repeat.

    Close #1 and open something else and the new structure is #1 too, which
    makes its commands read exactly like the previous structure's. Deduping on
    the text alone suppressed the new structure's line, and `_live_entries`
    then dropped the old one as dead — so `characterise` followed by `report`
    produced a record claiming a complete recipe and carrying none.
    Reproducible in ChimeraX with close, reopen, characterise, report.
    """
    import gc

    first = FakeStructure("first structure")
    commands._record(session, "molcompose characterise A D model #1",
                     _ref_with_handle(first))
    # Same structure, same text: genuinely a repeat, and still one line.
    commands._record(session, "molcompose characterise A D model #1",
                     _ref_with_handle(first))
    assert len(recipe(session)) == 1

    second = FakeStructure("reopened, also #1")
    commands._record(session, "molcompose characterise A D model #1",
                     _ref_with_handle(second))
    assert len(recipe(session)) == 2

    # And when the first structure goes, its line goes with it — leaving the
    # new structure's, which is the whole point.
    del first
    gc.collect()
    assert len(recipe(session)) == 1


def test_a_deleted_structure_is_dropped_even_at_a_reused_address(session):
    """`id()` membership alone is not proof that a structure is still open.

    CPython reuses addresses, so a freed structure's recipe line can match a
    newly allocated object that happens to land where the old one was — and
    the closed structure's commands go into the next report, which is the
    exact failure `_live_entries` exists to prevent, arriving by a route it
    did not test for. ChimeraX marks a closed model `deleted`, so that is
    asked first.
    """
    class Deleted(FakeStructure):
        deleted = True

    handle = Deleted("closed, but still addressable")
    commands._record(session, "molcompose characterise A D model #1",
                     _ref_with_handle(handle))
    # Present in the model list by identity, and still dropped: being listed
    # is not the same as being alive.
    session.models = SimpleNamespace(list=lambda: [handle])
    assert recipe(session) == []
