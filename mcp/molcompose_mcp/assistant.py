"""Pure intent-level decisions for the additive MCP assistant façade."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from .contracts import (
    ArtifactFileCheck,
    ArtifactQualityResult,
    AssistantOutcome,
    EvidenceKind,
    FigureGoal,
)

CONTRACT_VERSION = "1"
SUPPORTED_BUNDLE_SERIES = (0, 1)

FIGURE_PRESETS = {
    "interface-overview": "interface-focus",
    "interaction-closeup": "licorice-closeup",
    "binder-closeup": "paratope-closeup",
    "epitope-surface": "epitope-surface",
    "hotspot-map": "hotspot-focus",
    "confidence": "predicted-structure",
    "whole-complex": "complex-by-chain",
    "metric-map": "metric-map",
}
INTERFACE_FIGURE_GOALS = {
    "interface-overview",
    "interaction-closeup",
    "binder-closeup",
    "epitope-surface",
    "hotspot-map",
}


def artifact_quality(
    artifacts: Mapping[str, str | None],
) -> ArtifactQualityResult:
    """Verify the concrete files an export claims to have written."""
    checks: dict[str, ArtifactFileCheck] = {}
    for name, value in artifacts.items():
        if value is None:
            continue
        path = Path(value)
        exists = path.is_file()
        try:
            size = path.stat().st_size if exists else None
        except OSError:
            exists, size = False, None
        checks[name] = {
            "path": str(path),
            "exists": exists,
            "non_empty": bool(exists and size),
            "bytes": size,
        }
    return {
        "passed": bool(checks) and all(
            check["non_empty"] for check in checks.values()
        ),
        "artifacts": checks,
    }


def _model_specs(models: Sequence[Mapping[str, object]]) -> list[str]:
    return [
        str(model["spec"])
        for model in models
        if isinstance(model.get("spec"), str)
        and model.get("class") != "PseudobondGroup"
    ]


def choose_interface(
    models: Sequence[Mapping[str, object]],
    chains: Sequence[Mapping[str, object]],
    *,
    model: str | None = None,
    group_a: Sequence[str] | None = None,
    group_b: Sequence[str] | None = None,
    contacting_pairs: Sequence[Mapping[str, object]] | None = None,
) -> AssistantOutcome:
    """Choose only an unambiguous model and chain pair; otherwise ask."""
    specs = _model_specs(models)
    if not specs:
        return {
            "status": "failed",
            "error": "no_structure",
            "message": "No atomic structure is open in the live ChimeraX session.",
        }
    if model is None:
        if len(specs) != 1:
            return {
                "status": "needs_input",
                "question": "Which open model should be analysed?",
                "choices": specs,
            }
        model = specs[0]
    elif model not in specs:
        return {
            "status": "needs_input",
            "question": f"Model {model} is not open. Which open model should be analysed?",
            "choices": specs,
        }

    if (group_a is None) != (group_b is None):
        return {
            "status": "needs_input",
            "question": "Both chain groups are required.",
            "choices": ["provide group_a and group_b"],
        }
    if group_a is not None and group_b is not None:
        return {
            "status": "completed",
            "model": model,
            "group_a": list(group_a),
            "group_b": list(group_b),
        }

    protein_chains = [
        str(chain["chain_id"])
        for chain in chains
        if chain.get("model_spec") == model
        and chain.get("polymer_type") == "protein"
        and isinstance(chain.get("chain_id"), str)
    ]
    if len(protein_chains) == 2:
        return {
            "status": "completed",
            "model": model,
            "group_a": [protein_chains[0]],
            "group_b": [protein_chains[1]],
        }
    if len(protein_chains) < 2:
        return {
            "status": "failed",
            "error": "insufficient_protein_chains",
            "message": f"Model {model} has fewer than two protein chains.",
        }

    pairs = []
    for pair in contacting_pairs or ():
        chain_a, chain_b = pair.get("chain_a"), pair.get("chain_b")
        if isinstance(chain_a, str) and isinstance(chain_b, str):
            pairs.append((chain_a, chain_b))
    if len(pairs) == 1:
        return {
            "status": "completed",
            "model": model,
            "group_a": [pairs[0][0]],
            "group_b": [pairs[0][1]],
        }
    if pairs:
        return {
            "status": "needs_input",
            "model": model,
            "question": "Which contacting chain pair should be analysed?",
            "choices": [f"{left}:{right}" for left, right in pairs],
        }
    return {
        "status": "needs_input",
        "model": model,
        "question": "Which chain groups should be analysed?",
        "choices": protein_chains,
    }


def figure_plan(goal: FigureGoal, *, interface_ready: bool) -> AssistantOutcome:
    """Map a documented intent to an existing preset, never a new style."""
    if goal in INTERFACE_FIGURE_GOALS and not interface_ready:
        return {
            "status": "needs_input",
            "question": "An interface must be analysed before this figure can be composed.",
            "choices": ["analyse_interface"],
        }
    return {
        "status": "completed",
        "preset": FIGURE_PRESETS[goal],
        "operations": ["apply_style"],
    }


def export_decision(path: str, *, exists: bool, confirmed: bool) -> AssistantOutcome:
    if exists and not confirmed:
        return {
            "status": "needs_confirmation",
            "confirmation": "overwrite_local_file",
            "target": path,
        }
    return {"status": "completed", "target": path}


def external_evidence_decision(
    kind: EvidenceKind,
    *,
    confirmed: bool,
) -> AssistantOutcome:
    if kind == "pythiastudio" and not confirmed:
        return {
            "status": "needs_confirmation",
            "confirmation": "upload_structure_to_pythiastudio",
        }
    return {"status": "completed"}


def _series(version: str) -> tuple[int, int] | None:
    try:
        major, minor, *_rest = version.split(".")
        return int(major), int(minor)
    except (TypeError, ValueError):
        return None


def compatibility_status(server_version: str, bundle_version: str) -> dict[str, object]:
    """An explicit version handshake; unknown versions are never guessed."""
    if not bundle_version:
        return {
            "server_version": server_version,
            "bundle_version": "",
            "contract_version": CONTRACT_VERSION,
            "compatible": False,
            "warning": "The installed MolCompose bundle version could not be read.",
        }
    compatible = _series(bundle_version) == SUPPORTED_BUNDLE_SERIES
    return {
        "server_version": server_version,
        "bundle_version": bundle_version,
        "contract_version": CONTRACT_VERSION,
        "compatible": compatible,
        "warning": None if compatible else "This server supports MolCompose bundle 0.1.x.",
    }
