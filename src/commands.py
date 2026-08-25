"""Canonical molcompose command family: validation, orchestration, and logging."""

import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from chimerax.core.errors import UserError

from .adapters.exporter import ExportOptions, export_figure
from .adapters.model_context import (
    CRITERIA,
    amino_chain_sequence,
    atom_points,
    backbone_atoms,
    buried_area,
    cbeta_and_plddt,
    delta_sasa,
    experimental_method,
    heavy_atoms_by_residue,
    interaction_atoms,
    list_protein_models,
    measure_residue_sasa,
    model_ref,
    plddt_values,
    residue_key,
    residue_sequences,
    sequential_index_map,
    structure_path,
    structure_stem,
)
from .adapters.renderer import (
    VIEW_PAD,
    build_reference_style_commands,
    compact_residue_spec,
    contact_commands,
    focus_commands,
    hbond_commands,
    interaction_commands,
    palette_spec,
    render_preset,
    reset_commands,
)
from .core.affinity import CONTACT_CUTOFF, predict_affinity
from .core.align import align_chains, relabel, residue_mapping
from .core.blocks import KINDS as BLOCK_KINDS
from .core.blocks import Block, block_name
from .core.blocks import clear_commands as clear_block_commands
from .core.blocks import define_commands as define_block_commands
from .core.coloring import assign, build_scale, group_by_color
from .core.confidence import build_report, interface_plddt, pdockq_score
from .core.ddg import (
    FORMATS as DDG_FORMATS,
)
from .core.ddg import (
    IDENTITY_THRESHOLD,
    detect_format,
    summarize_by_residue,
    verify_wild_types,
)
from .core.ddg import (
    load as load_ddg,
)
from .core.ddg import (
    restrict_to as restrict_ddg,
)
from .core.dockq import (
    CLASH_CUTOFF,
    FNAT_CUTOFF,
    INTERFACE_CUTOFF,
    MINIMUM_IDENTITY,
    apply_superposition,
    count_clashes,
    coverage_report,
    interface_coverage,
    interface_keys,
    matched_backbone,
    residue_contacts,
    superpose,
)
from .core.dockq import (
    evaluate as evaluate_dockq,
)
from .core.dockq import (
    rmsd as coord_rmsd,
)
from .core.interactions import (
    KINDS,
    InteractionParams,
    describe,
    detect_interactions,
    summarize,
)
from .core.interfaces import (
    DEFAULT_VDW_OVERLAP,
    InterfaceResult,
    detect_interface,
)
from .core.mmpbsa import (
    RESULTS_FILE,
    DecompositionError,
    parse_chain_map,
    remap,
    totals_beside,
    verify_residue_names,
)
from .core.mmpbsa import by_residue as mmpbsa_by_residue
from .core.mmpbsa import load as load_energies
from .core.mmpbsa import ranked as ranked_energies
from .core.pae import load_pae_matrix, pair_scores
from .core.prediction import assess, find_pae_file, find_summary_file
from .core.presets import BODY_GREY, NO_DATA, get_preset
from .core.report import FORMATS, ReportData, render
from .core.rmsf import FluctuationError
from .core.rmsf import by_residue as rmsf_by_residue
from .core.rmsf import load as load_rmsf
from .core.summary import parse as parse_summary
from .core.viewpoint import (
    cross,
    interface_axis,
    normalise,
    open_book,
    perpendicular,
    side_on,
)


@dataclass(frozen=True)
class RecipeEntry:
    """One command, with when it ran, how it entered the session, and on what.

    `model` is a weak reference to the structure the command acted on, or None
    for commands that act on no particular one. It is what lets a closed
    structure take its commands with it: see `_live_entries`.
    """

    command: str
    timestamp: str
    source: str  # "session" | "panel" | "agent"
    model: object = None  # weakref.ref to the ChimeraX model, or None


@dataclass
class MolComposeState:
    interfaces: dict[str, InterfaceResult] = field(default_factory=dict)
    interactions: dict[str, tuple] = field(default_factory=dict)
    ddg: dict[str, tuple] = field(default_factory=dict)
    # Per-residue end-point energies, already remapped onto the model's chains
    # and verified against its residue names.
    energies: dict[str, tuple] = field(default_factory=dict)
    # Which solvation model produced them, per model id: "MM/GBSA" or
    # "MM/PBSA". Stored because the two are different methods with different
    # names, and everything downstream said "MM/PBSA" for both — so a run
    # read under Generalized Born was labelled with the name of the other
    # method, on the colour key and in the hot-spot ranking.
    energy_method: dict[str, str] = field(default_factory=dict)
    # Per-residue RMS fluctuation in Å, keyed (chain, number).
    flexibility: dict[str, dict] = field(default_factory=dict)
    interface_params: dict[str, tuple[tuple[str, ...], tuple[str, ...], str, float]] = (
        field(default_factory=dict)
    )
    blocks: dict[str, tuple] = field(default_factory=dict)
    # Numbers a command computed, per model, so a view can show them without
    # having been the caller that ran it. The panel used to fill its result
    # tiles from each command's return value, which only the click that ran it
    # ever sees — so after an agent characterised a complex through MCP the
    # panel sat there with nine dashes beside a fully analysed structure.
    # Raw values, never formatted: how a number is displayed is the view's
    # business, and there is exactly one place that decides it.
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    # Contacting chain pairs found by `interface all`, per model. Kept so the
    # "detect an interface first" refusal can tell a user who has just surveyed
    # the structure that the survey deliberately chose nothing — the sequence
    # "interface all" then "buriedarea" otherwise answers a list of four
    # contacting pairs with "Detect an interface first".
    surveys: dict[str, tuple[tuple[str, str, int], ...]] = field(default_factory=dict)
    recipe: list[RecipeEntry] = field(default_factory=list)
    # Which structure each cache key currently belongs to, weakly held. Model
    # IDs are reused, so without this the caches above outlive their subject:
    # see `_drop_cache_from_another_structure`.
    owners: dict[str, object] = field(default_factory=dict)
    # Depth of nested command execution. A command run *by* another MolCompose
    # command must not add its own recipe line: the caller already recorded the
    # single command a user would type to reproduce the whole step.
    _nesting: int = 0
    # How commands are currently entering the session. The panel sets this while
    # handling a click so a report can distinguish a click from a typed command.
    source: str = "session"
    # A source declared by an out-of-process caller for its next command, and
    # consumed by the next `_record`. The agent bridge is the caller that needs
    # it: ChimeraX's REST control carries no identity, so before this existed
    # every agent command was recorded as "session" and the report's provenance
    # sentence said the user had issued them. See `cmd_source`.
    pending_source: str = ""


def state_for(session) -> MolComposeState:
    state = getattr(session, "_molcompose_state", None)
    if state is None:
        state = MolComposeState()
        session._molcompose_state = state
    elif type(state) is not MolComposeState:
        # The state lives on the session and outlives this module, so
        # reloading the bundle -- which ChimeraX does on its own, and which a
        # `toolshed reload` or an update mid-session does deliberately --
        # leaves an instance of the previous class behind. It looks fine until
        # a command reaches a field the old class never had, and then raises
        # AttributeError from somewhere deep inside, which is the worst shape
        # an error can take.
        #
        # Carrying the values across rather than starting empty, because the
        # interface the user detected before the reload is still true and
        # making them detect it again would be a silent, annoying loss.
        state = _migrated(state)
        session._molcompose_state = state
    return state


def _migrated(previous) -> MolComposeState:
    """A current state carrying whatever the previous one still has."""
    fresh = MolComposeState()
    for name in (f.name for f in fields(MolComposeState)):
        if hasattr(previous, name):
            setattr(fresh, name, getattr(previous, name))
    return fresh


def _run(session, command):
    """Run a ChimeraX command, echoing it only when it is the outermost one.

    ChimeraX logs every command it runs, which is how a user sees what a tool
    did on their behalf and how they learn the command to retype. That is
    worth having for a single `molcompose style`, and is noise for anything
    that fans out: one `molcompose characterise` issued 55 echoed lines —
    every colour, every pseudobond, every name — and buried its own findings
    among them.

    So the echo follows the same rule the recipe does. A command issued *by*
    another MolCompose command is internal; the caller already reported the
    one line a user would type, and the recipe already records it.
    """
    from chimerax.core.commands import run

    run(session, command, log=state_for(session)._nesting == 0)


def _record(session, command: str, ref=None) -> None:
    """Add one line to the reproducible command recipe.

    The recipe is what the manuscript claims makes an analysis replayable, so
    every command that produces a result or changes appearance records itself
    here — not only interface detection. Three rules keep it honest:

    - commands invoked *by* another MolCompose command are suppressed, so
      `characterise` contributes one line rather than the six it runs;
    - an identical consecutive line *on the same structure* is not repeated,
      so re-running a command to refresh a result does not inflate the
      record. The structure has to be part of that test: ChimeraX reuses
      model ids, so closing #1 and opening something else gives a second
      structure whose commands read identically. Comparing the text alone
      suppressed the new structure's line and then dropped the old one as
      dead, leaving a report that claimed a complete recipe and carried
      none — reproducible with close, reopen, characterise, report;
    - a line is tied to the structure it acted on, so closing that structure
      takes the line with it (`_live_entries`).
    """
    state = state_for(session)
    if state._nesting > 0:
        return
    token = _model_token(session, ref)
    if state.recipe:
        previous = state.recipe[-1]
        was = previous.model() if previous.model is not None else None
        now = token() if token is not None else None
        if previous.command == command and was is now:
            return
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    # A source declared by an out-of-process caller wins over the ambient one
    # and is consumed here, so it applies to exactly one recorded command. The
    # panel's `recording_source` block is not overridden: it sets `source`, and
    # nothing over the bridge is inside it.
    source = state.pending_source or state.source
    state.pending_source = ""
    state.recipe.append(RecipeEntry(command, stamp, source, token))


def _model_token(session, ref):
    """A weak reference to the model behind a ModelRef, when there is one.

    The reference is taken to the object the *session* holds, not to whatever
    wrapper this call happens to have been handed. `_live_entries` asks
    whether the target is still among the open models, so a line tied to a
    second wrapper of the same structure answers "no" the moment that wrapper
    is collected — while the structure is still open. The report then prints
    "The complete command recipe (0 commands) ... reproduces every value
    reported here" over a fully populated analysis, which is worse than a
    missing line: it is a false claim about reproducibility, in the record
    that exists to support one.

    Commands are handed their model by `AtomicStructureArg`, which resolves a
    C pointer to a Python instance; today that is the session's own object, so
    the lookup is a no-op. It is not a guarantee ChimeraX makes, and the
    failure it would cause is silent, so the canonical object is looked up
    rather than assumed.
    """
    handle = getattr(ref, "handle", None)
    if handle is None:
        return None
    try:
        return weakref.ref(_session_held_model(session, handle))
    except TypeError:  # a test double, or anything not weak-referenceable
        return None


def _session_held_model(session, handle):
    """The object `session.models` holds for `handle`'s structure, or `handle`.

    Matched on the underlying C++ structure, never on model ID: IDs are
    reused, so a stale wrapper and a freshly opened structure can share one.
    Resolving by ID would tie a line to whatever structure holds that ID next
    — the cross-structure leak `_live_entries` exists to prevent, reintroduced
    one layer down. The pointer is read here, at record time, while the
    structure is certainly open, so it is never compared against a freed one.
    """
    try:
        open_models = list(session.models.list())
    except AttributeError:  # a session double with no model list
        return handle
    if any(model is handle for model in open_models):
        return handle
    pointer = getattr(handle, "cpp_pointer", None)
    if pointer is None:
        return handle
    for model in open_models:
        if getattr(model, "cpp_pointer", None) == pointer:
            return model
    return handle


def _displayed_model(session):
    """Any open protein model, for commands that act on the view not a model.

    An export renders whatever is on screen rather than one structure, so it
    has no ModelRef of its own. Tying its recipe line to a structure that was
    open at the time means the line describes an image of that structure and
    leaves the record when the structure does.
    """
    try:
        models = list_protein_models(session)
    except AttributeError:  # a session double with no model list
        return None
    return models[0] if models else None


def _live_entries(session) -> list[RecipeEntry]:
    """Recipe entries whose structure is still open.

    Model IDs are reused: close #1 and open something else, and the new
    structure is #1 too. So a recipe kept as one flat list per session carried
    the previous analysis into the next report — a 1ACB report listing nine
    commands about a predicted barnase-barstar complex, naming a PAE file and
    a ΔΔG file that describe neither chain of it, under the sentence "the
    complete command recipe ... reproduces every value reported here". It did
    not: replaying it would have failed on the first `dockq`.

    Entries with no model (`molcompose reset` with no target, say) are kept:
    they belong to the session rather than to a structure.

    Liveness is membership in the session's model list, not merely a live weak
    reference. ChimeraX models sit in reference cycles, so a closed structure
    survives until the cycle collector next runs — long enough for the very
    report that must not contain it. The weak reference still earns its place:
    once the model *is* collected there is nothing left to compare.

    ChimeraX's own `deleted` flag is asked first where it exists. Membership
    was tested by `id()` alone, and CPython reuses addresses: a freed
    structure's recipe line can match a newly allocated object that happens to
    land at the same address, which puts the closed structure's commands back
    into the next report — the precise failure this function exists to
    prevent, arriving by a route it did not check. `deleted` answers the
    question directly rather than by proxy.
    """
    open_models = _open_model_ids(session)
    kept = []
    for entry in state_for(session).recipe:
        if entry.model is None:
            kept.append(entry)
            continue
        target = entry.model()
        if target is None or getattr(target, "deleted", False):
            continue
        if open_models is None or id(target) in open_models:
            kept.append(entry)
    return kept


def _open_model_ids(session):
    """Identities of the models currently open, or None if unknowable."""
    try:
        return {id(model) for model in session.models.list()}
    except AttributeError:  # a session double with no model list
        return None


def recipe_commands(session) -> tuple[str, ...]:
    """The recipe as replayable command strings."""
    return tuple(entry.command for entry in _live_entries(session))


def recipe_log(session) -> tuple[dict, ...]:
    """The recipe with timestamps and source attribution."""
    return tuple(
        {"command": entry.command, "timestamp": entry.timestamp, "source": entry.source}
        for entry in _live_entries(session)
    )


def remember_metric(session, ref, name: str, value) -> None:
    """Store one computed number against its model, for views to read back."""
    if value is None:
        return
    state_for(session).metrics.setdefault(ref.model_id, {})[name] = value


@contextmanager
def _nested(session):
    """Mark commands issued inside this block as internal to the caller."""
    state = state_for(session)
    state._nesting += 1
    try:
        yield
    finally:
        state._nesting -= 1


# Announced whenever a command changes something a view could be showing —
# an interface detected, a ΔΔG table loaded, a model reset. Anyone may listen;
# nobody has to.
#
# It exists because the panel had no way to learn about work it did not do
# itself. Its preset list is built from "is there an interface for this
# model", and it only ever rebuilt that on its own clicks — so `molcompose
# interface A D` typed at the command line, or run by an agent through MCP,
# left the panel showing the whole-structure presets and nothing else. The
# state was right and the view was stale, which is the worst version of this
# for a tool whose claim is that the panel, the command line and the agent are
# peers doing the same work.
STATE_CHANGED = "molcompose state changed"


def ensure_state_trigger(session):
    """Register the notification, once per session. Returns the trigger set."""
    triggers = getattr(session, "triggers", None)
    if triggers is None:  # a session double in the tests
        return None
    try:
        if not triggers.has_trigger(STATE_CHANGED):
            triggers.add_trigger(STATE_CHANGED)
    except (AttributeError, KeyError, ValueError):
        return None
    return triggers


def residue_keys_as_text(mapping: dict) -> dict[str, float]:
    """`{("A", 12): 1.83}` -> `{"A:12": 1.83}`.

    A command's return value is serialised by the REST bridge under
    `json true`. JSON has no tuple keys, and ChimeraX wedges on the attempt
    rather than raising: the session stops answering entirely, which reads as
    a hung analysis rather than as a bad return type. The export and report
    commands had the same shape when they returned Path.

    Session state keeps the tuple keys -- they are what the colouring and the
    sequence exporter index by, and they never leave the process.
    """
    return {f"{chain}:{number}": value for (chain, number), value in mapping.items()}


def notify_state_changed(session, model_id: str | None = None) -> None:
    """Tell listeners the session's MolCompose state moved.

    Deliberately unable to fail the command that sent it. A listener is a view
    refreshing itself; if one raises, the analysis that triggered it has
    already succeeded and must still return its result. The alternative — a
    broken panel handler turning a working `molcompose interface` into an
    error — trades a stale list for a lost analysis.
    """
    # Suppressed inside a nested command, the same rule the recipe follows:
    # `characterise` runs six analyses, and a view has no use for six refreshes
    # mid-sequence — the first would arrive when only the interface existed,
    # which is exactly how the result tiles came to be read before the buried
    # area and affinity behind them had been stored. The outermost command
    # notifies once, when the state is whole.
    if state_for(session)._nesting > 0:
        return
    triggers = ensure_state_trigger(session)
    if triggers is None:
        return
    try:
        triggers.activate_trigger(STATE_CHANGED, model_id)
    except Exception as error:  # noqa: BLE001 - a listener's failure is not ours
        logger = getattr(session, "logger", None)
        if logger is not None:
            logger.info(f"MolCompose: a view failed to refresh ({error})")


@contextmanager
def recording_source(session, source: str):
    """Attribute commands issued inside this block to `source` (e.g. "panel")."""
    state = state_for(session)
    previous = state.source
    state.source = source
    try:
        yield
    finally:
        state.source = previous


