"""Typed MCP tool surface over the canonical molcompose commands."""

import argparse
import functools
import json
import re
import sys
from pathlib import Path

from . import __version__
from .assistant import (
    artifact_quality,
    choose_interface,
    compatibility_status,
    export_decision,
    external_evidence_decision,
    figure_plan,
)
from .chimerax import (
    NO_VALUE,
    ChimeraXClient,
    ChimeraXCommandError,
    ChimeraXUnavailable,
    command_value,
    error_text,
    log_text,
)
from .contracts import (
    CRITERION_VALUES,
    DDG_FORMAT_VALUES,
    EXTERNAL_UPLOAD,
    HOTSPOT_METRIC_VALUES,
    INTERACTION_TYPE_VALUES,
    LOCAL_WRITE,
    OPEN_WORLD_MUTATION,
    PREDICTOR_VALUES,
    PRESET_VALUES,
    READ_ONLY,
    REPORT_FORMAT_VALUES,
    SEQUENCE_SOURCE_VALUES,
    SESSION_MUTATION,
    STATISTIC_VALUES,
    AnalysisResult,
    AssistantOutcome,
    ChainGroup,
    Criterion,
    DdgFormat,
    DisplayResult,
    Distance,
    Dpi,
    EvidenceKind,
    FigureArtifactResult,
    FigureGoal,
    FocusTarget,
    HotspotMetric,
    ImageDimension,
    InteractionSelection,
    KeyFontSize,
    Labels,
    MinimumArea,
    ModelListResult,
    OperationResult,
    OptionalApiKey,
    PaeCutoff,
    PredictionArtifactResult,
    Predictor,
    Preset,
    PreviewSize,
    PythiaTool,
    ReportArtifactResult,
    ReportFormat,
    SequenceSource,
    ServerProfile,
    Solvation,
    Statistic,
    Supersample,
    Temperature,
    TopCount,
)
from .launch import BUNDLE_MISSING, ChimeraXNotFound, bridge_is_up, bundle_is_missing, start
from .output_contract import preserve_output_fields, report_tool_errors
from .presentation import present_analysis
from .recipe import RecipeLog, build_provenance, read_canonical_recipe
from .validate import (
    chain_id,
    chain_ids,
    enum_value,
    model_spec,
    one_of,
    structure_path,
    token,
    token_list,
)
from .validate import (
    chain_map as validate_chain_map,
)

# Kept in lockstep with the bundle; cross-checked by mcp/tests against src/.
PRESETS = PRESET_VALUES

# Presets that overlay reference structures on a characterised model. They
# need three arguments the others do not take, so naming one without them
# cannot produce a working command. Listing a preset in PRESETS without
# listing its requirements here is what makes an agent pick a style it can
# see and cannot call; `test_reference_presets_stay_in_lockstep_with_bundle`
# checks this tuple against the bundle's own `reference_comparison` flag.
REFERENCE_PRESETS = ("design-reference",)
#: Kept beside CRITERIA so the closed sets an argument may take are all in
#: one place. They mirror src/core/report.py and src/core/ddg.py; a value
#: the bundle would reject is rejected here first, before it is spliced
#: into a command line.
REPORT_FORMATS = REPORT_FORMAT_VALUES
DDG_FORMATS = DDG_FORMAT_VALUES
CRITERIA = CRITERION_VALUES
STATISTICS = STATISTIC_VALUES
HOTSPOT_METRICS = HOTSPOT_METRIC_VALUES
INTERACTION_TYPES = INTERACTION_TYPE_VALUES
PREDICTORS = PREDICTOR_VALUES
SEQUENCE_SOURCES = SEQUENCE_SOURCE_VALUES
DISTANCE_RANGE = (2.0, 10.0)
PROFILE_VALUES = ("assistant", "expert", "all")


def _server_instructions(profile: ServerProfile) -> str:
    """Guidance that names only tools exposed by the selected profile."""
    common = (
        "Analyse protein-protein interfaces and compose reproducible "
        "publication figures in UCSF ChimeraX through MolCompose.\n\n"
        "Read the `skipped` block before the numbers. A refused metric is "
        "information, not an omission — report it. Confidence scores are "
        "refused on experimental structures because a B-factor column is "
        "not pLDDT; ipSAE, pDockQ2 and LIS are refused without a PAE file "
        "beside the model. Do not substitute one metric for another, and "
        "do not compute one yourself from coordinates.\n\n"
        "Interpret confidence at the scope it measures: ipTM is a whole-complex "
        "placement score, while pDockQ2 and ipSAE are chain-pair interface "
        "scores and pLDDT is local. A numerical band is meaningful only with "
        "its predictor and oligomeric state. If confidence metrics disagree, "
        "report the disagreement and inspect the PAE-supported interface and "
        "model or seed convergence; do not average or silently choose one. "
        "Interface size alone cannot identify crystal packing — biological "
        "assembly, symmetry contacts, conservation and chemistry are separate "
        "evidence.\n\n"
        "Never report a number without its criterion and cutoff. The "
        "interface `contact_pairs` field counts contacting residue pairs; "
        "label it explicitly, because atom-pair counts differ several-fold. "
        "Unless the user requests another interface definition, keep the "
        "default heavy criterion and 4.5 Å cutoff. "
        "Never call a predicted interface real on one "
        "score. Never say a figure was produced when only the view was "
        "styled."
    )
    if profile == "expert":
        return (
            common
            + "\n\nUse the typed expert tools directly: prefer "
            "`characterise_interface` for the complete analysis battery, "
            "`apply_style` for documented presets, `export_figure` for "
            "artifacts, and treat `get_recipe` as process-scoped history. "
            "Read `molcompose://skill` before an unfamiliar analysis."
        )
    assistant = (
        "\n\nCall `inspect_session` first and respect its compatibility "
        "warning. Then prefer `analyse_interface`: it selects only an "
        "unambiguous model and chain pair, or returns choices, before "
        "running the complete characterisation battery. Use "
        "`compose_figure` only selects a tested preset. Call "
        "`render_preview` and inspect whether the "
        "subject is cropped, labels overlap, or a colour key is unreadable. "
        "If the preview is unavailable or ambiguous, say that you cannot "
        "visually verify the figure instead of claiming it passed review. "
        "Only then use `export_artifact` for output: it asks before overwrite and saves "
        "the canonical ChimeraX session recipe plus scoped provenance. The "
        "guided tools already carry the policy needed for routine interface "
        "questions, so do not enumerate or read MCP resources first."
    )
    if profile == "assistant":
        return common + assistant
    return (
        common
        + assistant
        + " Process-local history from `get_recipe` can omit earlier panel, "
        "command-line, or MCP-process operations."
    )

# Display-state-only native commands. Everything else is rejected: MolCompose
# is non-destructive by design, and so is its agent surface.
#
# `open` and `close` were on this list until 2026-08-21 and made the comment
# above false. `open` runs a .cxc or a .py as readily as it reads a .pdb, so
# it was arbitrary command execution sitting inside a list of display verbs,
# and `close all` ends the session the agent was asked to describe. Opening a
# structure is still available -- through `open_structure`, which validates
# what it is handed. That is the difference the word "typed" is meant to name.
NATIVE_WHITELIST = frozenset(
    {
        "view",
        "turn",
        "zoom",
        "select",
        "color",
        "show",
        "hide",
        "info",
        "version",
        "lighting",
        "graphics",
        "roll",
        "rock",
        "stop",
        "measure",
    }
)

_INTERFACE_LOG = re.compile(
    r"Group A: (?P<a>\d+) residues, Group B: (?P<b>\d+) residues, "
    r"(?P<contacts>\d+) contact pairs"
)
_BLOCK_REPR = re.compile(
    r"^Block\(kind='(?P<kind>[^']+)', name='(?P<name>[^']+)', "
    r"spec='[^']*', residue_count=(?P<count>\d+)\)$"
)
_BLOCK_LABELS = {
    "groupA": "Group A chains",
    "groupB": "Group B chains",
    "ifaceA": "Interface on A",
    "ifaceB": "Interface on B",
}


class WhitelistError(ValueError):
    pass


_TOOLSHED_VERSION = re.compile(
    r"MolCompose\][^)]*\)\*\*\s*\((?P<version>[^)]+)\)|"
    r"MolCompose[^(\n]*\((?P<bare>\d[^)\n]*)\)"
)


def parse_bundle_version(listing: str) -> str:
    """The MolCompose version out of `toolshed list installed`, or "".

    ChimeraX writes the listing as markdown, so the name arrives wrapped in a
    link and the version in the parentheses after it. Returning "" rather than
    a fallback is deliberate: this feeds a provenance record, and an absent
    version is a gap a reader can see, where a stale one reads as fact.
    """
    match = _TOOLSHED_VERSION.search(listing or "")
    if match is None:
        return ""
    return (match.group("version") or match.group("bare") or "").strip()


