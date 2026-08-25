"""Assemble and render a complete interface characterization report.

Collects every analysis MolCompose can produce for one interface — geometry,
typed interactions, energetics, prediction confidence — into a single
machine-readable record, and renders it as JSON, CSV, or Markdown. The
Markdown rendering includes a Methods paragraph that can be pasted into a
manuscript, and every report carries the exact command recipe that produced
it.
"""

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

AGENT_SOURCE = "agent"


def is_agent(source: str) -> bool:
    """Whether a recorded command came in over the agent bridge.

    The bridge used to declare itself as exactly "agent". It now says which
    CLI it is — "agent:codex" — so a session that used two clients can be told
    apart, and every place that asked `source == "agent"` stopped recognising
    an agent at all. In the panel that hid the list of commands a turn had
    run. Here it was worse: the report went on to state that no command was
    issued through the agent interface, in a paragraph written for a Methods
    section. A disclosure that fails closed is the failure this record exists
    to prevent, so the family test lives in one place and both callers use it.
    """
    return source == AGENT_SOURCE or source.startswith(AGENT_SOURCE + ":")


FORMATS = ("json", "csv", "md")


@dataclass
class ReportData:
    model_id: str
    model_name: str
    chains_a: tuple[str, ...]
    chains_b: tuple[str, ...]
    criterion: str
    cutoff: float
    residues_a: int
    residues_b: int
    contact_pairs: int
    interface_residues: tuple[tuple[str, str], ...] = ()  # (side, label)
    interactions: tuple[dict, ...] = ()
    interaction_counts: dict[str, int] = field(default_factory=dict)
    buried_area: float | None = None
    affinity: dict | None = None
    confidence: dict | None = None
    commands: tuple[str, ...] = ()
    # The same commands with timestamps and source attribution. Kept separate
    # from `commands` so that block stays copy-pasteable for replay.
    command_log: tuple[dict, ...] = ()
    software: dict = field(default_factory=dict)
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat(timespec="seconds")


def disclosure_text(data: ReportData) -> str:
    """A provenance sentence written for direct inclusion in a manuscript.

    Journals increasingly require that AI involvement be declared. MolCompose
    cannot know whether a model was involved in deciding *what* to analyse, but
    it does know how each command entered the session, so the sentence states
    that and nothing more — an overreaching claim would be worse than none.
    """
    sources = {entry.get("source", "session") for entry in data.command_log}
    version = data.software.get("molcompose", "?")
    chimerax = data.software.get("chimerax", "?")
    count = len(data.commands)
    if count == 0:
        # The sentence has to stay true of the file it is written into. With
        # no recipe the standard wording became "the complete command recipe
        # (0 commands) is included in this record and reproduces every value
        # reported here" — printed over a full interface, affinity and
        # interaction section, and refuted by the same file. It is written for
        # direct inclusion in a Methods section, so it is the one line that
        # has to hold no matter what went wrong upstream.
        #
        # Nor is there anything to attribute: with no commands recorded,
        # neither the user nor an agent can be said to have issued them, so
        # both clauses below are omitted rather than guessed at.
        return (
            f"This analysis was produced with MolCompose v{version} in UCSF "
            f"ChimeraX {chimerax}. No command recipe was recorded for this "
            "analysis: the commands that produced the values above are not in "
            "this record, and it cannot be replayed from itself. The analysis "
            "must be repeated to reproduce them."
        )
    base = (
        f"This analysis was produced with MolCompose v{version} in UCSF ChimeraX "
        f"{chimerax}. The complete command recipe ({count} "
        f"command{'' if count == 1 else 's'}) is included in this record and "
        "reproduces every value reported here."
    )
    if any(is_agent(source) for source in sources):
        return base + (
            " Some or all commands were issued through the molcompose-mcp agent "
            "interface by a large language model client; the per-command source "
            "attribution is given in the provenance record."
        )
    # Not "all commands were issued directly by the user", which this cannot
    # know. ChimeraX's REST bridge carries no identity: a command recorded as
    # "session" was typed at the command line, sent by a script, or sent by a
    # client that did not identify itself. The agent bridge does identify
    # itself — so the honest statement is that none declared an agent, not that
    # a human did the typing. The stronger sentence was in a paragraph written
    # for a manuscript, which is the worst place to overstate what is known.
    return base + (
        " No command in this record was issued through the molcompose-mcp agent "
        "interface, which identifies itself as its source; the remainder were "
        "issued from the panel or the ChimeraX command line."
    )