def cmd_source(session, name):
    """Declare who is about to issue the next command.

    In-process callers use `recording_source`, which is scoped by a `with`
    block. Nothing over the REST bridge can do that: ChimeraX's remote control
    cannot tell an agent from a script from the user's own curl, so a caller
    that knows who it is has to say so.

    One-shot on purpose — it applies to the next recorded command and then
    reverts. A sticky flag set by the agent bridge would attribute the user's
    later typing to the agent, and the failure mode here is the milder one: if
    the declared command errors, nothing is recorded and the declaration is
    still armed, so at worst one later command is over-attributed. Claiming an
    agent was involved when it was not is a much smaller problem than the
    reverse, which is what this exists to fix.
    """
    if not str(name).strip():
        raise UserError("a source name cannot be empty")
    state = state_for(session)
    state.pending_source = str(name).strip()
    return state.pending_source


# --- structured returns for out-of-process callers ------------------------
#
# Several commands answer with a frozen dataclass. In process that is the best
# possible answer: the panel and anything importing this module get a typed
# object with named fields. Over the REST bridge it is the worst one — the
# bridge's serialiser has no rule for our dataclasses, falls back to `str()`,
# and the caller receives `"AffinityResult(delta_g=-10.6, ...)"`, a Python
# repr they would have to parse back into data.
#
# ChimeraX's answer to this is `return_json`. A command whose signature has
# that keyword is handed it by the dispatcher, and returns a `JSONResult`
# carrying both forms: the bridge emits `json_value`, every in-process caller
# keeps receiving `python_value`. Nothing that calls these functions today
# passes `return_json`, so nothing that calls them today changes.


def _json_result(python_value, json_value, return_json: bool):
    """`python_value` as always, or both forms when the caller asked for JSON."""
    if not return_json:
        return python_value
    from chimerax.core.commands import JSONResult

    return JSONResult(json_value=json_value, python_value=python_value)


def _residue_json(key) -> dict:
    from dataclasses import asdict

    return asdict(key)


def _interface_json(result, chains_a=None, chains_b=None, criterion=None) -> dict:
    """An `InterfaceResult` as named values.

    The counts come first because they are what a caller usually wants, and
    what the MCP server used to recover by running a regular expression over
    the log line that reported them.
    """
    payload = {
        "cutoff": result.cutoff,
        "residues_a": len(result.group_a),
        "residues_b": len(result.group_b),
        "contact_pairs": len(result.contacts),
        "group_a": [_residue_json(key) for key in result.group_a],
        "group_b": [_residue_json(key) for key in result.group_b],
        "contacts": [
            {"a": _residue_json(pair.a), "b": _residue_json(pair.b)}
            for pair in result.contacts
        ],
    }
    if chains_a is not None:
        payload["chains_a"] = list(chains_a)
    if chains_b is not None:
        payload["chains_b"] = list(chains_b)
    if criterion is not None:
        payload["criterion"] = criterion
    return payload


def _model_suffix(ref) -> str:
    return f" model {ref.model_id}"


def parse_chain_group(text: str) -> tuple[str, ...]:
    raw_items = text.split(",")
    items = [item.strip() for item in raw_items]
    if any(item == "" for item in items) and len(items) > 1:
        raise UserError("chain groups must not contain empty chain IDs")
    items = [item for item in items if item]
    if not items:
        raise UserError("a chain group needs at least one chain ID")
    unique = []
    for item in items:
        if item not in unique:
            unique.append(item)
    return tuple(unique)


def resolve_model(session, model):
    resolved = _resolve(session, model)
    _drop_cache_from_another_structure(session, resolved)
    return resolved


def _resolve_reference_models(session, references, primary_id: str) -> tuple:
    """Resolve a comma-separated list of open model ids without changing state."""
    requested = parse_chain_group(str(references))
    requested = tuple(item if item.startswith("#") else f"#{item}" for item in requested)
    if primary_id in requested:
        raise UserError("the design model must not also be listed as a reference")
    available = {ref.model_id: ref.handle for ref in list_protein_models(session)}
    missing = [model_id for model_id in requested if model_id not in available]
    if missing:
        known = ", ".join(available) or "none"
        raise UserError(
            f"reference model(s) not open: {', '.join(missing)}; open models: {known}"
        )
    return tuple(available[model_id] for model_id in requested)


def _resolve(session, model):
    if model is not None:
        return model
    refs = list_protein_models(session)
    if len(refs) == 1:
        return refs[0].handle
    if not refs:
        raise UserError("No protein model is open; open a structure first")
    available = ", ".join(ref.model_id for ref in refs)
    raise UserError(
        f"Multiple protein models are open ({available}); choose one with the 'model' option"
    )


def _drop_cache_from_another_structure(session, model) -> None:
    """Forget cached analyses when a model ID starts meaning a different structure.

    Everything MolCompose remembers between commands — the detected interface,
    the typed interactions, the loaded ΔΔG, the chain groups — is keyed by
    model ID, and ChimeraX reuses those: close #1, open something else, and it
    is #1 again.

    So `molcompose characterise A B` on one complex, `close all`, then a
    different structure, and `molcompose confidence` reported the first one's
    interface as if it belonged to the second — "32 contact pairs, ipLDDT
    98.2, pDockQ 0.335" for a structure with a single protein chain and no
    interface at all. Commands that re-resolve chains (buriedarea, affinity,
    hotspots) failed honestly with "unknown protein chain(s)"; the ones
    reading the cache did not, and produced numbers instead.
    """
    state = state_for(session)
    model_id = f"#{getattr(model, 'id_string', '?')}"
    previous = state.owners.get(model_id)
    if previous is not None and previous() is model:
        return
    if previous is not None:
        for cache in (
            state.interfaces, state.interactions, state.ddg,
            state.interface_params, state.blocks, state.metrics, state.surveys,
        ):
            cache.pop(model_id, None)
    try:
        state.owners[model_id] = weakref.ref(model)
    except TypeError:  # a test double, or anything not weak-referenceable
        state.owners.pop(model_id, None)


def _detect_interface_missing(session, model_id: str) -> UserError:
    """The refusal, plus what to do about it when a survey has already run.

    `interface all` reports every contacting chain pair and deliberately makes
    none of them the active one, so "interface all" followed by "buriedarea"
    used to answer a list of four contacting pairs with "Detect an interface
    first" — technically true and reasonably infuriating.
    """
    base = (
        f"Detect an interface first with 'molcompose interface' for model {model_id}"
    )
    surveyed = state_for(session).surveys.get(model_id)
    if not surveyed:
        return UserError(base)
    pairs = ", ".join(f"{a}-{b}" for a, b, _count in surveyed)
    best = max(surveyed, key=lambda row: row[2])
    return UserError(
        f"{base}. 'interface all' found {len(surveyed)} contacting pair(s) "
        f"({pairs}) but does not choose one — name the pair you want, e.g. "
        f"'molcompose interface {best[0]} {best[1]}'"
    )


def _side_on_camera(model, preset, interface):
    """The camera basis a preset asks for, or None.

    Lives here rather than in the renderer because it needs coordinates and
    the renderer only ever sees atomspecs. Best-effort throughout: a preset
    that wants a fixed viewpoint but cannot be given one still draws, in
    whatever orientation the view is already in, which is what it did before
    this existed.
    """
    geometry = preset.geometry
    if interface is None or not (geometry.viewpoint or geometry.label_spread):
        return None
    try:
        points_a = [record.point for record in
                    interaction_atoms(model, interface.group_a)]
        points_b = [record.point for record in
                    interaction_atoms(model, interface.group_b)]
        if not points_a or not points_b:
            return None
        return side_on(points_a, points_b, points_a + points_b,
                       roll=geometry.viewpoint_roll)
    except (ValueError, AttributeError):
        return None


def _label_positions(model, interface):
    """Each interface residue's centroid, keyed the way the labels are.

    Lives beside `_side_on_camera` for the same reason: the renderer sees
    atomspecs and this needs coordinates. Without it the label fan is blind to
    two residues being close together on screen.
    """
    if interface is None:
        return {}
    positions: dict[tuple[str, int], tuple[float, float, float]] = {}
    try:
        for side in (interface.group_a, interface.group_b):
            for record in interaction_atoms(model, side):
                key = (record.key.chain_id, record.key.number)
                x, y, z = positions.get(key, (0.0, 0.0, 0.0))
                count = positions.setdefault(f"n{key}", 0) + 1
                positions[f"n{key}"] = count
                positions[key] = (x + record.point[0], y + record.point[1],
                                  z + record.point[2])
    except (ValueError, AttributeError):
        return {}
    return {
        key: tuple(value / positions[f"n{key}"] for value in total)
        for key, total in positions.items()
        if not isinstance(key, str)
    }


def cmd_style(
    session,
    preset,
    *,
    model=None,
    labels=None,
    rankBy="dsasa",
    references=None,
    align=None,
    partner=None,
):  # noqa: N803
    """Apply a preset, optionally overriding how many residues it labels.

    `labels` exists because the count was a property of the preset and nothing
    else — and presets were designed for different jobs. `paratope-closeup`
    labels two residues per side because two is what fits a tight close-up with
    its labels fanned apart; `licorice-chain` labels three. Put those two side
    by side in one plate, and the panel
    that happens to use the close-up shows fewer labels than its neighbour —
    a difference nobody chose, inherited from what each preset was originally
    for. `labels 0` turns them off; any count applies to each side.
    """
    rank_by = str(rankBy).lower()
    if rank_by not in HOTSPOT_METRICS:
        raise UserError(
            f"rankBy must be one of {', '.join(HOTSPOT_METRICS)}: {rankBy}"
        )

    model = resolve_model(session, model)
    try:
        preset_obj = get_preset(preset)
    except ValueError as error:
        raise UserError(str(error)) from error
    if labels is not None:
        if labels < 0:
            raise UserError("labels must be 0 or more")
        preset_obj = replace(
            preset_obj, geometry=replace(preset_obj.geometry, label_top=labels)
        )
    ref = model_ref(model)
    interface = None
    if preset_obj.requires_interface:
        interface = state_for(session).interfaces.get(ref.model_id)
        if interface is None:
            raise _detect_interface_missing(session, ref.model_id)
    if preset_obj.reference_comparison:
        if labels is not None or rank_by != "dsasa":
            raise UserError(
                "design-reference does not use labels or rankBy; its epitope "
                "comes from the detected interface"
            )
        if not references or not align or not partner:
            raise UserError(
                "design-reference needs references, align and partner, e.g. "
                "references #2,#3 align A partner B"
            )
        reference_models = _resolve_reference_models(session, references, ref.model_id)
        try:
            commands = build_reference_style_commands(
                ref,
                tuple(model_ref(item) for item in reference_models),
                preset_obj,
                interface,
                align_chain=str(align),
                partner_chain=str(partner),
            )
        except ValueError as error:
            raise UserError(str(error)) from error
        with _nested(session):
            for command in commands:
                _run(session, command)
        reference_text = ",".join(model_ref(item).model_id for item in reference_models)
        _record(
            session,
            f"molcompose style {preset_obj.slug}{_model_suffix(ref)} "
            f"references {reference_text} align {align} partner {partner}",
            ref,
        )
        session.logger.info(
            f"MolCompose applied preset {preset_obj.slug} v{preset_obj.version} "
            f"to {ref.model_id} with {len(reference_models)} reference structure(s)"
        )
        return commands
    if references is not None or align is not None or partner is not None:
        raise UserError(
            "references, align and partner are only used by the design-reference preset"
        )
    if preset_obj.confidence_coloring:
        method = experimental_method(model)
        if method:
            raise UserError(
                f"{ref.model_id} is an experimentally determined structure ({method}); "
                "its B-factors are temperature factors, not pLDDT. The "
                "predicted-structure preset applies only to predicted models."
            )
        try:
            confidence = build_report(plddt_values(model))
        except ValueError as error:
            raise UserError(str(error)) from error
        with _nested(session):
            commands = render_preset(
                session, ref, preset_obj, interface,
                runner=_run, confidence=confidence,
            )
        session.logger.info(
            f"MolCompose pLDDT scale detected: {confidence.scale} "
            f"(mean {confidence.normalized_mean:.1f}); "
            f"{len(confidence.low_confidence_keys())} low-confidence residues faded"
        )
    elif preset_obj.hotspot_emphasis:
        params = state_for(session).interface_params.get(ref.model_id)
        if params is None:
            raise _detect_interface_missing(session, ref.model_id)
        chains_a, chains_b, _criterion, _cutoff = params
        try:
            hotspots = delta_sasa(session, model, chains_a, chains_b)
        except ValueError as error:
            raise UserError(str(error)) from error
        if not hotspots:
            raise UserError(
                "no interface residue buries measurable surface, so there is "
                "nothing for this preset to grade"
            )
        with _nested(session):
            commands = render_preset(
                session, ref, preset_obj, interface, runner=_run, hotspots=hotspots
            )
        top = hotspots[0]
        session.logger.info(
            f"MolCompose graded {len(hotspots)} interface residues by buried area; "
            f"most buried: {top[1]} {top[0][0]}:{top[0][1]} ({top[4]:.0f} Å²)"
        )
    else:
        # A preset that limits its side chains needs the ranking to choose
        # them by, and so does one that frames on its top residues — the
        # close-up asks for no limit on side chains but still has to know
        # which few to point the camera at. Asking only about `stick_top`
        # left the close-up framing the whole pair, which makes it an
        # overview drawn with thin sticks.
        #
        # Best-effort: without buried areas it draws them all and frames the
        # pair, which is what it did before either limit existed.
        #
        # The whole ranking is fetched, not the top few. Both limits are
        # counted per side, and a ranking truncated to N globally can hold
        # fewer than N of one chain — which is the starvation the per-side
        # selection exists to prevent, reintroduced one level up. `top 0` is
        # every residue above the area threshold; the renderer does the
        # cutting, where it knows which side each residue is on.
        # Which residues get sticks, frames and labels. It ranked by buried
        # area whatever the figure was coloured by, so a panel painted with
        # MM/PBSA could label the residues that bury the most surface and
        # leave the ones the colour calls strongest unnamed — on
        # barnase-barstar, Arg83 and Arg87 came out deep red and unlabelled
        # while Asp35 was named. The default is unchanged, because that is
        # what every existing figure was drawn with.
        hotspots = None
        if preset_obj.geometry.stick_top or preset_obj.geometry.frame_top:
            try:
                with _nested(session):
                    hotspots = cmd_hotspots(session, model=model, metric=rank_by)
            except UserError:
                hotspots = None
        camera = _side_on_camera(model, preset_obj, interface)
        with _nested(session):
            commands = render_preset(
                session, ref, preset_obj, interface, runner=_run,
                hotspots=hotspots, camera=camera,
                label_positions=_label_positions(model, interface),
            )
    _record(
        session,
        f"molcompose style {preset_obj.slug}{_model_suffix(ref)}"
        + (f" labels {labels}" if labels is not None else "")
        + (f" rankBy {rank_by}" if rank_by != "dsasa" else ""),
        ref,
    )
    session.logger.info(
        f"MolCompose applied preset {preset_obj.slug} v{preset_obj.version} to {ref.model_id}"
    )
    return commands


def cmd_interface(
    session, group_a, group_b, *, model=None, distance=4.5, criterion="heavy",
    return_json=False,
):
    model = resolve_model(session, model)
    chains_a = parse_chain_group(group_a)
    chains_b = parse_chain_group(group_b)
    overlap = sorted(set(chains_a) & set(chains_b))
    if overlap:
        raise UserError(
            f"Group A and Group B must not overlap (shared: {', '.join(overlap)})"
        )
    if criterion not in CRITERIA:
        raise UserError(
            f"interface criterion must be one of {', '.join(CRITERIA)}: {criterion}"
        )
    # Under `vdw` the number is an overlap in angstroms, normally negative,
    # not a distance. Callers that leave `distance` at its 4.5 default would
    # otherwise be asking for 4.5 A of interpenetration, which nothing meets.
    if criterion == "vdw" and distance == 4.5:
        distance = DEFAULT_VDW_OVERLAP
    try:
        points_a = atom_points(model, chains_a, criterion)
        points_b = atom_points(model, chains_b, criterion)
        result = detect_interface(
            points_a, points_b, cutoff=distance, criterion=criterion
        )
    except ValueError as error:
        raise UserError(str(error)) from error
    ref = model_ref(model)
    state = state_for(session)
    state.interfaces[ref.model_id] = result
    state.interface_params[ref.model_id] = (chains_a, chains_b, criterion, distance)
    # Buried area, ΔG, DockQ and the PAE scores were all computed against the
    # previous interface. Keeping them would let the panel show a number for a
    # cutoff nobody asked for, so re-detection clears them and the tiles read
    # "—" until they are recomputed — which is the truth.
    state.metrics.pop(ref.model_id, None)
    _define_blocks(session, ref, result, chains_a, chains_b)
    # The criterion is recorded even when it is today's default, as the
    # distance already was: writing one default and omitting the other was
    # arbitrary. A recipe exists so a published figure can be replayed on a
    # later version, and this default is the one argument the project has
    # actually discussed changing (heavy atoms at 4.5 A versus C-beta at
    # 8 A). A recipe that omits it replays silently differently the day it
    # moves; one that states it replays the figure that was published. The
    # other two recording sites below do the same, for the same reason.
    _record(
        session,
        f"molcompose interface {','.join(chains_a)} {','.join(chains_b)}"
        f"{_model_suffix(ref)} distance {distance:g}"
        + f" criterion {criterion}",
        ref,
    )
    session.logger.info(
        f"MolCompose interface {ref.model_id} "
        f"A=({','.join(chains_a)}) B=({','.join(chains_b)}) "
        f"cutoff {distance} Å criterion {criterion} — "
        f"Group A: {len(result.group_a)} residues, "
        f"Group B: {len(result.group_b)} residues, "
        f"{len(result.contacts)} contact pairs"
    )
    notify_state_changed(session, ref.model_id)
    return _json_result(
        result,
        _interface_json(result, chains_a, chains_b, criterion),
        return_json,
    )