# Re-export for existing callers. Full native grammar validation is separate
# from command construction; a verb allowlist cannot enforce host semantics.
from .native_commands import native_allowed  # noqa: E402, F401


def quote_path(path) -> str:
    text = str(path)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("\n", " ").replace("\r", " ")
    return f'"{text}"'


def _model_suffix(model: str | None) -> str:
    """` model #1`, or nothing.

    The specifier is validated rather than escaped. Every typed tool routes
    its `model` argument through here, so this one function is where
    `model="#1; delete all"` stops being a working way to run `delete all`.
    """
    checked = model_spec(model)
    return f" model {checked}" if checked else ""


def build_style_command(preset: str, model: str | None = None,
                        labels: int | None = None,
                        references: str | None = None,
                        align: str | None = None,
                        partner: str | None = None) -> str:
    if preset not in PRESETS:
        raise ValueError(f"unknown MolCompose preset: {preset}; choose from {', '.join(PRESETS)}")
    command = f"molcompose style {preset}{_model_suffix(model)}"
    if labels is not None:
        if labels < 0:
            raise ValueError("labels must be 0 or more")
        command += f" labels {labels}"
    reference_spec = model_spec(references, "references")
    given = tuple(
        name
        for name, value in (
            ("references", reference_spec), ("align", align), ("partner", partner)
        )
        if value
    )
    if preset in REFERENCE_PRESETS:
        if len(given) != 3:
            missing = [n for n in ("references", "align", "partner") if n not in given]
            raise ValueError(
                f"{preset} needs references, align and partner; missing "
                f"{', '.join(missing)}. Open the reference structures first, "
                f"then name them, e.g. references='#2,#3', align='A', partner='B'"
            )
        command += (
            f" references {reference_spec}"
            f" align {chain_id(align, 'align')}"
            f" partner {chain_id(partner, 'partner')}"
        )
    elif given:
        raise ValueError(
            f"{preset} does not take {', '.join(given)}; only "
            f"{', '.join(REFERENCE_PRESETS)} overlays reference structures"
        )
    return command


def build_interface_command(
    group_a: list[str],
    group_b: list[str],
    model: str | None = None,
    distance: float = 4.5,
    criterion: str = "heavy",
) -> str:
    if criterion not in CRITERIA:
        raise ValueError(f"criterion must be one of {', '.join(CRITERIA)}: {criterion}")
    low, high = DISTANCE_RANGE
    if not low <= distance <= high:
        raise ValueError(f"distance must be between {low} and {high} Å: {distance}")
    if not group_a or not group_b:
        raise ValueError("both chain groups need at least one chain ID")
    a_text = ",".join(chain_ids(group_a, "group_a"))
    b_text = ",".join(chain_ids(group_b, "group_b"))
    command = f"molcompose interface {a_text} {b_text}{_model_suffix(model)} distance {distance:g}"
    if criterion != "heavy":
        command += f" criterion {criterion}"
    return command


def build_export_command(  # noqa: PLR0913 - one keyword per export option
    path,
    width: int = 2400,
    height: int = 1800,
    supersample: int = 3,
    transparent: bool = False,
    save_session: bool = False,
    overwrite: bool = False,
    dpi: int = 300,
    save_recipe: bool = False,
    key_font_size: int | None = None,
) -> str:
    def flag(value: bool) -> str:
        return "true" if value else "false"

    return (
        f"molcompose export {quote_path(path)} width {width} height {height} "
        f"supersample {supersample} transparent {flag(transparent)} "
        f"saveSession {flag(save_session)} overwrite {flag(overwrite)} "
        f"dpi {dpi} saveRecipe {flag(save_recipe)}"
        + (f" keyFontSize {key_font_size}" if key_font_size is not None else "")
    )


def build_hotspots_command(
    model: str | None = None,
    min_area: float = 10.0,
    top: int = 0,
    metric: str = "dsasa",
) -> str:
    """`metric` picks the question, so the command has to carry it.

    `min_area` is a ΔSASA threshold and means nothing to an energy ranking, so
    it is not sent with one — passing it would read as a filter that silently
    did nothing.
    """
    metric = enum_value(metric, HOTSPOT_METRICS, "metric")
    command = f"molcompose hotspots{_model_suffix(model)}"
    if min_area != 10.0 and metric == "dsasa":
        command += f" minArea {min_area:g}"
    if top:
        command += f" top {top}"
    if metric != "dsasa":
        command += f" metric {metric}"
    return command


def build_flexibility_command(path, chains: str, model: str | None = None) -> str:
    """`chains` is one per block of the file, ordered — see cmd_flexibility."""
    checked_chains = ",".join(chain_ids(chains, "chains"))
    return (
        f"molcompose flexibility {quote_path(path)} chains {checked_chains}"
        f"{_model_suffix(model)}"
    )


def name_block_rows(value) -> list[dict] | None:
    """`blocks` rows as records, so an agent does not index into a tuple."""
    if not isinstance(value, (list, tuple)):
        return None
    rows = []
    for block in value:
        if isinstance(block, dict):
            rows.append(block)
        elif isinstance(block, (list, tuple)) and len(block) >= 4:
            kind, name, label, count = block[:4]
            rows.append({"kind": kind, "name": name,
                         "label": label, "count": count})
        elif isinstance(block, str):
            match = _BLOCK_REPR.fullmatch(block)
            if match is None or match.group("kind") not in _BLOCK_LABELS:
                return None
            kind = match.group("kind")
            rows.append({
                "kind": kind,
                "name": match.group("name"),
                "label": _BLOCK_LABELS[kind],
                "count": int(match.group("count")),
            })
        else:
            return None
    return rows or None


def parse_interface_counts(text: str) -> dict | None:
    match = _INTERFACE_LOG.search(text)
    if match is None:
        return None
    return {
        "group_a_residues": int(match.group("a")),
        "group_b_residues": int(match.group("b")),
        "contact_pairs": int(match.group("contacts")),
    }


def _info_rows(value) -> list[dict] | None:
    """Decode the value returned by ChimeraX ``info`` commands.

    In ChimeraX 1.12, ``info models`` and ``info chains`` use ``JSONResult``
    whose JSON value is itself a JSON string.  The REST bridge therefore
    returns a string containing an array rather than the array directly.
    Keep that host-specific double encoding local to the two discovery calls;
    an ordinary string returned by another MolCompose command must stay a
    string.
    """
    if value is NO_VALUE:
        return None
    decoded = value
    if isinstance(decoded, str):
        try:
            decoded = json.loads(decoded)
        except ValueError:
            return None
    if not isinstance(decoded, list):
        return None
    return [row for row in decoded if isinstance(row, dict)]


def normalise_model_listing(
    models_value,
    chains_value,
    models_log: str = "",
    chains_log: str = "",
) -> dict:
    """Return concise structure discovery data from native ChimeraX ``info``.

    Native ``info chains`` includes every sequence and residue atomspec.  The
    agent needs only model identity, chain identity and polymer type to choose
    an analysis, so returning the full rows wastes context and can bury the
    two chain identifiers under hundreds of residue entries.  Log text remains
    as a fallback for bridges that were not started with ``json true``.
    """
    result: dict[str, object] = {"models": [], "chains": [], "log": ""}

    model_rows = _info_rows(models_value)
    model_specs: list[str] = []
    if model_rows is not None:
        result["models"] = [
            {
                "spec": row.get("spec"),
                "name": row.get("value"),
                "class": row.get("class"),
            }
            for row in model_rows
            if row.get("present", True)
            and row.get("class") != "PseudobondGroup"
        ]
        model_specs = [
            row["spec"]
            for row in result["models"]
            if isinstance(row.get("spec"), str)
        ]
    elif models_log.strip():
        result["models_text"] = models_log.strip()

    chain_rows = _info_rows(chains_value)
    if chain_rows is not None:
        chains = []
        for row in chain_rows:
            if not row.get("present", True):
                continue
            spec = row.get("spec")
            explicit_model = (
                spec.split("/", 1)[0]
                if isinstance(spec, str) and spec.startswith("#") and "/" in spec
                else None
            )
            residues = row.get("residues")
            sequence = row.get("sequence")
            residue_count = (
                len(residues)
                if isinstance(residues, list)
                else len(sequence)
                if isinstance(sequence, str)
                else None
            )
            chains.append(
                {
                    "spec": spec,
                    "model_spec": (
                        explicit_model
                        if explicit_model is not None
                        else model_specs[0]
                        if len(model_specs) == 1
                        else None
                    ),
                    "chain_id": row.get("value", row.get("chain_id")),
                    "polymer_type": row.get("polymer type"),
                    "residue_count": residue_count,
                }
            )
        result["chains"] = chains
    elif chains_log.strip():
        result["chains_text"] = chains_log.strip()

    logs = "\n".join(text.strip() for text in (models_log, chains_log) if text.strip())
    result["log"] = logs
    return result