def _group_label(chains) -> str:
    return ",".join(chains)


def methods_paragraph(data: ReportData) -> str:
    """A Methods sentence set describing exactly how these numbers were made."""
    software = data.software
    parts = [
        f"Interface analysis was performed with MolCompose "
        f"v{software.get('molcompose', '?')} in UCSF ChimeraX "
        f"{software.get('chimerax', '?')}.",
        f"Interface residues between chains {_group_label(data.chains_a)} and "
        f"{_group_label(data.chains_b)} of {data.model_name} were defined as residue "
        f"pairs with any {'heavy-atom' if data.criterion == 'heavy' else 'Cβ (Cα for glycine)'} "
        f"pair within {data.cutoff:g} Å, yielding {data.residues_a} and "
        f"{data.residues_b} residues respectively across {data.contact_pairs} "
        f"contacting residue pairs.",
    ]
    if data.buried_area is not None:
        parts.append(
            f"The interface buries {data.buried_area:.0f} Å² of solvent-accessible "
            "surface area (ChimeraX measure buriedarea)."
        )
    if data.interaction_counts:
        listed = ", ".join(
            f"{count} {kind.replace('-', ' ')}"
            for kind, count in sorted(data.interaction_counts.items())
            if count
        )
        if listed:
            parts.append(
                f"Typed non-covalent interactions across the interface comprise "
                f"{listed}, detected with distance and geometry criteria following "
                "PLIP and Arpeggio conventions."
            )
    if data.affinity:
        parts.append(
            f"The predicted binding free energy is "
            f"{data.affinity['delta_g']:.2f} kcal/mol "
            f"(K_d = {data.affinity['kd']:.2e} M at "
            f"{data.affinity['temperature']:g} °C), computed with the PRODIGY "
            "IC-NIS contacts model (Vangone & Bonvin, eLife 2015) using "
            "ChimeraX solvent-accessible surface areas."
        )
    if data.confidence:
        confidence = data.confidence
        sentence = (
            f"For this predicted model the mean pLDDT is "
            f"{confidence['mean_plddt']:.1f}"
        )
        if confidence.get("iplddt") is not None:
            sentence += f", the interface pLDDT is {confidence['iplddt']:.1f}"
        if confidence.get("pdockq") is not None:
            sentence += f", and pDockQ is {confidence['pdockq']:.3f}"
        parts.append(sentence + ".")
        parts.append(
            "Interface residues were computed on a predicted model; contacts "
            "should be interpreted in light of these confidence estimates."
        )
    return " ".join(parts)


def as_dict(data: ReportData) -> dict:
    return {
        "generated_at": data.generated_at,
        "software": data.software,
        "model": {"id": data.model_id, "name": data.model_name},
        "interface": {
            "chains_a": list(data.chains_a),
            "chains_b": list(data.chains_b),
            "criterion": data.criterion,
            "cutoff": data.cutoff,
            "residues_a": data.residues_a,
            "residues_b": data.residues_b,
            "contact_pairs": data.contact_pairs,
            "buried_area": data.buried_area,
            "residues": [
                {"side": side, "residue": label} for side, label in data.interface_residues
            ],
        },
        "interactions": {
            "counts": data.interaction_counts,
            "items": list(data.interactions),
        },
        "affinity": data.affinity,
        "confidence": data.confidence,
        "methods": methods_paragraph(data),
        "commands": list(data.commands),
        "provenance": {
            "command_log": list(data.command_log),
            "disclosure_text": disclosure_text(data),
        },
    }


def render_json(data: ReportData) -> str:
    return json.dumps(as_dict(data), indent=2, ensure_ascii=False)