def cmd_interface_all(
    session, *, model=None, distance=4.5, criterion="heavy", return_json=False
):
    from itertools import combinations

    model = resolve_model(session, model)
    if criterion not in CRITERIA:
        raise UserError(
            f"interface criterion must be one of {', '.join(CRITERIA)}: {criterion}"
        )
    ref = model_ref(model)
    records = []
    for chain_a, chain_b in combinations([chain.chain_id for chain in ref.chains], 2):
        try:
            points_a = atom_points(model, (chain_a,), criterion)
            points_b = atom_points(model, (chain_b,), criterion)
            result = detect_interface(
            points_a, points_b, cutoff=distance, criterion=criterion
        )
        except ValueError as error:
            raise UserError(str(error)) from error
        if result.contacts:
            records.append((chain_a, chain_b, result))
            session.logger.info(
                f"MolCompose interface {ref.model_id} {chain_a}-{chain_b}: "
                f"{len(result.contacts)} contact pairs at {distance} Å"
            )
    if not records:
        session.logger.info(
            f"MolCompose interface {ref.model_id}: no contacting chain pairs at {distance} Å"
        )
    # A survey, not a choice. Storing the pairs does not make any of them the
    # active interface — deciding that for the user would silently replace an
    # interface they had set on purpose — but it does let the next command's
    # refusal say what was found and how to pick one.
    state_for(session).surveys[ref.model_id] = tuple(
        (chain_a, chain_b, len(result.contacts))
        for chain_a, chain_b, result in records
    )
    if records:
        best = max(records, key=lambda row: len(row[2].contacts))
        session.logger.info(
            f"  none of these is the active interface yet — choose one with "
            f"'molcompose interface {best[0]} {best[1]}' "
            f"(most contacts) before measuring or styling"
        )
    _record(
        session,
        f"molcompose interface all{_model_suffix(ref)} distance {distance:g}"
        + f" criterion {criterion}",
        ref,
    )
    records = tuple(records)
    return _json_result(
        records,
        [
            {
                "chain_a": chain_a,
                "chain_b": chain_b,
                **_interface_json(result, criterion=criterion),
            }
            for chain_a, chain_b, result in records
        ],
        return_json,
    )


FOCUS_TARGETS = ("model", "interface", "faceon", "openbook")


def cmd_focus(session, target="interface", *, model=None):
    if target not in FOCUS_TARGETS:
        raise UserError(
            f"focus target must be one of {', '.join(FOCUS_TARGETS)}: {target}"
        )
    if target in ("faceon", "openbook"):
        return _focus_geometric(session, target, model)
    model = resolve_model(session, model)
    ref = model_ref(model)
    interface = None
    if target == "interface":
        interface = state_for(session).interfaces.get(ref.model_id)
        if interface is None:
            raise _detect_interface_missing(session, ref.model_id)
    commands = focus_commands(ref, interface)
    for command in commands:
        _run(session, command)
    _record(session, f"molcompose focus {target}{_model_suffix(ref)}", ref)
    session.logger.info(f"MolCompose focused view on {target} for {ref.model_id}")
    return commands


def cmd_export(
    session,
    path,
    *,
    width=2400,
    height=1800,
    supersample=3,
    transparent=False,
    saveSession=False,  # noqa: N803 - matches the ChimeraX command keyword
    overwrite=False,
    dpi=300,
    saveRecipe=False,  # noqa: N803 - matches the ChimeraX command keyword
    keyFontSize=None,  # noqa: N803 - matches the ChimeraX command keyword
):
    try:
        options = ExportOptions(
            Path(path),
            width=width,
            height=height,
            supersample=supersample,
            transparent=transparent,
            save_session=saveSession,
            overwrite=overwrite,
            dpi=dpi,
            save_recipe=saveRecipe,
            key_font_size=keyFontSize,
        )
        # The recipe is read before the export records its own line, so the
        # sidecar describes the analysis that produced the figure rather than
        # ending with the export of itself.
        image_path, session_path, commands, recipe_path = export_figure(
            session, options, runner=_run, recipe=recipe_commands(session)
        )
    except (ValueError, FileExistsError, OSError) as error:
        raise UserError(str(error)) from error
    for command in commands:
        session.logger.info(f"MolCompose export: {command}")
    if recipe_path is not None:
        session.logger.info(f"MolCompose recipe: {recipe_path}")
    _record(
        session,
        f"molcompose export {options.path} width {width:g} height {height:g} "
        f"supersample {supersample:g} transparent {str(transparent).lower()} "
        f"saveSession {str(saveSession).lower()}"
        + (f" keyFontSize {keyFontSize:g}" if keyFontSize is not None else ""),
        _displayed_model(session),
    )
    # Strings, not Paths — see cmd_report. Returning Path objects here killed
    # the ChimeraX process whenever an agent exported a figure over REST: the
    # image was written, then serialising the return value crashed the bridge,
    # so the provenance record the export exists to produce was lost.
    return (
        str(image_path),
        (str(session_path) if session_path else None),
        commands,
        (str(recipe_path) if recipe_path else None),
    )


def cmd_hbonds(session, *, model=None, off=False):
    model = resolve_model(session, model)
    ref = model_ref(model)
    if off:
        commands = hbond_commands(None, off=True)
        for command in commands:
            _run(session, command)
        _record(session, f"molcompose hbonds{_model_suffix(ref)} off true", ref)
        session.logger.info(f"MolCompose cleared hydrogen bonds for {ref.model_id}")
        return commands
    interface = state_for(session).interfaces.get(ref.model_id)
    if interface is None:
        raise _detect_interface_missing(session, ref.model_id)
    commands = hbond_commands(interface)
    for command in commands:
        _run(session, command)
    _record(session, f"molcompose hbonds{_model_suffix(ref)}", ref)
    session.logger.info(
        f"MolCompose displayed interface hydrogen bonds for {ref.model_id} "
        f"(see the hbonds count above)"
    )
    return commands


def _read_pae_tokens(path) -> tuple[int | None, str | None]:
    """Rows in the PAE matrix, or the loader's reason for not producing one.

    Exactly one of the two is set. Keeping the failure separate from a missing
    count matters: "no matrix here" and "no count taken" would otherwise both
    arrive as None, and the first has to withdraw the metrics.
    """
    try:
        return int(load_pae_matrix(Path(path)).shape[0]), None
    except (ValueError, OSError) as error:
        return None, str(error)


def cmd_capabilities(  # noqa: N803
    session, *, model=None, predictor="generic", paeFile=None,  # noqa: N803
    summaryFile=None, return_json=False,  # noqa: N803
):
    """Report the structure's provenance and which metrics it supports."""
    model = resolve_model(session, model)
    ref = model_ref(model)
    method = experimental_method(model)
    values = plddt_values(model)
    scale = None
    bfactor_issue = None
    if values and not method:
        try:
            scale = build_report(values).scale
        except ValueError as error:
            scale = None
            bfactor_issue = str(error)
    pae = paeFile or find_pae_file(structure_path(model), predictor)
    summary = summaryFile or find_summary_file(structure_path(model), predictor)
    tokens, pae_error = _read_pae_tokens(pae) if pae and not method else (None, None)
    residues = len(amino_chain_sequence(model)) if tokens is not None else None
    # Keywords, not position: `assess` gained `summary_file` between
    # `pae_file` and `pae_tokens`, and a positional call would have slid the
    # token count into it and every argument after it one place along —
    # silently, since they are all optional and most are None.
    caps = assess(
        method,
        bool(values) and scale is not None,
        plddt_scale=scale,
        pae_file=pae,
        summary_file=summary,
        pae_tokens=tokens,
        residue_count=residues,
        pae_error=pae_error,
        bfactor_issue=bfactor_issue,
    )

    session.logger.info(
        f"MolCompose capabilities {ref.model_id} ({ref.name}): {caps.kind}"
        + (f" — {caps.detail}" if caps.detail else "")
    )
    if caps.pae_file:
        session.logger.info(f"  PAE matrix found: {caps.pae_file}")
    if caps.summary_file:
        session.logger.info(f"  ipTM summary found: {caps.summary_file}")
    session.logger.info(f"  available: {', '.join(caps.available)}")
    for metric, reason in sorted(caps.unavailable.items()):
        session.logger.info(f"  unavailable — {metric}: {reason}")
    _record(session, f"molcompose capabilities{_model_suffix(ref)}", ref)
    from dataclasses import asdict

    return _json_result(caps, asdict(caps), return_json)


# pDockQ's published interface: Cβ–Cβ within 8 Å, Cα for glycine.
PDOCKQ_CRITERION, PDOCKQ_CUTOFF = "cbeta", 8.0


def _canonical_pdockq(session, model, ref, report, interface):
    """pDockQ over the interface its own definition names, not the shown one.

    Best-effort: if the chains cannot be re-measured for any reason the metric
    is simply absent, which is better than quietly reporting one computed at a
    different cutoff under the same name.
    """
    params = state_for(session).interface_params.get(ref.model_id)
    if params is None:
        return None
    chains_a, chains_b, criterion, cutoff = params
    if (criterion, float(cutoff)) == (PDOCKQ_CRITERION, PDOCKQ_CUTOFF):
        # Already the right definition; no need to measure it twice.
        keys = tuple(interface.group_a) + tuple(interface.group_b)
        value = interface_plddt(report, keys)
        return (pdockq_score(value, len(interface.contacts))
                if value is not None else None)
    try:
        canonical = detect_interface(
            atom_points(model, chains_a, PDOCKQ_CRITERION),
            atom_points(model, chains_b, PDOCKQ_CRITERION),
            cutoff=PDOCKQ_CUTOFF,
            criterion=PDOCKQ_CRITERION,
        )
    except (ValueError, KeyError):
        return None
    keys = tuple(canonical.group_a) + tuple(canonical.group_b)
    value = interface_plddt(report, keys)
    if value is None or not canonical.contacts:
        return None
    return pdockq_score(value, len(canonical.contacts))


def cmd_confidence(session, *, model=None):
    """Report prediction-confidence metrics computable from the structure file."""
    model = resolve_model(session, model)
    ref = model_ref(model)
    method = experimental_method(model)
    if method:
        raise UserError(
            f"{ref.model_id} is an experimentally determined structure ({method}); "
            "its B-factors are temperature factors, not pLDDT confidence values. "
            "Confidence metrics apply only to predicted models."
        )
    try:
        report = build_report(plddt_values(model))
    except ValueError as error:
        raise UserError(str(error)) from error
    metrics = {
        "scale": report.scale,
        "mean_plddt": report.normalized_mean,
        "iplddt": None,
        "contact_pairs": None,
        "pdockq": None,
    }
    lines = [
        f"MolCompose confidence for {ref.model_id}: "
        f"pLDDT scale {report.scale}, mean pLDDT {report.normalized_mean:.1f}"
    ]
    interface = state_for(session).interfaces.get(ref.model_id)
    if interface is not None:
        keys = tuple(interface.group_a) + tuple(interface.group_b)
        iplddt = interface_plddt(report, keys)
        contact_pairs = len(interface.contacts)
        metrics["iplddt"] = iplddt
        metrics["contact_pairs"] = contact_pairs
        # pDockQ is computed at *its own* definition — Cβ at 8 Å — rather than
        # over whatever interface happens to be detected, the way `affinity`
        # already fixes its own 5.5 Å heavy-atom contacts. Inheriting the
        # displayed interface made the number depend on a cutoff chosen for
        # looking at figures: on the 4.5 Å heavy-atom default this model read
        # 0.443 where the published definition gives 0.521. A metric named
        # after a paper should be the number that paper defines, and the panel
        # should not have to be re-detected to get it.
        canonical = _canonical_pdockq(session, model, ref, report, interface)
        if canonical is not None:
            metrics["pdockq"] = canonical
        if iplddt is not None:
            lines.append(
                f"  interface ({contact_pairs} contact pairs at "
                f"{interface.cutoff:g} Å): ipLDDT {iplddt:.1f}"
                + (f", pDockQ {metrics['pdockq']:.3f} (Cβ 8.0 Å, as defined)"
                   if metrics.get("pdockq") is not None else "")
            )
    else:
        lines.append(
            "  no detected interface — run 'molcompose interface' "
            "(criterion cbeta, 8.0 Å) for ipLDDT and pDockQ"
        )
    # Was "(planned)", which stopped being true once the summary parser landed:
    # seven of the eight engines' ipTM is read, four of them per chain pair.
    # "iPAE" appeared in that line and nowhere else in the codebase, so it
    # promised a metric that was never designed, let alone planned.
    lines.append(
        "  ipTM and pTM come from the prediction's summary file — run "
        "'molcompose ipsae <pae-file>', which reports them per chain pair "
        "where the engine provides them and whole-complex where it does not"
    )
    for line in lines:
        session.logger.info(line)
    _record(session, f"molcompose confidence{_model_suffix(ref)}", ref)
    remember_metric(session, ref, "plddt", metrics.get("mean_plddt"))
    remember_metric(session, ref, "iplddt", metrics.get("iplddt"))
    remember_metric(session, ref, "pdockq", metrics.get("pdockq"))
    notify_state_changed(session, ref.model_id)
    return metrics


def _parse_chain_map(text: str | None) -> dict[str, str]:
    """`A:C,B:D` -> {model chain: reference chain}."""
    if not text:
        return {}
    mapping = {}
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise UserError(f"chain map entries must look like modelChain:refChain: {item}")
        model_chain, reference_chain = (part.strip() for part in item.split(":", 1))
        if not model_chain or not reference_chain:
            raise UserError(f"chain map entries must look like modelChain:refChain: {item}")
        mapping[model_chain] = reference_chain
    return mapping


def _align_to_reference(model, ref_model, chain_pairs, model_id, reference_id):
    """Residue-key mapping from the model into the reference's key space.

    Built from a per-chain sequence alignment rather than from residue numbers,
    because the two structures need not share a numbering convention — see
    `core/align.py`. Returns (mapping, alignments) so the caller can report what
    the alignment found.
    """
    model_chains = [model_chain for model_chain, _ in chain_pairs]
    reference_chains = [reference_chain for _, reference_chain in chain_pairs]
    model_sequences = residue_sequences(model, model_chains)
    reference_sequences = residue_sequences(ref_model, reference_chains)
    alignments = align_chains(model_sequences, reference_sequences, chain_pairs)
    if not alignments:
        raise UserError(
            f"no chain of {model_id} could be aligned to {reference_id}; "
            f"checked {', '.join(f'{m}->{r}' for m, r in chain_pairs)}"
        )

    unrelated = [
        alignment for alignment in alignments if alignment.identity < MINIMUM_IDENTITY
    ]
    if unrelated:
        detail = "; ".join(
            f"model chain {alignment.model_chain} vs reference chain "
            f"{alignment.reference_chain}: {alignment.identity:.0%} identity over "
            f"{alignment.aligned} aligned residues"
            for alignment in unrelated
        )
        raise UserError(
            f"these chains are not the same protein, so DockQ would be meaningless "
            f"({detail}); pair the chains explicitly with chainMap"
        )
    return residue_mapping(alignments), alignments