BRIDGE_TEXT_ONLY = (
    "The ChimeraX REST bridge is not in JSON mode, so this command's return "
    "value could not be read and only the log is reported. Restart the bridge "
    "with: remotecontrol rest start port 3000 json true"
)


def with_log(log: str, value=NO_VALUE, **values) -> dict:
    """A tool result: the values at the top level, the ChimeraX log alongside.

    The log is kept as one field rather than as the payload. An agent that
    wants the numbers reads the fields; one that wants to see what ChimeraX
    actually did — or to show a user the same lines they would have seen in
    the Log — reads ``log``.
    """
    result = {key: item for key, item in values.items() if item is not None}
    result["log"] = log
    if value is NO_VALUE:
        result["note"] = BRIDGE_TEXT_ONLY
    return result


def name_hotspot_rows(value) -> list[dict] | None:
    """Name the fields of `cmd_hotspots`' rows.

    The command returns ``((chain, number, icode), name, alone, complexed,
    delta)`` per residue, which crosses the bridge as a positional array. The
    numbers are all there; only the field names are lost, and this puts them
    back. ``buried_area`` is the ΔSASA the hot-spot ranking is ordered by —
    the residue's solvent-accessible area alone minus its area in the complex.
    """
    if not isinstance(value, (list, tuple)):
        return None
    rows = []
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) != 5:
            return None
        key, name, alone, complexed, delta = row
        if not isinstance(key, (list, tuple)) or len(key) != 3:
            return None
        chain, number, icode = key
        rows.append(
            {
                "residue": f"{name} {chain}:{number}{icode}".strip(),
                "chain": chain,
                "number": number,
                "insertion_code": icode,
                "name": name,
                "sasa_alone": alone,
                "sasa_complexed": complexed,
                "buried_area": delta,
            }
        )
    return rows


def name_ddg_rows(value) -> list[dict] | None:
    """Name the fields of `cmd_ddg`' rows: ((chain, position), wild_type, ddg, n)."""
    if not isinstance(value, (list, tuple)):
        return None
    rows = []
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            return None
        key, wild_type, ddg, mutations = row
        if not isinstance(key, (list, tuple)) or len(key) != 2:
            return None
        chain, position = key
        rows.append(
            {
                "residue": f"{wild_type} {chain}:{position}",
                "chain": chain,
                "position": position,
                "wild_type": wild_type,
                "ddg": ddg,
                "mutations": mutations,
            }
        )
    return rows


def command_list(value) -> list[str] | None:
    """The ChimeraX commands a display tool issued, as a list of strings.

    The display presets return the commands they ran rather than a
    measurement: that *is* their result, and it is what makes a styling step
    reproducible by hand or replayable into another session.
    """
    if not isinstance(value, (list, tuple)):
        return None
    return [str(item) for item in value]


# --- MCP wiring -----------------------------------------------------------

