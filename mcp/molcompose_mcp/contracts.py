"""Machine-readable MCP contracts shared by tool registrations and validators.

The runtime validators remain authoritative.  These aliases make the same
domains visible to an MCP client before it chooses a tool, so an invalid value
can be corrected without first sending a ChimeraX command.
"""

from typing import Annotated, Literal, NotRequired, Required

from mcp.types import ToolAnnotations
from pydantic import Field
from typing_extensions import TypedDict

PRESET_VALUES = (
    "clean-cartoon",
    "complex-by-chain",
    "interface-focus",
    "flat-outline",
    "licorice-closeup",
    "licorice-chain",
    "surface-complex",
    "epitope-surface",
    "surface-partner-a",
    "surface-translucent",
    "surface-epitope-map",
    "paratope-closeup",
    "hotspot-focus",
    "predicted-structure",
    "metric-map",
    "design-reference",
)
CRITERION_VALUES = ("heavy", "cbeta", "vdw")
REPORT_FORMAT_VALUES = ("json", "csv", "md")
DDG_FORMAT_VALUES = ("tabular", "pythia", "pythia-ppi")
STATISTIC_VALUES = ("min", "max", "mean")
HOTSPOT_METRIC_VALUES = ("dsasa", "energy")
INTERACTION_TYPE_VALUES = (
    "salt-bridge",
    "hydrophobic",
    "pi-stacking",
    "cation-pi",
    "disulfide",
)
PREDICTOR_VALUES = (
    "generic",
    "alphafold3",
    "alphafold-server",
    "alphafold-db",
    "af2-multimer",
    "protenix",
    "boltz",
    "colabfold",
    "chai",
)
SEQUENCE_SOURCE_VALUES = ("interface", "plddt", "ddg", "dsasa", "bfactor", "mmpbsa")

Preset = Literal[*PRESET_VALUES]
Criterion = Literal[*CRITERION_VALUES]
ReportFormat = Literal[*REPORT_FORMAT_VALUES]
DdgFormat = Literal[*DDG_FORMAT_VALUES]
Statistic = Literal[*STATISTIC_VALUES]
HotspotMetric = Literal[*HOTSPOT_METRIC_VALUES]
Predictor = Literal[*PREDICTOR_VALUES]
SequenceSource = Literal[*SEQUENCE_SOURCE_VALUES]
FocusTarget = Literal["model", "interface"]
PythiaTool = Literal["pythia", "pythia-ppi"]
FigureGoal = Literal[
    "interface-overview",
    "interaction-closeup",
    "binder-closeup",
    "epitope-surface",
    "hotspot-map",
    "confidence",
    "whole-complex",
    "metric-map",
]
EvidenceKind = Literal["ddg", "energy", "flexibility", "pythiastudio"]
Solvation = Literal["pb", "gb"]
OutcomeStatus = Literal["completed", "needs_input", "needs_confirmation", "failed"]
ServerProfile = Literal["assistant", "expert", "all"]
AssistantNextStep = Literal[
    "open_structure",
    "analyse_interface",
    "compose_figure",
    "render_preview",
    "export_artifact",
    "load_external_evidence",
]