def cmd_dockq(session, reference, *, model=None, chainMap=None, return_json=False):  # noqa: N803
    """DockQ and CAPRI components of a predicted complex against a reference."""
    model = resolve_model(session, model)
    ref_model = reference
    model_ref_info = model_ref(model)
    reference_info = model_ref(ref_model)
    if model_ref_info.model_id == reference_info.model_id:
        raise UserError("the model and the reference must be different structures")

    params = state_for(session).interface_params.get(model_ref_info.model_id)
    if params is None:
        raise _detect_interface_missing(session, model_ref_info.model_id)
    chains_a, chains_b, _criterion, _cutoff = params
    mapping = _parse_chain_map(chainMap)
    ref_chains_a = [mapping.get(chain, chain) for chain in chains_a]
    ref_chains_b = [mapping.get(chain, chain) for chain in chains_b]

    chain_pairs = tuple(
        zip(list(chains_a) + list(chains_b), ref_chains_a + ref_chains_b, strict=True)
    )
    key_map, alignments = _align_to_reference(
        model, ref_model, chain_pairs, model_ref_info.model_id, reference_info.model_id
    )

    try:
        # Heavy atoms for contacts (Fnat), backbone for the RMSD terms. The model's
        # residues are relabelled into the reference's key space by the alignment,
        # so every comparison below pairs residues that genuinely correspond.
        model_heavy_a = relabel(heavy_atoms_by_residue(model, chains_a), key_map)
        model_heavy_b = relabel(heavy_atoms_by_residue(model, chains_b), key_map)
        ref_heavy_a = heavy_atoms_by_residue(ref_model, ref_chains_a)
        ref_heavy_b = heavy_atoms_by_residue(ref_model, ref_chains_b)
        if not ref_heavy_a or not ref_heavy_b:
            # Name only the group that is actually empty. Predictors disagree on
            # chain naming — Protenix emits A/B where AF3 and Boltz-2 emit A/D —
            # so this is the routine way a run goes wrong, and the message has to
            # say which side to map rather than implicate both.
            missing = (ref_chains_a if not ref_heavy_a else []) + (
                ref_chains_b if not ref_heavy_b else []
            )
            raise ValueError(
                f"the reference {reference_info.model_id} has no protein residues in "
                f"chain(s) {','.join(missing)}; give the model-to-reference chain "
                f"correspondence with chainMap, e.g. chainMap "
                f"{','.join(f'{m}:{r}' for m, r in chain_pairs)}"
            )

        native = residue_contacts(ref_heavy_a, ref_heavy_b, FNAT_CUTOFF)
        modelled = residue_contacts(model_heavy_a, model_heavy_b, FNAT_CUTOFF)
        fnat, fnonnat, native_count, shared = _fnat(native, modelled)

        # iRMSD over reference interface residues (10 Å definition).
        keys_a, keys_b = interface_keys(ref_heavy_a, ref_heavy_b, INTERFACE_CUTOFF)
        ref_backbone = {
            **backbone_atoms(ref_model, ref_chains_a),
            **backbone_atoms(ref_model, ref_chains_b),
        }
        model_backbone = {
            **relabel(backbone_atoms(model, chains_a), key_map),
            **relabel(backbone_atoms(model, chains_b), key_map),
        }
        coverage = interface_coverage(keys_a | keys_b, model_backbone)
        if not coverage.is_scorable:
            raise UserError(
                f"refusing to score: only {coverage_report(coverage)}, too few for "
                f"DockQ to describe the model rather than the mapping. The chains "
                f"aligned, so check that the right chains were paired (chainMap) and "
                f"that the reference covers the modelled construct."
            )
        mobile, target = matched_backbone(ref_backbone, model_backbone, keys_a | keys_b)
        irmsd = _superposed(mobile, target)

        # LRMSD: superpose on the larger group, measure the smaller one.
        receptor_keys, ligand_keys = (
            (set(ref_heavy_a), set(ref_heavy_b))
            if len(ref_heavy_a) >= len(ref_heavy_b)
            else (set(ref_heavy_b), set(ref_heavy_a))
        )
        receptor_mobile, receptor_target = matched_backbone(
            ref_backbone, model_backbone, receptor_keys
        )
        rotation, mobile_centre, target_centre = superpose(receptor_mobile, receptor_target)
        ligand_mobile, ligand_target = matched_backbone(
            ref_backbone, model_backbone, ligand_keys
        )
        lrmsd = coord_rmsd(
            apply_superposition(ligand_mobile, rotation, mobile_centre, target_centre),
            ligand_target,
        )
        result = evaluate_dockq(
            fnat, fnonnat, irmsd, lrmsd, native_count, shared, len(keys_a | keys_b),
            clashes=count_clashes(model_heavy_a, model_heavy_b),
        )
    except ValueError as error:
        raise UserError(str(error)) from error

    session.logger.info(
        f"MolCompose DockQ {model_ref_info.model_id} vs {reference_info.model_id} "
        f"({','.join(chains_a)} ↔ {','.join(chains_b)}): "
        f"DockQ {result.dockq:.3f} ({result.capri_class})"
    )
    session.logger.info(
        f"  Fnat {result.fnat:.3f} ({result.shared_contacts}/{result.native_contacts} "
        f"reference contacts), Fnonnat {result.fnonnat:.3f}, "
        f"iRMSD {result.irmsd:.2f} Å, LRMSD {result.lrmsd:.2f} Å"
    )
    session.logger.info(
        f"  F1 {result.f1:.3f} (precision/recall over interface contacts), "
        f"{result.clashes} clashing residue pair(s) below {CLASH_CUTOFF:g} Å in the model"
    )
    session.logger.info(
        "  residues paired by sequence alignment, not by number: "
        + ", ".join(
            f"{alignment.model_chain}->{alignment.reference_chain} "
            f"{alignment.aligned} aligned, {alignment.identity:.0%} identity"
            for alignment in alignments
        )
    )
    # An incomplete mapping still scores, but the user has to be told the score
    # rests on part of the interface rather than all of it.
    if not coverage.is_complete:
        session.logger.warning(
            f"MolCompose DockQ: only {coverage_report(coverage)} — the score covers "
            f"that part of the interface only"
        )
    _record(
        session,
        f"molcompose dockq {reference_info.model_id}{_model_suffix(model_ref_info)}"
        + (f" chainMap {chainMap}" if chainMap else ""),
        model_ref_info,
    )
    remember_metric(session, model_ref_info, "dockq", result.dockq)
    # DockQ's own parts. One tile cannot carry six numbers, and CAPRI reports
    # quote them, so they travel to the view as the tile's detail rather than
    # living only in the Log.
    for name in ("fnat", "fnonnat", "irmsd", "lrmsd", "f1", "clashes"):
        remember_metric(session, model_ref_info, f"dockq_{name}",
                        getattr(result, name, None))
    state_for(session).metrics.setdefault(
        model_ref_info.model_id, {})["dockq_capri"] = result.capri_class
    notify_state_changed(session, model_ref_info.model_id)
    from dataclasses import asdict

    return _json_result(result, asdict(result), return_json)


def _fnat(native, modelled):
    from .core.dockq import fnat_scores

    return fnat_scores(native, modelled)


def _superposed(mobile, target):
    from .core.dockq import superposed_rmsd

    return superposed_rmsd(mobile, target)


def cmd_affinity(session, *, model=None, temperature=25.0, return_json=False):
    """Predicted binding free energy and Kd (PRODIGY IC-NIS model)."""
    model = resolve_model(session, model)
    ref = model_ref(model)
    interface = state_for(session).interfaces.get(ref.model_id)
    if interface is None:
        raise _detect_interface_missing(session, ref.model_id)

    chains_a = sorted({key.chain_id for key in interface.group_a})
    chains_b = sorted({key.chain_id for key in interface.group_b})
    if not chains_a or not chains_b:
        raise UserError("the detected interface has no contacting residues")
    try:
        # The model is defined at 5.5 Å heavy-atom contacts, independent of the
        # cutoff used for the stored interface.
        contacts = detect_interface(
            atom_points(model, chains_a),
            atom_points(model, chains_b),
            cutoff=CONTACT_CUTOFF,
        )
        pairs = [(pair.a.name, pair.b.name) for pair in contacts.contacts]
        sasa = measure_residue_sasa(session, model, chains_a + chains_b)
        result = predict_affinity(pairs, sasa, temperature)
    except ValueError as error:
        raise UserError(str(error)) from error

    session.logger.info(
        f"MolCompose affinity {ref.model_id} "
        f"({','.join(chains_a)} ↔ {','.join(chains_b)}, PRODIGY IC-NIS, "
        f"{CONTACT_CUTOFF:g} Å contacts, {temperature:g} °C): "
        f"ΔG {result.delta_g:.2f} kcal/mol, Kd {result.kd:.2e} M"
    )
    session.logger.info(
        f"  {result.contact_pairs} contacts — "
        + ", ".join(f"{name} {result.bins[name]}" for name in ("CC", "AC", "PP", "AP"))
        + f"; NIS apolar {result.nis_apolar:.1f}%, charged {result.nis_charged:.1f}%"
    )
    _record(
        session,
        f"molcompose affinity{_model_suffix(ref)}"
        + (f" temperature {temperature:g}" if temperature != 25.0 else ""),
        ref,
    )
    remember_metric(session, ref, "dg", result.delta_g)
    remember_metric(session, ref, "kd", result.kd)
    notify_state_changed(session, ref.model_id)
    from dataclasses import asdict

    return _json_result(result, asdict(result), return_json)


def _interaction_group_commands(session, ref) -> tuple[str, ...]:
    """`close` for each MolCompose pseudobond group belonging to this model.

    Named `mc-<kind>` when drawn, which is what identifies them among any
    other pseudobonds the session holds — ChimeraX's own hydrogen bonds and
    contacts are separate groups and are not touched here.
    """
    try:
        from chimerax.atomic import all_pseudobond_groups
    except ImportError:  # pragma: no cover - depends on the host ChimeraX
        return ()
    ids = []
    for group in all_pseudobond_groups(session):
        if not str(getattr(group, "name", "")).startswith("mc-"):
            continue
        spec = getattr(group, "atomspec", None) or f"#{group.id_string}"
        ids.append(spec)
    return tuple(f"close {spec}" for spec in sorted(set(ids)))


def cmd_interactions(
    session,
    *,
    model=None,
    types=None,
    off=False,
    saltBridge=4.0,  # noqa: N803 - ChimeraX keyword style
    hydrophobic=4.5,
    piStacking=5.5,  # noqa: N803
    cationPi=6.0,  # noqa: N803
    return_json=False,
):
    """Typed non-covalent interactions across the detected interface."""
    model = resolve_model(session, model)
    ref = model_ref(model)
    state = state_for(session)

    if off:
        # Close the pseudobond groups rather than deleting bond by bond. The
        # per-pair form asked ChimeraX to remove one specific pseudobond for
        # each interaction recorded, and any that was already gone — because a
        # preset hid it, because the interface was redetected, because the
        # button was pressed twice — aborted the run with "No pseudobond
        # between /A ALA 23 CB and /B TYR 83 CD2 found for mc-hydrophobic".
        # A hide that fails when there is less to hide than expected is the
        # wrong shape for a hide.
        #
        # `pbond delete` cannot take a group: it requires exactly two atoms.
        # The groups are submodels, so closing them by their model id removes
        # each whole, and a group that is already gone is simply not in the
        # list to close.
        state.interactions.pop(ref.model_id, ())
        commands = _interaction_group_commands(session, ref)
        for command in commands:
            _run(session, command)
        _record(session, f"molcompose interactions{_model_suffix(ref)} off true", ref)
        session.logger.info(f"MolCompose cleared interaction display for {ref.model_id}")
        return _json_result(commands, {"cleared": list(commands)}, return_json)

    interface = state.interfaces.get(ref.model_id)
    if interface is None:
        raise _detect_interface_missing(session, ref.model_id)
    kinds = KINDS if types is None else tuple(
        item.strip() for item in types.split(",") if item.strip()
    )
    params = InteractionParams(
        salt_bridge=saltBridge,
        hydrophobic=hydrophobic,
        pi_stacking=piStacking,
        cation_pi=cationPi,
    )
    try:
        atoms_a = interaction_atoms(model, interface.group_a)
        atoms_b = interaction_atoms(model, interface.group_b)
        found = detect_interactions(atoms_a, atoms_b, kinds, params)
    except ValueError as error:
        raise UserError(str(error)) from error

    state.interactions[ref.model_id] = found
    for command in interaction_commands(found):
        _run(session, command)

    counts = summarize(found)
    session.logger.info(
        f"MolCompose interactions {ref.model_id} "
        f"(salt-bridge {params.salt_bridge:g} Å, hydrophobic {params.hydrophobic:g} Å, "
        f"pi-stacking {params.pi_stacking:g} Å, cation-pi {params.cation_pi:g} Å): "
        + ", ".join(f"{kind} {counts[kind]}" for kind in kinds if kind in counts)
    )
    defaults = InteractionParams()
    _record(
        session,
        f"molcompose interactions{_model_suffix(ref)}"
        + (f" types {','.join(kinds)}" if types is not None else "")
        + (f" saltBridge {saltBridge:g}" if saltBridge != defaults.salt_bridge else "")
        + (f" hydrophobic {hydrophobic:g}" if hydrophobic != defaults.hydrophobic else "")
        + (f" piStacking {piStacking:g}" if piStacking != defaults.pi_stacking else "")
        + (f" cationPi {cationPi:g}" if cationPi != defaults.cation_pi else ""),
        ref,
    )
    # `summarize` and `describe` are what `characterise` already puts in its
    # summary, so the one-call and the individual paths report interactions in
    # the same shape rather than in two shapes that have to be reconciled.
    return _json_result(
        found, {"counts": counts, "items": describe(found)}, return_json
    )


def cmd_ipsae(session, path=None, *, model=None, paeCutoff=10.0, predictor="generic",  # noqa: N803
              summaryFile=None):  # noqa: N803
    """ipSAE interface scores (Dunbrack 2025) from a prediction's PAE file."""
    model = resolve_model(session, model)
    ref = model_ref(model)
    if path is None:
        # The tool can already locate the companion file for every supported
        # predictor layout, so requiring the user to type it was busywork —
        # and the person most likely to get it wrong is the one who just
        # unzipped a download and does not know what the file is called.
        path = find_pae_file(structure_path(model), predictor)
        if path is None:
            raise UserError(
                f"no PAE file found next to {ref.name}. Pass one explicitly, or "
                "check that the predictor's confidence file was kept alongside "
                "the structure — without it ipSAE, pDockQ2 and LIS cannot be "
                "computed."
            )
        session.logger.info(f"MolCompose using PAE file {Path(path).name}")
    try:
        matrix = load_pae_matrix(Path(path))
        coords, plddt = cbeta_and_plddt(model)
        scores = pair_scores(
            matrix, amino_chain_sequence(model), coords, plddt, paeCutoff
        )
    except ValueError as error:
        raise UserError(str(error)) from error
    session.logger.info(
        f"MolCompose interface scores for {ref.model_id} (PAE cutoff {paeCutoff:g}, "
        f"file {Path(path).name}):"
    )
    _attach_iptm(session, model, ref, scores, summaryFile)
    for pair, values in scores.items():
        # The two directions are named after the chains they actually describe.
        # They were hardcoded "A→B" and "B→A", which is right only when the
        # chains happen to be called A and B: an AlphaFold2-Multimer model
        # whose chains are B and C reported "B-C: ipSAE … (A→B …, B→A …)", so
        # the asymmetry — which is the whole reason ipSAE reports two numbers —
        # was attributed to chains that are not in the file.
        first, _, second = pair.partition("-")
        line = (
            f"  {pair}: ipSAE {values['max']:.4f} "
            f"({first}→{second} {values['asym_ab']:.4f}, "
            f"{second}→{first} {values['asym_ba']:.4f}), "
            f"pDockQ2 {values['pdockq2']:.4f}, LIS {values['lis']:.4f}"
        )
        if values.get("iptm") is not None:
            line += f", ipTM {values['iptm']:.4f}"
        elif values.get("iptm_global") is not None:
            line += (
                f", ipTM {values['iptm_global']:.4f} (whole complex — this "
                f"engine reports no per-chain-pair value)"
            )
        session.logger.info(line)
    _record(
        session,
        f"molcompose ipsae {path}{_model_suffix(ref)}"
        + (f" paeCutoff {paeCutoff:g}" if paeCutoff != 10.0 else ""),
        ref,
    )
    # The best-scoring pair, which is the one the panel's tiles show. Storing
    # every pair would need a view that can display them; storing the same one
    # the click path already chose keeps the two paths showing one number.
    if scores:
        best = max(scores.values(), key=lambda row: row.get("max") or 0.0)
        remember_metric(session, ref, "ipsae", best.get("max"))
        remember_metric(session, ref, "pdockq2", best.get("pdockq2"))
        remember_metric(session, ref, "iptm", best.get("iptm"))
        remember_metric(session, ref, "iptm_global", best.get("iptm_global"))
        remember_metric(session, ref, "lis", best.get("lis"))
    # Mean PAE over the off-diagonal: the matrix's own summary of how well the
    # model places any residue relative to any other. Computed here because the
    # matrix is already loaded and parsed — it was being read, used for ipSAE,
    # and thrown away.
    remember_metric(session, ref, "pae", _mean_offdiagonal(matrix))
    notify_state_changed(session, ref.model_id)
    return scores


def _mean_offdiagonal(matrix) -> float | None:
    """Mean PAE excluding the diagonal, which is zero by construction.

    Including it would divide by n² and drag every value towards zero by
    exactly the fraction of the matrix that is definitionally self-comparison —
    a 100-residue model's mean would read 1% low, a dimer's a little less. The
    number is small either way, which is what makes it worth doing correctly
    rather than approximately.
    """
    import numpy as np

    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[0] < 2:
        return None
    total = float(values.sum() - np.trace(values))
    count = values.shape[0] * values.shape[1] - values.shape[0]
    return total / count if count else None


def _attach_iptm(session, model, ref, scores: dict, summary_file=None) -> None:
    """Add ipTM to each chain pair, from the summary file beside the model.

    ipTM lives in a different file from the PAE matrix for four of the five
    engines, and two of them report only a whole-complex figure. That
    distinction is carried through rather than flattened: `iptm` is the value
    for this pair, `iptm_global` is a value for the entire model that happens
    to be all the engine offers. Reporting the second as though it were the
    first would overstate what is known about a particular interface.
    """
    try:
        source = structure_path(model)
        # An explicit file wins over the search. Discovery covers the engines
        # and the naming schemes this project knows; a run named some other
        # way had no way in at all, because nothing in the panel or the
        # command layer could say "the summary is this one".
        path = summary_file or find_summary_file(source)
        if path is None:
            return
        # The *structure's* stem, not the summary file's. AF2-Multimer's single
        # iptm_ptm.json is keyed by model name, and this passed `iptm_ptm` —
        # which matches no key, so the parser correctly refused and AF2 models
        # never got an ipTM at all. The refusal is what kept it invisible:
        # nothing was ever wrong in the output, a number was just missing.
        report = parse_summary(path, Path(source).stem if source else "")
    except (ValueError, OSError) as error:
        session.logger.info(f"MolCompose could not read the summary file: {error}")
        return

    if report.ptm is not None:
        remember_metric(session, ref, "ptm", report.ptm)
    order = [chain.chain_id for chain in ref.chains]
    session.logger.info(
        f"MolCompose using summary file {Path(path).name} "
        f"({report.engine}, {'per chain pair' if report.has_pairwise else 'whole complex only'})"
    )
    for pair, values in scores.items():
        left, _, right = pair.partition("-")
        if report.has_pairwise and left in order and right in order:
            value = report.pair(order.index(left), order.index(right))
            if value is not None:
                values["iptm"] = value
                continue
        if report.iptm is not None:
            values["iptm_global"] = report.iptm