def create_server(chimerax_url: str = "http://127.0.0.1:3000",
                  source: str = "agent", launch: bool = True,
                  profile: ServerProfile = "all"):
    """`source` names who is issuing, for the bundle's provenance record.

    "agent" is all this server can know on its own: it is a stdio server and
    the client that launched it is its parent process, not something it can
    identify. The panel does know — it launches the CLI itself — so it passes
    a name like "agent:codex" through the config it writes, and a session
    that used two clients can be told apart afterwards.

    The name is the CLI, not the model. Which model a CLI ran is inside that
    CLI, and recording a guess would be worse than recording the tool.
    """
    from mcp.server.mcpserver import Context, Image, MCPServer
    from mcp.types import CallToolResult, TextContent

    if profile not in PROFILE_VALUES:
        raise ValueError(
            f"unknown MCP profile {profile!r}; choose assistant, expert, or all"
        )

    app = MCPServer(
        "molcompose",
        # Sent to every client at connect, whatever it is and without the user
        # installing anything. That makes it the only place guidance reaches an
        # agent for free — a skill file has to be copied into a directory the
        # client happens to read, which most do not have. So the few rules an
        # agent gets wrong without being told live here, and the long-form
        # judgement is served as `molcompose://skill` rather than asked of the
        # user — a skill file installed by hand reaches only clients that have
        # a skills directory, and only users who knew to look.
        instructions=_server_instructions(profile),
    )

    def expose_tool(*profiles: ServerProfile, **options):
        """Register at the selected interface seam while keeping local helpers."""
        def register(function):
            if profile == "all" or profile in profiles:
                registered = (
                    preserve_output_fields(function)
                    if options.get("structured_output")
                    else function
                )
                app.tool(**options)(report_tool_errors(registered))
            return function
        return register

    def expose_resource(*profiles: ServerProfile, uri: str, **options):
        """Keep expert methodology out of the focused assistant discovery path."""
        if profile == "all" or profile in profiles:
            return app.resource(uri, **options)

        def keep_internal(function):
            return function

        return keep_internal

    def _assistant_boundary(operation: str):
        """Turn expert-tool errors into the façade's stable outcome protocol."""
        def decorate(function):
            @functools.wraps(function)
            def guarded(*args, **kwargs):
                try:
                    outcome = function(*args, **kwargs)
                except Exception as error:  # noqa: BLE001 - protocol boundary
                    message = re.sub(
                        r"(?i)(api[_-]?key|authorization)(\s*[:=]\s*)\S+",
                        r"\1\2[REDACTED]",
                        str(error),
                    )
                    bridge_failure = isinstance(error, ChimeraXUnavailable)
                    outcome = {
                        "status": "failed",
                        "error": (
                            "chimerax_operation_failed"
                            if bridge_failure
                            else "operation_failed"
                        ),
                        "message": message,
                        "next_action": (
                            f"Start the MolCompose bridge and retry {operation}."
                            if bridge_failure
                            else (
                                "Resolve the reported issue and retry "
                                f"{operation}."
                            )
                        ),
                    }
                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text=json.dumps(outcome, ensure_ascii=False, default=str),
                    )],
                    structuredContent=outcome,
                )
            return guarded
        return decorate

    client = ChimeraXClient(chimerax_url)
    # Whether this server has already tried to bring ChimeraX up. One attempt
    # per process: a machine with no ChimeraX would otherwise pay the launch
    # timeout on every tool call, and the second failure says nothing the first
    # did not.
    launched = {"tried": not launch, "checked_bundle": False}

    def _ensure_chimerax() -> None:
        """Bring ChimeraX up if nothing is listening, and say so if it cannot be.

        Called before the first command rather than at import: an MCP client
        starts its servers when it starts, often long before anyone asks a
        structural question, and launching a molecular viewer at that moment
        would be startling and usually wasted.
        """
        if bridge_is_up(chimerax_url, timeout=2.0):
            return
        if launched["tried"]:
            return
        launched["tried"] = True
        try:
            if not start(chimerax_url):
                raise ChimeraXUnavailable(
                    f"Started ChimeraX but its bridge never answered on "
                    f"{chimerax_url}. If a ChimeraX is already running, its "
                    "bridge may be on another port — pass --chimerax-url with "
                    "the one it printed."
                )
        except ChimeraXNotFound as error:
            raise ChimeraXUnavailable(str(error)) from error

    recipe = RecipeLog()

    def _remember_client(ctx) -> None:
        try:
            info = ctx.session.client_params.clientInfo
            if info and info.name and recipe.client_name == "unknown":
                version = f" {info.version}" if getattr(info, "version", "") else ""
                recipe.client_name = f"{info.name}{version}"
        except Exception:  # noqa: BLE001 - client identity is best-effort metadata
            pass

    def _invoke(command: str, _source: str = "") -> tuple:
        """Run one command; return its value and its log, not one at the
        expense of the other."""
        effective_source = _source or source
        _ensure_chimerax()
        if not launched["checked_bundle"]:
            launched["checked_bundle"] = True
            if bundle_is_missing(client.run):
                raise ChimeraXUnavailable(BUNDLE_MISSING)
        _declare(effective_source)
        try:
            payload = client.run(command)
            error = payload.get("error")
            if error:
                raise ChimeraXCommandError(command, error_text(error))
        except Exception:
            # The declaration is one-shot and still armed, so disarm it rather
            # than letting it attach to whatever ChimeraX runs next — which,
            # after a failed agent command, may well be the user retrying by
            # hand. Over-attribution is the mild direction, but not free.
            _declare("session")
            raise
        recipe.add(command, effective_source)
        return command_value(payload), log_text(payload)

    def _declare(source: str) -> None:
        """Tell ChimeraX who is issuing the next command.

        ChimeraX's REST control carries no identity, so a command sent from
        here is indistinguishable from one the user typed or curled. Without
        this the bundle recorded every agent command as "session", and the
        report's provenance sentence — written for a Methods section — said the
        user had issued them.

        Best-effort: a bundle too old to know the command would reject it, and
        that must not stop the analysis. The agent-side record in `recipe`
        stays authoritative either way.
        """
        checked_source = token(source, "source")
        try:
            client.run(f"molcompose source {checked_source}")
        except Exception:  # noqa: BLE001, S110 - attribution must not break the call
            pass

    def _run(command: str, _source: str = "") -> str:
        return _invoke(command, _source or source)[1]

    @expose_resource(
        "expert",
        uri="molcompose://skill",
        name="MolCompose interface analysis",
        description=(
            "Which measure answers which question at a protein-protein "
            "interface, which numbers not to believe, and how to read two "
            "measures disagreeing. Read it before an unfamiliar analysis."
        ),
        mime_type="text/markdown",
    )
    def skill() -> str:
        """The domain judgement the tool surface cannot carry.

        Served rather than installed. A skill file copied into a directory by
        hand reaches only the clients that have such a directory and only the
        users who knew to look for it; this reaches anything that speaks MCP,
        with nothing asked of the person running it.

        Shipped in the wheel as package data — see mcp/pyproject.toml. The
        copy at skill/SKILL.md is the one a person browses, and a test keeps
        the two byte-identical.
        """
        return (Path(__file__).with_name("SKILL.md")).read_text(encoding="utf-8")

    @expose_tool("expert", annotations=READ_ONLY, structured_output=True)
    def list_models(ctx: Context) -> ModelListResult:
        """List open structure models and their chains (native ChimeraX info).

        Returns concise structured ``models`` and ``chains`` records.  Sequence
        and residue arrays from ``info chains`` are deliberately omitted; call
        an interface tool for residue-level data."""
        _remember_client(ctx)
        models_value, models_log = _invoke("info models", _source="server")
        chains_value, chains_log = _invoke("info chains", _source="server")
        return normalise_model_listing(
            models_value, chains_value, models_log, chains_log
        )

    @expose_tool("expert", annotations=OPEN_WORLD_MUTATION)
    def open_structure(path_or_id: str, ctx: Context) -> str:
        """Open a local structure file or fetch a PDB ID (native ChimeraX open).

        Refuses paths ChimeraX would execute rather than parse: `open` is one
        command with two jobs, and only fetching a structure is this tool's.
        """
        _remember_client(ctx)
        return _run(f"open {quote_path(structure_path(path_or_id))}")

    if profile == "assistant":
        @app.tool(
            name="open_structure",
            annotations=OPEN_WORLD_MUTATION,
            structured_output=True,
        )
        @_assistant_boundary("open_structure")
        def open_structure_assistant(
            path_or_id: str, ctx: Context
        ) -> AssistantOutcome:
            """Open one validated structure and return a recoverable outcome."""
            return {
                "status": "completed",
                "data": {"log": open_structure(path_or_id, ctx)},
            }

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def apply_style(preset: Preset, model: str | None = None,
                    labels: Labels | None = None,
                    references: str | None = None,
                    align: str | None = None,
                    partner: str | None = None) -> DisplayResult:
        """Apply a versioned MolCompose preset: clean-cartoon, complex-by-chain,
        interface-focus (requires detect_interface first; a rendered look with
        the two partners coloured against each other to show where the
        interface is), flat-outline (same question, drawn flat with a black
        outline instead of shading, which is what survives single-column width
        and greyscale printing), licorice-closeup (every interface side chain
        rather than the top few, with labels and hydrogen bonds, for looking at
        the chemistry rather than the extent), hotspot-focus (also requires
        detect_interface; colours interface residues by buried area on one ramp
        across both partners, to show which residues carry it), or
        predicted-structure (pLDDT confidence coloring for AlphaFold/ESMFold
        output files, with automatic 0-1 / 0-100 scale detection).

        The rest, which this list used to leave out — half the presets the tool
        accepts were undiscoverable, so an agent could only reach them by
        guessing a name. All but metric-map require detect_interface first.

        - licorice-chain: licorice-closeup with each partner's carbons in its
          own colour, for telling the two sides apart in a close-up.
        - paratope-closeup: the binder's interface side chains against a plain
          partner, side-on. Named for a paratope but not restricted to one.
        - surface-complex: both partners as solid surface in chain colours, for
          shape rather than residues.
        - epitope-surface / surface-partner-a: one side drawn as surface with
          the interface painted on it, the other as cartoon. Which side is
          which is the only difference.
        - surface-translucent: the same with the surface see-through, so the
          backbone underneath stays visible.
        - surface-epitope-map: the partner surface coloured by per-residue
          buried area rather than by membership.
        - metric-map: cartoon coloured by whatever per-residue values are
          loaded — ddG, MM/PBSA, RMSF. The one preset that needs no interface.

        `labels` overrides how many residues per side the preset labels; 0 turns
        them off. Leave it out to keep the preset's own count, which differs
        between presets and will differ between panels of one plate.

        design-reference overlays solved or predicted reference structures on a
        characterised design, to show whether the design lands where the
        references do. It is the one preset that takes `references`, `align`
        and `partner`, and it requires all three: open the references first,
        then name them as `references='#2,#3'` with `align` the chain the
        structures are superposed on (the target) and `partner` the chain
        compared across them (the binder). The epitope comes from the detected
        interface, so no residue is named. Two references are the most it can
        draw in distinct colours.

        Returns `commands`: the ChimeraX commands the preset issued."""
        value, text = _invoke(
            build_style_command(preset, model, labels, references, align, partner)
        )
        return with_log(text, value, commands=command_list(value))

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def characterise_interface(
        group_a: ChainGroup,
        group_b: ChainGroup,
        model: str | None = None,
        distance: Distance = 4.5,
        criterion: Criterion = "heavy",
        style: bool = True,
    ) -> AnalysisResult:
        """PREFERRED entry point for describing a protein-protein interface.

        Runs the whole standard characterisation in one call and returns a single
        structured summary: interface residues and contacts, typed non-covalent
        interactions (salt bridges, hydrophobic, pi-stacking, cation-pi,
        disulfide), buried surface area, predicted binding free energy and Kd,
        the residues burying the most surface, prediction-confidence metrics when
        the model is predicted, and the publication figure.

        The summary is returned as values — `interface`, `interactions`,
        `buried_area`, `affinity`, `hotspots`, `confidence`,
        `interface_scores`, and `skipped` — with the ChimeraX log alongside
        them under `log`. Every step that could not run is named in `skipped`
        together with the reason it was refused.

        Use this instead of calling detect_interface, analyze_interactions,
        measure_buried_area, predict_affinity and rank_hotspots one by one:
        anything that does not apply to this structure is reported under
        "skipped" with the reason, rather than failing the call.

        group_a and group_b are lists of bare chain identifiers as they appear
        in the file — ["A"], ["H", "L"] — not ChimeraX atomspecs: "/A" and
        "#1/A" are both rejected. Name the model with the `model` argument
        instead. Call list_models first if the chain identifiers are unknown."""
        checked_a = ",".join(chain_ids(group_a, "group_a"))
        checked_b = ",".join(chain_ids(group_b, "group_b"))
        checked_criterion = enum_value(criterion, CRITERIA, "criterion")
        low, high = DISTANCE_RANGE
        if not low <= distance <= high:
            raise ValueError(f"distance must be between {low} and {high} Å: {distance}")
        command = (
            f"molcompose characterise {checked_a} {checked_b}"
            f"{_model_suffix(model)} distance {distance:g}"
        )
        if checked_criterion != "heavy":
            command += f" criterion {checked_criterion}"
        if not style:
            command += " style false"
        value, text = _invoke(command)
        # `cmd_characterise` already builds exactly this summary, `skipped`
        # entries and all, and it crosses the bridge as a nested JSON object.
        # Spreading it at the top level keeps the shape the command produced
        # rather than burying it a level down under a key of this layer's
        # invention.
        if isinstance(value, dict):
            return present_analysis({**value, "log": text})
        return present_analysis(with_log(text, value))

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def detect_interface(
        group_a: ChainGroup,
        group_b: ChainGroup,
        model: str | None = None,
        distance: Distance = 4.5,
        criterion: Criterion = "heavy",
    ) -> AnalysisResult:
        """Detect interface residues between two non-overlapping chain groups.
        Groups are bare chain identifiers — ["A"], ["H", "L"] — not atomspecs;
        name the model with `model`. criterion 'heavy' = all heavy atoms
        (default cutoff 4.5 Å); 'cbeta' = one Cβ point per residue
        (conventional cutoff 8.0 Å).

        Returns the counts — `residues_a`, `residues_b`, `contact_pairs` — and
        the residues themselves under `group_a` / `group_b`, each named with
        its chain, number and atomspec, plus the contacting pairs."""
        value, text = _invoke(
            build_interface_command(group_a, group_b, model, distance, criterion)
        )
        if isinstance(value, dict):
            return present_analysis({**value, "log": text})
        # A bridge that cannot return values still logs the counts, and those
        # are worth recovering — but say plainly that this is the scraped
        # fallback rather than the reported result.
        return present_analysis(
            with_log(text, value, counts=parse_interface_counts(text))
        )

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def detect_all_interfaces(
        model: str | None = None,
        distance: Distance = 4.5,
        criterion: Criterion = "heavy",
    ) -> AnalysisResult:
        """Report every contacting protein chain pair of the model.

        Returns `pairs`: one record per contacting chain pair, with its
        `chain_a`, `chain_b` and the same interface counts and residues
        `detect_interface` reports."""
        checked_criterion = enum_value(criterion, CRITERIA, "criterion")
        low, high = DISTANCE_RANGE
        if not low <= distance <= high:
            raise ValueError(f"distance must be between {low} and {high} Å: {distance}")
        command = f"molcompose interface all{_model_suffix(model)} distance {distance:g}"
        if checked_criterion != "heavy":
            command += f" criterion {checked_criterion}"
        value, text = _invoke(command)
        return present_analysis(
            with_log(text, value, pairs=value if isinstance(value, list) else None)
        )

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def focus(target: FocusTarget = "interface", model: str | None = None) -> DisplayResult:
        """Fit the view to the whole model or the detected interface.

        Returns `commands`: the ChimeraX commands issued."""
        if target not in ("model", "interface"):
            raise ValueError("target must be model or interface")
        value, text = _invoke(f"molcompose focus {target}{_model_suffix(model)}")
        return with_log(text, value, commands=command_list(value))

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def show_hbonds(model: str | None = None, off: bool = False) -> DisplayResult:
        """Show (or clear, with off=true) hydrogen bonds across the detected
        interface using native ChimeraX hbonds. Requires detect_interface first.

        Returns `commands`: the ChimeraX commands issued."""
        command = f"molcompose hbonds{_model_suffix(model)}"
        if off:
            command += " off true"
        value, text = _invoke(command)
        return with_log(text, value, commands=command_list(value))

    @expose_tool("expert", annotations=LOCAL_WRITE, structured_output=True)
    def write_report(
        path: str,
        model: str | None = None,
        format: ReportFormat | None = None,
    ) -> ReportArtifactResult:
        """Write a complete interface characterization report (json/csv/md) covering
        geometry, typed interactions, buried area, predicted affinity, prediction
        confidence, an auto-written Methods paragraph, and the command recipe.
        Format follows the file suffix unless given. Requires detect_interface.

        Returns `report`: the path written."""
        command = f"molcompose report {quote_path(path)}{_model_suffix(model)}"
        if format:
            command += f" format {one_of(format, REPORT_FORMATS, 'format')}"
        value, text = _invoke(command)
        return with_log(text, value, report=value if isinstance(value, str) else None)

    @expose_tool("expert", annotations=EXTERNAL_UPLOAD, structured_output=True)
    def predict_ddg_pythiastudio(
        structure_path: str,
        output_path: str,
        tool: PythiaTool = "pythia-ppi",
        api_key: OptionalApiKey = None,
    ) -> PredictionArtifactResult:
        """Fetch ΔΔG predictions from the PythiaStudio REST API and write them as a
        tabular file that `load_ddg` can then load. This is the only networked
        tool: the ChimeraX bundle itself never calls out. Requires an API key
        (`PYTHIASTUDIO_API_KEY` preferred; the argument is a deprecated fallback).
        `tool` is 'pythia-ppi' (binding ΔΔG)
        or 'pythia' (stability ΔΔG).

        Returns the `path` written, the number of `mutations` in it and the
        `tool` that produced them — `path` is what load_ddg takes next."""
        from pathlib import Path as _Path

        from .pythiastudio import request_prediction, to_tabular

        payload = request_prediction(structure_path, tool=tool, key=api_key)
        text = to_tabular(payload)
        _Path(output_path).write_text(text, encoding="utf-8")
        rows = text.count("\n") - 1
        return {
            "path": output_path,
            "mutations": rows,
            "tool": tool,
            "log": "PythiaStudio prediction written to a local table.",
        }

    class EnergySolvationRequired(ChimeraXCommandError):
        """The canonical energy parser requires an explicit PB/GB choice."""

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def load_energy(
        path: str,
        chains: str,
        model: str | None = None,
        top: TopCount = 10,
        solvation: Solvation | None = None,
    ) -> OperationResult:
        """Load a per-residue MM/PBSA decomposition written by gmx_MMPBSA
        (FINAL_DECOMP_MMPBSA.dat) — a residue's contribution to binding, which
        is a third notion of "which residue matters" alongside buried area
        (geometry) and predicted ΔΔG (what removing it costs).

        `chains` maps the file's chain letters onto the model's, as in
        'A:A,B:D', and is required: GROMACS relabels chains when a system is
        built, so the file's letters are usually not the structure's, and
        guessing attaches one partner's energies to the other. The residue
        names are checked against the structure and a contradicted map is
        refused.

        When the file carries both PB and GB sections, set `solvation` to
        'pb' or 'gb' explicitly. Neither section is selected by default.

        Values keep the file's sign — negative where a residue contributes
        favourably, the opposite of the ΔΔG convention. The absolute binding
        energy is not loaded: MM/PBSA totals are not comparable with the
        predicted ΔG this tool reports, so only the decomposition is read.
        Colour it with apply_style/color by 'mmpbsa', or rank with
        rank_hotspots(metric='energy')."""
        command = (
            f"molcompose energy {quote_path(path)} chains {validate_chain_map(chains, 'chains')}"
            f"{_model_suffix(model)}"
        )
        if top != 10:
            command += f" top {top}"
        if solvation is not None:
            command += f" solvation {enum_value(solvation, ('pb', 'gb'), 'solvation')}"
        try:
            value, text = _invoke(command)
        except ChimeraXCommandError as error:
            if solvation is None and re.search(
                r"this decomposition carries \d+ solvation models", str(error)
            ):
                raise EnergySolvationRequired(
                    command,
                    f"{error} Retry with solvation='pb' or solvation='gb'.",
                ) from error
            raise
        return present_analysis(with_log(text, value))

    @expose_tool("expert", annotations=READ_ONLY, structured_output=True)
    def list_blocks(model: str | None = None) -> AnalysisResult:
        """The four named parts detection divides a complex into — the group A
        and group B chains, and the interface residues on each side.

        Each is a real ChimeraX name, so it can be used in any display command
        the whitelist allows: `color mc1_ifaceA red`, `show mc1_groupB
        cartoons`, and so on. Without this an agent has to guess those names or
        rebuild the same selections from residue lists it already has.

        Requires detect_interface or characterise_interface first."""
        value, text = _invoke(f"molcompose blocks{_model_suffix(model)}")
        return present_analysis(with_log(text, value, blocks=name_block_rows(value)))

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def load_flexibility(
        path: str,
        chains: str,
        model: str | None = None,
    ) -> OperationResult:
        """Load per-residue RMS fluctuation written by `gmx rmsf -res` — how
        much each residue moves over an MD trajectory. It is the one thing
        every other metric here is blind to: they describe a single
        conformation, this describes how much that conformation moves.

        `chains` names one chain per block of the file, in the order the
        selection was written, as in 'A,D'. It is required because
        `gmx rmsf -res` restarts its numbering at each chain — a two-chain file
        reads 1..110 then 1..89, not 1..199 — and nothing in the file says
        which chain is which.

        Load MD output onto the structure the simulation ran on, not the
        deposited entry: a repaired structure has residues a crystal structure
        lacks, and the counts are checked rather than trimmed to fit.

        Fluctuation is not a contribution. A residue that moves a great deal
        may be a loop nowhere near the interface, and one that barely moves may
        just be buried in the core. Colour it with 'rmsf'."""
        value, text = _invoke(build_flexibility_command(path, chains, model))
        return present_analysis(with_log(text, value))

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def load_ddg(
        path: str,
        model: str | None = None,
        format: DdgFormat | None = None,
        statistic: Statistic = "min",
    ) -> AnalysisResult:
        """Load predicted mutation effects (ΔΔG) produced by an external predictor
        (Pythia, Pythia-PPI, FoldX, Rosetta, ...) and rank interface residues by
        them. `format` is 'tabular' or 'pythia'; `statistic` is min (most
        stabilising), max (most destabilising) or mean. MolCompose does not run
        the predictors — see predict_ddg_pythiastudio to fetch results first.

        Returns `ddg`: one record per residue with its `chain`, `position`,
        `wild_type`, the `ddg` value under the chosen statistic and how many
        `mutations` it was taken over, ordered by that statistic."""
        command = f"molcompose ddg {quote_path(path)}{_model_suffix(model)}"
        if format:
            command += f" format {one_of(format, DDG_FORMATS, 'format')}"
        checked_statistic = enum_value(statistic, STATISTICS, "statistic")
        if checked_statistic != "min":
            command += f" statistic {checked_statistic}"
        value, text = _invoke(command)
        return present_analysis(with_log(text, value, ddg=name_ddg_rows(value)))

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def rank_hotspots(
        model: str | None = None,
        min_area: MinimumArea = 10.0,
        top: TopCount = 0,
        metric: HotspotMetric = "dsasa",
    ) -> AnalysisResult:
        """Rank interface residues by what makes them matter. Requires
        detect_interface first.

        `metric='dsasa'` (default) ranks by buried surface area — the residues
        that contribute most surface. `metric='energy'` ranks by MM/PBSA
        contribution to binding, most favourable (most negative) first, and
        needs load_energy first. They are different questions and can disagree,
        so say which one you used when you report the answer.

        Returns `hotspots`: one entry per residue, ordered by the chosen
        metric, each with its `chain`, `number` and `name`. Under 'dsasa' each
        also carries `buried_area` (Å²) and the `sasa_alone` /
        `sasa_complexed` the difference is taken between; under 'energy' the
        value is kcal/mol and those two are null, because no surface figure was
        measured."""
        value, text = _invoke(
            build_hotspots_command(model, min_area, top, metric)
        )
        return present_analysis(
            with_log(text, value, hotspots=name_hotspot_rows(value))
        )

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def measure_buried_area(model: str | None = None) -> AnalysisResult:
        """Buried solvent-accessible surface area (Å²) of the detected interface.

        Returns `buried_area` as a number, with the log alongside."""
        value, text = _invoke(f"molcompose buriedarea{_model_suffix(model)}")
        area = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        return present_analysis(with_log(text, value, buried_area=area))

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def predict_affinity(
        model: str | None = None,
        temperature: Temperature = 25.0,
    ) -> AnalysisResult:
        """Predict binding free energy (kcal/mol) and dissociation constant Kd (M)
        for the detected interface using the PRODIGY IC-NIS contacts model
        (Vangone & Bonvin, eLife 2015). Requires detect_interface first.

        Returns `affinity`: `delta_g`, `kd`, `temperature`, the contact `bins`
        the model is built on, `nis_apolar` / `nis_charged` percentages and
        `contact_pairs`. Note that the affinity model counts contacts at 5.5 Å,
        not at the interface-detection cutoff."""
        command = f"molcompose affinity{_model_suffix(model)}"
        if temperature != 25.0:
            command += f" temperature {temperature:g}"
        value, text = _invoke(command)
        return present_analysis(
            with_log(text, value, affinity=value if isinstance(value, dict) else None)
        )

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def analyze_interactions(
        model: str | None = None,
        types: InteractionSelection | None = None,
        off: bool = False,
    ) -> AnalysisResult:
        """Detect and display typed non-covalent interactions across the detected
        interface: salt-bridge, hydrophobic, pi-stacking, cation-pi, disulfide.
        `types` is a comma-separated subset; omit for all. Requires
        detect_interface first. Use off=true to clear the display.

        Returns `counts` per interaction type and `items`, one record per
        interaction naming the residues on both sides, their distance and the
        atoms involved — the same shape characterise_interface reports. With
        off=true, returns the display commands it cleared."""
        command = f"molcompose interactions{_model_suffix(model)}"
        if types:
            command += f" types {','.join(token_list(types, INTERACTION_TYPES, 'types'))}"
        if off:
            command += " off true"
        value, text = _invoke(command)
        if isinstance(value, dict):
            return present_analysis({**value, "log": text})
        return present_analysis(with_log(text, value))

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def compute_ipsae(
        pae_file: str,
        model: str | None = None,
        pae_cutoff: PaeCutoff = 10.0,
    ) -> AnalysisResult:
        """ipSAE interface scores (Dunbrack 2025, d0res variant) from a
        prediction's PAE file (AF2/AF3/ColabFold JSON or Boltz NPZ).

        Returns `interface_scores`, keyed by chain pair ("A-B"), each with its
        ipSAE, pDockQ2 and LIS values."""
        command = f"molcompose ipsae {quote_path(pae_file)}{_model_suffix(model)}"
        if pae_cutoff != 10.0:
            command += f" paeCutoff {pae_cutoff:g}"
        value, text = _invoke(command)
        return present_analysis(
            with_log(
                text,
                value,
                interface_scores=value if isinstance(value, dict) else None,
            )
        )

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def score_against_reference(
        reference: str, model: str | None = None, chain_map: str | None = None
    ) -> AnalysisResult:
        """DockQ and its CAPRI components (Fnat, iRMSD, LRMSD) for a predicted
        complex against an open reference structure. Unlike pLDDT/pDockQ/ipSAE
        (which need no reference) this validates against a trusted structure.
        `reference` is a model spec like '#2'; `chain_map` is 'A:C,B:D' when the
        chain IDs differ. Requires detect_interface on the model first.

        Residues are paired between model and reference by sequence alignment,
        so the two need not share a numbering scheme — a prediction numbered
        1-N scores correctly against a reference in chymotrypsinogen, Kabat or
        any other convention, insertion codes included. Chain *identity* is not
        inferred: use `chain_map` when the chain IDs differ. Scoring is refused
        outright if the aligned chains are not the same protein, or if the
        mapping reaches too little of the reference interface to be meaningful,
        and a partial mapping is reported with the shortfall named.

        Returns `dockq` with the score and its CAPRI components: `fnat`,
        `fnonnat`, `irmsd`, `lrmsd`, `capri_class`, the contact counts the
        score is built from, and `f1` / `clashes` reported alongside."""
        command = (
            f"molcompose dockq {model_spec(reference, 'reference')}"
            f"{_model_suffix(model)}"
        )
        checked_map = validate_chain_map(chain_map)
        if checked_map:
            command += f" chainMap {checked_map}"
        value, text = _invoke(command)
        return present_analysis(
            with_log(text, value, dockq=value if isinstance(value, dict) else None)
        )

    @expose_tool("expert", annotations=READ_ONLY, structured_output=True)
    def check_capabilities(
        model: str | None = None,
        predictor: Predictor = "generic",
        pae_file: str | None = None,
    ) -> AnalysisResult:
        """Report whether a structure is experimental or predicted and exactly which
        analyses it supports, with a reason for each that it does not. Call this
        first when you do not know a structure's provenance: it prevents asking
        for confidence metrics on a crystal structure or PAE-derived scores
        without a PAE matrix. `predictor` guides the search for a companion PAE
        file: alphafold-server, alphafold-db, colabfold, boltz or generic.

        Returns `capabilities`: `kind` (experimental / predicted / unknown),
        `detail`, any `pae_file` found, the `available` analyses, and
        `unavailable` mapping each unsupported metric to the reason."""
        command = f"molcompose capabilities{_model_suffix(model)}"
        checked_predictor = enum_value(predictor, PREDICTORS, "predictor")
        if checked_predictor != "generic":
            command += f" predictor {checked_predictor}"
        if pae_file:
            command += f" paeFile {quote_path(pae_file)}"
        value, text = _invoke(command)
        return present_analysis(
            with_log(
                text,
                value,
                capabilities=value if isinstance(value, dict) else None,
            )
        )

    @expose_tool("expert", annotations=READ_ONLY, structured_output=True)
    def get_confidence(model: str | None = None) -> AnalysisResult:
        """Report prediction-confidence metrics (pLDDT scale and mean, and — when
        an interface has been detected — ipLDDT and pDockQ). For canonical
        pDockQ, detect the interface with criterion cbeta at 8.0 Å first.

        Returns the metrics under `confidence` as named numbers."""
        value, text = _invoke(f"molcompose confidence{_model_suffix(model)}")
        return present_analysis(
            with_log(text, value, confidence=value if isinstance(value, dict) else None)
        )

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def show_contacts(model: str | None = None, off: bool = False) -> DisplayResult:
        """Show (or clear, with off=true) close-contact pseudobonds across the
        detected interface. Requires detect_interface first.

        Returns `commands`: the ChimeraX commands issued."""
        command = f"molcompose contacts{_model_suffix(model)}"
        if off:
            command += " off true"
        value, text = _invoke(command)
        return with_log(text, value, commands=command_list(value))

    @expose_tool("expert", annotations=SESSION_MUTATION, structured_output=True)
    def reset(model: str | None = None) -> DisplayResult:
        """Restore the MolCompose neutral publication baseline.

        Returns `commands`: the ChimeraX commands issued."""
        value, text = _invoke(f"molcompose reset{_model_suffix(model)}")
        return with_log(text, value, commands=command_list(value))

    @expose_tool("expert", annotations=LOCAL_WRITE, structured_output=True)
    def export_figure(  # noqa: PLR0913 - one keyword per export option
        path: str,
        width: ImageDimension = 2400,
        height: ImageDimension = 1800,
        supersample: Supersample = 3,
        transparent: bool = False,
        save_session: bool = False,
        overwrite: bool = False,
        dpi: Dpi = 300,
        save_recipe: bool = False,
        key_font_size: KeyFontSize | None = None,
        ctx: Context = None,
    ) -> FigureArtifactResult:
        """Export the publication image — .png or .tif — and stamp `dpi` into
        it so a publisher reads the physical size. Optionally writes the .cxs
        session and a .cxc command recipe beside it. Always writes a
        provenance JSON. With save_recipe=true, the provenance commands come
        from the canonical cross-turn .cxc sidecar. Otherwise the JSON labels
        its command list as process-local rather than claiming session coverage.
        `key_font_size` sets the colour key's font in pixels of this image
        only, for a figure whose final printed width the caller knows; the
        scene's own size is put back afterwards. Requires a windowed ChimeraX
        on macOS."""
        if ctx is not None:
            _remember_client(ctx)
        target = Path(path)
        provenance_path = target.with_suffix(".provenance.json")
        targets = [target, provenance_path]
        if save_recipe:
            targets.append(target.with_suffix(".cxc"))
        if save_session:
            targets.append(target.with_suffix(".cxs"))
        if not overwrite:
            for candidate in targets:
                if candidate.exists() or candidate.is_symlink():
                    raise FileExistsError(
                        f"export target already exists: {candidate}; choose another "
                        "name or explicitly set overwrite=true"
                    )
        text = _run(
            build_export_command(
                path, width, height, supersample, transparent, save_session,
                overwrite, dpi, save_recipe, key_font_size,
            )
        )
        # The provenance file is only written once the image it describes
        # exists. Until 2026-08-21 it was written unconditionally, so a failed
        # export -- a bad path, a refused overwrite, no OpenGL -- still left a
        # record on disk attesting to the commands that made a figure nobody
        # had. That is the one failure this whole file exists to prevent.
        if not Path(path).is_file():
            raise RuntimeError(
                f"ChimeraX did not write {path}; no provenance record was "
                f"created. ChimeraX said: {text.strip() or '(nothing)'}"
            )
        recipe_path = Path(path).with_suffix(".cxc")
        canonical_commands = None
        scope = "process"
        if save_recipe:
            if not recipe_path.is_file():
                raise RuntimeError(
                    f"ChimeraX wrote {path} but did not write the requested "
                    f"canonical recipe {recipe_path}; no provenance record was created"
                )
            canonical_commands = read_canonical_recipe(recipe_path)
            scope = "session"
        provenance = build_provenance(
            recipe,
            _molcompose_version(),
            __version__,
            canonical_commands=canonical_commands,
            scope=scope,
        )
        # A second exporter may have created the sidecar after the preflight.
        # Exclusive creation preserves that file instead of silently replacing it.
        with provenance_path.open("w" if overwrite else "x", encoding="utf-8") as stream:
            stream.write(json.dumps(provenance, indent=2))
        return {
            "png": str(path),
            "session": str(Path(path).with_suffix(".cxs")) if save_session else None,
            "recipe": str(recipe_path) if save_recipe else None,
            "provenance": str(provenance_path),
            "log": text,
        }

    @expose_tool("expert", annotations=LOCAL_WRITE, structured_output=True)
    def export_sequence_coloring(
        path: str | None = None,
        model: str | None = None,
        source: SequenceSource = "interface",
        load: bool = True,
    ) -> DisplayResult:
        """Write the per-residue colouring as an SCF file for the ChimeraX
        Sequence Viewer, so the same quantity that colours the structure can be
        read along the sequence. `source` is interface, plddt, ddg, dsasa or
        bfactor. One file per chain; positions are alignment columns, not
        residue numbers.

        Returns `commands`: the ChimeraX commands issued."""
        command = f"molcompose seqcolor{' ' + quote_path(path) if path else ''}"
        command += _model_suffix(model)
        command += f" source {enum_value(source, SEQUENCE_SOURCES, 'source')}"
        if not load:
            command += " load false"
        value, text = _invoke(command)
        return with_log(text, value, commands=command_list(value))

    @expose_tool("expert", annotations=SESSION_MUTATION)
    def run_native(command: str) -> str:
        """Run one whitelisted, display-state-only native ChimeraX command
        (view/turn/zoom/select/color/show/hide/info/version/...).
        Coordinate- or file-modifying commands are rejected."""
        if not native_allowed(command):
            raise WhitelistError(
                f"command not in the display-only whitelist: {command!r}. "
                "Use the typed molcompose tools for figure work; coordinate- or "
                "file-modifying commands are not available through this server."
            )
        return _run(command)

    @expose_tool("assistant", "expert", annotations=READ_ONLY)
    def render_preview(max_px: PreviewSize = 512) -> Image:
        """Small PNG preview of the current view for self-checking
        (windowed ChimeraX required on macOS)."""
        import tempfile

        with tempfile.TemporaryDirectory(prefix="molcompose-mcp-") as folder:
            preview = Path(folder) / "preview.png"
            _run(
                f"save {quote_path(preview)} width {max_px} height {max_px}",
                _source="server",
            )
            if not preview.exists():
                raise ChimeraXUnavailable(
                    "preview render produced no file — on macOS run ChimeraX "
                    "windowed, not --nogui"
                )
            data = preview.read_bytes()
        return Image(data=data, format="png")

    @expose_tool("expert", annotations=READ_ONLY)
    def get_recipe() -> list[str]:
        """Commands observed by this MCP process (not the cross-turn session recipe)."""
        return recipe.commands()

    _bundle_version = {"value": ""}

    def _molcompose_version() -> str:
        """The installed bundle's version, asked for rather than assumed.

        This was the string "0.1.0" while the bundle shipped 0.1.1, so every
        provenance record this server wrote named a version that had not
        produced it -- in the one file whose entire job is to say what did.
        A hardcoded version is only ever right until the next release, and
        nothing fails when it stops being right.

        Read once per process from ChimeraX itself and cached. If the listing
        cannot be read the field is left empty rather than filled with a
        guess: an absent version is a gap a reader can see.
        """
        if not _bundle_version["value"]:
            try:
                listing = _run("toolshed list installed", _source="server")
            except Exception:  # noqa: BLE001 - provenance metadata is best-effort
                return ""
            _bundle_version["value"] = parse_bundle_version(listing)
        return _bundle_version["value"]

    @expose_tool("assistant", annotations=READ_ONLY, structured_output=True)
    @_assistant_boundary("inspect_session")
    def inspect_session(ctx: Context) -> AssistantOutcome:
        """Inspect live models, chains, capabilities and version compatibility."""
        listing = list_models(ctx)
        capabilities = {}
        interfaces = {}
        for model_row in listing.get("models", []):
            model = model_row.get("spec")
            if isinstance(model, str):
                capabilities[model] = check_capabilities(model=model)
                try:
                    blocks = list_blocks(model=model).get("blocks")
                except ChimeraXCommandError as error:
                    if not str(error).startswith("Detect an interface first"):
                        raise
                    blocks = []
                interfaces[model] = {
                    "ready": bool(blocks),
                    "blocks": blocks or [],
                }
        return {
            "status": "completed",
            "data": {
                **listing,
                "capabilities": capabilities,
                "interfaces": interfaces,
            },
            "compatibility": compatibility_status(__version__, _molcompose_version()),
        }

    @expose_tool("assistant", annotations=SESSION_MUTATION, structured_output=True)
    @_assistant_boundary("analyse_interface")
    def analyse_interface(
        group_a: ChainGroup | None = None,
        group_b: ChainGroup | None = None,
        model: str | None = None,
        distance: Distance = 4.5,
        criterion: Criterion = "heavy",
        style: bool = True,
        ctx: Context = None,
    ) -> AssistantOutcome:
        """Characterise one unambiguous interface or return concrete choices.

        Explicit groups are kept. Without them, automatic selection happens
        only for one two-chain model or one contacting pair.
        """
        listing = list_models(ctx)
        decision = choose_interface(
            listing.get("models", []),
            listing.get("chains", []),
            model=model,
            group_a=group_a,
            group_b=group_b,
        )
        if (
            decision["status"] == "needs_input"
            and decision.get("question") == "Which chain groups should be analysed?"
        ):
            selected_model = decision.get("model") or model
            pair_result = detect_all_interfaces(
                model=selected_model,
                distance=distance,
                criterion=criterion,
            )
            decision = choose_interface(
                listing.get("models", []),
                listing.get("chains", []),
                model=selected_model,
                contacting_pairs=pair_result.get("pairs") or [],
            )
        if decision["status"] != "completed":
            return decision
        result = characterise_interface(
            decision["group_a"],
            decision["group_b"],
            model=decision["model"],
            distance=distance,
            criterion=criterion,
            style=style,
        )
        return {
            **decision,
            "result": result,
            "next_steps": [
                "compose_figure",
                "load_external_evidence",
                "render_preview",
                "export_artifact",
            ],
        }

    @expose_tool("assistant", annotations=SESSION_MUTATION, structured_output=True)
    @_assistant_boundary("compose_figure")
    def compose_figure(
        goal: FigureGoal,
        model: str | None = None,
        ctx: Context = None,
    ) -> AssistantOutcome:
        """Map a figure goal to an existing preset and apply it.

        No visual style is invented. Interface-dependent goals refuse to run
        until an interface exists; use ``analyse_interface`` first.
        """
        listing = list_models(ctx)
        models = [
            row.get("spec")
            for row in listing.get("models", [])
            if isinstance(row.get("spec"), str)
        ]
        if model is None:
            if len(models) != 1:
                return {
                    "status": "needs_input",
                    "question": "Which open model should be styled?",
                    "choices": models,
                }
            model = models[0]
        elif model not in models:
            return {
                "status": "needs_input",
                "question": f"Model {model} is not open. Which model should be styled?",
                "choices": models,
            }
        try:
            blocks = list_blocks(model=model).get("blocks")
        except ChimeraXCommandError as error:
            if not str(error).startswith("Detect an interface first"):
                raise
            blocks = []
        plan = figure_plan(goal, interface_ready=bool(blocks))
        if plan["status"] != "completed":
            return plan
        result = apply_style(plan["preset"], model=model)
        return {**plan, "model": model, "result": result}

    @expose_tool("assistant", annotations=LOCAL_WRITE, structured_output=True)
    @_assistant_boundary("export_artifact")
    def export_artifact(
        path: str,
        width: ImageDimension = 2400,
        height: ImageDimension = 1800,
        supersample: Supersample = 3,
        transparent: bool = False,
        save_session: bool = False,
        confirmed_overwrite: bool = False,
        dpi: Dpi = 300,
        key_font_size: KeyFontSize | None = None,
        ctx: Context = None,
    ) -> AssistantOutcome:
        """Export a figure with its canonical recipe, asking before overwrite."""
        target = Path(path)
        related_targets = [
            target,
            target.with_suffix(".cxc"),
            target.with_suffix(".provenance.json"),
        ]
        if save_session:
            related_targets.append(target.with_suffix(".cxs"))
        existing_targets = [
            str(candidate) for candidate in related_targets
            if candidate.exists() or candidate.is_symlink()
        ]
        decision = export_decision(
            path,
            exists=bool(existing_targets),
            confirmed=confirmed_overwrite,
        )
        if decision["status"] != "completed":
            decision["choices"] = existing_targets
            return decision
        result = export_figure(
            path,
            width=width,
            height=height,
            supersample=supersample,
            transparent=transparent,
            save_session=save_session,
            overwrite=bool(existing_targets) and confirmed_overwrite,
            dpi=dpi,
            save_recipe=True,
            key_font_size=key_font_size,
            ctx=ctx,
        )
        qa = artifact_quality({
            name: result.get(name)
            for name in ("png", "session", "recipe", "provenance")
        })
        if not qa["passed"]:
            failed = [
                name
                for name, check in qa["artifacts"].items()
                if not check["non_empty"]
            ]
            raise RuntimeError(
                "Export did not produce complete non-empty artifacts: "
                + ", ".join(failed)
            )
        return {**decision, "result": result, "qa": qa}

    @expose_tool("assistant", annotations=EXTERNAL_UPLOAD, structured_output=True)
    @_assistant_boundary("load_external_evidence")
    def load_external_evidence(  # noqa: PLR0913 - one field per supported loader
        kind: EvidenceKind,
        path: str,
        model: str | None = None,
        chains: str | None = None,
        format: DdgFormat | None = None,
        statistic: Statistic = "min",
        structure_path: str | None = None,
        tool: PythiaTool = "pythia-ppi",
        confirm_external: bool = False,
        confirmed_overwrite: bool = False,
        solvation: Solvation | None = None,
    ) -> AssistantOutcome:
        """Route supported local files or one confirmed external prediction.

        Local files need no confirmation. PythiaStudio sends a structure to an
        external service and returns ``needs_confirmation`` first.
        """
        decision = external_evidence_decision(kind, confirmed=confirm_external)
        if decision["status"] != "completed":
            return decision
        if kind == "pythiastudio" and Path(path).exists() and not confirmed_overwrite:
            return {
                "status": "needs_confirmation",
                "confirmation": "overwrite_local_file",
                "target": path,
            }
        if kind == "ddg":
            result = load_ddg(path, model=model, format=format, statistic=statistic)
        elif kind == "energy":
            if not chains:
                return {
                    "status": "needs_input",
                    "question": "An energy chain map is required.",
                    "choices": ["A:A,B:D"],
                }
            try:
                result = load_energy(path, chains=chains, model=model, solvation=solvation)
            except EnergySolvationRequired as error:
                return {
                    "status": "needs_input",
                    "question": (
                        "Which solvation section should be loaded? Set solvation to pb or gb."
                    ),
                    "choices": ["pb", "gb"],
                    "message": str(error),
                }
        elif kind == "flexibility":
            if not chains:
                return {
                    "status": "needs_input",
                    "question": "The ordered flexibility chains are required.",
                    "choices": ["A,D"],
                }
            result = load_flexibility(path, chains=chains, model=model)
        else:
            if not structure_path:
                return {
                    "status": "needs_input",
                    "question": "A local structure path is required for PythiaStudio.",
                    "choices": ["provide structure_path"],
                }
            prediction = predict_ddg_pythiastudio(structure_path, path, tool=tool)
            loaded = load_ddg(path, model=model, format=tool, statistic=statistic)
            return {
                "status": "completed",
                "data": {"prediction": prediction, "loaded": loaded},
            }
        return {"status": "completed", "result": result}

    return app


