"""Deterministic display values layered over exact MolCompose results."""

from collections.abc import Mapping
from math import isfinite


def display_area(value: float) -> str:
    """An area for prose; the exact float remains available under ``raw``."""
    number = float(value)
    if not isfinite(number):
        return f"{number} Å²"
    return f"{round(number)} Å²"


def display_energy(value: float) -> str:
    """A kcal/mol value at report precision."""
    return f"{float(value):.2f} kcal/mol"


def display_kd(value: float) -> str:
    """A dissociation constant in stable scientific notation."""
    return f"{float(value):.2e} M"


def _display_temperature(value: float) -> str:
    number = float(value)
    text = f"{number:g}"
    return f"{text} °C"


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _interface_summary(interface: Mapping[str, object]) -> str | None:
    required = ("residues_a", "residues_b", "contact_pairs", "criterion", "cutoff")
    if any(interface.get(key) is None for key in required):
        return None
    cutoff = interface["cutoff"]
    cutoff_text = f"{float(cutoff):g}" if _number(cutoff) else str(cutoff)
    return (
        f"{interface['residues_a']} + {interface['residues_b']} interface residues; "
        f"{interface['contact_pairs']} contacting residue pairs "
        f"({interface['criterion']} criterion, {cutoff_text} Å cutoff)"
    )


def present_analysis(result: Mapping[str, object]) -> dict[str, object]:
    """Add exact ``raw`` and prose-safe ``display`` fields to one result.

    Existing top-level fields are retained for compatibility.  Formatting is
    deliberately limited to values already returned by MolCompose; this
    module never calculates or substitutes a scientific metric.
    """
    presented = dict(result)
    raw = {
        key: value
        for key, value in result.items()
        if key not in {"log", "raw", "display"}
    }
    display: dict[str, object] = {}

    area = result.get("buried_area")
    if _number(area):
        display["buried_area"] = display_area(area)

    affinity = result.get("affinity")
    if isinstance(affinity, Mapping):
        formatted_affinity = {}
        if _number(affinity.get("delta_g")):
            formatted_affinity["delta_g"] = display_energy(affinity["delta_g"])
        if _number(affinity.get("kd")):
            formatted_affinity["kd"] = display_kd(affinity["kd"])
        if _number(affinity.get("temperature")):
            formatted_affinity["temperature"] = _display_temperature(
                affinity["temperature"]
            )
        if formatted_affinity:
            display["affinity"] = formatted_affinity

    interface = result.get("interface")
    if isinstance(interface, Mapping):
        summary = _interface_summary(interface)
        if summary:
            display["interface"] = summary

    skipped = result.get("skipped")
    if isinstance(skipped, Mapping):
        display["skipped"] = dict(skipped)

    presented["raw"] = raw
    presented["display"] = display
    return presented