def cmd_contacts(session, *, model=None, off=False):
    model = resolve_model(session, model)
    ref = model_ref(model)
    if off:
        commands = contact_commands(None, off=True)
        for command in commands:
            _run(session, command)
        _record(session, f"molcompose contacts{_model_suffix(ref)} off true", ref)
        session.logger.info(f"MolCompose cleared close contacts for {ref.model_id}")
        return commands
    interface = state_for(session).interfaces.get(ref.model_id)
    if interface is None:
        raise _detect_interface_missing(session, ref.model_id)
    commands = contact_commands(interface)
    for command in commands:
        _run(session, command)
    _record(session, f"molcompose contacts{_model_suffix(ref)}", ref)
    session.logger.info(
        f"MolCompose displayed interface close contacts for {ref.model_id}"
    )
    return commands


def cmd_buriedarea(session, *, model=None):
    """Buried solvent-accessible surface area of the detected interface (Å²)."""
    model = resolve_model(session, model)
    ref = model_ref(model)
    params = state_for(session).interface_params.get(ref.model_id)
    if params is None:
        raise _detect_interface_missing(session, ref.model_id)
    chains_a, chains_b, _criterion, _cutoff = params
    try:
        # `measure buriedarea` logs its value but returns None, so compute it
        # from SASA sums: (SASA_A + SASA_B - SASA_AB) / 2.
        area = buried_area(session, model, chains_a, chains_b)
    except ValueError as error:
        raise UserError(str(error)) from error
    session.logger.info(
        f"MolCompose buried area {ref.model_id} "
        f"({','.join(chains_a)} ↔ {','.join(chains_b)}): {area:.0f} Å²"
    )
    _record(session, f"molcompose buriedarea{_model_suffix(ref)}", ref)
    remember_metric(session, ref, "bsa", area)
    notify_state_changed(session, ref.model_id)
    return area


def cmd_ddg(  # noqa: A002
    session, path, *, model=None, format=None, statistic="min", top=15, interfaceOnly=True  # noqa: N803
):
    """Load predicted mutation effects (ΔΔG) from an external predictor."""
    model = resolve_model(session, model)
    ref = model_ref(model)
    target = Path(path)
    if not target.is_file():
        raise UserError(f"ΔΔG file does not exist: {target}")
    fmt = (format or detect_format(target)).lower()
    if fmt not in DDG_FORMATS:
        raise UserError(f"ΔΔG format must be one of {', '.join(DDG_FORMATS)}: {fmt}")
    try:
        index_map = sequential_index_map(model) if fmt == "pythia" else None
        effects = load_ddg(target, fmt, index_map)
    except (ValueError, OSError) as error:
        raise UserError(str(error)) from error

    # The file's wild-type residues are the only thing tying it to a structure.
    # Chain letters coincide across unrelated entries often enough that this is
    # not a theoretical concern: 1BRS has a chain E and so does 1ACB.
    names = {
        (chain, number): name
        for chain, residues in residue_sequences(
            model, [c.chain_id for c in ref.chains]
        ).items()
        for (_c, number, _icode), name in residues
    }
    check = verify_wild_types(effects, names)
    if check.total and check.rate < IDENTITY_THRESHOLD:
        raise UserError(
            f"{target.name} does not describe {ref.name}: only "
            f"{check.rate:.0%} of its residues match the structure's own "
            f"({check.mismatched} of {check.total} disagree, e.g. "
            f"{'; '.join(check.examples)}). Check that the ΔΔG file was "
            "computed on this structure."
        )

    state = state_for(session)
    state.ddg[ref.model_id] = effects

    # A saturation scan covers every chain of the deposited file — for 1BRS,
    # three copies of each partner — so ranking it whole answers a different
    # question from the one a detected interface asks.
    scanned = len(effects)
    interface = state.interfaces.get(ref.model_id)
    restricted = False
    if interfaceOnly and interface is not None:
        keys = tuple(interface.group_a) + tuple(interface.group_b)
        at_interface = restrict_ddg(effects, ((key.chain_id, key.number) for key in keys))
        if at_interface:
            effects, restricted = at_interface, True

    try:
        rows = summarize_by_residue(effects, statistic)
    except ValueError as error:
        raise UserError(str(error)) from error

    scope = (
        f"{len(effects)} of {scanned} substitutions at the detected interface"
        if restricted
        else f"{len(effects)} substitutions"
    )
    session.logger.info(
        f"MolCompose ΔΔG {ref.model_id} from {target.name} ({fmt}): "
        f"{scope} over {len(rows)} residues, ranked by {statistic}"
    )
    if interfaceOnly and interface is None:
        session.logger.info(
            "  no interface detected — ranking every scanned residue; run "
            "'molcompose interface' first to restrict to the interface"
        )
    for (chain, number), wild_type, value, count in rows[: top if top > 0 else len(rows)]:
        session.logger.info(
            f"  {wild_type} {chain}:{number} — {statistic} ΔΔG {value:+.2f} "
            f"({count} substitutions)"
        )
    _record(
        session,
        f"molcompose ddg {target}{_model_suffix(ref)} format {fmt}"
        + (f" statistic {statistic}" if statistic != "min" else "")
        + (f" top {top:g}" if top != 15 else "")
        + ("" if interfaceOnly else " interfaceOnly false"),
        ref,
    )
    notify_state_changed(session, ref.model_id)
    return rows



def matching_open_model(session, energies, exclude_id: str):
    """The open model this decomposition does describe, or None.

    Returned as the model rather than a sentence so the panel can act on it:
    the selector keeps whatever was chosen when a model is added, so someone
    who opens the structure they were just told to open is still pointed at
    the old one. Naming it in the error was the first version of this and
    left the last step to the reader.
    """
    try:
        from chimerax.atomic import AtomicStructure

        models = session.models.list()
    except (ImportError, AttributeError):
        return None
    for model in models:
        if not isinstance(model, AtomicStructure):
            continue
        candidate = model_ref(model)
        if candidate.model_id == exclude_id:
            continue
        names = {
            (chain_id, number): name
            for chain_id, residues in residue_sequences(
                model, [c.chain_id for c in candidate.chains]
            ).items()
            for (_c, number, _icode), name in residues
        }
        if names and not verify_residue_names(energies, names):
            return model
    return None


def matching_open_model_for_blocks(session, path, chains, exclude_id: str):
    """The open model whose chains have the lengths this RMSF file expects.

    A different question from the MM/GBSA one and it has to be asked
    differently: `gmx rmsf -res` carries no residue names, only one value per
    residue per chain, so all a structure can be checked against is how many
    residues each named chain has. That is weaker — two structures of the same
    size would both pass — but it is the whole of what the file says, and it
    catches the case this exists for, where the repaired structure has
    residues the deposited one does not.
    """
    from .core.rmsf import FluctuationError
    from .core.rmsf import blocks as rmsf_blocks
    from .core.rmsf import parse as parse_rmsf

    try:
        from chimerax.atomic import AtomicStructure

        models = session.models.list()
        found = rmsf_blocks(parse_rmsf(Path(path).read_text()))
    except (ImportError, AttributeError, FluctuationError, OSError, ValueError):
        return None
    wanted = parse_chain_group(chains)
    for model in models:
        if not isinstance(model, AtomicStructure):
            continue
        candidate = model_ref(model)
        if candidate.model_id == exclude_id:
            continue
        sequences = residue_sequences(model, list(wanted))
        if any(chain not in sequences for chain in wanted):
            continue
        if len(found) != len(wanted):
            continue
        if all(
            len(block) == len(sequences[chain])
            for block, chain in zip(found, wanted, strict=True)
        ):
            return model
    return None


def _matching_open_model(session, energies, exclude_id: str) -> str:
    """Another open model the file does describe, named for the panel.

    The step people miss. Told the structure is wrong, they open the right
    one — and the panel goes on acting on the first, because its selector
    keeps whatever was chosen when a model is added rather than following the
    newest. Pressing the button again then produces the same error about a
    structure that is no longer the one they mean.

    Auto-selecting the newest model instead would break the other flow in
    this panel: a DockQ reference is opened the same way, and the analysis
    would jump to it. So the selection is left alone and the mismatch says
    where to point it.
    """
    found = matching_open_model(session, energies, exclude_id)
    if found is None:
        return ""
    candidate = model_ref(found)
    return (
        f" {candidate.name} ({candidate.model_id}) is already open and "
        "does match."
    )


def _repaired_structure_hint(path) -> str:
    """" The repaired structure is beside it: X." — or nothing at all.

    Named only when it is actually there. An MD result describes the repaired
    structure the trajectory ran on, not the deposited entry and not a
    predicted model: repair adds the residues a crystal did not resolve, and
    from the first gap onward every residue number after it moves. Loading
    onto the wrong one does not fail, it shifts every value along, which is
    why the residue names are checked at all.

    Someone who has just been told the structure is wrong then has to find the
    right one, and for a run they did themselves it is sitting in the same
    directory as the file they just chose. Saying so costs a clause. Saying
    "there should be a repaired structure somewhere" when there is not would
    cost more than it gives, so nothing is said in that case.
    """
    try:
        folder = Path(path).parent
        found = sorted(
            candidate.name
            for pattern in ("*repaired*.pdb", "*repaired*.cif")
            for candidate in folder.glob(pattern)
        )
    except OSError:
        return ""
    if not found:
        return ""
    if len(found) == 1:
        return f" The repaired structure is beside it: {found[0]}."
    return f" Beside it: {', '.join(found[:3])}."


def _energy_method(path, solvation: str | None) -> str:
    """"MM/GBSA" or "MM/PBSA", from the choice or from the file itself.

    `gmx_MMPBSA` is the program's name and it writes `FINAL_DECOMP_MMPBSA.dat`
    whichever model was run, so the file name says nothing. The two are
    different methods: Generalized Born is MM/GBSA, Poisson-Boltzmann is
    MM/PBSA, and they disagree by several kcal/mol. Labelling a Generalized
    Born run "MM/PBSA" names the method that was not used.

    A file carrying one model needs no choice and still knows which it is, so
    the heading is read rather than left unlabelled.
    """
    from .core.mmpbsa import solvation_models

    if solvation:
        return "MM/GBSA" if solvation.lower().startswith("g") else "MM/PBSA"
    models = solvation_models(path)
    if len(models) == 1:
        return "MM/GBSA" if models[0].lower().startswith("g") else "MM/PBSA"
    return "MM/PBSA"


def cmd_energy(session, path, *, chains=None, model=None, top=10,
               solvation=None):
    """Load a per-residue MM/PBSA decomposition and attach it to a structure.

    `chains` maps the file's chain letters onto the model's and is required
    rather than inferred. GROMACS relabels chains when a system is built, so a
    decomposition of PDB 1BRS arrives with chains A and B where the structure
    has A and D; guessing by order would attach the ligand's energies to
    whatever the model happens to call B, silently and plausibly.

    `solvation` -- "gb" or "pb" -- is required only when the run computed
    both, which writes the whole decomposition twice under its own heading.
    The two disagree by several kcal/mol, so the file cannot pick for you.
    """
    if not chains:
        raise UserError(
            "'chains' is required: it maps the file's chain letters onto the "
            "model's, as in 'chains A:A,B:D'. GROMACS relabels chains when a "
            "system is built, so the letters in the file are usually not the "
            "structure's, and guessing would attach one partner's energies to "
            "the other."
        )
    model = resolve_model(session, model)
    ref = model_ref(model)
    target = Path(path)
    if not target.is_file():
        raise UserError(f"decomposition file does not exist: {target}")
    try:
        chain_map = parse_chain_map(chains)
        energies = remap(load_energies(target, solvation), chain_map)
    except (DecompositionError, OSError) as error:
        raise UserError(str(error)) from error
    if not energies:
        raise UserError(
            f"no residue of {target.name} is on a chain the map mentions "
            f"({', '.join(sorted(parse_chain_map(chains)))})"
        )

    names = {
        (chain, number): name
        for chain, residues in residue_sequences(
            model, [c.chain_id for c in ref.chains]
        ).items()
        for (_c, number, _icode), name in residues
    }
    problems = verify_residue_names(energies, names)
    if problems:
        # Which advice depends on how much disagrees. A wrong chain map moves
        # one side of the file onto the wrong chain, so roughly half the
        # residues survive; nearly everything disagreeing means the file is
        # about a different structure, and the usual cause is loading an MD
        # result onto the deposited entry or a prediction instead of the
        # repaired structure the trajectory was actually run on. Saying "check
        # the chain map" to someone who has the wrong structure open sends
        # them to re-check something that was already right.
        # A constant shift is the repaired-versus-deposited mistake, and it
        # is worth checking before the fraction is: repair adds the residues
        # a crystal did not resolve, so how much disagrees depends on where
        # the gaps fall rather than on how wrong the pairing is. A file three
        # residues out can still match most of a structure by coincidence.
        from .core.mmpbsa import numbering_offset

        shift = numbering_offset(energies, names)
        share = len(problems) / len(energies) if energies else 0
        if shift is not None:
            advice = (
                f"Every residue in the file sits {abs(shift)} "
                f"{'position' if abs(shift) == 1 else 'positions'} "
                f"{'later' if shift > 0 else 'earlier'} than the same residue "
                "here, which is what happens when a decomposition computed on "
                "the repaired structure is loaded onto the deposited entry or "
                "a predicted model: repair adds the residues the experiment "
                "did not resolve, and every number after the first gap moves. "
                "Load the structure the trajectory ran on."
            ) + _repaired_structure_hint(target) + _matching_open_model(
                session, energies, ref.model_id
            )
        elif share > 0.8:
            advice = (
                "Almost none of it matches, so this is very likely the wrong "
                "structure rather than the wrong chain map: MD repairs the "
                "structure before it runs, and the decomposition describes "
                "the repaired one. Load that file, not the deposited entry "
                "and not a predicted model."
            ) + _repaired_structure_hint(target) + _matching_open_model(
                session, energies, ref.model_id
            )
        else:
            advice = (
                "Check which of the file's chains is which of the structure's."
            ) + _matching_open_model(session, energies, ref.model_id)
        raise UserError(
            f"{target.name} does not describe {ref.name} under the chain map "
            f"given: {len(problems)} of {len(energies)} residues disagree "
            f"(e.g. {'; '.join(problems[:3])}). {advice}"
        )

    state = state_for(session)
    state.energies[ref.model_id] = energies
    method = _energy_method(target, solvation)
    state.energy_method[ref.model_id] = method
    session.logger.info(
        f"MolCompose {method} {ref.model_id} from {target.name}: "
        f"{len(energies)} residues over chains "
        f"{', '.join(sorted({e.chain for e in energies}))}, "
        "as contribution to binding (negative is favourable)"
    )
    for energy in ranked_energies(energies, top=top if top > 0 else 0):
        session.logger.info(
            f"  {energy.residue_name} {energy.chain}:{energy.number} — "
            f"{energy.energy:+.2f} ± {energy.standard_error:.2f} kcal/mol"
        )
    # The overall energy is in a sibling file, and is reported rather than
    # stored: leaving it out entirely meant a user who had computed it could
    # not see it anywhere, and putting it in the metric tiles beside PRODIGY's
    # ΔG would claim they are the same quantity. The Log is where a number
    # with this many caveats belongs.
    totals = totals_beside(target)
    if totals:
        session.logger.info(
            "  overall binding energy in "
            + f"{RESULTS_FILE}, for reference only: "
            + ", ".join(f"{t.label} {t.total:+.2f}" for t in totals)
            + " kcal/mol"
        )
        if len(totals) > 1:
            spread = max(t.total for t in totals) - min(t.total for t in totals)
            session.logger.info(
                f"  the {abs(spread):.1f} kcal/mol between the two solvation "
                "models is the error bar on that treatment alone"
            )
    session.logger.info(
        "  this is a per-residue contribution, not the interface's ΔG: "
        "absolute MM/PBSA binding energies carry no entropy term and move "
        "with the internal dielectric, so they are not comparable with the "
        "predicted ΔG the panel reports"
    )
    _record(
        session,
        f"molcompose energy {target} chains {chains}{_model_suffix(ref)}"
        + (f" solvation {solvation}" if solvation else "")
        + (f" top {top:g}" if top != 10 else ""),
        ref,
    )
    notify_state_changed(session, ref.model_id)
    return energies



def cmd_flexibility(session, path, *, chains=None, model=None):
    """Load per-residue RMS fluctuation from an MD trajectory.

    The one thing every other metric here is blind to: all of them describe a
    single conformation, and this describes how much that conformation moves.

    `chains` names one chain per block of the file, in the order the selection
    was written, because `gmx rmsf -res` restarts its numbering at each chain
    and nothing in the file says which is which.
    """
    if not chains:
        raise UserError(
            "'chains' is required: name one chain per block of the file, in "
            "the order the selection was written, as in 'chains A,D'. "
            "`gmx rmsf -res` restarts its numbering at each chain, so a "
            "two-chain file reads 1..110 then 1..89 and nothing in it says "
            "which chain is which."
        )
    model = resolve_model(session, model)
    ref = model_ref(model)
    target = Path(path)
    if not target.is_file():
        raise UserError(f"fluctuation file does not exist: {target}")
    wanted = parse_chain_group(chains)
    sequences = residue_sequences(model, list(wanted))
    missing = [c for c in wanted if c not in sequences]
    if missing:
        raise UserError(
            f"{ref.name} has no chain(s) {', '.join(missing)}"
        )
    try:
        values = load_rmsf(target)
        placed = rmsf_by_residue(values, tuple(
            (chain, tuple(number for (_c, number, _i), _name in sequences[chain]))
            for chain in wanted
        ))
    except (FluctuationError, OSError) as error:
        raise UserError(str(error) + _repaired_structure_hint(target)) from error

    state = state_for(session)
    state.flexibility[ref.model_id] = placed
    highest = sorted(placed.items(), key=lambda item: item[1], reverse=True)[:5]
    session.logger.info(
        f"MolCompose flexibility {ref.model_id} from {target.name}: "
        f"{len(placed)} residues over chains {', '.join(wanted)}, "
        "RMS fluctuation in Å"
    )
    for (chain, number), value in highest:
        session.logger.info(f"  {chain}:{number} — {value:.2f} Å")
    session.logger.info(
        "  fluctuation is not a contribution: a residue that moves a lot may "
        "be a flexible loop away from the interface, and one that moves "
        "little may simply be buried in the core"
    )
    _record(
        session,
        f"molcompose flexibility {target} chains {','.join(wanted)}"
        f"{_model_suffix(ref)}",
        ref,
    )
    notify_state_changed(session, ref.model_id)
    return residue_keys_as_text(placed)