ChainId = Annotated[str, Field(pattern=r"^[A-Za-z0-9]{1,4}$")]
ChainGroup = Annotated[list[ChainId], Field(min_length=1)]
Distance = Annotated[float, Field(ge=2.0, le=10.0)]
Temperature = Annotated[float, Field(gt=-273.15, le=1000.0)]
PaeCutoff = Annotated[float, Field(gt=0.0, le=100.0)]
Labels = Annotated[int, Field(ge=0)]
TopCount = Annotated[int, Field(ge=0)]
MinimumArea = Annotated[float, Field(ge=0.0)]
ImageDimension = Annotated[int, Field(ge=1, le=16384)]
Supersample = Annotated[int, Field(ge=1, le=8)]
Dpi = Literal[0] | Annotated[int, Field(ge=72, le=2400)]
KeyFontSize = Annotated[int, Field(ge=4, le=400)]
PreviewSize = Annotated[int, Field(ge=1, le=16384)]
ApiKey = Annotated[
    str,
    Field(
        json_schema_extra={"writeOnly": True},
        description="Deprecated fallback; prefer PYTHIASTUDIO_API_KEY.",
    ),
]
OptionalApiKey = Annotated[ApiKey | None, Field(deprecated=True)]
InteractionSelection = Annotated[
    str,
    Field(
        pattern=(
            r"^\s*(salt-bridge|hydrophobic|pi-stacking|cation-pi|disulfide)"
            r"(\s*,\s*(salt-bridge|hydrophobic|pi-stacking|cation-pi|disulfide))*\s*$"
        )
    ),
]


class OperationResult(TypedDict):
    log: str
    value: NotRequired[object]
    value_available: NotRequired[bool]
    raw: NotRequired[dict[str, object]]
    display: NotRequired[dict[str, object]]
    warnings: NotRequired[list[str]]
    skipped: NotRequired[dict[str, str]]


class ModelListResult(OperationResult, total=False):
    models: Required[list[dict[str, object]]]
    chains: Required[list[dict[str, object]]]


class AnalysisResult(OperationResult, total=False):
    interface: dict[str, object]
    interactions: dict[str, object]
    buried_area: float | None
    affinity: dict[str, object] | None
    hotspots: list[dict[str, object]] | None
    confidence: dict[str, object] | None
    interface_scores: list[dict[str, object]] | dict[str, object] | None
    steps: list[str]
    pairs: list[dict[str, object]] | None
    counts: dict[str, object] | None
    group_a: list[dict[str, object]]
    group_b: list[dict[str, object]]
    contact_pairs: int
    contacts: list[dict[str, object]]
    items: list[dict[str, object]]
    blocks: list[dict[str, object]] | None
    ddg: list[dict[str, object]] | None
    dockq: dict[str, object] | None
    capabilities: dict[str, object] | None


class DisplayResult(OperationResult, total=False):
    commands: Required[list[str] | None]


class ArtifactResult(OperationResult, total=False):
    path: str
    report: str | None
    png: str
    session: str | None
    recipe: str | None
    provenance: str
    mutations: int
    tool: str


class ReportArtifactResult(OperationResult):
    report: str | None


class PredictionArtifactResult(OperationResult):
    path: str
    mutations: int
    tool: str


class FigureArtifactResult(OperationResult):
    png: str
    session: str | None
    recipe: str | None
    provenance: str


class CompatibilityResult(TypedDict):
    server_version: str
    bundle_version: str
    contract_version: str
    compatible: bool
    warning: str | None


class ArtifactFileCheck(TypedDict):
    path: str
    exists: bool
    non_empty: bool
    bytes: int | None


class ArtifactQualityResult(TypedDict):
    passed: bool
    artifacts: dict[str, ArtifactFileCheck]


class AssistantOutcome(TypedDict):
    status: OutcomeStatus
    message: NotRequired[str]
    error: NotRequired[str]
    next_action: NotRequired[str]
    next_steps: NotRequired[list[AssistantNextStep]]
    question: NotRequired[str]
    choices: NotRequired[list[str]]
    confirmation: NotRequired[str]
    target: NotRequired[str]
    model: NotRequired[str]
    group_a: NotRequired[list[str]]
    group_b: NotRequired[list[str]]
    preset: NotRequired[str]
    operations: NotRequired[list[str]]
    data: NotRequired[dict[str, object]]
    result: NotRequired[dict[str, object]]
    qa: NotRequired[ArtifactQualityResult]
    compatibility: NotRequired[CompatibilityResult]


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
SESSION_MUTATION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
LOCAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
OPEN_WORLD_MUTATION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
EXTERNAL_UPLOAD = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