def render_csv(data: ReportData) -> str:
    """Flat key/value + interaction rows, for spreadsheets."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["section", "key", "value"])
    writer.writerow(["model", "id", data.model_id])
    writer.writerow(["model", "name", data.model_name])
    writer.writerow(["interface", "chains_a", _group_label(data.chains_a)])
    writer.writerow(["interface", "chains_b", _group_label(data.chains_b)])
    writer.writerow(["interface", "criterion", data.criterion])
    writer.writerow(["interface", "cutoff", data.cutoff])
    writer.writerow(["interface", "residues_a", data.residues_a])
    writer.writerow(["interface", "residues_b", data.residues_b])
    writer.writerow(["interface", "contact_pairs", data.contact_pairs])
    if data.buried_area is not None:
        writer.writerow(["interface", "buried_area_A2", f"{data.buried_area:.1f}"])
    for kind, count in sorted(data.interaction_counts.items()):
        writer.writerow(["interaction_counts", kind, count])
    if data.affinity:
        for key, value in data.affinity.items():
            writer.writerow(["affinity", key, value])
    if data.confidence:
        for key, value in data.confidence.items():
            writer.writerow(["confidence", key, value])
    writer.writerow([])
    writer.writerow(["interaction", "type", "residue_a", "residue_b", "distance", "detail"])
    for item in data.interactions:
        writer.writerow(
            [
                "interaction",
                item.get("kind", ""),
                item.get("residue_a", ""),
                item.get("residue_b", ""),
                f"{item.get('distance', 0.0):.2f}",
                item.get("detail", ""),
            ]
        )
    return buffer.getvalue()


def render_markdown(data: ReportData) -> str:
    lines = [
        f"# Interface report — {data.model_name} ({data.model_id})",
        "",
        f"*Generated {data.generated_at} by MolCompose "
        f"v{data.software.get('molcompose', '?')} in UCSF ChimeraX "
        f"{data.software.get('chimerax', '?')}.*",
        "",
        "## Interface",
        "",
        "| Property | Value |",
        "|---|---|",
        f"| Group A | {_group_label(data.chains_a)} |",
        f"| Group B | {_group_label(data.chains_b)} |",
        f"| Criterion | {data.criterion} |",
        f"| Cutoff | {data.cutoff:g} Å |",
        f"| Group A residues | {data.residues_a} |",
        f"| Group B residues | {data.residues_b} |",
        f"| Contacting residue pairs | {data.contact_pairs} |",
    ]
    if data.buried_area is not None:
        lines.append(f"| Buried surface area | {data.buried_area:.0f} Å² |")
    if data.affinity:
        lines.append(f"| Predicted ΔG | {data.affinity['delta_g']:.2f} kcal/mol |")
        lines.append(
            f"| Predicted K_d | {data.affinity['kd']:.2e} M "
            f"@ {data.affinity['temperature']:g} °C |"
        )
    if data.confidence:
        lines.append(f"| Mean pLDDT | {data.confidence['mean_plddt']:.1f} |")
        if data.confidence.get("iplddt") is not None:
            lines.append(f"| Interface pLDDT | {data.confidence['iplddt']:.1f} |")
        if data.confidence.get("pdockq") is not None:
            lines.append(f"| pDockQ | {data.confidence['pdockq']:.3f} |")

    if data.interaction_counts:
        lines += ["", "## Typed interactions", "", "| Type | Count |", "|---|---|"]
        for kind, count in sorted(data.interaction_counts.items()):
            lines.append(f"| {kind} | {count} |")
    if data.interactions:
        lines += [
            "",
            "| Type | Residue A | Residue B | Distance | Detail |",
            "|---|---|---|---|---|",
        ]
        for item in data.interactions:
            lines.append(
                f"| {item.get('kind', '')} | {item.get('residue_a', '')} | "
                f"{item.get('residue_b', '')} | {item.get('distance', 0.0):.2f} Å | "
                f"{item.get('detail', '')} |"
            )

    if data.interface_residues:
        lines += ["", "## Interface residues", ""]
        for side in ("A", "B"):
            labels = [
                label for group, label in data.interface_residues if group == side
            ]
            if labels:
                lines.append(f"- **Group {side}** ({len(labels)}): {', '.join(labels)}")

    lines += ["", "## Methods", "", methods_paragraph(data)]
    if data.commands:
        lines += ["", "## Command recipe", "", "```"]
        lines.extend(data.commands)
        lines.append("```")
    lines += ["", "## Provenance", "", disclosure_text(data)]
    if data.command_log:
        lines += [
            "",
            "| # | Command | Issued | Source |",
            "|---|---|---|---|",
        ]
        for index, entry in enumerate(data.command_log, start=1):
            lines.append(
                f"| {index} | `{entry.get('command', '')}` | "
                f"{entry.get('timestamp', '')} | {entry.get('source', '')} |"
            )
    return "\n".join(lines) + "\n"


def render(data: ReportData, fmt: str) -> str:
    if fmt not in FORMATS:
        raise ValueError(f"report format must be one of {', '.join(FORMATS)}: {fmt}")
    return {"json": render_json, "csv": render_csv, "md": render_markdown}[fmt](data)