COLOR_METRICS = ("plddt", "ddg", "dsasa", "bfactor", "mmpbsa", "rmsf")
# Which metrics can be asked for over the whole structure rather than
# over the interface. DSASA cannot: it is defined by what two chains
# bury in each other, so it has no value away from their contact.
WHOLE_STRUCTURE_SCOPES = ("interface", "all")


def _color_by_plddt(session, model, ref):
    """Whole-model pLDDT colouring, refused on experimentally determined models.

    Lives beside ΔΔG and ΔSASA because it is the same operation — paint
    residues by a per-residue quantity — even though the other two are
    interface-scoped and this one is not. Keeping it in `style` alone left the
    three metric colourings split across two parts of the interface for no
    reason a user could infer.
    """
    method = experimental_method(model)
    if method:
        raise UserError(
            f"{ref.model_id} is an experimentally determined structure ({method}); "
            "its B-factors are temperature factors, not pLDDT. Confidence "
            "colouring applies only to predicted models."
        )
    try:
        report = build_report(plddt_values(model))
    except ValueError as error:
        raise UserError(str(error)) from error
    _run(session, f"color bfactor {ref.atomspec} palette {palette_spec(report.scale)}")
    session.logger.info(
        f"MolCompose coloured {ref.model_id} by pLDDT "
        f"(scale {report.scale}, mean {report.normalized_mean:.1f})"
    )
    return report


class BFactorRange(NamedTuple):
    """The span a B-factor map was painted over.

    A NamedTuple rather than a bare tuple because the panel reads `.low` and
    `.high` off whatever a metric returns. Handing back a plain tuple raised
    AttributeError on the first click — the same failure pLDDT had, in the
    same place, for the same reason: a new metric added without the caller
    that reads the result being told about it.
    """

    low: float
    middle: float
    high: float


def _color_by_bfactor(session, model, ref):
    """Whole-model B-factor colouring, refused on predicted models.

    The mirror of `_color_by_plddt`, and the refusal runs the other way. Both
    read the B-factor column; on a deposited structure it holds temperature
    factors and on a predicted one it holds pLDDT, and the two mean opposite
    things — high B-factor is disorder, high pLDDT is confidence. Painting a
    predicted model with a "disorder" scale would invert every reading, so it
    is refused rather than allowed with a caveat.

    Blue-white-red across the observed range, which is what ChimeraX's own
    B-factor colouring uses and what a crystallographer expects to see.
    """
    method = experimental_method(model)
    if not method:
        raise UserError(
            f"{ref.model_id} has no deposited experimental method, so its "
            "B-factor column is pLDDT rather than temperature factors. Use "
            "'molcompose color by plddt' instead."
        )
    values = [atom.bfactor for atom in model.atoms]
    if not values:
        raise UserError(f"{ref.model_id} carries no B-factor values")
    low, high = min(values), max(values)
    if high <= low:
        raise UserError(
            f"{ref.model_id}'s B-factors are all {low:g}; there is nothing to grade"
        )
    middle = (low + high) / 2
    palette = f"{low:g},#3B6FB6:{middle:g},#F2F2F2:{high:g},#C0392B"
    _run(session, f"color bfactor {ref.atomspec} palette {palette}")
    _draw_key(session, (("#3B6FB6", f"{low:.0f}"), ("#F2F2F2", f"{middle:.0f}"),
                        ("#C0392B", f"{high:.0f}")))
    session.logger.info(
        f"MolCompose coloured {ref.model_id} by B-factor "
        f"({method}); range {low:.1f} … {high:.1f} Å²"
    )
    _record(session, f"molcompose color by bfactor{_model_suffix(ref)}", ref)
    return BFactorRange(low, middle, high)


def _draw_key(session, stops):
    """Draw the colour scale that makes a metric figure readable.

    The stops come from the scale the figure was actually painted with. A key
    assembled separately is a promise to eventually disagree with the figure,
    and a wrong key is worse than none because it is read as authoritative.
    """
    from .core.presets import ColorKey

    # `blended`, and the bar is a true gradient because `key_labels` now emits
    # each anchor once: the structure is interpolated between the same anchors,
    # so the two agree. The pLDDT key is the one that still steps, and it is
    # drawn from `key_stops` in the renderer rather than from here, because
    # AlphaFold's four bands are categorical and its boundaries are the labels
    # worth printing.
    #
    # Two earlier shapes were wrong. No treatment at all blended five band
    # colours into a gradient the stepped structure did not have; doubling the
    # stops fixed that by making the bar step too, which was right only while
    # the structure stepped.
    for command in ColorKey().commands(stops=stops, treatment="blended"):
        _run(session, command)


def _metric_residue_values(session, model, ref, metric, statistic, scope):
    """Per-residue values for a metric, and how they should be scaled.

    Split out of `cmd_color_by` so the sequence export cannot drift from the
    structure colouring. Both call this, both then call `build_scale` on what
    it returns, so a residue that is dark red on the ribbon is dark red in the
    Sequence Viewer by construction rather than by two implementations
    agreeing. Returns `(by_residue, values, kind, unit)`, where `values` is
    keyed by `(chain_id, residue_number)`.
    """
    state = state_for(session)
    interface = state.interfaces.get(ref.model_id)
    if scope == "all":
        # Whole structure: every residue is a candidate, and no interface is
        # needed. The data the user loaded is usually whole-chain, and
        # restricting it to a contact they may not have detected yet was
        # showing them less than they supplied.
        # Proper ResidueKeys, not the raw ChimeraX residues. Everything
        # downstream joins these into atomspecs, and a flat `a|b|c` union over
        # 586 residues overflows ChimeraX's recursive atomspec parser —
        # `compact_residue_spec` collapses them into per-chain ranges instead,
        # and it needs the key type to do it.
        by_residue = {
            (key.chain_id, key.number): key
            for key in (residue_key(ref.model_id, residue)
                        for residue in model.residues)
            if key.chain_id
        }
    else:
        if interface is None:
            raise _detect_interface_missing(session, ref.model_id)
        keys = tuple(interface.group_a) + tuple(interface.group_b)
        by_residue = {(key.chain_id, key.number): key for key in keys}

    if metric == "rmsf":
        placed = state.flexibility.get(ref.model_id)
        if not placed:
            raise UserError(
                "no fluctuations are loaded; run "
                "'molcompose flexibility <file.xvg> chains <list>' first"
            )
        in_scope = {key: value for key, value in placed.items() if key in by_residue}
        if not in_scope:
            where = "this structure" if scope == "all" else "the detected interface"
            raise UserError(
                f"the loaded fluctuations cover no residue of {where}"
            )
        # More is more, and none of it is signed: a sequential ramp, like
        # buried area, rather than the diverging one the energies use.
        return by_residue, in_scope, "sequential", "Å"

    if metric == "mmpbsa":
        loaded = state.energies.get(ref.model_id)
        if not loaded:
            raise UserError(
                "no MM/PBSA decomposition is loaded; run "
                "'molcompose energy <file> chains <map>' first"
            )
        in_scope = {
            key: value for key, value in mmpbsa_by_residue(loaded).items()
            if key in by_residue
        }
        if not in_scope:
            where = "this structure" if scope == "all" else "the detected interface"
            raise UserError(
                f"the loaded decomposition covers no residue of {where}; check "
                "the chain map it was loaded with"
            )
        # Negative is the favourable end, so the ramp is read the other way
        # round and red still means "matters more". The values are the file's.
        return by_residue, in_scope, "diverging-negative", "kcal/mol"

    if metric == "ddg":
        effects = state.ddg.get(ref.model_id)
        if not effects:
            raise UserError(
                "no ΔΔG predictions are loaded; run 'molcompose ddg <file>' first"
            )
        in_scope = restrict_ddg(effects, by_residue)
        if not in_scope:
            where = "this structure" if scope == "all" else "the detected interface"
            raise UserError(
                f"the loaded ΔΔG predictions do not cover any residue of {where}; "
                "check that they were computed on this structure"
            )
        rows = summarize_by_residue(in_scope, statistic)
        values = {(chain, number): value for (chain, number), _wt, value, _n in rows}
        kind, unit = "diverging", "kcal/mol"
    else:
        params = state.interface_params.get(ref.model_id)
        if params is None:
            raise _detect_interface_missing(session, ref.model_id)
        chains_a, chains_b, _criterion, _cutoff = params
        try:
            rows = delta_sasa(session, model, chains_a, chains_b)
        except ValueError as error:
            raise UserError(str(error)) from error
        values = {(chain, number): delta for (chain, number, _icode), _n, _a, _c, delta in rows}
        kind, unit = "sequential", "Å²"

    return by_residue, values, kind, unit


def cmd_color_by(session, metric, *, model=None, statistic="max",
                 scope="interface"):
    """Colour residues by a per-residue metric rather than by chain.

    `scope` chooses between the interface and the whole structure. It
    defaults to the interface because that is what these metrics are
    usually asked about, and because a saturation scan covers every chain
    of the deposited file — three copies of each partner for 1BRS — so
    ranking all of it against one interface drowns the interface. But the
    data loaded is often whole-chain, and refusing to draw it was showing
    the user less than they gave us.
    """
    metric = metric.lower()
    if metric not in COLOR_METRICS:
        raise UserError(
            f"colour metric must be one of {', '.join(COLOR_METRICS)}: {metric}"
        )
    model = resolve_model(session, model)
    ref = model_ref(model)
    state = state_for(session)

    if scope not in WHOLE_STRUCTURE_SCOPES:
        raise UserError(
            f"scope must be one of {', '.join(WHOLE_STRUCTURE_SCOPES)}: {scope}"
        )

    if metric == "plddt":
        # Confidence is a property of the whole model, not of an interface, so
        # this branch needs no detected interface.
        report = _color_by_plddt(session, model, ref)
        _record(session, f"molcompose color by plddt{_model_suffix(ref)}", ref)
        return report

    if metric == "bfactor":
        # The crystallographic counterpart of pLDDT, and deliberately its own
        # metric rather than a mode of it: the two read the same column and
        # mean opposite things. High pLDDT is confidence; high B-factor is
        # disorder. Refusing one on a predicted model and the other on an
        # experimental one is what keeps that straight.
        return _color_by_bfactor(session, model, ref)

    if metric == "dsasa" and scope == "all":
        raise UserError(
            "ΔSASA is defined by what two chains bury in each other, so it "
            "has no value away from their contact; use scope interface"
        )

    by_residue, values, kind, unit = _metric_residue_values(
        session, model, ref, metric, statistic, scope
    )
    interface = state.interfaces.get(ref.model_id)

    entries = [
        (by_residue[key].atomspec, value)
        for key, value in values.items()
        if key in by_residue
    ]
    if not entries:
        raise UserError("no interface residue carries a value for this metric")

    scale = build_scale([value for _spec, value in entries], kind)

    # The bodies give up their colour for as long as a ramp is painted. Warm
    # against cool tells the two proteins apart, which is worth having until
    # the question changes: a diverging ΔΔG scale is red-to-blue by
    # convention, and the partners sit on those hues. Whichever of the two a
    # residue belongs to stops mattering the moment its value is the subject.
    #
    # Interface residues the metric cannot speak for take the same grey rather
    # than keeping their partner colour, which would put "no data" and "highly
    # destabilising" in the same red.
    scored = {spec for spec, _value in entries}
    candidates = (
        tuple(by_residue.values()) if scope == "all"
        else tuple(interface.group_a) + tuple(interface.group_b)
    )
    unscored = [key for key in candidates if key.atomspec not in scored]
    # Surfaces are in the target, and were not until 2026-08-18. Without the
    # `s` a metric never reaches a surface at all: it paints atoms and cartoons
    # and leaves the envelope holding whatever colour the preset gave it. On
    # surface-translucent that is EPITOPE_BLUE, sitting next to a diverging key
    # whose most-negative block is #2166AC -- three degrees apart in hue. The
    # figure showed a large blue patch reading "strongly stabilising" on a
    # dataset whose every value is positive. A colour on a figure whose whole
    # content is a scale must be a value or must be the no-data colour; there
    # is no third category, and a surface is not exempt from that.
    for chain in ref.chains:
        _run(session, f"color {chain.atomspec} {BODY_GREY} target cs")
    if unscored:
        _run(session, f"color {compact_residue_spec(unscored)} {NO_DATA} target acs")

    # Grouped by colour, then compacted per group. Joining raw atomspecs with
    # `|` is what raised RecursionError the moment this was asked for a whole
    # structure rather than an interface: one band of a 586-residue scan is
    # hundreds of terms, and the parser recurses once per term.
    by_key = {key.atomspec: key for key in candidates}
    for color, specs in group_by_color(assign(entries, scale)).items():
        keys = [by_key[spec] for spec in specs if spec in by_key]
        joined = compact_residue_spec(keys) if keys else "|".join(specs)
        _run(session, f"color {joined} {color} target acs")

    # The key comes from the scale just built, so it cannot disagree with the
    # colours on the structure.
    _draw_key(session, scale.key_labels)

    session.logger.info(
        f"MolCompose coloured {len(entries)} "
        f"{'residues' if scope == 'all' else 'interface residues'} of "
        f"{ref.model_id} by {metric} "
        f"({statistic if metric == 'ddg' else 'per-residue'}), "
        f"{kind} scale {scale.low:+.2f} … {scale.high:+.2f} {unit}"
    )
    # The scale ends come from the data's 2nd/98th percentile, not from a
    # published range: a documented range that the data exceeds would flatten
    # exactly the residues worth looking at.
    for color, label in scale.legend:
        session.logger.info(f"  {color}  {label} {unit}")
    _record(
        session,
        f"molcompose color by {metric}{_model_suffix(ref)}"
        + (f" statistic {statistic}" if metric == "ddg" and statistic != "max" else "")
        + (f" scope {scope}" if scope != "interface" else ""),
        ref,
    )
    return scale


SEQCOLOR_SOURCES = ("interface", "plddt", "ddg", "dsasa", "bfactor", "mmpbsa")


def _seqcolor_entries(session, model, ref, source, statistic):
    """`{chain_id: [(column, colour, label)]}` for one source, plus a caption.

    Colours come from the same functions that paint the structure — the AF
    band table for pLDDT, `build_scale` for the metric ramps, the interface
    preset's own colours for interface membership — so the sequence and the
    ribbon cannot disagree about what a colour means.
    """
    from .adapters.sequence import model_columns
    from .core.coloring import build_scale
    from .core.confidence import band_color, band_label, build_report
    from .core.presets import PRESETS

    columns = model_columns(model)
    per_chain: dict[str, list] = {}

    def add(chain_id, key, colour, label):
        column = columns.get(chain_id, {}).get(key)
        if column is not None:
            per_chain.setdefault(chain_id, []).append((column, colour, label))

    if source == "interface":
        interface = state_for(session).interfaces.get(ref.model_id)
        if interface is None:
            raise _detect_interface_missing(session, ref.model_id)
        colour_a, colour_b = PRESETS["interface-focus"].interface_colors()
        for keys, colour, label in (
            (interface.group_a, colour_a, "interface, group A"),
            (interface.group_b, colour_b, "interface, group B"),
        ):
            for key in keys:
                add(key.chain_id,
                    (key.chain_id, key.number, key.insertion_code or ""),
                    colour, label)
        return per_chain, "interface residues"

    if source == "plddt":
        values = plddt_values(model)
        if not values:
            raise UserError(f"{ref.model_id} carries no per-residue values to read")
        scale = build_report(values).scale
        for key, value in values:
            add(key.chain_id,
                (key.chain_id, key.number, key.insertion_code or ""),
                band_color(value, scale), band_label(value, scale))
        return per_chain, f"pLDDT, {scale} scale"

    if source == "bfactor":
        values = plddt_values(model)   # the same column, read as what it is
        if not values:
            raise UserError(f"{ref.model_id} carries no B-factor values")
        scale = build_scale([value for _key, value in values], "sequential")
        for key, value in values:
            add(key.chain_id,
                (key.chain_id, key.number, key.insertion_code or ""),
                scale.color_for(value), "B-factor")
        return per_chain, f"B-factor {scale.low:.0f}–{scale.high:.0f} Å²"

    # ddg, dsasa and mmpbsa: the same values and the same scale the structure
    # gets, so the sequence and the ribbon cannot disagree.
    scope = "all" if source in ("ddg", "mmpbsa") else "interface"
    by_residue, values, kind, unit = _metric_residue_values(
        session, model, ref, source, statistic, scope
    )
    if not values:
        raise UserError("no residue carries a value for this metric")
    scale = build_scale(list(values.values()), kind)
    label = {
        "ddg": "ΔΔG",
        "dsasa": "buried area",
        # Named for the solvation model that produced it. Generalized Born is
        # MM/GBSA and Poisson-Boltzmann is MM/PBSA; the key used to say the
        # latter for both.
        "mmpbsa": (
            f"{state_for(session).energy_method.get(ref.model_id, 'MM/PBSA')} "
            "contribution"
        ),
    }[source]
    for (chain_id, number), value in values.items():
        key = by_residue.get((chain_id, number))
        insertion = getattr(key, "insertion_code", "") or "" if key else ""
        add(chain_id, (chain_id, number, insertion),
            scale.color_for(value), f"{label} {scale.color_for(value)}")
    return per_chain, f"{label} {scale.low:.2f}–{scale.high:.2f} {unit}"