def own_executable() -> str:
    """This server's own absolute path, for a config another process will read.

    A client launches the command string it was given, in its own environment
    — not in the shell that installed the package. `molcompose-mcp` on its own
    therefore works from pipx and fails from a virtualenv nobody activated,
    which is the commonest way a correct registration still does not run.
    Printing the resolved path removes the question.
    """
    import shutil

    argv0 = Path(sys.argv[0])
    if argv0.name and argv0.exists():
        return str(argv0.resolve())
    return shutil.which("molcompose-mcp") or "molcompose-mcp"


def config_json(chimerax_url: str, source: str = "agent",
                profile: ServerProfile = "all") -> str:
    """The MCP stdio-server registration for this install, as JSON."""
    entry = {"command": own_executable(), "args": ["--chimerax-url", chimerax_url]}
    if profile != "all":
        entry["args"] += ["--profile", profile]
    if source and source != "agent":
        entry["args"] += ["--source", source]
    return json.dumps({"mcpServers": {"molcompose": entry}}, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="MolCompose MCP server")
    parser.add_argument(
        "--chimerax-url",
        default="http://127.0.0.1:3000",
        help="Base URL of the ChimeraX REST bridge (remotecontrol rest)",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help=(
            "Do not start ChimeraX when its bridge is not answering. Without "
            "this, the first tool call launches a windowed ChimeraX with the "
            "bridge open and leaves it running afterwards."
        ),
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help=(
            "Print the MCP registration for this install and exit — the "
            "resolved absolute path of this executable, and the ChimeraX URL. "
            "Paste it into a client's config, or pipe it."
        ),
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_VALUES,
        default="all",
        help=(
            "Tool surface: assistant exposes the guided workflow, expert "
            "exposes the original typed tools, and all preserves both."
        ),
    )
    parser.add_argument(
        "--source",
        default="agent",
        help=(
            "How to attribute commands in the bundle's provenance record. "
            "The panel passes the CLI it launched, as 'agent:codex', so a "
            "session that used more than one client can be told apart."
        ),
    )
    args = parser.parse_args()
    if args.print_config:
        print(config_json(args.chimerax_url, args.source, args.profile))
        return
    create_server(
        args.chimerax_url,
        args.source,
        launch=not args.no_launch,
        profile=args.profile,
    ).run()


if __name__ == "__main__":
    main()