def cmd_seqcolor(session, path=None, *, model=None, source="interface",
                 statistic="max", load=True):
    """Write the per-residue colouring as SCF, for the Sequence Viewer.

    The same quantity that colours the structure, laid out along the sequence —
    where "which stretch of chain carries this interface" is a shape rather
    than a scatter of highlighted side chains. PICKLUSTER offers this through a
    right-click menu; here it is a command, so the panel, the command line and
    an agent all reach it and every use is recorded in the recipe.
    """
    from .core.scf import scf_text

    source = str(source).lower()
    if source not in SEQCOLOR_SOURCES:
        raise UserError(
            f"seqcolor source must be one of {', '.join(SEQCOLOR_SOURCES)}: {source}"
        )
    model = resolve_model(session, model)
    ref = model_ref(model)
    per_chain, caption = _seqcolor_entries(session, model, ref, source, statistic)
    if not per_chain:
        raise UserError(
            f"no residue of {ref.model_id} carries a {source} colour to export"
        )

    target = Path(path) if path else _default_scf_path(model, ref, source)
    if target.suffix.lower() != ".scf":
        target = target.with_suffix(".scf")
    if not target.parent.is_dir():
        raise UserError(f"output directory does not exist: {target.parent}")

    written = []
    for chain_id, entries in sorted(per_chain.items()):
        # One file per chain: SCF columns are per sequence, so chain B's
        # column 1 is its own first residue and not a continuation of A's.
        chain_target = (target if len(per_chain) == 1
                        else target.with_name(f"{target.stem}_{chain_id}.scf"))
        text = scf_text(entries, header=(
            f"MolCompose {source} colouring of {ref.model_id} chain {chain_id}",
            caption,
            "columns are alignment positions, not residue numbers",
        ))
        try:
            chain_target.write_text(text, encoding="utf-8")
        except OSError as error:
            raise UserError(f"could not write {chain_target}: {error}") from error
        written.append((chain_id, chain_target))
        session.logger.info(
            f"MolCompose seqcolor {ref.model_id}/{chain_id}: {len(entries)} "
            f"residues -> {chain_target}"
        )

    if load:
        for chain_id, chain_target in written:
            _load_scf(session, ref, chain_id, chain_target)

    _record(
        session,
        f"molcompose seqcolor {target}{_model_suffix(ref)} source {source}"
        + ("" if load else " load false"),
        ref,
    )
    return [str(chain_target) for _chain, chain_target in written]


def _default_scf_path(model, ref, source):
    """Beside the structure when it has a file, otherwise in the temp folder."""
    import tempfile

    stem = f"{structure_stem(model, 'model')}_{source}"
    source_path = structure_path(model)
    folder = Path(source_path).parent if source_path else Path(tempfile.gettempdir())
    if not folder.is_dir():
        folder = Path(tempfile.gettempdir())
    return folder / f"{stem}.scf"


def _load_scf(session, ref, chain_id, path):
    """Open the chain's sequence and load the file into it.

    Best-effort: the colouring is already on disk and the command has already
    reported it, so a Sequence Viewer that will not open is a reason to say so
    rather than to fail the export.
    """
    try:
        _run(session, f"sequence chain {ref.atomspec}/{chain_id}")
        alignment = _alignment_for(session, ref, chain_id)
        if alignment is None:
            session.logger.info(
                "MolCompose seqcolor: no sequence alignment to load into; open "
                f"one with 'sequence chain {ref.atomspec}/{chain_id}'"
            )
            return
        _run(session, f'sequence viewer {alignment} scfLoad "{path}" color false')
        session.logger.info(
            f"MolCompose seqcolor: loaded into sequence viewer {alignment}"
        )
    except Exception as error:  # noqa: BLE001 - the file is written either way
        session.logger.info(
            f"MolCompose seqcolor: wrote {path} but could not load it ({error}); "
            f"load it by hand with 'sequence viewer <alignment> scfLoad'"
        )


def _alignment_for(session, ref, chain_id):
    """Identifier of the alignment showing this chain, or None.

    By chain rather than "the most recently opened one": exporting a complex
    writes a file per chain and opens a viewer per chain, and taking the newest
    each time round the loop is a race against the order things happen to be
    created in. ChimeraX names these `1/E`, `1/I` — the model id without its
    hash, then the chain.
    """
    try:
        alignments = list(session.alignments.alignments)
    except AttributeError:
        return None
    wanted = f"{ref.model_id.lstrip('#')}/{chain_id}"
    for alignment in alignments:
        if getattr(alignment, "ident", None) == wanted:
            return wanted
    # Fall back to any alignment whose identifier ends with this chain, so a
    # different naming scheme degrades to "probably right" instead of "wrong".
    for alignment in alignments:
        ident = getattr(alignment, "ident", "") or ""
        if ident.endswith(f"/{chain_id}"):
            return ident
    return None


HOTSPOT_METRICS = ("dsasa", "energy")


def cmd_hotspots(session, *, model=None, minArea=10.0, top=0, metric="dsasa"):  # noqa: N803
    """Rank interface residues by what makes them matter.

    Three orthogonal notions of "matters", and the default stays the one this
    command has always meant. Buried area is geometry: how much surface a
    residue loses on binding. MM/PBSA decomposition is what keeping it earns.
    Predicted ΔΔG — what removing it costs — is ranked by `molcompose ddg`,
    which has to load the scan anyway.

    Because they are different questions, the answer says which one it
    answered. Two hot-spot figures that disagree about the top residue are
    only confusing if neither says what it ranked by.
    """
    metric = str(metric).lower()
    if metric not in HOTSPOT_METRICS:
        raise UserError(
            f"hot-spot metric must be one of {', '.join(HOTSPOT_METRICS)}: {metric}"
        )
    model = resolve_model(session, model)
    ref = model_ref(model)
    params = state_for(session).interface_params.get(ref.model_id)
    if params is None:
        raise _detect_interface_missing(session, ref.model_id)
    chains_a, chains_b, _criterion, _cutoff = params

    if metric == "energy":
        rows = _hotspots_by_energy(session, ref, top)
    else:
        try:
            rows = delta_sasa(session, model, chains_a, chains_b)
        except ValueError as error:
            raise UserError(str(error)) from error
        rows = tuple(row for row in rows if row[4] >= minArea)
        if top and top > 0:
            rows = rows[:top]
        session.logger.info(
            f"MolCompose hot spots {ref.model_id} "
            f"({','.join(chains_a)} ↔ {','.join(chains_b)}, ΔSASA ≥ {minArea:g} Å²): "
            f"{len(rows)} residues"
        )
        # `top` already trimmed `rows`; logging a further fixed 20 meant that
        # asking for everything (top 0) silently printed only the first 20.
        for (chain, number, icode), name, _alone, _complexed, delta in rows:
            session.logger.info(
                f"  {name} {chain}:{number}{icode} — {delta:.1f} Å² buried"
            )
    _record(
        session,
        f"molcompose hotspots{_model_suffix(ref)}"
        + (f" minArea {minArea:g}" if minArea != 10.0 and metric == "dsasa" else "")
        + (f" top {top:g}" if top else "")
        + (f" metric {metric}" if metric != "dsasa" else ""),
        ref,
    )
    return rows


def _hotspots_by_energy(session, ref, top):
    """Interface residues ranked by end-point energy contribution to binding.

    Returned in the same shape as the buried-area ranking so callers do not
    branch: the two middle fields carry no meaning here and are None, because
    filling them with zeros would read as "no surface buried".
    """
    energies = state_for(session).energies.get(ref.model_id)
    if not energies:
        raise UserError(
            "no MM/PBSA decomposition is loaded; run "
            "'molcompose energy <file> chains <map>' first"
        )
    ordered = ranked_energies(energies, top=top if top and top > 0 else 0)
    session.logger.info(
        f"MolCompose hot spots {ref.model_id} by "
        f"{state_for(session).energy_method.get(ref.model_id, 'MM/PBSA')} "
        "contribution: "
        f"{len(ordered)} residues, most favourable first"
    )
    for energy in ordered:
        session.logger.info(
            f"  {energy.residue_name} {energy.chain}:{energy.number} — "
            f"{energy.energy:+.2f} ± {energy.standard_error:.2f} kcal/mol"
        )
    return tuple(
        ((energy.chain, energy.number, ""), energy.residue_name, None, None,
         energy.energy)
        for energy in ordered
    )


def cmd_characterise(  # noqa: N803
    session, group_a, group_b, *, model=None, distance=4.5, criterion="heavy",
    style=True, paeFile=None, summaryFile=None,  # noqa: N803
):
    """Run the standard interface characterisation end to end, in one call.

    Agents have been shown to under-use analysis tools when left to choose them
    (BioDesignBench reports ~14% of expert depth), so the complete workflow is
    offered as a single operation returning one structured summary.
    """
    model = resolve_model(session, model)
    ref = model_ref(model)
    summary: dict = {"model": ref.model_id, "name": ref.name, "steps": [], "skipped": {}}

    # One recipe line for the whole battery: replaying this command reproduces
    # every step below, so recording the steps individually would describe a
    # workflow the user never issued.
    _record(
        session,
        f"molcompose characterise {group_a} {group_b}{_model_suffix(ref)} "
        f"distance {distance:g}"
        + f" criterion {criterion}"
        + ("" if style else " style false"),
        ref,
    )

    with _nested(session):
        result = _characterise_steps(
            session, summary, model, ref, group_a, group_b, distance, criterion,
            style, paeFile, summaryFile,
        )
    # Outside the block, and it has to be: every step above runs nested, and a
    # notification sent from in there is suppressed by the same rule that keeps
    # the recipe to one line. Sent from inside `_characterise_steps` — where it
    # started — a view refreshed only on the incidental model-add triggers the
    # styling step happens to fire, and read the result tiles before the
    # buried area and affinity behind them had been stored.
    notify_state_changed(session, ref.model_id)
    return result


def _characterise_steps(  # noqa: N803
    session, summary, model, ref, group_a, group_b, distance, criterion, style,
    paeFile=None, summaryFile=None,  # noqa: N803
):
    interface = cmd_interface(
        session, group_a, group_b, model=model, distance=distance, criterion=criterion
    )
    summary["steps"].append("interface")
    summary["interface"] = {
        "chains_a": list(state_for(session).interface_params[ref.model_id][0]),
        "chains_b": list(state_for(session).interface_params[ref.model_id][1]),
        "criterion": criterion,
        "cutoff": distance,
        "residues_a": len(interface.group_a),
        "residues_b": len(interface.group_b),
        "contact_pairs": len(interface.contacts),
    }

    def _attempt(name, function):
        try:
            value = function()
        except UserError as error:
            summary["skipped"][name] = str(error)
            return None
        summary["steps"].append(name)
        return value

    interactions = _attempt(
        "interactions", lambda: cmd_interactions(session, model=model)
    )
    if interactions is not None:
        summary["interactions"] = summarize(interactions)
        summary["interaction_detail"] = describe(interactions)

    area = _attempt("buried_area", lambda: cmd_buriedarea(session, model=model))
    if isinstance(area, (int, float)):
        summary["buried_area"] = float(area)

    affinity = _attempt("affinity", lambda: cmd_affinity(session, model=model))
    if affinity is not None:
        summary["affinity"] = {
            "delta_g": affinity.delta_g,
            "kd": affinity.kd,
            "temperature": affinity.temperature,
        }

    hotspots = _attempt("hotspots", lambda: cmd_hotspots(session, model=model, top=10))
    if hotspots:
        summary["hotspots"] = [
            {
                "residue": f"{name} {chain}:{number}{icode}".strip(),
                "buried_area": round(delta, 1),
            }
            for (chain, number, icode), name, _a, _c, delta in hotspots
        ]

    confidence = _attempt("confidence", lambda: cmd_confidence(session, model=model))
    if confidence:
        summary["confidence"] = {
            key: value for key, value in confidence.items() if value is not None
        }

    # ipSAE, pDockQ2 and LIS need the PAE matrix, which `confidence` does not
    # read — it works from coordinates and B-factors alone. Leaving this out
    # meant "characterise everything" returned every geometric quantity and
    # none of the three scores that actually say whether a predicted interface
    # should be believed. The PAE file is discovered beside the model; when
    # there is none, or the tokens do not line up with the residues, that is
    # reported under "skipped" like any other step.
    # The two files carry through. Characterise is the button the panel runs
    # after a file is chosen by hand, and it used to discard both — so a user
    # who pointed at the PAE and the summary, then pressed Characterise
    # Interface again to see the numbers change, saw them not change. The
    # files were being found for the capabilities card and nowhere else.
    scores = _attempt(
        "interface_scores",
        lambda: cmd_ipsae(
            session, paeFile, model=model, summaryFile=summaryFile
        ) if paeFile else cmd_ipsae(session, model=model, summaryFile=summaryFile),
    )
    if scores:
        summary["interface_scores"] = _scores_for_pair(
            scores,
            summary["interface"]["chains_a"],
            summary["interface"]["chains_b"],
        )

    if style:
        _attempt("figure", lambda: cmd_style(session, "interface-focus", model=model))

    session.logger.info(
        f"MolCompose characterisation of {ref.model_id} complete: "
        f"{', '.join(summary['steps'])}"
        + (f" (skipped: {', '.join(summary['skipped'])})" if summary["skipped"] else "")
    )
    return summary


def _focus_geometric(session, target, model):
    """Face-on and open-book, the two interface views dragging cannot reach.

    Face-on looks down the axis joining the two interface centroids, so the
    contact patch reads as a footprint. Open book separates the partners along
    that axis and turns one a half circle about a shared perpendicular, so
    both binding faces end up presented at once.

    Open book moves the coordinates, which is the only way to do it and is why
    it warns: a figure exported afterwards shows a complex that has been taken
    apart, and `molcompose reset` is what puts it back.
    """
    model = resolve_model(session, model)
    ref = model_ref(model)
    interface = state_for(session).interfaces.get(ref.model_id)
    if interface is None:
        raise _detect_interface_missing(session, ref.model_id)
    coords_a = _interface_coords(model, interface.group_a)
    coords_b = _interface_coords(model, interface.group_b)
    if not coords_a or not coords_b:
        raise UserError("the detected interface has no coordinates to orient by")

    try:
        if target == "faceon":
            axis = interface_axis(coords_a, coords_b)
            commands = (
                f"view matrix camera {_camera_along(axis)}",
                f"view {ref.atomspec} pad {VIEW_PAD}",
            )
        else:
            left, right = open_book(coords_a, coords_b)
            # The camera has to move too. Flipping one partner leaves both
            # binding faces pointing the same way along the interface axis,
            # and from the viewer's previous angle that reads as a jumble
            # rather than as an opened book.
            axis = interface_axis(coords_a, coords_b)
            commands = (
                *_open_book_commands(ref, interface, left, right),
                f"view matrix camera {_camera_along(axis)}",
                f"view {ref.atomspec} pad {VIEW_PAD}",
            )
    except ValueError as error:
        raise UserError(str(error)) from error

    for command in commands:
        _run(session, command)
    _record(session, f"molcompose focus {target}{_model_suffix(ref)}", ref)
    if target == "openbook":
        session.logger.warning(
            f"MolCompose moved the two partners of {ref.model_id} apart to open "
            f"the interface. The coordinates have changed; 'molcompose reset "
            f"model {ref.model_id}' restores them."
        )
    session.logger.info(f"MolCompose set the {target} view for {ref.model_id}")
    return commands


def _interface_coords(model, keys) -> list[tuple[float, float, float]]:
    wanted = {(key.chain_id, key.number, key.insertion_code) for key in keys}
    return [
        point.xyz
        for point in atom_points(model, {key.chain_id for key in keys}, "cbeta")
        if (point.residue.chain_id, point.residue.number,
            point.residue.insertion_code) in wanted
    ]


def _camera_along(axis) -> str:
    """A camera matrix looking down `axis`, as ChimeraX's `view matrix` wants it."""
    forward = normalise(axis)
    up = perpendicular(forward)
    right = cross(up, forward)
    rows = (right, up, forward)
    return ",".join(
        f"{rows[row][column]:.6f}" if column < 3 else "0"
        for row in range(3)
        for column in range(4)
    )


def _open_book_commands(ref, interface, left, right) -> tuple[str, ...]:
    chains_a = "|".join(
        sorted({f"{ref.model_id}/{key.chain_id}" for key in interface.group_a})
    )
    chains_b = "|".join(
        sorted({f"{ref.model_id}/{key.chain_id}" for key in interface.group_b})
    )
    commands = []
    for spec, placement in ((chains_a, left), (chains_b, right)):
        if not spec:
            continue
        if placement.angle:
            axis = ",".join(f"{value:.6f}" for value in placement.axis)
            centre = ",".join(f"{value:.6f}" for value in placement.centre)
            commands.append(
                f"turn {axis} {placement.angle:g} center {centre} "
                f"models {spec} coordinateSystem {ref.model_id}"
            )
        shift = ",".join(f"{value:.6f}" for value in placement.shift)
        commands.append(f"move {shift} models {spec} coordinateSystem {ref.model_id}")
    return tuple(commands)


def _define_blocks(session, ref, interface, chains_a, chains_b) -> tuple[Block, ...]:
    """Name the four parts of the complex, replacing any previous definition.

    The names are cleared first rather than overwritten: re-detecting at a
    different cutoff produces a different interface, and a name still pointing
    at the old residue list is the same staleness as a cached analysis
    outliving its model. Clearing is best-effort — a name that was never
    defined is not an error worth surfacing.
    """
    by_chain = {chain.chain_id: chain.atomspec for chain in ref.chains}
    specs = {
        "groupA": "|".join(by_chain[c] for c in chains_a if c in by_chain),
        "groupB": "|".join(by_chain[c] for c in chains_b if c in by_chain),
        "ifaceA": compact_residue_spec(interface.group_a) if interface.group_a else "",
        "ifaceB": compact_residue_spec(interface.group_b) if interface.group_b else "",
    }
    with _nested(session):
        for command in clear_block_commands(ref.model_id):
            try:
                _run(session, command)
            except Exception:  # noqa: BLE001 - undefined name, nothing to clear
                pass
        for command in define_block_commands(ref.model_id, specs):
            _run(session, command)

    counts = {
        "groupA": sum(1 for c in chains_a if c in by_chain),
        "groupB": sum(1 for c in chains_b if c in by_chain),
        "ifaceA": len(interface.group_a),
        "ifaceB": len(interface.group_b),
    }
    blocks = tuple(
        Block(kind, block_name(ref.model_id, kind), specs[kind], counts[kind])
        for kind in BLOCK_KINDS
        if specs[kind]
    )
    state_for(session).blocks[ref.model_id] = blocks
    session.logger.info(
        "MolCompose named "
        + ", ".join(f"{b.name} ({b.residue_count})" for b in blocks)
    )
    return blocks


def cmd_blocks(session, *, model=None):
    """List the four named parts of a characterised complex."""
    ref = model_ref(resolve_model(session, model))
    blocks = state_for(session).blocks.get(ref.model_id)
    if not blocks:
        raise _detect_interface_missing(session, ref.model_id)
    session.logger.info(f"MolCompose blocks for {ref.model_id}:")
    for block in blocks:
        session.logger.info(
            f"  {block.name} — {block.label}, {block.residue_count} "
            + ("chains" if block.kind.startswith("group") else "residues")
        )
    _record(session, f"molcompose blocks{_model_suffix(ref)}", ref)
    return blocks


def _scores_for_pair(scores: dict, chains_a, chains_b) -> list[dict]:
    """The PAE scores for the chain pairs spanning the detected interface.

    `cmd_ipsae` scores every pair of chains in the model, which is the right
    answer to "what does the PAE say about this prediction" and the wrong one
    to "what does it say about the interface I just characterised". A
    six-chain crystal form would bury the pair being described in fourteen
    others.
    """
    wanted = {
        frozenset((a, b))
        for a in chains_a
        for b in chains_b
        if a != b
    }
    rows = []
    for pair, values in scores.items():
        left, _, right = pair.partition("-")
        if frozenset((left, right)) not in wanted:
            continue
        rows.append({
            "chains": pair,
            "ipsae": values.get("max"),
            "pdockq2": values.get("pdockq2"),
            "lis": values.get("lis"),
            # Kept apart on purpose: `iptm` is this pair's, `iptm_global` is
            # the whole model's and is all some engines report.
            "iptm": values.get("iptm"),
            "iptm_global": values.get("iptm_global"),
        })
    return rows


def cmd_report(session, path, *, model=None, format=None):  # noqa: A002
    """Write a complete interface characterization report."""
    model = resolve_model(session, model)
    ref = model_ref(model)
    state = state_for(session)
    params = state.interface_params.get(ref.model_id)
    interface = state.interfaces.get(ref.model_id)
    if params is None or interface is None:
        raise _detect_interface_missing(session, ref.model_id)

    target = Path(path)
    fmt = (format or target.suffix.lstrip(".") or "md").lower()
    if fmt == "markdown":
        fmt = "md"
    if fmt not in FORMATS:
        raise UserError(f"report format must be one of {', '.join(FORMATS)}: {fmt}")
    if not target.parent.is_dir():
        raise UserError(f"output directory does not exist: {target.parent}")

    chains_a, chains_b, criterion, cutoff = params

    # Fill in the analyses that have not been run yet; failures degrade the
    # report rather than aborting it. These are nested so that writing a report
    # does not add commands to the recipe the report itself prints.
    buried_area = None
    affinity = None
    confidence = None
    with _nested(session):
        try:
            area = cmd_buriedarea(session, model=model)
            buried_area = float(area) if isinstance(area, (int, float)) else None
        except (UserError, TypeError, ValueError):
            pass
        try:
            result = cmd_affinity(session, model=model)
            affinity = {
                "delta_g": result.delta_g,
                "kd": result.kd,
                "temperature": result.temperature,
                "contact_pairs": result.contact_pairs,
            }
        except UserError:
            pass
        try:
            metrics = cmd_confidence(session, model=model)
            confidence = {
                key: metrics[key]
                for key in ("mean_plddt", "iplddt", "pdockq")
                if metrics.get(key) is not None
            } or None
        except UserError:
            pass

    interactions = state.interactions.get(ref.model_id, ())
    counts = summarize(interactions) if interactions else {}

    def label(key):
        return f"{key.name} {key.chain_id}:{key.number}{key.insertion_code}".strip()

    data = ReportData(
        model_id=ref.model_id,
        model_name=ref.name,
        chains_a=tuple(chains_a),
        chains_b=tuple(chains_b),
        criterion=criterion,
        cutoff=cutoff,
        residues_a=len(interface.group_a),
        residues_b=len(interface.group_b),
        contact_pairs=len(interface.contacts),
        interface_residues=tuple(
            [("A", label(key)) for key in interface.group_a]
            + [("B", label(key)) for key in interface.group_b]
        ),
        interactions=tuple(
            {
                "kind": item.kind,
                "residue_a": label(item.a),
                "residue_b": label(item.b),
                "distance": item.distance,
                "detail": item.detail,
            }
            for item in interactions
        ),
        interaction_counts=counts,
        buried_area=buried_area,
        affinity=affinity,
        confidence=confidence,
        commands=recipe_commands(session),
        command_log=recipe_log(session),
        software={"molcompose": _version(), "chimerax": _chimerax_version(session)},
    )
    try:
        target.write_text(render(data, fmt), encoding="utf-8")
    except OSError as error:
        raise UserError(str(error)) from error
    if not data.commands:
        # The record says so in its provenance sentence, but every other
        # section of an empty-recipe file reads exactly as usual and that
        # sentence is not where anyone looks. Saying it in the log too is what
        # turns it into something the user meets now rather than something a
        # reviewer meets later.
        session.logger.warning(
            f"MolCompose report {target}: no command recipe was recorded for "
            f"{ref.model_id}, so this record cannot be replayed from itself"
        )
    # Recorded after writing, so the recipe inside the file is the analysis that
    # produced it rather than a record that includes its own export.
    _record(session, f"molcompose report {target}{_model_suffix(ref)} format {fmt}", ref)
    session.logger.info(f"MolCompose report written to {target} ({fmt})")
    # A string, not a Path: the REST bridge serialises whatever a command
    # returns, and a Path is not JSON-serialisable, so returning one drops the
    # connection and takes the ChimeraX process down with it. That is the whole
    # agent path, and the failure looks like a network error rather than a type
    # error, so it is worth the explicit note. See cmd_export for the same fix.
    return str(target)


def _version() -> str:
    from . import __version__

    return __version__


def _chimerax_version(session) -> str:
    try:
        from chimerax.core import buildinfo

        return str(buildinfo.version)
    except Exception:  # noqa: BLE001 - version is descriptive metadata only
        return "unknown"


def cmd_reset(session, *, model=None):
    model = resolve_model(session, model)
    ref = model_ref(model)
    commands = reset_commands(ref)
    for command in commands:
        _run(session, command)
    _record(session, f"molcompose reset{_model_suffix(ref)}", ref)
    session.logger.info(f"MolCompose reset {ref.model_id} to the neutral baseline")
    return commands



def cmd_overview(session):
    """List the subcommands, because `molcompose` alone is what people type.

    ChimeraX answers a bare command family with "Incomplete command", which is
    accurate and useless: it is the first thing someone types after installing,
    and it tells them nothing about what they installed.
    """
    registry = _command_registry()
    session.logger.info(
        f"MolCompose {_version()} — {len(registry)} commands. "
        "Every one of them writes itself to this Log, so an analysis can be "
        "replayed from it."
    )
    for name in sorted(registry):
        if name == "molcompose":
            continue
        synopsis = getattr(registry[name][1], "synopsis", "") or ""
        session.logger.info(f"  {name:<28} {synopsis}")
    session.logger.info(
        "  'usage <command>' gives the arguments; the panel is at "
        "Tools → Structure Analysis → MolCompose"
    )
    return tuple(sorted(name for name in registry if name != "molcompose"))


def _command_registry():
    from chimerax.atomic import AtomicStructureArg
    from chimerax.core.commands import BoolArg, CmdDesc, FloatArg, IntArg, StringArg

    return {
        "molcompose": (
            cmd_overview,
            CmdDesc(synopsis="List the MolCompose commands"),
        ),
        "molcompose style": (
            cmd_style,
            CmdDesc(
                required=[("preset", StringArg)],
                keyword=[("model", AtomicStructureArg), ("labels", IntArg),
                         ("rankBy", StringArg), ("references", StringArg),
                         ("align", StringArg), ("partner", StringArg)],
                synopsis="Apply a versioned MolCompose visual preset",
            ),
        ),
        "molcompose ddg": (
            cmd_ddg,
            CmdDesc(
                required=[("path", StringArg)],
                keyword=[
                    ("interfaceOnly", BoolArg),
                    ("model", AtomicStructureArg),
                    ("format", StringArg),
                    ("statistic", StringArg),
                    ("top", IntArg),
                ],
                synopsis="Load predicted mutation effects (ΔΔG) from a predictor",
            ),
        ),
        "molcompose flexibility": (
            cmd_flexibility,
            CmdDesc(
                required=[("path", StringArg)],
                keyword=[
                    ("chains", StringArg),
                    ("model", AtomicStructureArg),
                ],
                synopsis="Load per-residue RMS fluctuation from a trajectory",
            ),
        ),
        "molcompose energy": (
            cmd_energy,
            CmdDesc(
                required=[("path", StringArg)],
                keyword=[
                    ("chains", StringArg),
                    ("model", AtomicStructureArg),
                    ("top", IntArg),
                    ("solvation", StringArg),
                ],
                synopsis="Load a per-residue MM/PBSA decomposition",
            ),
        ),
        "molcompose color by": (
            cmd_color_by,
            CmdDesc(
                required=[("metric", StringArg)],
                keyword=[
                    ("model", AtomicStructureArg),
                    ("statistic", StringArg),
                    ("scope", StringArg),
                ],
                synopsis="Colour residues by a per-residue metric",
            ),
        ),
        "molcompose hotspots": (
            cmd_hotspots,
            CmdDesc(
                keyword=[
                    ("metric", StringArg),
                    ("model", AtomicStructureArg),
                    ("minArea", FloatArg),
                    ("top", IntArg),
                ],
                synopsis="Rank interface residues by buried surface area",
            ),
        ),
        "molcompose blocks": (
            cmd_blocks,
            CmdDesc(
                keyword=[("model", AtomicStructureArg)],
                synopsis="List the four named parts of a characterised complex",
            ),
        ),
        "molcompose dockq": (
            cmd_dockq,
            CmdDesc(
                required=[("reference", AtomicStructureArg)],
                keyword=[("model", AtomicStructureArg), ("chainMap", StringArg)],
                synopsis="DockQ and CAPRI components against a reference complex",
            ),
        ),
        "molcompose characterise": (
            cmd_characterise,
            CmdDesc(
                required=[("group_a", StringArg), ("group_b", StringArg)],
                keyword=[
                    ("model", AtomicStructureArg),
                    ("distance", FloatArg),
                    ("criterion", StringArg),
                    ("style", BoolArg),
                    ("paeFile", StringArg),
                    ("summaryFile", StringArg),
                ],
                synopsis="Run the full interface characterisation in one call",
            ),
        ),
        "molcompose report": (
            cmd_report,
            CmdDesc(
                required=[("path", StringArg)],
                keyword=[("model", AtomicStructureArg), ("format", StringArg)],
                synopsis="Write a complete interface characterization report",
            ),
        ),
        "molcompose buriedarea": (
            cmd_buriedarea,
            CmdDesc(
                keyword=[("model", AtomicStructureArg)],
                synopsis="Buried surface area of the detected interface",
            ),
        ),
        "molcompose affinity": (
            cmd_affinity,
            CmdDesc(
                keyword=[("model", AtomicStructureArg), ("temperature", FloatArg)],
                synopsis="Predict binding free energy and Kd (PRODIGY IC-NIS)",
            ),
        ),
        "molcompose interactions": (
            cmd_interactions,
            CmdDesc(
                keyword=[
                    ("model", AtomicStructureArg),
                    ("types", StringArg),
                    ("off", BoolArg),
                    ("saltBridge", FloatArg),
                    ("hydrophobic", FloatArg),
                    ("piStacking", FloatArg),
                    ("cationPi", FloatArg),
                ],
                synopsis="Detect typed non-covalent interactions across the interface",
            ),
        ),
        "molcompose ipsae": (
            cmd_ipsae,
            CmdDesc(
                optional=[("path", StringArg)],
                keyword=[
                    ("model", AtomicStructureArg),
                    ("paeCutoff", FloatArg),
                    ("predictor", StringArg),
                    ("summaryFile", StringArg),
                ],
                synopsis="ipSAE interface scores from a prediction PAE file",
            ),
        ),
        "molcompose interface": (
            cmd_interface,
            CmdDesc(
                required=[("group_a", StringArg), ("group_b", StringArg)],
                keyword=[
                    ("model", AtomicStructureArg),
                    ("distance", FloatArg),
                    ("criterion", StringArg),
                ],
                synopsis="Detect an interface between two protein chain groups",
            ),
        ),
        "molcompose interface all": (
            cmd_interface_all,
            CmdDesc(
                keyword=[
                    ("model", AtomicStructureArg),
                    ("distance", FloatArg),
                    ("criterion", StringArg),
                ],
                synopsis="Detect every contacting protein chain pair",
            ),
        ),
        "molcompose focus": (
            cmd_focus,
            CmdDesc(
                optional=[("target", StringArg)],
                keyword=[("model", AtomicStructureArg)],
                synopsis="Fit the view to a model or detected interface",
            ),
        ),
        "molcompose export": (
            cmd_export,
            CmdDesc(
                required=[("path", StringArg)],
                keyword=[
                    ("width", IntArg),
                    ("height", IntArg),
                    ("supersample", IntArg),
                    ("transparent", BoolArg),
                    ("saveSession", BoolArg),
                    ("overwrite", BoolArg),
                    ("dpi", IntArg),
                    ("saveRecipe", BoolArg),
                    ("keyFontSize", IntArg),
                ],
                synopsis="Export a publication image, with print resolution, "
                         "and optionally the session and command recipe",
            ),
        ),
        "molcompose capabilities": (
            cmd_capabilities,
            CmdDesc(
                keyword=[
                    ("model", AtomicStructureArg),
                    ("predictor", StringArg),
                    ("paeFile", StringArg),
                    ("summaryFile", StringArg),
                ],
                synopsis="Report which analyses this structure supports",
            ),
        ),
        "molcompose confidence": (
            cmd_confidence,
            CmdDesc(
                keyword=[("model", AtomicStructureArg)],
                synopsis="Report pLDDT, ipLDDT, and pDockQ for a predicted model",
            ),
        ),
        "molcompose contacts": (
            cmd_contacts,
            CmdDesc(
                keyword=[("model", AtomicStructureArg), ("off", BoolArg)],
                synopsis="Show close contacts across the detected interface",
            ),
        ),
        "molcompose hbonds": (
            cmd_hbonds,
            CmdDesc(
                keyword=[("model", AtomicStructureArg), ("off", BoolArg)],
                synopsis="Show hydrogen bonds across the detected interface",
            ),
        ),
        "molcompose seqcolor": (
            cmd_seqcolor,
            CmdDesc(
                optional=[("path", StringArg)],
                keyword=[
                    ("model", AtomicStructureArg),
                    ("source", StringArg),
                    ("statistic", StringArg),
                    ("load", BoolArg),
                ],
                synopsis="Export the per-residue colouring as SCF for the "
                         "Sequence Viewer",
            ),
        ),
        "molcompose source": (
            cmd_source,
            CmdDesc(
                required=[("name", StringArg)],
                synopsis="Declare who issues the next command, for the recipe's "
                         "source attribution",
            ),
        ),
        "molcompose reset": (
            cmd_reset,
            CmdDesc(
                keyword=[("model", AtomicStructureArg)],
                synopsis="Reset a model to the MolCompose neutral baseline",
            ),
        ),
    }


def register_command(command_name, logger):
    from chimerax.core.commands import register

    registry = _command_registry()
    if command_name not in registry:
        raise ValueError(f"Unknown MolCompose command: {command_name}")
    callback, descriptor = registry[command_name]
    register(command_name, descriptor, callback, logger=logger)
