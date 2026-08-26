"""Docked Qt panel: a thin, tabbed client over the canonical molcompose commands."""

import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from chimerax.atomic.widgets import AtomicStructureMenuButton
from chimerax.core.tools import ToolInstance
from chimerax.ui import MainToolWindow
from Qt.QtCore import QProcess, QSize, Qt, Signal
from Qt.QtGui import QIcon
from Qt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..adapters.exporter import COLUMN_MM, MM_PER_INCH, pixels_for, quote_path
from ..adapters.model_context import (
    experimental_method,
    model_ref,
    plddt_values,
    structure_stem,
)
from ..adapters.renderer import (
    INTERACTION_COLORS,
    SURFACE_COLOR,
    SURFACE_TRANSPARENCY,
    compact_residue_spec,
)
from ..core.agent_cli import (
    CUSTOM_AGENT,
    CUSTOM_KEY,
    DEFAULT_CHIMERAX_URL,
    build_command,
    custom_agent,
    find_agents,
    finish_process_input,
    get_agent,
    interactive_command,
    locate,
    readiness,
    write_mcp_config,
)
from ..core.blocks import KINDS as BLOCK_KINDS
from ..core.blocks import LABELS as BLOCK_LABELS
from ..core.blocks import block_name
from ..core.confidence import build_report
from ..core.presets import BODY_GREY, PRESETS, get_preset, grouped_presets
from ..core.report import is_agent

# Narrow enough to dock beside the graphics window without the cards
# collapsing. Everything inside has to survive this width, which is why the
# button rows wrap rather than run off the edge.
MINIMUM_PANEL_WIDTH = 300

# ChimeraX's own scheme for bundle documentation: the page that shipped with
# this install, not a URL that can go stale or need a network.
# What the presets draw their key at. The panel starts here so that an
# untouched export sends no keyFontSize at all and behaves exactly as before.
DEFAULT_KEY_FONT = 42

HELP_PAGE = "help:user/tools/molcompose.html"

_TARGETS = ("model", "interface", "faceon", "openbook")
_CRITERIA = ("heavy", "cbeta", "vdw")
_CRITERION_DEFAULT_CUTOFF = {"heavy": 4.5, "cbeta": 8.0, "vdw": -0.4}


def _classify_structure(method, values) -> tuple[str, str]:
    """Classify the B-factor field before the panel offers confidence controls."""
    if method:
        return (
            "experimental",
            f"Experimental structure ({method}) — its B-factors are temperature "
            "factors, not confidence, so no confidence metric applies.",
        )
    try:
        build_report(values)
    except ValueError as error:
        return "unknown", f"Confidence unavailable — {error}."
    return (
        "predicted",
        "Predicted model — pLDDT read from the B-factor column. ipSAE, "
        "pDockQ2, LIS and ipTM additionally need the prediction's own files "
        "(Interface tab).",
    )

# One deliberate theme: porcelain surfaces, indigo accent, soft indigo tints.
_PANEL_QSS = """
QWidget#content { background: #F1F2F7; }
QScrollArea { border: none; background: #F1F2F7; }
QTabWidget::pane { border: none; padding-top: 10px; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab {
    border: none;
    border-radius: 16px;
    padding: 8px 16px;
    margin: 2px 3px;
    background: transparent;
    color: #5d6068;
}
QTabBar::tab:selected { background: #4F46E5; color: white; font-weight: 600; }
QTabBar::tab:hover:!selected { background: #ECEEF6; }
QWidget#card {
    background: white;
    border: 1px solid #E7E9F0;
    border-radius: 12px;
}
QLabel#cardTitle { font-weight: 700; font-size: 14px; color: #2f323a; }
QPushButton {
    border: none;
    border-radius: 9px;
    padding: 9px 14px;
    background: #EEF1F8;
    color: #3a3d45;
    font-weight: 500;
}
QPushButton:hover { background: #E3E7F2; }
QPushButton:pressed { background: #D6DBEA; }
QPushButton#primary { background: #4F46E5; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #4338CA; }
QPushButton#tonal { background: #EEF2FF; color: #4F46E5; font-weight: 600; }
QPushButton#tonal:hover { background: #E0E7FF; }
/* Disabled has to *look* disabled. Without these rules a tonal button kept
   its indigo-on-lavender emphasis when disabled, so a pLDDT button on a
   crystal structure read as highlighted-and-broken rather than as
   not-applicable — the exact opposite of what disabling it was for. */
QPushButton:disabled { background: #F3F4F8; color: #BDC0CB; }
QPushButton#primary:disabled { background: #CBCDEA; color: #F5F5FB; }
QPushButton#tonal:disabled { background: #F3F4F8; color: #BDC0CB; }
QListWidget, QTableWidget {
    border: none;
    background: #FAFBFE;
    border-radius: 8px;
    alternate-background-color: #F1F3F9;
    color: #2f323a;
    gridline-color: #E8EAF1;
    outline: none;
}
QListWidget::item, QTableWidget::item {
    color: #2f323a;
    padding: 4px 6px;
    border: none;
}
QListWidget::item:selected, QTableWidget::item:selected {
    background: #E0E7FF;
    color: #312E81;
}
QListWidget::item:hover, QTableWidget::item:hover { background: #EEF1F8; }
QTableCornerButton::section { background: #F7F8FC; border: none; }
/* The header widget itself, not just its sections. Sections are styled below,
   but the strip past the last one is painted by the header, and with no rule
   for it that strip came out solid black — a dark block sitting in the
   results table, visible in the panel and in any screenshot of it. */
QHeaderView { background: #F7F8FC; border: none; }
QHeaderView::section {
    background: #F7F8FC;
    border: none;
    font-weight: 600;
    font-size: 11px;
    color: #8A8D96;
    padding: 4px 6px;
}
/* QLineEdit had no rule at all, so the executable and argument fields fell
   back to a platform default that painted them as solid black bars with the
   path in white — unreadable, and the same class of omission as the
   QHeaderView strip below. They are text inputs like the combos above, so
   they are styled like them. */
QLineEdit {
    border: 1px solid #E2E4EC;
    border-radius: 8px;
    padding: 6px 9px;
    background: white;
    color: #2f323a;
    selection-background-color: #E0E7FF;
    selection-color: #312E81;
    min-height: 18px;
}
QLineEdit:focus { border: 1px solid #4F46E5; }
/* Disabled means "this is what will run, and it is not yours to edit here" —
   the built-in argument templates. It has to read as inert, not as broken. */
QLineEdit:disabled { background: #F6F7FA; color: #8A8D96; border: 1px solid #EAECF3; }
QLineEdit::placeholder { color: #A9ACB6; }
QComboBox, QDoubleSpinBox, QSpinBox {
    border: 1px solid #E2E4EC;
    border-radius: 8px;
    padding: 6px 9px;
    background: white;
    color: #2f323a;
    min-height: 18px;
}
QComboBox::item { color: #2f323a; }
QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus { border: 1px solid #4F46E5; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: white;
    border: 1px solid #DDE0EA;
    border-radius: 8px;
    padding: 4px;
    color: #2f323a;
    selection-background-color: #EEF2FF;
    selection-color: #312E81;
    outline: none;
}
/* A checkbox draws its own label, and this rule set the spacing and nothing
   else — so the text alone fell through to the system palette while every
   card behind it stayed porcelain white. On macOS in dark mode that palette
   makes it white, and the labels disappear: "Transparent background", "Also
   save the command recipe", "Semi-transparent interface surface" and
   "Override the preset" were all invisible after dark, and readable again in
   the morning. This theme paints its own backgrounds unconditionally, so it
   has to paint its own text unconditionally too. */
QCheckBox { spacing: 6px; color: #2f323a; }
QCheckBox:disabled { color: #A9ACB6; }
QLabel#sectionTitle { font-weight: 600; font-size: 11px; color: #8A8D96; }
QLabel#hint { color: #7c7f88; font-size: 12px; }
QLabel#blockName { color: #2f323a; font-size: 12px; }
QLabel#blockSpec { color: #9296a0; font-size: 11px; font-family: Menlo, monospace; }
QLabel#blockCount { color: #7c7f88; font-size: 11px; }
QPushButton#swatch { border: 1px solid #C7CAD4; border-radius: 4px; padding: 0; }
QPushButton#rowAction {
    background: #F4F5FA; color: #4F46E5; border: none;
    border-radius: 6px; padding: 4px 10px; font-size: 11px; font-weight: 600;
}
QPushButton#rowAction:hover { background: #EEF2FF; }
QPushButton#rowAction:disabled { background: #F7F8FB; color: #BFC2CC; }
QLabel#chipClickable { padding: 3px 8px; border-radius: 6px; font-size: 11px; }
QWidget#tile {
    background: #F7F8FC;
    border: 1px solid #EAECF3;
    border-radius: 10px;
}
QWidget#tileActive {
    background: #EEF2FF;
    border: 1px solid #C7D2FE;
    border-radius: 10px;
}
/* A metric this structure can never produce. Dashed border and washed-out
   text, so "not applicable here" and "not computed yet" stop looking alike. */
QWidget#tileMuted {
    background: #F6F7FA;
    border: 1px dashed #DCDEE8;
    border-radius: 10px;
}
QWidget#tileMuted QLabel#tileValue { color: #C6C9D3; }
QWidget#tileMuted QLabel#tileCaption { color: #C6C9D3; }
QLabel#tileValue { font-size: 16px; font-weight: 700; color: #312E81; }
QLabel#tileCaption {
    font-size: 10px; font-weight: 600; color: #8A8D96; letter-spacing: 0.4px;
}
QLabel#metric {
    font-weight: 600;
    color: #312E81;
    background: #EEF2FF;
    border-radius: 8px;
    padding: 8px 10px;
}
QLabel#status {
    color: #B42318;
    background: #FEF3F2;
    border-radius: 8px;
    padding: 6px 10px;
}
QPlainTextEdit#chatLog {
    background: white;
    color: #2F323A;
    border: 1px solid #E2E4EC;
    border-radius: 10px;
    padding: 10px;
    font-size: 12px;
}
QPlainTextEdit#chatDetails {
    background: #1F2430;
    color: #D9DCE3;
    border: none;
    border-radius: 10px;
    padding: 10px;
    /* Menlo only, plus the generic. Naming Consolas — a Windows font — made Qt
       populate its whole font-family alias table looking for it, which it
       reports as "Populating font family aliases took 263 ms" on every
       launch. The generic keyword covers the platforms Menlo is missing on. */
    font-family: Menlo, monospace;
    font-size: 12px;
}
QLabel#agentRunStatus {
    color: #4F46E5;
    background: #EEF2FF;
    border-radius: 8px;
    padding: 7px 10px;
    font-weight: 600;
}
QLabel#agentVerified {
    color: #166534;
    background: #F0FDF4;
    border: 1px solid #BBF7D0;
    border-radius: 8px;
    padding: 8px 10px;
}
QLabel#agentUnverified {
    color: #92400E;
    background: #FFFBEB;
    border: 1px solid #FDE68A;
    border-radius: 8px;
    padding: 8px 10px;
}
QPlainTextEdit#chatInput {
    background: white;
    border: 1px solid #E2E4EC;
    border-radius: 8px;
    padding: 8px;
    color: #2f323a;
    font-size: 12px;
}
/* The agent tab's status strip: which CLI, whether the bridge is up. A muted
   line rather than a heading, because it reports rather than instructs — the
   same weight as the print-size hint on the Export card. */
QLabel#agentStatus {
    color: #5d6068;
    background: #F7F8FC;
    border: 1px solid #EAECF3;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 12px;
}
QLabel#agentStatusWarn {
    color: #92400E;
    background: #FFFBEB;
    border: 1px solid #FDE68A;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 12px;
}
/* Suggestion chips. The examples used to be a fourteen-line blockquote that
   owned the tab; these carry the same content and put it into the input. */
QPushButton#suggest {
    background: #F4F5FA;
    color: #4F46E5;
    border: 1px solid #E7E9F0;
    border-radius: 14px;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
    text-align: left;
}
QPushButton#suggest:hover { background: #EEF2FF; border: 1px solid #C7D2FE; }
/* The disclosure that hides the executable path and argument template. */
QPushButton#disclosure {
    background: transparent;
    color: #8A8D96;
    border: none;
    padding: 4px 0;
    font-size: 11px;
    font-weight: 600;
    text-align: left;
}
QPushButton#disclosure:hover { color: #4F46E5; background: transparent; }
QLabel#examples {
    background: #F7F8FC;
    border-left: 3px solid #4F46E5;
    border-radius: 6px;
    padding: 12px 14px;
    color: #3c3f47;
    font-size: 12px;
}
QLabel#code {
    /* Menlo only, plus the generic. Naming Consolas — a Windows font — made Qt
       populate its whole font-family alias table looking for it, which it
       reports as "Populating font family aliases took 263 ms" on every
       launch. The generic keyword covers the platforms Menlo is missing on. */
    font-family: Menlo, monospace;
    font-size: 12px;
    background: #1F2430;
    color: #D9DCE3;
    border-radius: 10px;
    padding: 12px;
}
"""


def _validated_model_spec(model_spec: str) -> str:
    if not model_spec.startswith("#"):
        raise ValueError(f"model spec must start with '#': {model_spec}")
    return model_spec


def _validated_chain_group(chain_ids) -> str:
    validated = []
    for chain_id in chain_ids:
        if not chain_id or "," in chain_id or any(ch.isspace() for ch in chain_id):
            raise ValueError(f"invalid chain ID: {chain_id!r}")
        validated.append(chain_id)
    if not validated:
        raise ValueError("a chain group needs at least one chain ID")
    return ",".join(validated)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def style_command(model_spec: str, preset_slug: str, labels: int | None = None) -> str:
    """`labels` overrides how many residues per side the preset labels.

    None leaves the preset's own count, which differs between presets for
    historical reasons — two for the tight close-up, three for the near view,
    none for the metric carriers.
    """
    if preset_slug not in PRESETS:
        raise ValueError(f"unknown MolCompose preset: {preset_slug}")
    command = f"molcompose style {preset_slug} model {_validated_model_spec(model_spec)}"
    if labels is not None:
        if labels < 0:
            raise ValueError("labels must be 0 or more")
        command += f" labels {labels}"
    return command


def interface_command(
    model_spec: str, group_a, group_b, distance: float, criterion: str = "heavy"
) -> str:
    if criterion not in _CRITERIA:
        raise ValueError(
            f"interface criterion must be one of {', '.join(_CRITERIA)}: {criterion}"
        )
    spec = _validated_model_spec(model_spec)
    a_text = _validated_chain_group(group_a)
    b_text = _validated_chain_group(group_b)
    command = f"molcompose interface {a_text} {b_text} model {spec} distance {distance:g}"
    if criterion != "heavy":
        command += f" criterion {criterion}"
    return command


def focus_command(model_spec: str, target: str) -> str:
    if target not in _TARGETS:
        raise ValueError(
            f"focus target must be one of {', '.join(_TARGETS)}: {target}"
        )
    return f"molcompose focus {target} model {_validated_model_spec(model_spec)}"


def export_command(  # noqa: PLR0913 - one keyword per export option
    path,
    width: int,
    height: int,
    supersample: int,
    transparent: bool,
    save_session: bool,
    overwrite: bool,
    dpi: int = 300,
    save_recipe: bool = False,
    key_font_size: int | None = None,
) -> str:
    return (
        f"molcompose export {quote_path(path)} width {width} height {height} "
        f"supersample {supersample} transparent {_bool_text(transparent)} "
        f"saveSession {_bool_text(save_session)} overwrite {_bool_text(overwrite)} "
        f"dpi {dpi} saveRecipe {_bool_text(save_recipe)}"
        + (f" keyFontSize {key_font_size}" if key_font_size is not None else "")
    )


def seqcolor_command(model_spec: str, source: str, path=None,
                     load: bool = True) -> str:
    """Export the per-residue colouring as SCF for the Sequence Viewer."""
    command = "molcompose seqcolor"
    if path:
        command += f" {quote_path(path)}"
    command += f" model {_validated_model_spec(model_spec)} source {source}"
    if not load:
        command += " load false"
    return command


def hbonds_command(model_spec: str, off: bool = False) -> str:
    command = f"molcompose hbonds model {_validated_model_spec(model_spec)}"
    if off:
        command += " off true"
    return command


def contacts_command(model_spec: str, off: bool = False) -> str:
    command = f"molcompose contacts model {_validated_model_spec(model_spec)}"
    if off:
        command += " off true"
    return command


def hotspots_command(model_spec: str, min_area: float = 10.0, top: int = 0) -> str:
    command = f"molcompose hotspots model {_validated_model_spec(model_spec)}"
    if min_area != 10.0:
        command += f" minArea {min_area:g}"
    if top:
        command += f" top {top}"
    return command


def dockq_command(model_spec: str, reference_spec: str, chain_map: str = "") -> str:
    reference = _validated_model_spec(reference_spec)
    command = f"molcompose dockq {reference} model {_validated_model_spec(model_spec)}"
    if chain_map:
        command += f" chainMap {chain_map}"
    return command


# Kept in step with COLOR_METRICS in commands.py. It was ("ddg", "dsasa")
# while the panel offered a pLDDT button, so the button raised on every click.
COLOR_METRICS = ("plddt", "ddg", "dsasa", "bfactor", "mmpbsa", "rmsf")
# What each metric is called, and in what unit, where the panel reports it.
# Every entry of COLOR_METRICS needs one; a drift test asserts that, because
# the conditional this replaced mislabelled a B-factor map as buried area the
# moment a fourth metric existed.
# How each result tile writes its number. One table, because the same format
# strings were repeated across three handlers — `f"{area:.0f}"` in the buried
# area, characterise and hot-spot paths — and a fourth caller now reads the same
# values back out of session state. Two places formatting one tile is how a
# B-factor map came to be labelled "buried area".
TILE_FORMATS = {
    "bsa": "{:.0f}",
    "pdockq": "{:.3f}",
    "plddt": "{:.1f}",
    "iplddt": "{:.1f}",
    "ptm": "{:.3f}",
    "pae": "{:.2f}",
    "lis": "{:.3f}",
    "dg": "{:.2f}",
    "kd": "{:.1e}",
    "dockq": "{:.3f}",
    "ipsae": "{:.3f}",
    "pdockq2": "{:.3f}",
    "iptm": "{:.3f}",
}

METRIC_LABELS = {
    "plddt": "pLDDT",
    "ddg": "ΔΔG (kcal/mol)",
    "dsasa": "buried area (Å²)",
    "bfactor": "B-factor (Å²)",
    # Named for what it is rather than for the method, because the panel puts
    # it beside ΔΔG and the two are opposite in sign: this one is negative
    # where a residue contributes.
    "mmpbsa": "End-point energy contribution (kcal/mol)",
    "rmsf": "RMS fluctuation (Å)",
}


def color_by_command(model_spec: str, metric: str, scope: str = "interface") -> str:
    if metric not in COLOR_METRICS:
        raise ValueError(
            f"colour metric must be one of {', '.join(COLOR_METRICS)}: {metric}"
        )
    if scope not in ("interface", "all"):
        raise ValueError(f"scope must be interface or all: {scope}")
    command = f"molcompose color by {metric} model {_validated_model_spec(model_spec)}"
    # Only the interface-scoped metrics take a scope; pLDDT and B-factor are
    # whole-model by nature and the command rejects the keyword for them.
    if scope != "interface" and metric in ("ddg",):
        command += f" scope {scope}"
    return command


def ddg_command(model_spec: str, path, statistic: str = "min") -> str:
    command = (
        f"molcompose ddg {quote_path(path)} model {_validated_model_spec(model_spec)}"
    )
    if statistic != "min":
        command += f" statistic {statistic}"
    return command


def energy_command(model_spec: str, path, chains: str, solvation: str = "") -> str:
    """`chains` is not optional and not defaulted — see cmd_energy.

    `solvation` is needed only when the run computed both GB and PB, which
    writes the decomposition twice. The panel asks before calling rather than
    letting the load fail: the refusal is correct but only useful to someone
    who can then choose, and the panel had no control that let them.
    """
    command = (
        f"molcompose energy {quote_path(path)} chains {chains} "
        f"model {_validated_model_spec(model_spec)}"
    )
    if solvation:
        command += f" solvation {solvation}"
    return command


def flexibility_command(model_spec: str, path, chains: str) -> str:
    """`chains` is one per block, ordered — see cmd_flexibility."""
    return (
        f"molcompose flexibility {quote_path(path)} chains {chains} "
        f"model {_validated_model_spec(model_spec)}"
    )


def report_command(path, fmt: str = "") -> str:
    command = f"molcompose report {quote_path(path)}"
    if fmt:
        command += f" format {fmt}"
    return command


def affinity_command(model_spec: str, temperature: float = 25.0) -> str:
    command = f"molcompose affinity model {_validated_model_spec(model_spec)}"
    if temperature != 25.0:
        command += f" temperature {temperature:g}"
    return command


def characterise_command(
    model_spec: str, group_a, group_b, distance: float, criterion: str = "heavy",
    style: bool = True, pae_file: str = "", summary_file: str = "",
) -> str:
    if criterion not in _CRITERIA:
        raise ValueError(
            f"interface criterion must be one of {', '.join(_CRITERIA)}: {criterion}"
        )
    spec = _validated_model_spec(model_spec)
    a_text = _validated_chain_group(group_a)
    b_text = _validated_chain_group(group_b)
    command = (
        f"molcompose characterise {a_text} {b_text} model {spec} distance {distance:g}"
    )
    if criterion != "heavy":
        command += f" criterion {criterion}"
    if not style:
        command += " style false"
    # A file the user chose by hand travels with the run. Without this the
    # panel found the file, showed it in the table, and then characterised
    # without it — the numbers a user pressed the button to update did not.
    if pae_file:
        command += f" paeFile {quote_path(pae_file)}"
    if summary_file:
        command += f" summaryFile {quote_path(summary_file)}"
    return command


def interactions_command(model_spec: str, types: str = "", off: bool = False) -> str:
    command = f"molcompose interactions model {_validated_model_spec(model_spec)}"
    if types:
        command += f" types {types}"
    if off:
        command += " off true"
    return command


def reset_command(model_spec: str) -> str:
    return f"molcompose reset model {_validated_model_spec(model_spec)}"


def _section(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionTitle")
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def _short_name(name: str, limit: int = 48) -> str:
    """A file name that fits, with the middle taken out rather than the end.

    ColabFold writes names like
    `1brs_unrelaxed_rank_001_alphafold2_multimer_v3_model_1_seed_2066.pdb`,
    68 characters, and the header carrying it stretched the whole panel to
    fit. What has to survive is what tells one of five models from another —
    the rank at the front, the model and seed at the back — so the middle goes
    and both ends stay. The limit is set where that name keeps `rank_001` and
    `model_1_seed_2066`; the engine and version in between are the same across
    the five. The full name is the widget's tooltip either way.
    """
    if len(name) <= limit:
        return name
    keep = limit - 1
    head = keep // 2
    return f"{name[:head]}…{name[-(keep - head):]}"


class _ClickableLabel(QLabel):
    """A QLabel that reports clicks, so a legend chip can also be a control."""

    clicked = Signal()

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _readable_argv(argv) -> str:
    """The command that ran, with the paths in it reduced to names.

    The flags are worth showing: `--allowedTools mcp__molcompose` is the whole
    confinement claim, and `--print` is why the turn cannot ask a follow-up.
    The two absolute paths are not. One is the binary, already named a line
    above by the status strip; the other is a temporary directory with a
    random suffix that differs every turn. Both put a local filesystem into
    any screenshot of this box, and neither tells the reader anything.
    """
    return " ".join(
        Path(part).name if part.startswith("/") else part for part in argv
    )


def _agent_run_status(exit_code: int, operation_count: int) -> str:
    """User-facing outcome without equating a clean exit with live analysis."""
    if exit_code != 0:
        return f"Agent failed · exit code {exit_code}"
    if operation_count == 0:
        return "Answer returned · live analysis not verified"
    return "Analysis complete  ✓"


class MolComposeTool(ToolInstance):
    SESSION_ENDURING = True
    SESSION_SAVE = False
    help = "help:user/tools/molcompose.html"

    def __init__(self, session, tool_name):
        super().__init__(session, tool_name)
        self.tool_window = MainToolWindow(self)
        self._hbonds_shown = False
        self._contacts_shown = False
        self._interactions_shown = False
        self._spinning = False
        self._table_mode = "none"
        self._last_result = None
        self._group_a_color = None
        self._group_b_color = None
        self._pae_path = ""
        self._summary_path = ""
        self._ddg_loaded = False
        self._block_colors: dict[str, str] = {}
        # (widget, the caption it was built with), so a tile that gains a
        # qualifier — DockQ's CAPRI class — can drop it again.
        self._tile_captions: dict[str, tuple] = {}
        self._build_ui()
        # After the widgets exist, never before: the first notification can
        # arrive while this constructor is still on the stack if something else
        # is mid-command, and the handler touches widgets.
        self._handlers = self._listen_for_state_changes()
        self.tool_window.manage("side")

    def _listen_for_state_changes(self):
        """Ask to be told when a command changes what this panel is showing.

        The panel used to learn about state only from its own clicks, so an
        interface detected at the command line — or by an agent through MCP —
        left it listing the whole-structure presets as though nothing had
        happened. Returns the handler, or None where there is no trigger set to
        register with (a session double in the tests).
        """
        from ..commands import STATE_CHANGED, ensure_state_trigger

        triggers = ensure_state_trigger(self.session)
        if triggers is None:
            return []
        wanted = [(STATE_CHANGED, self._on_state_changed)]
        # Closing the structure is not a MolCompose state change, so nothing
        # above covers it — and the result tiles hold numbers about a specific
        # structure. Without this, `close` followed by `open` left the previous
        # structure's buried area and ΔG on screen beside the new one.
        try:
            from chimerax.core.models import ADD_MODELS, REMOVE_MODELS

            wanted += [(ADD_MODELS, self._on_models_changed),
                       (REMOVE_MODELS, self._on_models_changed)]
        except ImportError:
            pass
        handlers = []
        for name, callback in wanted:
            try:
                handlers.append(triggers.add_handler(name, callback))
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
        return handlers

    def delete(self):
        """Stop listening before going away.

        A handler left registered on a deleted panel is called with dead
        widgets on the next command that changes state, which fails inside
        whatever analysis sent the notification.
        """
        for handler in getattr(self, "_handlers", None) or ():
            try:
                handler.remove()
            except (AttributeError, ValueError):
                continue
        self._handlers = []
        super().delete()

    def _on_models_changed(self, _trigger_name=None, _models=None) -> None:
        """A structure opened or closed, so the tiles may be about nothing.

        They are cleared rather than recomputed: whatever they held described a
        structure that is no longer the one on screen. `_on_state_changed` then
        refills whatever the session still knows about the current model, which
        is how reopening a structure that has already been analysed comes back
        with its numbers instead of blanks.
        """
        if getattr(self, "_preset_combo", None) is None:
            return
        self._clear_metrics()
        self._on_state_changed()

    def _on_state_changed(self, _trigger_name=None, _model_id=None) -> None:
        """Rebuild the parts of the panel that are derived from session state.

        Deliberately narrow. It re-reads what the session knows — is there an
        interface for this model, what did detection name — and does not touch
        the results table, the metric tiles or any panel-local flag. Those are
        filled from a command's return value by the click that ran it, and
        clearing them here would let a notification arriving mid-click wipe
        what that click was in the middle of writing.
        """
        if getattr(self, "_preset_combo", None) is None:
            return
        model = self._current_model()
        if model is None:
            return
        has_interface = self._live_interface() is not None
        self._fill_presets(not experimental_method(model), has_interface)
        if has_interface:
            self._enable_interface_views()
        self._refresh_block_rows()
        self._refresh_tiles_from_state()
        # A colouring is what draws a key, so whether the key font applies
        # changes with the same events this handler already watches.
        if getattr(self, "_key_font_spin", None) is not None:
            self._update_key_font_hint()

    # -- command execution -------------------------------------------------

    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def _run_command(self, command: str):
        from chimerax.core.commands import run
        from chimerax.core.errors import UserError

        from ..commands import recording_source

        try:
            # Attribute the command to the panel, so a report can distinguish a
            # click from a typed command without either being misreported.
            with recording_source(self.session, "panel"):
                result = run(self.session, command, log=True)
            self._set_status("")
            return result
        except UserError as error:
            self._set_status(str(error))
            return None

    def _run_quiet(self, command: str) -> None:
        from chimerax.core.commands import run

        run(self.session, command, log=False)

    def _current_model(self):
        return self._model_button.value

    def _current_model_spec(self):
        model = self._current_model()
        if model is None:
            self._set_status("Open a protein structure first")
            return None
        return model_ref(model).model_id

    # -- UI construction ---------------------------------------------------

    def _card(self, title: str):
        box = QWidget()
        box.setObjectName("card")
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(14, 12, 14, 14)
        box.setLayout(layout)
        card_title = QLabel(title)
        card_title.setObjectName("cardTitle")
        layout.addWidget(card_title)
        return box, layout

    def _apply_tab_icons(self, current: int) -> None:
        """Dark icons on the unselected tabs, white on the selected one.

        Two sets rather than one neutral compromise: the selected tab is white
        on indigo and the rest are grey on the panel background, and a single
        mid-grey reads as washed out on both. Qt does not recolour an icon per
        tab state, so the swap is done here.

        Silent when the files are missing. A packaging mistake should cost the
        icons, not the panel — the tabs still have their labels.
        """
        icons = Path(__file__).resolve().parent.parent / "icons"
        for index, (name, _label) in enumerate(self.TABS):
            variant = "light" if index == current else "dark"
            icon = QIcon()
            found = False
            for size in (16, 32, 64):
                path = icons / f"{name}-{variant}-{size}.png"
                if path.is_file():
                    icon.addFile(str(path), QSize(size, size))
                    found = True
            if found:
                self._tabs.setTabIcon(index, icon)
        # 18, not 16: beside this tab font a 16 px glyph reads as delicate
        # rather than as a peer of the label.
        self._tabs.setIconSize(QSize(18, 18))

    def _tab(self):
        """A tab that scrolls on its own.

        The scroll area used to wrap the whole tab widget instead of sitting
        inside each tab, which had three consequences in a docked side panel:
        the tab widget took the height of its tallest page, so the short pages
        ended in dead space; the panel demanded that height from the dock, so
        the ChimeraX log got squeezed out; and nothing stopped horizontal
        overflow, so a scroll bar appeared under everything.
        """
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.Shape.NoFrame)
        # Vertical only. Anything too wide has to wrap or shrink; a sideways
        # scroll bar in a side panel means content the user cannot see.
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("content")
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(2, 6, 2, 2)
        inner.setLayout(layout)
        page.setWidget(inner)
        return page, layout

    # The tab strip, and the icon file each one loads. Emoji were used here
    # until 2026-08-17, and emoji are not one picture: the same strip is Apple
    # Color Emoji on macOS, Segoe UI Emoji on Windows, and four empty boxes on a
    # Linux machine with no emoji font installed. A bundle on the Toolshed does
    # not get to choose its user's platform, so it brings its own artwork.
    TABS = (
        ("compose", "Compose"),
        ("interface", "Interface"),
        ("export", "Export"),
        ("agent", "Agent"),
    )

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        for builder, (_icon, label) in zip(
            (self._build_compose_tab, self._build_interface_tab,
             self._build_export_tab, self._build_agent_tab),
            self.TABS, strict=True,
        ):
            tabs.addTab(builder(), label)
        self._tabs = tabs
        self._apply_tab_icons(tabs.currentIndex())
        tabs.currentChanged.connect(self._apply_tab_icons)

        self._status = QLabel("")
        self._status.setObjectName("status")
        self._status.setWordWrap(True)
        self._status.setVisible(False)

        content = QWidget()
        content.setObjectName("content")
        content.setStyleSheet(_PANEL_QSS)
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(tabs, 1)
        layout.addWidget(self._status)
        content.setLayout(layout)

        # No outer scroll area: each tab scrolls itself, so the panel asks the
        # dock for a height it can actually give rather than for the tallest
        # page's worth.
        content.setMinimumWidth(MINIMUM_PANEL_WIDTH)
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(content)
        self.tool_window.ui_area.setLayout(outer)
        self._refresh_chains()

    def _build_compose_tab(self) -> QWidget:
        tab, layout = self._tab()

        structure_card, structure_layout = self._card("Structure")
        self._model_button = AtomicStructureMenuButton(self.session)
        self._model_button.value_changed.connect(self._refresh_chains)
        self._model_summary = _hint("No protein model open")
        structure_layout.addWidget(self._model_button)
        structure_layout.addWidget(self._model_summary)
        layout.addWidget(structure_card)

        style_card, style_layout = self._card("Style")
        # What kind of structure this is decides which presets and which metric
        # colourings mean anything, so it is stated before either is offered.
        # Both used to be listed unconditionally, which put a pLDDT button on
        # crystal structures whose only possible outcome was a refusal.
        self._structure_kind = QLabel("Open a structure")
        self._structure_kind.setObjectName("hint")
        self._structure_kind.setWordWrap(True)
        style_layout.addWidget(self._structure_kind)

        self._preset_combo = QComboBox()
        style_layout.addWidget(_section("Publication preset"))
        style_layout.addWidget(self._preset_combo)
        apply_button = QPushButton("Apply Style")
        apply_button.setObjectName("primary")
        apply_button.clicked.connect(self._on_apply_style)
        style_layout.addWidget(apply_button)

        # pLDDT only. ΔΔG and ΔSASA were here too, on the reasoning that all
        # three are the same operation — paint residues by a per-residue
        # quantity. But what a user needs in order to reach them differs, and
        # that is what decides where a control belongs: pLDDT needs only the
        # file, while ΔSASA needs a detected interface and ΔΔG needs an
        # interface and an uploaded file. Both of those are Interface-tab
        # work, and they now live there.
        style_layout.addWidget(_section("Colour by metric"))
        metric_row = QHBoxLayout()
        self._metric_buttons: dict[str, QPushButton] = {}
        # Two buttons, and exactly one of them is ever live: they read the
        # same B-factor column and mean opposite things. B-factor was reachable
        # from the command line but had no control here, which made it a
        # capability the panel simply did not admit to.
        for label, metric in (("pLDDT", "plddt"), ("B-factor", "bfactor")):
            button = QPushButton(label)
            button.setObjectName("tonal")
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, m=metric: self._on_color_by(m))
            self._metric_buttons[metric] = button
            metric_row.addWidget(button)
        metric_row.addStretch(1)
        style_layout.addLayout(metric_row)
        self._metric_hint = _hint("")
        style_layout.addWidget(self._metric_hint)

        style_layout.addWidget(_section("Chain color override"))
        color_row = QHBoxLayout()
        self._chain_color_combo = QComboBox()
        color_row.addWidget(self._chain_color_combo, 1)
        pick_button = QPushButton("Pick Color…")
        pick_button.clicked.connect(self._on_pick_chain_color)
        color_row.addWidget(pick_button)
        style_layout.addLayout(color_row)
        layout.addWidget(style_card)

        # What is left of the old "Provenance & available metrics" card. The
        # predictor selector and the PAE picker moved to the Interface tab's
        # Files card, where the scores they feed are computed; here they were
        # controls with no visible consequence. This answers a question that
        # does belong on Compose — what can I do with this structure at all.
        capability_card, capability_layout = self._card("Available metrics")
        check_button = QPushButton("Check this structure")
        check_button.setObjectName("tonal")
        check_button.clicked.connect(self._on_check_capabilities)
        capability_layout.addWidget(check_button)
        self._capability_label = _hint(
            "Lists every metric this structure supports, and the reason for "
            "each it does not."
        )
        capability_layout.addWidget(self._capability_label)
        layout.addWidget(capability_card)

        view_card, view_layout = self._card("View")
        view_row = QHBoxLayout()
        fit_button = QPushButton("Fit View")
        fit_button.clicked.connect(self._on_fit_view)
        view_row.addWidget(fit_button)
        self._spin_button = QPushButton("▶ Rotate")
        self._spin_button.clicked.connect(self._on_toggle_rotation)
        view_row.addWidget(self._spin_button)
        view_layout.addLayout(view_row)

        # The two interface views that dragging cannot reach.
        view_layout.addWidget(_section("Interface views"))
        interface_view_row = QHBoxLayout()
        self._faceon_button = QPushButton("Face on")
        self._faceon_button.setObjectName("tonal")
        self._faceon_button.setEnabled(False)
        self._faceon_button.setToolTip(
            "Look down the axis joining the two partners, so the contact patch "
            "reads as a footprint rather than edge-on"
        )
        self._faceon_button.clicked.connect(lambda: self._on_focus("faceon"))
        interface_view_row.addWidget(self._faceon_button)
        self._openbook_button = QPushButton("Open book")
        self._openbook_button.setObjectName("tonal")
        self._openbook_button.setEnabled(False)
        self._openbook_button.setToolTip(
            "Separate the partners and turn one over, so both binding faces "
            "show at once. This moves the coordinates — Reset puts them back."
        )
        self._openbook_button.clicked.connect(lambda: self._on_focus("openbook"))
        interface_view_row.addWidget(self._openbook_button)
        view_layout.addLayout(interface_view_row)
        view_layout.addWidget(
            _hint("Both need a detected interface (Interface tab).")
        )

        # Shortcuts to ChimeraX's own tools. Deliberately not reimplemented:
        # these are better than anything this panel would grow, and the point
        # of a bundle is to sit inside ChimeraX rather than beside it. The
        # four chosen are the ones that answer a question this panel raises —
        # what is the sequence, what else is in contact, how far apart, and
        # what does an attribute look like painted on.
        view_layout.addWidget(_section("ChimeraX tools"))
        for label, handler, tip in (
            ("Sequences", self._on_show_sequence,
             "Every chain of this structure, interface partners first — "
             "uncoloured. To open them painted by a per-residue value, use "
             "Sequence colouring below"),
            ("Distances", lambda: self._on_show_tool("Distances"),
             "Measure and label distances; the labels the published interface "
             "figures carry"),
            # ChimeraX's own name for it, which is not the one on its window
            # title: "Render by Attribute" raises "No running or installed
            # tool named ...", so this button did nothing until 2026-08-20.
            ("Render by Attribute",
             lambda: self._on_show_tool("Render/Select by Attribute"),
             "Colour by any per-residue attribute, including ones MolCompose "
             "assigned"),
            ("Model Panel", lambda: self._on_show_tool("Model Panel"),
             "Show, hide and rename the open models"),
        ):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(handler)
            view_layout.addWidget(button)
        reset_button = QPushButton("Reset Appearance")
        reset_button.clicked.connect(self._on_reset)
        view_layout.addWidget(reset_button)
        # The help explains every button on all four tabs, and until now the
        # only way to it was the Help menu, where nobody looks while a panel is
        # open. Here because this group is already "open a ChimeraX window",
        # and because a new user lands on this tab.
        help_button = QPushButton("MolCompose Help")
        help_button.setObjectName("tonal")
        help_button.setToolTip(
            "What every tab and button does, and whose published method each "
            "number comes from"
        )
        help_button.clicked.connect(self._on_show_help)
        view_layout.addWidget(help_button)
        layout.addWidget(view_card)

        self._build_sequence_card(layout)

        layout.addStretch(1)
        return tab

    def _build_sequence_card(self, layout) -> None:
        """The per-residue colouring, on the sequence instead of on the fold.

        On Compose rather than Export since 2026-08-19. The button that matters
        here opens a window, and its first act is literally what the "Sequences"
        shortcut above performs — `sequence chain` per chain — after which it
        paints what it opened. Filing a viewer under Export left that tab
        holding an action that produces no file, and put the weaker of two
        near-identical buttons in a different tab from the stronger. Export is
        images and reports; this is a way of looking.
        """
        sequence_card, sequence_layout = self._card("Sequence colouring")
        sequence_layout.addWidget(
            _hint(
                "The same per-residue colouring, written as SCF and opened in "
                "the ChimeraX Sequence Viewer — where the extent of an "
                "interface, or a stretch of low confidence, is a shape rather "
                "than a scatter of highlighted residues."
            )
        )
        sequence_layout.addWidget(_section("Colour by"))
        self._seqcolor_combo = QComboBox()
        for label, value in (
            ("Interface residues", "interface"),
            ("pLDDT confidence", "plddt"),
            ("ΔΔG", "ddg"),
            ("Buried area", "dsasa"),
            ("B-factor", "bfactor"),
        ):
            self._seqcolor_combo.addItem(label, value)
        self._seqcolor_combo.setToolTip(
            "Colours come from the same functions that paint the structure, so "
            "the sequence and the ribbon cannot disagree about what a colour "
            "means."
        )
        sequence_layout.addWidget(self._seqcolor_combo)
        # Showing is the point; the file is how ChimeraX gets told. The Sequence
        # Viewer colours columns by reading an SCF file, so one has to exist —
        # but that is our problem, not the user's, and the first version made
        # them name a path through a save dialog before anything appeared.
        # The primary action writes to a temporary file and opens the viewer;
        # saving one to keep is a separate, deliberate act.
        #
        # ("Export & Show" also rendered as "Export  Show": & is Qt's mnemonic
        # marker, so it ate the ampersand and turned the label into two verbs
        # with a hole between them.)
        show_button = QPushButton("Show in Sequence Viewer")
        show_button.setObjectName("tonal")
        show_button.clicked.connect(self._on_seqcolor_show)
        sequence_layout.addWidget(show_button)
        save_button = QPushButton("Save SCF file…")
        save_button.setToolTip(
            "Keep the colouring as a file — to load in another session, or to "
            "send to someone with the structure."
        )
        save_button.clicked.connect(self._on_seqcolor)
        sequence_layout.addWidget(save_button)
        layout.addWidget(sequence_card)

    def _build_interface_tab(self) -> QWidget:
        tab, layout = self._tab()

        # Which structure this page is acting on. The picker stays on Compose,
        # which is right — you choose a structure once and then work — but it
        # left this page with no answer to "acting on what", and this is the
        # page the work happens on.
        self._interface_structure = QLabel("No structure selected")
        self._interface_structure.setObjectName("hint")
        self._interface_structure.setWordWrap(True)
        layout.addWidget(self._interface_structure)

        detect_card, detect_layout = self._card("Detect interface")
        detect_layout.addWidget(
            _hint(
                "Pick the chains forming each side (1BRS example: A vs D), or "
                "scan all pairs and double-click a row. Clicking a chain "
                "highlights it in 3D."
            )
        )
        self._group_a = QListWidget()
        self._group_b = QListWidget()
        for widget in (self._group_a, self._group_b):
            widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            widget.setAlternatingRowColors(True)
            widget.setMaximumHeight(80)
            widget.itemSelectionChanged.connect(self._on_chain_selection_preview)
        detect_layout.addWidget(_section("Group A — one side"))
        detect_layout.addWidget(self._group_a)
        detect_layout.addWidget(_section("Group B — the other side"))
        detect_layout.addWidget(self._group_b)

        self._cutoff_label = _section("Criterion · cutoff")
        detect_layout.addWidget(self._cutoff_label)
        control_row = QHBoxLayout()
        self._criterion_combo = QComboBox()
        self._criterion_combo.addItem("Heavy atoms", "heavy")
        self._criterion_combo.addItem("Cβ–Cβ (Gly: Cα)", "cbeta")
        self._criterion_combo.addItem("VDW overlap", "vdw")
        self._criterion_combo.currentIndexChanged.connect(self._on_criterion_changed)
        control_row.addWidget(self._criterion_combo, 1)
        self._distance = QDoubleSpinBox()
        self._distance.setRange(2.0, 10.0)
        self._distance.setSingleStep(0.5)
        self._distance.setValue(4.5)
        self._distance.setSuffix(" Å")
        control_row.addWidget(self._distance)
        detect_layout.addLayout(control_row)

        self._auto_analyse = QCheckBox(
            "Analyse automatically (contacts, buried area, ΔG/Kd, interactions)"
        )
        self._auto_analyse.setChecked(True)
        detect_layout.addWidget(self._auto_analyse)

        characterise_button = QPushButton("Characterise Interface")
        characterise_button.setObjectName("primary")
        characterise_button.clicked.connect(self._on_characterise)
        detect_layout.addWidget(characterise_button)
        detect_layout.addWidget(
            _hint(
                "One pass: interface, typed interactions, buried area, ΔG/Kd, "
                "hot spots, and confidence where it applies. Your current "
                "styling is left alone — the figure is made below."
            )
        )
        action_row = QHBoxLayout()
        detect_button = QPushButton("Detect Only")
        detect_button.clicked.connect(self._on_detect_interface)
        action_row.addWidget(detect_button)
        scan_button = QPushButton("Scan All Pairs")
        scan_button.clicked.connect(self._on_all_chain_pairs)
        action_row.addWidget(scan_button)
        detect_layout.addLayout(action_row)
        layout.addWidget(detect_card)

        results_card, results_layout = self._card("Results")
        self._tiles: dict[str, QLabel] = {}
        self._tile_boxes: dict[str, QWidget] = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        # Three by three. The geometry on the top row, the energetics in the
        # middle, the prediction-confidence scores at the bottom — which used
        # to share one tile that showed whichever had run last.
        for index, (key, caption) in enumerate(
            (
                # Three groups, in this order on purpose: what the interface
                # is, then how good it is, then what the model as a whole
                # looks like. Interface before global, so ipTM sits with ipSAE
                # rather than beside the pTM it is easily confused with, and
                # the last row is the three whole-model numbers together.
                ("contacts", "CONTACTS"),
                ("residues", "RESIDUES"),
                ("bsa", "BURIED Å²"),
                ("dg", "ΔG kcal/mol"),
                ("kd", "Kd (M)"),
                # Interface quality. DockQ leads because it is the only one
                # measured against a known answer rather than predicted.
                ("dockq", "DOCKQ"),
                ("pdockq", "pDockQ"),
                ("pdockq2", "pDockQ2"),
                ("iptm", "ipTM"),
                ("ipsae", "ipSAE"),
                ("lis", "LIS"),
                ("iplddt", "ipLDDT"),
                # The whole model, not this interface.
                ("ptm", "pTM"),
                ("pae", "mean PAE Å"),
                ("plddt", "mean pLDDT"),
            )
        ):
            grid.addWidget(self._metric_tile(key, caption), index // 3, index % 3)
        results_layout.addLayout(grid)

        self._chip_row = QHBoxLayout()
        self._chip_row.setSpacing(4)
        self._chip_row.addStretch(1)
        results_layout.addLayout(self._chip_row)

        self._interface_result = QLabel("No interface detected yet")
        self._interface_result.setObjectName("metric")
        self._interface_result.setWordWrap(True)
        results_layout.addWidget(self._interface_result)
        self._results_table = QTableWidget(0, 2)
        self._results_table.setHorizontalHeaderLabels(["Result", ""])
        self._results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._results_table.setAlternatingRowColors(True)
        self._results_table.setMaximumHeight(150)
        self._results_table.verticalHeader().setVisible(False)
        header = self._results_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        self._results_table.cellDoubleClicked.connect(self._on_table_activated)
        results_layout.addWidget(self._results_table)
        # Buried area, ΔG/Kd, pDockQ and the PAE scores used to have a button
        # each here. "Characterise Interface" runs all four, and every one of
        # them was a second way to reach a number the card above was already
        # showing — a row of buttons offering to do what had just been done.
        # What stays is what characterise cannot do for you: copy the table,
        # and score against a reference structure you have to name.
        #
        # The two attributes survive because `_apply_structure_kind_to_metrics`
        # disables them on an experimental structure, together with the tiles
        # they fill. Kept as the handlers behind the Files card's loaders.
        self._confidence_button = QPushButton("pDockQ")
        self._ipsae_button = QPushButton("ipSAE / pDockQ2 / LIS")
        for hidden in (self._confidence_button, self._ipsae_button):
            hidden.setVisible(False)
        results_row = QHBoxLayout()
        copy_button = QPushButton("Copy Results")
        copy_button.clicked.connect(self._on_copy_results)
        results_row.addWidget(copy_button)
        results_row.addStretch(1)
        results_layout.addLayout(results_row)

        # DockQ needs a second structure, so it needs a chooser — and until
        # now it had neither. `_on_dockq` existed, read `self._reference_button`
        # and nothing ever built one or connected anything to the handler, so
        # the DOCKQ tile in the grid above could not be filled from the panel
        # at all. The same shape of gap as the B-factor metric: a capability
        # the UI did not admit to.
        dockq_row = QHBoxLayout()
        dockq_row.addWidget(QLabel("Compare with"))
        self._reference_button = AtomicStructureMenuButton(self.session)
        self._reference_button.setToolTip(
            "The experimental complex to score this model against. DockQ is "
            "reference-based: it says how close a prediction is to a known "
            "answer, which is a different question from whether an interface "
            "is believable on its own."
        )
        dockq_row.addWidget(self._reference_button, 1)
        # A reference is usually a file on disk, not something already open.
        # The chooser lists open models only, so scoring against a structure
        # you have not opened yet meant leaving the panel, opening it by hand,
        # and coming back — for the one command in here whose whole purpose is
        # to compare against an external answer.
        open_reference = QPushButton("Open…")
        open_reference.setObjectName("tonal")
        open_reference.setToolTip(
            "Open a reference structure from a file or a PDB id, and use it as "
            "the comparison."
        )
        open_reference.clicked.connect(self._on_open_reference)
        dockq_row.addWidget(open_reference)
        self._dockq_button = QPushButton("DockQ")
        self._dockq_button.setObjectName("tonal")
        self._dockq_button.clicked.connect(self._on_dockq)
        dockq_row.addWidget(self._dockq_button)
        results_layout.addLayout(dockq_row)
        layout.addWidget(results_card)

        # -- Files -------------------------------------------------------
        # One card for everything that comes from outside the structure: the
        # prediction's own confidence files, and a ΔΔG table from a separate
        # predictor. They were two rows in two places, which made them look
        # unrelated when the thing they have in common — MolCompose cannot
        # produce this, you have to supply it — is exactly what a user needs
        # to know.
        files_card, files_layout = self._card("Files")

        files_layout.addWidget(_section("Prediction confidence"))
        method_row = QHBoxLayout()
        self._predictor_combo = QComboBox()
        for label, value in (
            ("Detect automatically", "generic"),
            ("AlphaFold 3", "alphafold3"),
            ("AlphaFold Server", "alphafold-server"),
            ("AlphaFold DB", "alphafold-db"),
            ("AlphaFold 2 Multimer", "af2-multimer"),
            ("Protenix", "protenix"),
            ("Boltz / Boltz-2", "boltz"),
            ("ColabFold", "colabfold"),
            ("Chai-1", "chai"),
        ):
            self._predictor_combo.addItem(label, value)
        method_row.addWidget(self._predictor_combo, 1)
        resolve_button = QPushButton("Find files")
        resolve_button.setObjectName("tonal")
        resolve_button.setToolTip(
            "Locate the PAE matrix and the ipTM summary beside the model, and "
            "show which files were chosen before anything is computed from them."
        )
        resolve_button.clicked.connect(self._on_resolve_prediction_files)
        method_row.addWidget(resolve_button)
        files_layout.addLayout(method_row)

        # Resolution is shown, not just used. The engines index their samples
        # differently and the names differ by one character in places, so the
        # failure mode is a plausible number computed from another sample's
        # file — which looks exactly like success.
        self._file_table = QTableWidget(0, 2)
        self._file_table.setHorizontalHeaderLabels(["File", "Status"])
        self._file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._file_table.setMaximumHeight(88)
        self._file_table.verticalHeader().setVisible(False)
        self._file_table.horizontalHeader().setStretchLastSection(True)
        self._file_table.horizontalHeader().setHighlightSections(False)
        files_layout.addWidget(self._file_table)
        # Two buttons, because they are two files. "Find files" resolves both,
        # and either can come back missing while the other is found — so an
        # override for only one of them left the other unreachable: a run whose
        # summary is named in a way no predictor uses could report a PAE and no
        # ipTM, with nothing in the panel able to point at the file.
        choose_row = QHBoxLayout()
        pae_button = QPushButton("Choose PAE file…")
        pae_button.setToolTip(
            "Only needed when the PAE file is not beside the model, or is "
            "named in a way no supported predictor uses."
        )
        pae_button.clicked.connect(self._on_choose_pae)
        choose_row.addWidget(pae_button)
        summary_button = QPushButton("Choose summary file…")
        summary_button.setToolTip(
            "The file carrying ipTM and pTM, when it is not beside the model "
            "or is named in a way no supported predictor uses. It is a "
            "different file from the PAE matrix for every engine but ColabFold."
        )
        summary_button.clicked.connect(self._on_choose_summary)
        choose_row.addWidget(summary_button)
        files_layout.addLayout(choose_row)
        self._pae_label = _hint("Not resolved yet")
        files_layout.addWidget(self._pae_label)

        files_layout.addWidget(_section("Predicted ΔΔG"))
        ddg_row = QHBoxLayout()
        load_ddg_button = QPushButton("Load ΔΔG…")
        load_ddg_button.setToolTip(
            "Read predicted binding ΔΔG from an external predictor "
            "(PythiaStudio CSV or workbook, or a generic table) and rank the "
            "interface residues by it."
        )
        load_ddg_button.clicked.connect(self._on_load_ddg)
        ddg_row.addWidget(load_ddg_button)
        self._color_ddg_button = QPushButton("Colour by ΔΔG")
        self._color_ddg_button.setObjectName("tonal")
        self._color_ddg_button.setEnabled(False)
        self._color_ddg_button.setToolTip("Load ΔΔG predictions first")
        self._color_ddg_button.clicked.connect(lambda: self._on_color_by("ddg"))
        ddg_row.addWidget(self._color_ddg_button)
        self._color_dsasa_button = QPushButton("Colour by ΔSASA")
        self._color_dsasa_button.setObjectName("tonal")
        self._color_dsasa_button.setEnabled(False)
        self._color_dsasa_button.setToolTip("Detect an interface first")
        self._color_dsasa_button.clicked.connect(lambda: self._on_color_by("dsasa"))
        ddg_row.addWidget(self._color_dsasa_button)
        files_layout.addLayout(ddg_row)

        # The same shape one row down, because it is the same job: a
        # per-residue quantity the user brings with them, then a colouring.
        # Most people will never have an MD run behind them, but a disabled
        # row with a tooltip says what it wants; a hidden one says nothing.
        # Named for where the data comes from rather than for one method,
        # because it now holds two: an energy decomposition and a fluctuation,
        # and both arrive from a trajectory the panel never runs.
        files_layout.addWidget(_section("MD analysis"))
        # Before either button, because it applies to both and because the
        # failure it prevents is silent for MM/PBSA: a decomposition whose
        # residue names happen to match loads onto the wrong residues without
        # complaint. RMSF is refused outright, which is how this was found.
        # One sentence: the counts that make it concrete (108 deposited, 110
        # rebuilt) are in the help and in the error anyone actually hits.
        files_layout.addWidget(
            _hint(
                "MD repairs the structure before it runs. Load the repaired "
                "PDB, or the residues will not line up."
            )
        )
        energy_row = QHBoxLayout()
        load_energy_button = QPushButton("Load gmx_MMPBSA…")
        load_energy_button.setToolTip(
            "Read gmx_MMPBSA's per-residue decomposition "
            "(FINAL_DECOMP_MMPBSA.dat) — what each residue contributes to "
            "binding. Asks which of the file's chains is which of the "
            "structure's, because GROMACS usually renames them."
        )
        load_energy_button.clicked.connect(self._on_load_energy)
        energy_row.addWidget(load_energy_button)
        self._color_energy_button = QPushButton("Colour by MM/GBSA or MM/PBSA")
        self._color_energy_button.setObjectName("tonal")
        self._color_energy_button.setEnabled(False)
        self._color_energy_button.setToolTip("Load a decomposition first")
        self._color_energy_button.clicked.connect(
            lambda: self._on_color_by("mmpbsa")
        )
        energy_row.addWidget(self._color_energy_button)
        files_layout.addLayout(energy_row)
        files_layout.addWidget(
            _hint(
                "A residue's contribution to binding, negative where it is "
                "favourable — the opposite sign to ΔΔG. Not the interface's "
                "ΔG: MM/PBSA totals are not comparable with the predicted ΔG "
                "above."
            )
        )
        flex_row = QHBoxLayout()
        load_flex_button = QPushButton("Load RMSF…")
        load_flex_button.setToolTip(
            "Read per-residue RMS fluctuation from `gmx rmsf -res` — how much "
            "each residue moves over the trajectory. Asks which chains the "
            "file's blocks are, because gmx restarts its numbering at each."
        )
        load_flex_button.clicked.connect(self._on_load_flexibility)
        flex_row.addWidget(load_flex_button)
        self._color_rmsf_button = QPushButton("Colour by RMSF")
        self._color_rmsf_button.setObjectName("tonal")
        self._color_rmsf_button.setEnabled(False)
        self._color_rmsf_button.setToolTip("Load fluctuations first")
        self._color_rmsf_button.clicked.connect(lambda: self._on_color_by("rmsf"))
        flex_row.addWidget(self._color_rmsf_button)
        files_layout.addLayout(flex_row)
        files_layout.addWidget(
            _hint(
                "How much each residue moves, in Å. Not a contribution: a "
                "residue that moves a lot may be a loop away from the "
                "interface, and one that barely moves may just be buried."
            )
        )
        layout.addWidget(files_card)

        # -- Blocks ------------------------------------------------------
        blocks_card, blocks_layout = self._card("Blocks")
        blocks_layout.addWidget(
            _hint(
                "Detection divides the complex into four named parts. Each is "
                "a ChimeraX name, so it can be selected, recoloured, and "
                "referred to in a command."
            )
        )
        self._block_rows: dict[str, dict] = {}
        for kind in BLOCK_KINDS:
            row = QHBoxLayout()
            row.setSpacing(8)
            swatch = QPushButton("")
            swatch.setObjectName("swatch")
            swatch.setFixedSize(18, 18)
            swatch.setToolTip("Change this part's colour")
            swatch.clicked.connect(lambda _c=False, k=kind: self._on_pick_block_color(k))
            row.addWidget(swatch)

            # Two lines: what the part is, and the word ChimeraX knows it by.
            # The second is the reason the card exists — it is what you type.
            names = QVBoxLayout()
            names.setSpacing(0)
            label = QLabel(BLOCK_LABELS[kind])
            label.setObjectName("blockName")
            spec = QLabel("—")
            spec.setObjectName("blockSpec")
            names.addWidget(label)
            names.addWidget(spec)
            row.addLayout(names, 1)

            count = QLabel("—")
            count.setObjectName("blockCount")
            row.addWidget(count)
            select = QPushButton("Select")
            select.setObjectName("rowAction")
            select.clicked.connect(lambda _c=False, k=kind: self._on_select_block(k))
            row.addWidget(select)
            blocks_layout.addLayout(row)
            self._block_rows[kind] = {
                "swatch": swatch, "label": label, "spec": spec,
                "count": count, "select": select,
            }
        layout.addWidget(blocks_card)

        figure_card, figure_layout = self._card("Interface figure")
        self._surface_check = QCheckBox("Semi-transparent interface surface")
        self._surface_check.setToolTip(
            "Adds a faint envelope around both partners. Useful for seeing the "
            "shape of an unfamiliar complex, and it dims every colour beneath "
            "it — the published interface figures do without it."
        )
        figure_layout.addWidget(self._surface_check)
        swatch_row = QHBoxLayout()
        self._color_a_button = QPushButton("Group A color")
        self._color_a_button.clicked.connect(lambda: self._on_pick_group_color("a"))
        swatch_row.addWidget(self._color_a_button)
        self._color_b_button = QPushButton("Group B color")
        self._color_b_button.clicked.connect(lambda: self._on_pick_group_color("b"))
        swatch_row.addWidget(self._color_b_button)
        figure_layout.addLayout(swatch_row)
        # Which of the partner-coloured interface styles the button draws.
        # It used to draw `interface-focus` and nothing else, so the styles
        # added on 2026-08-16 could not be reached from this card at all —
        # the only preset chooser was on another tab, and it applies to the
        # whole structure rather than to the interface figure.
        #
        # Hot spots stay on their own button below: that preset paints a
        # metric ramp instead of partner colours, so it is a different
        # question rather than another way of drawing this one, and the two
        # group-colour buttons above do not apply to it.
        self._figure_preset_combo = QComboBox()
        for preset in grouped_presets().get("Interface", ()):
            if preset.hotspot_emphasis:
                continue
            self._figure_preset_combo.addItem(preset.display_name, preset.slug)
        self._figure_preset_combo.setToolTip(
            "Interface (partners): rendered, for a first look and for slides.\n"
            "Interface (flat outline): flat fills and a drawn edge, which is "
            "what survives single-column width and greyscale printing.\n"
            "Interface close-up: every side chain, labels and hydrogen bonds, "
            "framed on the residues that bury the most surface.\n"
            "The surface styles draw one group as a solid shape and leave the "
            "other a ribbon — pick the group by name, since which partner is "
            "chain A is a property of the file, not of the question. The "
            "translucent one keeps the fold visible inside the envelope."
        )
        figure_layout.addWidget(self._figure_preset_combo)

        # The count was a property of the preset and nothing else, so two
        # panels of one plate could disagree about how many residues are
        # labelled without anyone choosing that. Off by default here means
        # "whatever the preset was designed with"; ticking it takes over.
        #
        # A section header and a row, like every other control in this panel.
        # The first version put a bare "Label" checkbox against a full-width
        # spin box, which lined up with nothing above it, and carried the unit
        # inside the number as a suffix — " per side" is a phrase, not a unit
        # like Å or dpi, and it pushed the digit the eye is looking for into
        # the middle of a wide box.
        figure_layout.addWidget(_section("Residue labels"))
        label_row = QHBoxLayout()
        label_row.setSpacing(8)
        self._label_override = QCheckBox("Override the preset")
        self._label_override.setToolTip(
            "Unticked, each preset labels what it was designed to — two "
            "residues for the binder-loop close-up, three for the near view, "
            "none for the metric carriers. Tick this to set one count for "
            "every preset, which is what a multi-panel plate needs."
        )
        self._label_override.stateChanged.connect(self._on_label_override)
        label_row.addWidget(self._label_override)
        label_row.addStretch(1)
        self._label_count = QSpinBox()
        self._label_count.setRange(0, 20)
        self._label_count.setValue(3)
        self._label_count.setFixedWidth(64)
        self._label_count.setEnabled(False)
        self._label_count.setToolTip(
            "Residues per side, ranked by buried area. 0 turns labels off."
        )
        label_row.addWidget(self._label_count)
        self._label_unit = _hint("per side")
        label_row.addWidget(self._label_unit)
        figure_layout.addLayout(label_row)

        show_button = QPushButton("Show Interface Figure")
        show_button.setObjectName("primary")
        show_button.clicked.connect(self._on_show_interface)
        figure_layout.addWidget(show_button)
        # The two interface presets ask different questions of the same
        # geometry: where the interface is, versus which residues carry it.
        hotspot_button = QPushButton("Hot-spot Figure")
        hotspot_button.setObjectName("tonal")
        hotspot_button.setToolTip(
            "Same view, graded by buried area on one scale across both "
            "partners, so the eye compares magnitude rather than chain."
        )
        hotspot_button.clicked.connect(self._on_hotspot_figure)
        figure_layout.addWidget(hotspot_button)
        overlay_row = QHBoxLayout()
        self._hbonds_button = QPushButton("H-bonds")
        self._hbonds_button.clicked.connect(self._on_toggle_hbonds)
        overlay_row.addWidget(self._hbonds_button)
        self._contacts_button = QPushButton("Contacts")
        self._contacts_button.clicked.connect(self._on_toggle_contacts)
        overlay_row.addWidget(self._contacts_button)
        figure_layout.addLayout(overlay_row)
        self._interactions_button = QPushButton("Show Typed Interactions")
        self._interactions_button.setObjectName("tonal")
        self._interactions_button.clicked.connect(self._on_toggle_interactions)
        figure_layout.addWidget(self._interactions_button)
        layout.addWidget(figure_card)

        layout.addStretch(1)
        return tab

    def _metric_tile(self, key: str, caption: str) -> QWidget:
        box = QWidget()
        box.setObjectName("tile")
        layout = QVBoxLayout()
        layout.setSpacing(1)
        layout.setContentsMargins(10, 8, 10, 8)
        value = QLabel("—")
        value.setObjectName("tileValue")
        label = QLabel(caption)
        label.setObjectName("tileCaption")
        layout.addWidget(value)
        layout.addWidget(label)
        box.setLayout(layout)
        self._tiles[key] = value
        self._tile_boxes[key] = box
        self._tile_captions[key] = (label, caption)
        return box

    def _set_tile_tooltip(self, key: str, text: str) -> None:
        """Tooltip on the whole tile — the box and both labels.

        It had been set on the value label alone, so the hover target was the
        few characters of the number itself and the tooltip was, in practice,
        undiscoverable.
        """
        widgets = [self._tiles.get(key), self._tile_boxes.get(key)]
        caption = self._tile_captions.get(key)
        if caption:
            widgets.append(caption[0])
        for widget in widgets:
            if widget is not None:
                widget.setToolTip(text)

    def _set_metric(self, key: str, text: str) -> None:
        value = self._tiles.get(key)
        if value is None:
            return
        value.setText(text)
        box = self._tile_boxes.get(key)
        if box is not None:
            # A muted tile stays muted while it is empty: clearing metrics
            # must not quietly promote "impossible here" back to "pending".
            muted = box.objectName() == "tileMuted"
            if text != "—":
                box.setObjectName("tileActive")
            elif not muted:
                box.setObjectName("tile")
            box.setStyleSheet(_PANEL_QSS)

    # Tiles that exist only for predicted models. On a crystal structure they
    # can never be filled, and showing them in the same style as an unfilled
    # one says "not computed yet" when the truth is "never".
    PREDICTED_ONLY_TILES = ("ipsae", "pdockq2", "iptm", "ptm", "pae", "lis",
                            "pdockq", "plddt", "iplddt")

    def _apply_structure_kind_to_metrics(
        self, predicted: bool, method: str, confidence_issue: str = ""
    ) -> None:
        """Grey out what this structure can never produce.

        The author's complaint, and it is a fair one: an experimental
        structure still showed ipSAE, pDockQ2 and ipTM looking live. They were
        not clickable, but nothing said so — a disabled tonal button kept its
        indigo emphasis, and an empty tile looks the same whether the number
        is pending or impossible. Both now go visibly flat, and the reason is
        on the tooltip.
        """
        why = confidence_issue or (
            f"Predicted models only — this structure is experimental ({method})."
            if method else "Open a predicted structure first."
        )
        for key in self.PREDICTED_ONLY_TILES:
            box = self._tile_boxes.get(key)
            if box is None:
                continue
            if not predicted:
                box.setObjectName("tileMuted")
                box.setStyleSheet(_PANEL_QSS)
            box.setToolTip("" if predicted else why)
        for button in (getattr(self, "_confidence_button", None),
                       getattr(self, "_ipsae_button", None)):
            if button is not None:
                button.setEnabled(predicted)
                button.setToolTip("" if predicted else why)

    def _set_tile_value(self, key: str, value, prefix: str = "") -> None:
        """Write a number into a tile, formatted the one way that tile is."""
        if value is None:
            return
        fmt = TILE_FORMATS.get(key, "{}")
        try:
            self._set_metric(key, prefix + fmt.format(value))
        except (TypeError, ValueError):
            self._set_metric(key, prefix + str(value))

    def _refresh_tiles_from_state(self) -> None:
        """Fill the result tiles from what the session already knows.

        The click that runs a command sees its return value; nothing else does.
        So an interface characterised at the command line — or by an agent
        through MCP — left this panel showing nine dashes beside a fully
        analysed structure, which reads as "nothing has been done".

        Only ever sets, never clears. A tile filled by a click whose value is
        not in session state must survive a notification arriving afterwards,
        and a metric nobody has computed has to keep reading "—" rather than
        being invented here.
        """
        from ..commands import resolve_model, state_for

        model = self._current_model()
        if model is None:
            return
        try:
            resolved = resolve_model(self.session, model)
        except Exception:  # noqa: BLE001 - a refresh must not raise at the user
            return
        state = state_for(self.session)
        model_id = model_ref(resolved).model_id

        interface = state.interfaces.get(model_id)
        if interface is not None:
            self._set_metric("contacts", str(len(interface.contacts)))
            self._set_metric(
                "residues", f"{len(interface.group_a)}+{len(interface.group_b)}"
            )
        stored = state.metrics.get(model_id, {})
        self._describe_dockq(stored)
        self._describe_interface_definition(state.interface_params.get(model_id))
        for key in ("bsa", "dg", "kd", "dockq", "ipsae", "pdockq2",
                    "ptm", "pae", "lis", "pdockq", "plddt", "iplddt"):
            self._set_tile_value(key, stored.get(key))
        # ipTM keeps the distinction the two fields carry upstream: a per-pair
        # value is the interface's, a whole-complex one is marked with a tilde
        # because it averages over every chain pair in the model.
        if stored.get("iptm") is not None:
            self._set_tile_value("iptm", stored["iptm"])
        elif stored.get("iptm_global") is not None:
            self._set_tile_value("iptm", stored["iptm_global"], prefix="~")
        interactions = state.interactions.get(model_id)
        if interactions:
            self._set_chips(self._interaction_counts(interactions))

    def _describe_interface_definition(self, params) -> None:
        """Say which interface definition the averaged metrics were taken over."""
        if not params:
            for key in ("pdockq", "iplddt"):
                self._set_tile_tooltip(key, "")
            return
        _chains_a, _chains_b, criterion, cutoff = params
        # pDockQ measures its own Cβ 8 Å interface whatever is on screen, so it
        # says that rather than naming the detected one. ipLDDT genuinely is an
        # average over the interface you asked for, so it names it.
        self._set_tile_tooltip(
            "pdockq",
            "Measured over pDockQ's own interface definition — Cβ at 8 Å, as "
            "published — regardless of the cutoff used for display.",
        )
        self._set_tile_tooltip(
            "iplddt",
            f"Mean pLDDT over the interface as currently detected: "
            f"{criterion} at {cutoff:g} Å.",
        )

    def _describe_dockq(self, stored: dict) -> None:
        """Put DockQ's components on the tile, without giving each one a tile.

        Six more tiles for the parts of one number would double the grid to
        show a breakdown most readers never open. They go in the tooltip, and
        the CAPRI class — the categorical reading everyone actually quotes —
        joins the caption, because "0.977" and "High" say different things and
        the second is the one that ends up in a sentence.
        """
        widget = self._tiles.get("dockq")
        caption, original = self._tile_captions.get("dockq", (None, "DOCKQ"))
        if widget is None:
            return
        parts = [
            (f"Fnat {stored['dockq_fnat']:.3f}" if "dockq_fnat" in stored else ""),
            (f"Fnonnat {stored['dockq_fnonnat']:.3f}"
             if "dockq_fnonnat" in stored else ""),
            (f"iRMSD {stored['dockq_irmsd']:.2f} Å" if "dockq_irmsd" in stored else ""),
            (f"LRMSD {stored['dockq_lrmsd']:.2f} Å" if "dockq_lrmsd" in stored else ""),
            (f"F1 {stored['dockq_f1']:.3f}" if "dockq_f1" in stored else ""),
            (f"{int(stored['dockq_clashes'])} clashing residue pair(s)"
             if "dockq_clashes" in stored else ""),
        ]
        detail = ", ".join(part for part in parts if part)
        self._set_tile_tooltip("dockq", detail or "")
        capri = stored.get("dockq_capri")
        if caption is not None:
            caption.setText(f"{original} · {capri.upper()}" if capri else original)

    @staticmethod
    def _interaction_counts(interactions) -> dict:
        """Typed-interaction counts by kind, from what detection stored."""
        counts: dict = {}
        for item in interactions:
            kind = getattr(item, "kind", None) or (
                item.get("kind") if isinstance(item, dict) else None
            )
            if kind:
                counts[kind] = counts.get(kind, 0) + 1
        return counts

    def _clear_metrics(self) -> None:
        for key in self._tiles:
            self._set_metric(key, "—")
        self._set_chips({})

    def _set_chips(self, counts: dict) -> None:
        """Coloured interaction chips that double as a legend for the 3D view."""
        while self._chip_row.count():
            item = self._chip_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for kind, count in sorted(counts.items()):
            if not count:
                continue
            colour = INTERACTION_COLORS.get(kind, "#8A8D96")
            chip = _ClickableLabel(f"{kind.replace('-', ' ')} {count}")
            chip.setObjectName("chipClickable")
            chip.setStyleSheet(f"background: {colour}22; color: {colour};")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(
                f"Select the residues making the {kind.replace('-', ' ')} "
                f"interactions"
            )
            chip.clicked.connect(lambda k=kind: self._on_select_interaction(k))
            self._chip_row.addWidget(chip)
        self._chip_row.addStretch(1)

    def _build_export_tab(self) -> QWidget:
        tab, layout = self._tab()

        image_card, image_layout = self._card("Publication image")
        # Journals specify artwork in millimetres and dpi; this card used to
        # ask only for pixels, which left the conversion to the user on every
        # export and produced figures whose print size nobody had decided.
        image_layout.addWidget(_section("Print size"))
        preset_row = QHBoxLayout()
        self._print_size_combo = QComboBox()
        for label, width_mm in (
            ("Single column · 85 mm", COLUMN_MM["single"]),
            ("Double column · 174 mm", COLUMN_MM["double"]),
            ("Custom (px below)", 0.0),
        ):
            self._print_size_combo.addItem(label, width_mm)
        self._print_size_combo.currentIndexChanged.connect(self._on_print_size)
        preset_row.addWidget(self._print_size_combo, 1)
        self._dpi_combo = QComboBox()
        for dpi in (300, 600, 1200):
            self._dpi_combo.addItem(f"{dpi} dpi", dpi)
        self._dpi_combo.setCurrentIndex(1)
        self._dpi_combo.setToolTip(
            "Stamped into the file, so a publisher reads the physical size "
            "rather than asking for the figure again. 600 dpi is what most "
            "ask for when line art and a rendered image share a plate — "
            "which is what every figure this panel makes is."
        )
        self._dpi_combo.currentIndexChanged.connect(self._on_print_size)
        preset_row.addWidget(self._dpi_combo)
        image_layout.addLayout(preset_row)

        image_layout.addWidget(_section("Size (px)"))
        size_row = QHBoxLayout()
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 16384)
        self._width_spin.setValue(2400)
        self._height_spin = QSpinBox()
        self._height_spin.setRange(1, 16384)
        self._height_spin.setValue(1800)
        size_row.addWidget(self._width_spin)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self._height_spin)
        # `view` frames the scene for the window's shape, and `save` renders
        # a different shape without re-framing it, so an export whose aspect
        # ratio differs from the window's crops or pads the figure that was
        # composed on screen. This sets the height that makes them agree.
        aspect_button = QPushButton("Match window")
        aspect_button.setObjectName("tonal")
        aspect_button.setToolTip(
            "Set the height so the exported aspect ratio matches the "
            "graphics window. A different ratio re-crops the framing you "
            "composed on screen."
        )
        aspect_button.clicked.connect(self._on_match_aspect)
        size_row.addWidget(aspect_button)
        image_layout.addLayout(size_row)
        self._print_size_hint = _hint("")
        image_layout.addWidget(self._print_size_hint)

        image_layout.addWidget(_section("Supersample"))
        self._supersample_spin = QSpinBox()
        self._supersample_spin.setRange(1, 8)
        self._supersample_spin.setValue(3)
        image_layout.addWidget(self._supersample_spin)

        # The key's font is in pixels of the exported image, so what it comes
        # out as in print depends on how wide the figure is placed: the
        # default suits one panel across two columns and is too small for the
        # same panel as one cell of four. Leaving it at the shipped value
        # sends nothing, so an untouched panel exports exactly as before.
        image_layout.addWidget(_section("Colour key font"))
        key_row = QHBoxLayout()
        self._key_font_spin = QSpinBox()
        self._key_font_spin.setRange(4, 400)
        self._key_font_spin.setValue(DEFAULT_KEY_FONT)
        self._key_font_spin.setToolTip(
            "Pixels of the exported image, not points. Larger for a figure "
            "that will be printed small."
        )
        key_row.addWidget(self._key_font_spin)
        self._key_font_hint = _hint("")
        key_row.addWidget(self._key_font_hint, 1)
        image_layout.addLayout(key_row)
        self._key_font_spin.valueChanged.connect(self._update_key_font_hint)
        self._update_key_font_hint()

        self._transparent_check = QCheckBox("Transparent background")
        self._session_check = QCheckBox("Also save ChimeraX session (.cxs)")
        self._recipe_check = QCheckBox("Also save the command recipe (.cxc)")
        self._recipe_check.setChecked(True)
        self._recipe_check.setToolTip(
            "The commands that produced this figure, written beside it and "
            "replayable with `open <file>.cxc`. A recipe that lives only in "
            "the Log is gone when the session closes, and a figure sent to a "
            "collaborator arrives with nothing attached."
        )
        image_layout.addWidget(self._transparent_check)
        image_layout.addWidget(self._session_check)
        image_layout.addWidget(self._recipe_check)

        export_button = QPushButton("Export Image")
        export_button.setObjectName("primary")
        export_button.clicked.connect(self._on_export)
        image_layout.addWidget(export_button)
        reveal_button = QPushButton("Show Last Export in Finder")
        reveal_button.setObjectName("tonal")
        reveal_button.setEnabled(False)
        reveal_button.clicked.connect(self._on_reveal_export)
        self._reveal_button = reveal_button
        image_layout.addWidget(reveal_button)
        layout.addWidget(image_card)
        self._on_print_size()


        report_card, report_layout = self._card("Interface report")
        report_layout.addWidget(
            _hint(
                "One file with the full characterization: geometry, typed "
                "interactions, buried area, predicted ΔG/Kd, confidence, an "
                "auto-written Methods paragraph, and the command recipe."
            )
        )
        report_button = QPushButton("Write Report…")
        report_button.setObjectName("tonal")
        report_button.clicked.connect(self._on_report)
        report_layout.addWidget(report_button)
        report_layout.addWidget(
            _hint(
                "Every export is reproducible: the exact commands are recorded "
                "in the ChimeraX Log."
            )
        )
        layout.addWidget(report_card)

        layout.addStretch(1)
        return tab

    def _build_agent_tab(self) -> QWidget:
        """Action first, plumbing behind a disclosure, setup last.

        The previous order was the reverse of every other tab in this panel: the
        executable path and the argument template were the first two rows, then
        a Step 1/2/3 wall, then fourteen lines of example prompts, and the box
        you actually type in was below all of it. Nothing else here leads with
        configuration, and nothing else reads like a README.
        """
        tab, layout = self._tab()
        self._build_chat_card(layout)
        self._build_bridge_card(layout)
        layout.addStretch(1)
        return tab

    def _build_bridge_card(self, layout) -> None:
        """For driving this session from a client that is not this panel."""
        card, card_layout = self._card("Use your own client")
        card_layout.addWidget(
            _hint(
                "Claude Desktop, an editor, a script — anything that speaks MCP "
                "can drive these same validated, logged commands. The chat box "
                "above starts the bridge for you; this button is for when the "
                "client is somewhere else."
            )
        )
        self._bridge_button = QPushButton("Start Agent Bridge")
        self._bridge_button.setObjectName("tonal")
        self._bridge_button.clicked.connect(self._on_start_bridge)
        card_layout.addWidget(self._bridge_button)

        # Folded away by default. Someone who already has an MCP client can
        # hand it the setup instead of following it themselves, and someone
        # who does not never has to read it — which is why it is a disclosure
        # and not another paragraph on a tab that has enough of them.
        self._setup_prompt_toggle = QPushButton("")
        self._setup_prompt_toggle.setObjectName("disclosure")
        self._setup_prompt_toggle.clicked.connect(self._on_toggle_setup_prompt)
        card_layout.addWidget(self._setup_prompt_toggle)
        self._setup_prompt_box = QWidget()
        prompt_layout = QVBoxLayout()
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_layout.setSpacing(6)
        self._setup_prompt = QLabel()
        self._setup_prompt.setObjectName("code")
        self._setup_prompt.setWordWrap(True)
        self._setup_prompt.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        prompt_layout.addWidget(self._setup_prompt)
        copy_prompt = QPushButton("Copy setup prompt")
        copy_prompt.setObjectName("tonal")
        copy_prompt.clicked.connect(self._on_copy_setup_prompt)
        prompt_layout.addWidget(copy_prompt)
        self._setup_prompt_box.setLayout(prompt_layout)
        card_layout.addWidget(self._setup_prompt_box)
        self._set_setup_prompt_visible(False)

        card_layout.addWidget(_section("In a terminal, not the ChimeraX command line"))
        self._bridge_snippet = QLabel()
        snippet = self._bridge_snippet
        snippet.setObjectName("code")
        snippet.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(snippet)
        # Said in the panel because it is true of the machine, not of the
        # agent: the bridge the agent talks to is ChimeraX's own REST control,
        # which carries no authentication, so while a turn is possible any
        # process on this computer can drive this session. Nothing in the
        # tool surface changes that, so it is disclosed rather than implied.
        card_layout.addWidget(
            _hint(
                "While the bridge is running, ChimeraX accepts commands on "
                "127.0.0.1 without authentication — from the agent and from "
                "anything else on this computer. Stop it when you are not "
                "using it."
            )
        )
        card_layout.addWidget(
            _hint(
                "An agent reaches MolCompose through the same validated, "
                "logged commands as the buttons in this panel, and the panel "
                "reports the operations it verified rather than the agent's "
                "account of them. Every figure it exports carries the full "
                "command recipe and an agent-provenance record."
            )
        )
        layout.addWidget(card)

    # Four things a first-time user would actually ask, short enough to sit on
    # a chip. They replace a fourteen-line blockquote that owned the tab, and
    # unlike it they put the words into the input.
    CHAT_SUGGESTIONS = (
        ("Which chains touch?",
         "Which chains of the open structure actually touch each other?"),
        ("Characterise this interface",
         "Characterise the interface between the two chains that touch: "
         "contacts, salt bridges, buried area and the predicted binding "
         "affinity. Report the numbers the tools return."),
        ("Rank the hot spots",
         "Which residues bury the most surface at this interface?"),
        ("Make a figure",
         "Make a publication figure of this interface with a colour-blind safe "
         "palette and export it at 600 dpi."),
    )

    def _build_chat_card(self, layout) -> None:
        """A chat box that drives a locally installed, already-signed-in agent CLI."""
        self._agents = find_agents()
        self._server_executable = locate("molcompose-mcp")
        self._agent_process = None
        self._active_agent = None
        self._agent_answer_path = None
        self._agent_output_directory = None
        self._agent_raw_output = ""

        chat_card, chat_layout = self._card("Ask in this window")
        chat_layout.addWidget(
            _hint(
                "Runs your own installed, signed-in agent CLI as a subprocess and "
                "points it at this ChimeraX session. MolCompose never embeds a "
                "language model and never stores an API key."
            )
        )

        # What is set up, in one line. The picker and the paths are behind the
        # disclosure below: which binary runs is worth being able to see and
        # change, and worth not being the first thing in the tab.
        self._agent_status = QLabel("")
        self._agent_status.setObjectName("agentStatus")
        self._agent_status.setWordWrap(True)
        chat_layout.addWidget(self._agent_status)

        self._agent_setup_toggle = QPushButton("")
        self._agent_setup_toggle.setObjectName("disclosure")
        self._agent_setup_toggle.clicked.connect(self._on_toggle_agent_setup)
        chat_layout.addWidget(self._agent_setup_toggle)

        setup = QWidget()
        setup_layout = QVBoxLayout()
        setup_layout.setContentsMargins(0, 0, 0, 4)
        setup_layout.setSpacing(6)
        setup.setLayout(setup_layout)
        self._agent_setup = setup

        setup_layout.addWidget(_section("Agent CLI"))
        self._agent_combo = QComboBox()
        for agent, resolved in self._agents:
            self._agent_combo.addItem(agent.label, agent.key)
            self._agent_combo.setItemData(
                self._agent_combo.count() - 1, resolved, Qt.ItemDataRole.UserRole + 1
            )
        # Always offered, whether or not anything was auto-detected. The two
        # names this panel knows are not the two agents that exist: someone
        # else's CLI, or one of these installed where `locate` does not look,
        # used to mean the chat box simply never appeared.
        self._agent_combo.addItem(CUSTOM_AGENT.label, CUSTOM_KEY)
        self._agent_combo.currentIndexChanged.connect(self._on_agent_changed)
        setup_layout.addWidget(self._agent_combo)

        setup_layout.addWidget(_section("Executable"))
        path_row = QHBoxLayout()
        self._agent_path = QLineEdit()
        self._agent_path.setPlaceholderText("path to the agent executable")
        self._agent_path.setToolTip(
            "The binary this panel will run. Auto-detected for the agents "
            "MolCompose knows; type or browse to any other one."
        )
        self._agent_path.textChanged.connect(self._refresh_agent_status)
        path_row.addWidget(self._agent_path, 1)
        browse_button = QPushButton("Browse…")
        browse_button.setObjectName("tonal")
        browse_button.clicked.connect(self._on_browse_agent)
        path_row.addWidget(browse_button)
        setup_layout.addLayout(path_row)

        setup_layout.addWidget(_section("Arguments"))
        self._agent_arguments = QLineEdit()
        self._agent_arguments.setPlaceholderText(
            "arguments, e.g.  exec {prompt}   ·   --mcp-config {config} {prompt}"
        )
        self._agent_arguments.setToolTip(
            "{prompt} is replaced by what you type below and {config} by a "
            "generated MCP config pointing at this ChimeraX session. Leave "
            "{prompt} out and it is appended, which is what most CLIs want."
        )
        setup_layout.addWidget(self._agent_arguments)
        chat_layout.addWidget(setup)

        self._chat_run_status = QLabel("Ready")
        self._chat_run_status.setObjectName("agentRunStatus")
        chat_layout.addWidget(self._chat_run_status)

        self._chat_log = QPlainTextEdit()
        self._chat_log.setObjectName("chatLog")
        self._chat_log.setReadOnly(True)
        self._chat_log.setPlaceholderText(
            "The agent's answer appears here."
        )
        # Bounded, not just floored. With the configuration rows moved behind
        # the disclosure this became the only expanding widget in the card, so
        # an empty log grew into 400 px of dark nothing — the largest thing on
        # the tab was the part with no content in it.
        self._chat_log.setMinimumHeight(120)
        self._chat_log.setMaximumHeight(220)
        chat_layout.addWidget(self._chat_log)

        self._agent_verified = QLabel("")
        self._agent_verified.setObjectName("agentVerified")
        self._agent_verified.setWordWrap(True)
        self._agent_verified.setVisible(False)
        chat_layout.addWidget(self._agent_verified)

        self._agent_unverified = QLabel("")
        self._agent_unverified.setObjectName("agentUnverified")
        self._agent_unverified.setWordWrap(True)
        self._agent_unverified.setVisible(False)
        chat_layout.addWidget(self._agent_unverified)

        self._chat_details_toggle = QPushButton("▸  Run details")
        self._chat_details_toggle.setObjectName("disclosure")
        self._chat_details_toggle.clicked.connect(self._on_toggle_chat_details)
        chat_layout.addWidget(self._chat_details_toggle)

        self._chat_details = QPlainTextEdit()
        self._chat_details.setObjectName("chatDetails")
        self._chat_details.setReadOnly(True)
        self._chat_details.setMaximumHeight(160)
        self._chat_details.setVisible(False)
        chat_layout.addWidget(self._chat_details)

        self._chat_input = QPlainTextEdit()
        self._chat_input.setObjectName("chatInput")
        self._chat_input.setPlaceholderText(
            "Ask in plain language — or start from one of the suggestions below"
        )
        self._chat_input.setMaximumHeight(64)
        chat_layout.addWidget(self._chat_input)

        send_row = QHBoxLayout()
        self._chat_send = QPushButton("Send to agent")
        self._chat_send.setObjectName("primary")
        self._chat_send.clicked.connect(self._on_chat_send)
        send_row.addWidget(self._chat_send, 1)
        self._chat_stop = QPushButton("Stop")
        self._chat_stop.clicked.connect(self._on_chat_stop)
        self._chat_stop.setEnabled(False)
        send_row.addWidget(self._chat_stop)
        chat_layout.addLayout(send_row)

        # Two rows of two, each hugging its own text with a stretch after it.
        # A grid stretched them to half the card's width, and a 14 px radius on
        # a 260 px bar is not a chip — it is a button with slightly soft
        # corners, which is what these looked like.
        for start in (0, 2):
            row = QHBoxLayout()
            row.setSpacing(6)
            for label, prompt in self.CHAT_SUGGESTIONS[start:start + 2]:
                chip = QPushButton(label)
                chip.setObjectName("suggest")
                chip.setToolTip(prompt)
                chip.setSizePolicy(QSizePolicy.Policy.Maximum,
                                   QSizePolicy.Policy.Fixed)
                chip.clicked.connect(
                    lambda _checked=False, text=prompt:
                    self._chat_input.setPlainText(text)
                )
                row.addWidget(chip)
            row.addStretch(1)
            chat_layout.addLayout(row)

        # The longer prompts the chips are short forms of. Behind a disclosure
        # because they are worth reading once and in the way afterwards — the
        # fourteen-line blockquote they replace was permanently in the way.
        self._examples_toggle = QPushButton("")
        self._examples_toggle.setObjectName("disclosure")
        self._examples_toggle.clicked.connect(self._on_toggle_examples)
        chat_layout.addWidget(self._examples_toggle)
        self._examples = QLabel(
            "“Open 1BRS and show me which chains actually touch each other.”\n\n"
            "“Characterise the A–D interface: contacts, salt bridges, buried "
            "area, and the predicted binding affinity.”\n\n"
            "“Which residues bury the most surface, and how does that compare "
            "with the predicted ΔΔG?”\n\n"
            "“I have an AlphaFold model of this complex — how confident is the "
            "interface, and how close is it to the crystal structure?”\n\n"
            "“Draw the antigen as a surface with the epitope on it, and export "
            "it at single-column width.”\n\n"
            "“Write the complete interface report, including a Methods "
            "paragraph I can paste into the manuscript.”"
        )
        self._examples.setObjectName("examples")
        self._examples.setWordWrap(True)
        self._examples.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        chat_layout.addWidget(self._examples)
        self._set_examples_visible(False)

        # Each turn here is one non-interactive process: it cannot stop to ask
        # whether a tool call is allowed, which is exactly why the MolCompose
        # tools are permitted up front and nothing else is, and it cannot
        # answer a follow-up. A terminal can do both, against this same
        # session, so the panel hands the command over rather than pretending.
        terminal_button = QPushButton("Copy Terminal Command (interactive)")
        terminal_button.setObjectName("tonal")
        terminal_button.setToolTip(
            "Turns here are single non-interactive runs — one process per "
            "question, with the MolCompose tools pre-approved and nothing "
            "else. This copies the command that starts the same agent as a "
            "conversation in your terminal, pointed at this same ChimeraX "
            "session, where it can ask before each tool call and remember "
            "what you asked before."
        )
        terminal_button.clicked.connect(self._on_copy_terminal_command)
        chat_layout.addWidget(terminal_button)
        layout.addWidget(chat_card)
        self._on_agent_changed()
        self._set_agent_setup_visible(not self._agents)

    def _set_agent_setup_visible(self, visible: bool) -> None:
        """Open the disclosure when there is something to fix, closed otherwise.

        With no CLI auto-detected the panel cannot do anything until a path is
        given, so hiding the field that gives it would be a dead end.
        """
        self._agent_setup.setVisible(visible)
        self._agent_setup_toggle.setText(
            "▾  Hide setup" if visible else "▸  Setup — executable, arguments"
        )

    def _set_agent_choice_enabled(self, enabled: bool) -> None:
        """The agent cannot be changed out from under a turn that is running."""
        self._agent_combo.setEnabled(enabled)
        self._agent_path.setEnabled(enabled)
        if enabled:
            # Restoring, not enabling: the arguments field is editable only
            # for a custom command, and that rule outlives the turn.
            self._agent_arguments.setEnabled(
                self._agent_combo.currentData() == CUSTOM_KEY
            )
        else:
            self._agent_arguments.setEnabled(False)

    def _set_setup_prompt_visible(self, visible: bool) -> None:
        self._setup_prompt_box.setVisible(visible)
        self._setup_prompt_toggle.setText(
            "▾  Hide setup prompt" if visible
            else "▸  Setup prompt — hand the setup to an agent"
        )
        if visible:
            self._setup_prompt.setText(self._setup_prompt_text())

    def _on_toggle_setup_prompt(self) -> None:
        self._set_setup_prompt_visible(not self._setup_prompt_box.isVisible())

    def _on_copy_setup_prompt(self) -> None:
        QApplication.clipboard().setText(self._setup_prompt_text())
        self._set_status("Setup prompt copied — paste it into an MCP client.")

    def _setup_prompt_text(self) -> str:
        """The setup, addressed to an agent, split by who can actually do each step.

        The first version read as one paragraph of instructions and asked the
        agent to run `toolshed install` and `remotecontrol rest start`. It can
        do neither: both are outside the bridge's whitelist, and the second
        could not work anyway because it is the command that *creates* the
        bridge. An agent handed that tries, fails, and improvises.

        So the steps are numbered and each says whose it is. The port is read
        from the running bridge rather than assumed, and the agent is told to
        wait for its own tools to appear — registering an MCP server rarely
        takes effect until the CLI restarts, and a prompt that ignores that
        produces an agent confidently calling tools it does not have.
        """
        port = self._bridge_port() or 3000
        return (
            "Help me set up MolCompose, a UCSF ChimeraX bundle you drive "
            "through an MCP server. The first two steps are mine to run — "
            "ChimeraX takes no remote install and cannot be told remotely to "
            "open its own bridge. Ask me for them and wait.\n\n"
            "Step 1. I run `toolshed install ChimeraX_MolCompose` in ChimeraX, "
            "then quit it and start it again; a running session keeps the "
            "modules it already loaded.\n\n"
            "Step 2. I run `remotecontrol rest start port "
            f"{port} json true`. Ask me which port it printed — it is not "
            "always the one asked for.\n\n"
            "Step 3. Install `molcompose-mcp` and register it with yourself as "
            "an MCP stdio server, arguments "
            f"`--chimerax-url http://127.0.0.1:{port}`. Register its absolute "
            "path: you launch it in your own environment, not the shell that "
            "installed it. Most CLIs load a new server only at start, so "
            "restart if you must, and stop until your molcompose tools are "
            "listed.\n\n"
            "Step 4. Open PDB 1BRS and characterise the interface "
            "between chains A and D, then show it with the "
            "Interface (binder loop) preset. Walk me through every number you "
            "report. For each one: the exact command or sub-step that produced "
            "it, what it means, and its criterion and cutoff. Where a number "
            "has no cutoff, state the convention or formula that defines it "
            "instead. Also list any analyses that do not apply to this "
            "structure and why. Where a well-known reference range or "
            "experimental value exists, give it for comparison. A number "
            "without its yardstick compares to nothing."
        )

    def _set_examples_visible(self, visible: bool) -> None:
        self._examples.setVisible(visible)
        self._examples_toggle.setText(
            "▾  Hide examples" if visible else "▸  More examples of what to ask"
        )

    def _on_toggle_examples(self) -> None:
        self._set_examples_visible(not self._examples.isVisible())

    def _on_toggle_agent_setup(self) -> None:
        self._set_agent_setup_visible(not self._agent_setup.isVisible())

    def _set_chat_details_visible(self, visible: bool) -> None:
        self._chat_details.setVisible(visible)
        self._chat_details_toggle.setText(
            "▾  Hide run details" if visible else "▸  Run details"
        )

    def _on_toggle_chat_details(self) -> None:
        self._set_chat_details_visible(not self._chat_details.isVisible())

    def _refresh_agent_status(self, *_args) -> None:
        """One line: which CLI will run, and whether the bridge is up."""
        if getattr(self, "_agent_status", None) is None:
            return
        executable = self._agent_path.text().strip()
        label = self._agent_combo.currentText() or "Agent"
        port = self._bridge_port()
        bridge = (
            f"bridge on port {port}" if port else "bridge starts when you send"
        )
        self._refresh_bridge_card(port)
        if not executable:
            self._agent_status.setObjectName("agentStatusWarn")
            self._agent_status.setText(
                "No agent CLI found. ChimeraX launched from the Dock does not "
                "inherit your shell PATH, so an installed one can still be "
                "invisible here — open Setup and browse to it."
            )
        elif not self._server_executable:
            self._agent_status.setObjectName("agentStatusWarn")
            self._agent_status.setText(
                f"{label} ready, but molcompose-mcp is not on PATH — install it "
                "with pip so the agent can reach ChimeraX."
            )
        else:
            self._agent_status.setObjectName("agentStatus")
            # No path. This line answers "is it ready", not "which file" — and
            # the path is already in the Executable field one click away, which
            # is the same click you would make to change it. Printing it here
            # too put it on screen twice whenever Setup was open.
            #
            # The custom entry is the exception: "Custom command" identifies
            # nothing on its own, so there the binary's name is the label.
            detail = ""
            if self._agent_combo.currentData() == CUSTOM_KEY and executable:
                detail = f" · {Path(executable).name}"
            self._agent_status.setText(f"{label}{detail} · {bridge}")
        # An object name change needs the sheet reapplied to take effect.
        self._agent_status.setStyleSheet(_PANEL_QSS)

    # -- agent chat --------------------------------------------------------

    def _append_chat(self, text: str) -> None:
        self._chat_log.appendPlainText(text.rstrip())

    def _append_chat_detail(self, text: str) -> None:
        self._chat_details.appendPlainText(text.rstrip())

    def _refresh_bridge_card(self, port) -> None:
        """The button and the command line follow the bridge, not a constant.

        A running bridge on 3010 used to be offered a button reading "Start
        Agent Bridge (port 3000)" beside a command naming a port with nothing
        on it. Both now say where the bridge actually is, and the button stops
        inviting a start that ChimeraX will decline.
        """
        button = getattr(self, "_bridge_button", None)
        if button is not None:
            button.setText(
                f"Agent Bridge running on port {port}" if port
                else "Start Agent Bridge (port 3000)"
            )
            button.setEnabled(port is None)
        snippet = getattr(self, "_bridge_snippet", None)
        if snippet is not None:
            snippet.setText(
                "pip install molcompose-mcp\n"
                f"molcompose-mcp --chimerax-url http://127.0.0.1:{port or 3000}"
            )

    def _bridge_port(self) -> int | None:
        """The port ChimeraX's REST server is on, or None if it is not up.

        Asked of ChimeraX rather than guessed by probing 3000. A session that
        already had `remotecontrol rest start port 3010` — a second ChimeraX,
        a script, a habit — left this panel probing a port nothing was on, so
        it reported the bridge down while it was up. Clicking the button then
        ran `rest start port 3000`, which ChimeraX answers with success and no
        second listener when a server is already running, so the panel probed
        3000 again, still found nothing, and asked again. The loop had no exit.
        """
        try:
            from chimerax.rest_server.cmd import _server
        except Exception:  # pragma: no cover - depends on the host ChimeraX
            return None
        address = getattr(_server, "server_address", None) if _server else None
        return address[1] if address else None

    def _bridge_is_running(self) -> bool:
        return self._bridge_port() is not None

    def _on_agent_changed(self) -> None:
        """Show the selected agent's own path and arguments in the fields."""
        key = self._agent_combo.currentData()
        if key == CUSTOM_KEY:
            saved_path, saved_arguments = self._saved_agent()
            self._agent_path.setText(saved_path)
            self._agent_arguments.setText(saved_arguments)
            self._agent_arguments.setEnabled(True)
            self._refresh_agent_status()
            return
        self._agent_path.setText(
            self._agent_combo.currentData(Qt.ItemDataRole.UserRole + 1) or ""
        )
        agent = get_agent(key)
        self._agent_arguments.setText(" ".join(agent.arguments))
        self._refresh_agent_status()
        # The built-in argument templates are load-bearing — claude's
        # --allowedTools is what confines the agent to the MolCompose tools —
        # so they are shown rather than left a mystery, and not editable.
        # Editing them is what "Custom command" is for.
        self._agent_arguments.setEnabled(False)

    def _saved_agent(self) -> tuple[str, str]:
        """The custom executable and arguments remembered from last time."""
        settings = self._agent_settings()
        if settings is None:
            return getattr(self, "_custom_agent_memo", ("", ""))
        return settings.executable, settings.arguments

    def _remember_agent(self, executable: str, arguments: str) -> None:
        self._custom_agent_memo = (executable, arguments)
        settings = self._agent_settings()
        if settings is None:
            return
        settings.executable = executable
        settings.arguments = arguments
        settings.save()

    def _agent_settings(self):
        """ChimeraX's own settings store, or None where it is unavailable.

        A remembered path is a convenience, not a feature the panel depends
        on: if the settings API is missing or refuses to save, the field still
        works for this session and the chat box still runs.
        """
        if hasattr(self, "_agent_settings_cache"):
            return self._agent_settings_cache
        store = None
        try:
            from chimerax.core.settings import Settings

            class _AgentSettings(Settings):
                EXPLICIT_SAVE = {"executable": "", "arguments": ""}

            store = _AgentSettings(self.session, "molcompose_agent")
        except Exception:  # noqa: BLE001 - a settings store is optional here
            store = None
        self._agent_settings_cache = store
        return store

    def _on_browse_agent(self) -> None:
        start = self._agent_path.text() or str(Path.home())
        path, _filter = QFileDialog.getOpenFileName(
            None, "Choose an agent executable", start
        )
        if not path:
            return
        # Browsing to a binary means using it, so the selection follows the
        # path rather than leaving a built-in agent selected and its own
        # resolved executable about to overwrite what was just chosen.
        index = self._agent_combo.findData(CUSTOM_KEY)
        if index >= 0 and self._agent_combo.currentIndex() != index:
            arguments = self._agent_arguments.text()
            self._agent_combo.setCurrentIndex(index)
            self._agent_arguments.setText(arguments)
        self._agent_path.setText(path)
        self._remember_agent(path, self._agent_arguments.text())

    def _selected_agent(self):
        """The agent definition and executable the fields currently describe."""
        key = self._agent_combo.currentData()
        executable = self._agent_path.text().strip()
        if key == CUSTOM_KEY:
            if not executable:
                raise ValueError(
                    "choose the agent executable first — Browse…, or type its path"
                )
            self._remember_agent(executable, self._agent_arguments.text())
            return custom_agent(executable, self._agent_arguments.text()), executable
        agent = get_agent(key)
        return agent, (executable or agent.executable)

    def _bridge_url(self) -> str:
        """The address the bridge is actually answering on.

        Writing the default while ChimeraX listens elsewhere hands the agent an
        address with nothing behind it, and the failure surfaces as a tool call
        that times out rather than as a wrong port.
        """
        port = self._bridge_port()
        return f"http://127.0.0.1:{port}" if port else DEFAULT_CHIMERAX_URL

    def _agent_source(self, agent) -> str:
        """How this turn's commands will be attributed in the provenance record.

        The CLI, not the model: which model a CLI ran is inside that CLI, and
        the panel would be guessing. The panel does know which CLI it launched,
        which is the part that distinguishes two agents used in one session.
        """
        key = getattr(agent, "key", "")
        return f"agent:{key}" if key else "agent"

    def _write_agent_config(self, agent):
        """A temporary MCP config for this session, or None if unneeded."""
        if not agent.supports_mcp_config and not agent.interactive_arguments:
            return None
        if not self._server_executable:
            raise ValueError(
                "molcompose-mcp is not on PATH. Install it with "
                "pip install molcompose-mcp so the agent can reach ChimeraX."
            )
        import tempfile

        folder = Path(tempfile.mkdtemp(prefix="molcompose-agent-"))
        config_path = str(folder / "mcp.json")
        # The config names the port the bridge is actually on. Writing the
        # default while ChimeraX listens elsewhere hands the agent an address
        # with nothing behind it, and the failure surfaces as a tool call that
        # times out rather than as a wrong port.
        write_mcp_config(
            config_path, self._server_executable,
            self._bridge_url(), self._agent_source(agent),
        )
        return config_path

    def _on_copy_terminal_command(self) -> None:
        if not self._bridge_is_running():
            self._append_chat("[starting the agent bridge…]")
            self._run_quiet("remotecontrol rest start port 3000 json true")
        try:
            agent, executable = self._selected_agent()
            config_path = self._write_agent_config(agent)
        except ValueError as error:
            self._append_chat(f"[{error}]")
            return
        argv = interactive_command(agent, config_path, executable)
        if argv is None:
            self._append_chat(
                f"[MolCompose has no interactive form for {agent.label}. Start "
                "it however you normally do and point it at the MCP config "
                f"written to {config_path}.]"
                if config_path
                else f"[MolCompose has no interactive form for {agent.label}.]"
            )
            return
        command = " ".join(shlex.quote(part) for part in argv)
        QApplication.clipboard().setText(command)
        self._append_chat(
            "[copied — paste this in a terminal for an interactive session "
            f"against this ChimeraX window:]\n{command}"
        )

    def _on_chat_send(self) -> None:
        if self._agent_process is not None:
            self._append_chat("[an agent turn is already running]")
            return
        if not self._bridge_is_running():
            self._append_chat("[starting the agent bridge…]")
            self._run_quiet("remotecontrol rest start port 3000 json true")
        # A typed or browsed path counts as an agent found: the point of the
        # field is that auto-detection is not the only way to have one.
        chosen = self._agent_path.text().strip()
        problem = readiness(
            self._agents or ((None, chosen),) if chosen else self._agents,
            self._server_executable,
            self._bridge_is_running(),
        )
        if problem:
            self._append_chat(f"[{problem}]")
            return
        prompt = self._chat_input.toPlainText().strip()
        if not prompt:
            return

        try:
            agent, executable = self._selected_agent()
            config_path = (
                self._write_agent_config(agent) if agent.supports_mcp_config else None
            )
            self._agent_output_directory = None
            self._agent_answer_path = None
            if agent.final_message_arguments:
                self._agent_output_directory = tempfile.TemporaryDirectory(
                    prefix="molcompose-agent-answer-"
                )
                self._agent_answer_path = str(
                    Path(self._agent_output_directory.name) / "answer.md"
                )
            argv = build_command(
                agent,
                prompt,
                config_path,
                executable,
                self._agent_answer_path,
                server_executable=self._server_executable,
                chimerax_url=self._bridge_url(),
                source=self._agent_source(agent),
            )
        except ValueError as error:
            self._append_chat(f"[{error}]")
            return

        self._chat_log.setPlainText(f"❯ {prompt}\n")
        self._chat_details.clear()
        self._agent_verified.clear()
        self._agent_verified.setVisible(False)
        self._agent_unverified.clear()
        self._agent_unverified.setVisible(False)
        self._set_chat_details_visible(False)
        self._chat_run_status.setText(f"{agent.label} is analysing…")
        self._append_chat_detail(f"[running: {_readable_argv(argv)}]")
        # The full argv, with both absolute paths, goes to the Log — where a
        # "which binary actually ran" question is answered — rather than into
        # a box people screenshot.
        self.session.logger.info(f"MolCompose agent turn: {' '.join(argv)}")
        # Where the recipe stood before the turn, so the end of it can report
        # what this turn added. See `_report_agent_commands`.
        self._recipe_before_turn = len(self._recipe_log())
        self._chat_input.clear()
        self._chat_send.setEnabled(False)
        self._chat_stop.setEnabled(True)
        self._active_agent = agent
        self._agent_raw_output = ""

        process = QProcess()
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._on_chat_output)
        process.finished.connect(self._on_chat_finished)
        self._agent_process = process
        # Locked while a turn runs. The dropdown was live throughout, so the
        # panel could be showing one agent's name while another one was still
        # executing — and the status line, the setup fields and the config
        # written for the next turn would all describe the wrong one. Send was
        # already refused; the display was not.
        self._set_agent_choice_enabled(False)
        process.start(argv[0], argv[1:])
        finish_process_input(process, agent, prompt)

    def _on_chat_output(self) -> None:
        if self._agent_process is None:
            return
        chunk = bytes(self._agent_process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        if chunk.strip():
            self._agent_raw_output += chunk
            self._append_chat_detail(chunk)
            if not getattr(self._active_agent, "final_message_arguments", ()):
                self._append_chat(chunk)

    def _recipe_log(self) -> tuple:
        from ..commands import recipe_log

        try:
            return recipe_log(self.session)
        except Exception:  # noqa: BLE001 - the chat must not fail on its footer
            return ()

    def _report_agent_commands(self) -> tuple[str, ...]:
        """What the turn actually did, read from MolCompose rather than from it.

        The log box promised "the commands it ran" and showed only prose. The
        agent's own account of its tool calls is not evidence — it is more text
        from the same source as the answer. These lines come from the recipe:
        the commands that reached this session, tagged `agent` because the
        bridge declared itself before each one, in the order they arrived. An
        agent that claims a measurement it never took has nothing here.

        Reading MolCompose's record rather than the CLI's output also keeps
        this working for every agent the panel can launch. Parsing tool calls
        out of the stream would mean one parser per CLI, and would report what
        was asked for rather than what ran.
        """
        entries = self._recipe_log()[getattr(self, "_recipe_before_turn", 0):]
        commands = [e["command"] for e in entries if is_agent(e.get("source", ""))]
        if not commands:
            warning = (
                "⚠ No live MolCompose analysis was recorded for this turn. "
                "Do not treat the answer as verified against the open ChimeraX window."
            )
            unverified = getattr(self, "_agent_unverified", None)
            if unverified is not None:
                unverified.setText(warning)
                unverified.setVisible(True)
            else:
                self._append_chat(f"\n[{warning}]")
            return ()
        heading = f"✓ {len(commands)} MolCompose operation(s) verified"
        body = "\n".join(f"  {command}" for command in commands)
        verified = getattr(self, "_agent_verified", None)
        if verified is not None:
            verified.setText(f"{heading}\n{body}")
            verified.setVisible(True)
        else:
            self._append_chat(f"\n[{heading}]")
            for command in commands:
                self._append_chat(f"    {command}")
        return tuple(commands)

    def _on_chat_finished(self, exit_code=0, _status=None) -> None:
        if self._agent_answer_path:
            answer_path = Path(self._agent_answer_path)
            if answer_path.is_file():
                answer = answer_path.read_text(encoding="utf-8").strip()
                if answer:
                    self._append_chat(answer)
            elif exit_code == 0 and self._agent_raw_output.strip():
                self._append_chat(self._agent_raw_output)
        commands = self._report_agent_commands()
        self._chat_run_status.setText(_agent_run_status(exit_code, len(commands)))
        if exit_code != 0:
            self._set_chat_details_visible(True)
        if self._agent_output_directory is not None:
            self._agent_output_directory.cleanup()
        self._agent_output_directory = None
        self._agent_answer_path = None
        self._active_agent = None
        self._agent_process = None
        self._set_agent_choice_enabled(True)
        self._chat_send.setEnabled(True)
        self._chat_stop.setEnabled(False)

    def _on_chat_stop(self) -> None:
        if self._agent_process is not None:
            self._agent_process.kill()
            self._chat_run_status.setText("Stopping…")
            self._append_chat_detail("[stopped]")

    # -- callbacks ---------------------------------------------------------

    def _refresh_chains(self, *_args) -> None:
        model = self._current_model()
        self._group_a.clear()
        self._group_b.clear()
        self._chain_color_combo.clear()
        self._results_table.setRowCount(0)
        self._table_mode = "none"
        self._last_result = None
        self._clear_metrics()
        self._ddg_loaded = False
        if model is None:
            self._model_summary.setText("No protein model open")
            self._interface_structure.setText("No structure selected")
            self._refresh_structure_kind(None)
            return
        ref = model_ref(model)
        summary = f"{ref.name} ({ref.model_id}) · {len(ref.chains)} protein chains"
        short = (
            f"{_short_name(ref.name)} ({ref.model_id}) · "
            f"{len(ref.chains)} protein chains"
        )
        self._model_summary.setText(short)
        self._model_summary.setToolTip(summary)
        self._interface_structure.setText(f"Acting on {short}")
        self._interface_structure.setToolTip(summary)
        for chain in ref.chains:
            for widget in (self._group_a, self._group_b):
                item = QListWidgetItem(f"{chain.chain_id}   ·   {chain.residue_count} aa")
                item.setData(Qt.ItemDataRole.UserRole, chain.chain_id)
                widget.addItem(item)
            self._chain_color_combo.addItem(f"Chain {chain.chain_id}", chain.atomspec)
        self._pae_path = ""
        self._summary_path = ""
        self._pae_label.setText("PAE matrix: found automatically next to the model")
        self._capability_label.setText("Provenance not checked yet")
        self._refresh_structure_kind(model)

    def _refresh_structure_kind(self, model) -> None:
        """Say what kind of structure this is, then offer only what fits it.

        Experimental and predicted structures support disjoint halves of the
        toolkit, and which one you have is knowable from the file. Offering
        both regardless put a pLDDT button on crystal structures whose only
        possible outcome was a refusal, and listed a pLDDT preset that could
        not be applied.
        """
        if model is None:
            self._structure_kind.setText("Open a structure")
            self._metric_hint.setText("")
            self._fill_presets(predicted=False, has_interface=False)
            for button in self._metric_buttons.values():
                button.setEnabled(False)
                button.setToolTip("Open a structure first")
            self._refresh_metric_buttons(predicted=False, method="")
            return

        method = experimental_method(model)
        kind, detail = _classify_structure(method, plddt_values(model))
        predicted = kind == "predicted"
        confidence_issue = detail if kind == "unknown" else ""
        self._fill_presets(predicted, self._live_interface() is not None)
        self._structure_kind.setText(detail)
        self._refresh_metric_buttons(predicted, method or "", confidence_issue)
        self._apply_structure_kind_to_metrics(
            predicted, method or "", confidence_issue
        )
        self._refresh_block_rows()

    def _fill_presets(self, predicted: bool, has_interface: bool) -> None:
        """Rebuild the preset list with only what applies right now.

        Author's decision, 2026-08-16, replacing a version that listed every
        preset with the inapplicable ones greyed under headings. That kept the
        list stable but front-loaded it with things you cannot do: a fresh
        crystal structure showed one usable entry below a heading and a tail
        of disabled ones, and the whole thing read as broken rather than as
        gated. Now an entry appears when it can actually be applied — the
        pLDDT preset once the model is predicted, the interface presets once
        an interface exists — and a heading appears only when something is
        under it.

        The selection survives the rebuild when its preset is still listed,
        so detecting an interface does not silently move the combo off what
        the user had chosen. Otherwise it lands on the first entry, which by
        declaration order is Cartoon: the default the author confirmed.
        """
        combo = self._preset_combo
        keep = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        model = combo.model()
        for heading, presets in grouped_presets().items():
            usable = [
                preset for preset in presets
                if not (preset.confidence_coloring and not predicted)
                and not (preset.requires_interface and not has_interface)
            ]
            if not usable:
                continue
            combo.addItem(f"— {heading.lower()} —")
            model.item(combo.count() - 1).setEnabled(False)
            for preset in usable:
                combo.addItem(preset.display_name, preset.slug)
        restored = combo.findData(keep) if keep else -1
        if restored >= 0:
            combo.setCurrentIndex(restored)
        else:
            for index in range(combo.count()):
                if model.item(index).isEnabled():
                    combo.setCurrentIndex(index)
                    break
        combo.blockSignals(False)

    def _refresh_metric_buttons(
        self, predicted: bool, method: str, confidence_issue: str = ""
    ) -> None:
        """The two whole-model metrics; ΔΔG and ΔSASA are Interface-tab work.

        pLDDT and B-factor are mutually exclusive by construction. Both read
        the B-factor column, and which one it holds depends on where the file
        came from — so exactly one is live for any given structure, and the
        disabled one says which kind it wants.
        """
        for metric, button in self._metric_buttons.items():
            if metric == "plddt":
                enabled = predicted
                why = confidence_issue or (
                    f"Predicted models only: this structure's B-factors are "
                    f"temperature factors ({method})."
                    if method else "Open a predicted structure first"
                )
            elif metric == "bfactor":
                enabled = bool(method)
                why = confidence_issue or (
                    "Experimental structures only: this model's B-factor "
                    "column holds pLDDT, not temperature factors."
                    if not method else ""
                )
            else:
                enabled, why = False, ""
            button.setEnabled(enabled)
            button.setToolTip("" if enabled else why)
        self._metric_hint.setText(
            "Paints residues by a per-residue value instead of by chain. "
            "ΔΔG and ΔSASA colouring are in the Interface tab, where the data "
            "they need is loaded."
            if self._metric_buttons else ""
        )

    # -- blocks ------------------------------------------------------------

    def _show_interface_scores(self, scores: list) -> None:
        """Fill the three confidence tiles from whichever pairs were scored.

        ipTM is deliberately two fields upstream: a per-chain-pair value, and
        a whole-complex value that is all some engines report. The tile shows
        the pair's when there is one and marks the other with a tilde, because
        a global figure averaged over every chain pair is not a claim about
        this interface.
        """
        if not scores:
            return
        best = max(scores, key=lambda row: row.get("ipsae") or 0.0)
        for key, field in (("ipsae", "ipsae"), ("pdockq2", "pdockq2")):
            value = best.get(field)
            if value is not None:
                self._set_tile_value(key, value)
        if best.get("iptm") is not None:
            self._set_tile_value("iptm", best["iptm"])
        elif best.get("iptm_global") is not None:
            self._set_tile_value("iptm", best["iptm_global"], prefix="~")
            self._tiles["iptm"].setToolTip(
                "Whole complex — this engine reports no per-chain-pair ipTM, "
                "so this averages over every chain pair in the model."
            )
        self._tiles["ipsae"].setToolTip(
            " · ".join(
                f"{row['chains']}: ipSAE {row['ipsae']:.3f}, "
                f"pDockQ2 {row['pdockq2']:.3f}, LIS {row['lis']:.3f}"
                for row in scores
            )
        )

    def _on_focus(self, target: str) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        self._run_command(focus_command(spec, target))

    def _on_show_sequence(self) -> None:
        """Every chain's sequence, in ChimeraX's own viewer.

        `sequence chain` takes one spec, and it opened only the first chain
        here — useless on a complex, which is the only thing this panel is
        for. One call per chain, because the concatenated form ChimeraX also
        accepts builds an *alignment* and refuses chains whose sequences
        differ: `sequence chain #1/A#1/D` on barnase-barstar raises "Chains
        must have same sequence". A comma-separated list is rejected outright.

        Not a MolCompose command: it opens a native tool, so it is run quietly
        and stays out of the recipe. Nothing about the analysis changes.
        """
        model = self._current_model()
        if model is None:
            self._set_status("Open a structure first")
            return
        ref = model_ref(model)
        if not ref.chains:
            self._set_status("This structure has no protein chains")
            return
        # The interface partners first when there is an interface, because on
        # a six-chain crystal form the other four are not what you opened this
        # to read.
        wanted = self._interface_chain_ids() or [c.chain_id for c in ref.chains]
        opened = 0
        for chain in ref.chains:
            if chain.chain_id in wanted:
                self._run_quiet(f"sequence chain {chain.atomspec}")
                opened += 1
        self._set_status(f"Opened {opened} sequence viewer(s)")

    def _update_key_font_hint(self) -> None:
        """What this font will be at the print size the panel is set to.

        The number in the box is pixels of the image; what a reader cares
        about is points on the page, and the two are only related through the
        dpi and width already chosen here.
        """
        # Off when the scene has no key. Most presets draw none — the
        # interface styles colour by chain, not by a scale — and a live
        # spin box beside a figure with nothing to size implied that the
        # setting had an effect it could not have. `export` refuses the
        # keyword in that case, which was the only way to find out.
        from ..adapters.exporter import color_key

        has_key = color_key(self.session) is not None
        self._key_font_spin.setEnabled(has_key)
        if not has_key:
            self._key_font_hint.setText(
                "No colour key in this figure — only the metric colourings "
                "draw one."
            )
            return
        dpi = self._dpi_combo.currentData() or 300
        points = self._key_font_spin.value() / dpi * 72
        self._key_font_hint.setText(
            f"≈ {points:.1f} pt at {dpi} dpi"
            + ("  ·  journals ask for 7 pt" if points < 7 else "")
        )

    def _on_show_help(self) -> None:
        """Open the tool help, the copy that shipped with this install.

        `help:` is ChimeraX's own scheme for bundle documentation, so this
        finds the page next to the running code rather than a URL that can go
        stale or need a network.
        """
        self._run_quiet(f"help {HELP_PAGE}")

    def _on_show_tool(self, name: str) -> None:
        """Open one of ChimeraX's own tools.

        Quiet and unrecorded: opening a window changes nothing about the
        analysis, so it has no place in a recipe that claims to reproduce it.
        """
        self._run_quiet(f'ui tool show "{name}"')

    def _interface_chain_ids(self) -> list[str]:
        from ..commands import model_ref as _ref
        from ..commands import resolve_model, state_for

        model = self._current_model()
        if model is None:
            return []
        try:
            resolved = resolve_model(self.session, model)
        except Exception:  # noqa: BLE001
            return []
        params = state_for(self.session).interface_params.get(_ref(resolved).model_id)
        if not params:
            return []
        chains_a, chains_b, _criterion, _cutoff = params
        return list(chains_a) + list(chains_b)

    def _on_select_interaction(self, kind: str) -> None:
        """Select the residues taking part in one type of typed interaction.

        The chips read as a legend, and a legend that highlights what it names
        is worth more than one that only counts. They were plain labels, so
        clicking a chip did nothing at all.
        """
        from ..adapters.renderer import compact_residue_spec
        from ..commands import model_ref as _ref
        from ..commands import resolve_model, state_for

        model = self._current_model()
        if model is None:
            self._set_status("Open a structure first")
            return
        try:
            resolved = resolve_model(self.session, model)
        except Exception:  # noqa: BLE001
            return
        found = state_for(self.session).interactions.get(_ref(resolved).model_id, ())
        keys = []
        for interaction in found:
            if interaction.kind != kind:
                continue
            keys.extend((interaction.a, interaction.b))
        if not keys:
            self._set_status(f"No {kind.replace('-', ' ')} interactions to select")
            return
        self._run_quiet(f"select {compact_residue_spec(keys)}")
        self._set_status(
            f"Selected {len(set(keys))} residues in "
            f"{kind.replace('-', ' ')} interactions"
        )

    def _enable_interface_views(self) -> None:
        for button in (self._faceon_button, self._openbook_button):
            button.setEnabled(True)

    def _refresh_block_rows(self) -> None:
        """Show what detection produced, or reset the rows when it has not run."""
        blocks = self._live_blocks()
        found = {block.kind: block for block in blocks}
        preset = PRESETS["interface-focus"]
        defaults = {
            "groupA": BODY_GREY, "groupB": BODY_GREY,
            "ifaceA": preset.interface_colors()[0],
            "ifaceB": preset.interface_colors()[1],
        }
        for kind, widgets in self._block_rows.items():
            block = found.get(kind)
            colour = self._block_colors.get(kind) or defaults[kind]
            widgets["swatch"].setStyleSheet(
                f"QPushButton#swatch {{ background: {colour}; "
                f"border: 1px solid #C7CAD4; border-radius: 4px; }}"
            )
            widgets["spec"].setText(block.name if block else "—")
            widgets["count"].setText(
                f"{block.residue_count} "
                + ("chains" if kind.startswith("group") else "residues")
                if block else "—"
            )
            for key in ("swatch", "select"):
                widgets[key].setEnabled(block is not None)
            widgets["select"].setToolTip(
                "" if block else "Detect an interface first"
            )

    def _block_spec(self, kind: str) -> str | None:
        model = self._current_model()
        if model is None:
            self._set_status("Open a structure first")
            return None
        if not self._live_blocks():
            self._set_status("Detect an interface first")
            return None
        return block_name(model_ref(model).model_id, kind)


    def _live_blocks(self) -> tuple:
        """This model's blocks, via the funnel that invalidates stale ones.

        Reading `state.blocks` directly by model id skips
        `resolve_model`, which is where a cache belonging to a closed
        structure is dropped. ChimeraX reuses model ids, so the first
        version of this method showed the previous structure's block
        counts after `close all` and a fresh open — the same staleness
        this codebase has now been bitten by three times, in the recipe,
        in the cached analyses, and here.
        """
        from ..commands import model_ref as _ref
        from ..commands import resolve_model, state_for

        model = self._current_model()
        if model is None:
            return ()
        try:
            resolved = resolve_model(self.session, model)
        except Exception:  # noqa: BLE001 - no model is not an error here
            return ()
        return state_for(self.session).blocks.get(_ref(resolved).model_id, ())

    def _live_interface(self):
        """Whether this model has a detected interface, asked of the session.

        Not `self._last_result`, which is a copy this panel keeps and which
        only its own detect button ever fills in. Gating on that meant an
        interface detected from the command line or by the agent left every
        Interface preset in the Style list disabled — the panel had no idea it
        existed — and `_refresh_chains` cleared the copy whenever the model
        combo was rebuilt, so even the panel's own detection stopped counting
        as soon as anything touched that list.

        Through `resolve_model` for the reason `_live_blocks` documents:
        ChimeraX reuses model ids, and that is where a cache belonging to a
        closed structure gets dropped.
        """
        from ..commands import model_ref as _ref
        from ..commands import resolve_model, state_for

        model = self._current_model()
        if model is None:
            return None
        try:
            resolved = resolve_model(self.session, model)
        except Exception:  # noqa: BLE001 - no model is not an error here
            return None
        return state_for(self.session).interfaces.get(_ref(resolved).model_id)

    def _on_select_block(self, kind: str) -> None:
        name = self._block_spec(kind)
        if name is None:
            return
        self._run_quiet(f"select {name}")
        self._set_status(f"Selected {BLOCK_LABELS[kind]}")

    def _on_pick_block_color(self, kind: str) -> None:
        name = self._block_spec(kind)
        if name is None:
            return
        colour = QColorDialog.getColor()
        if not colour.isValid():
            return
        value = colour.name()
        self._block_colors[kind] = value
        # Cartoon and atoms both: an interface block is drawn as sticks over a
        # cartoon, and recolouring only one leaves the part two-toned.
        self._run_command(f"color {name} {value} target ac")
        self._refresh_block_rows()

    # -- prediction files ---------------------------------------------------

    @staticmethod
    def _missing_status(metrics: str, wanted) -> str:
        """"X unavailable" plus the filename that would have provided it."""
        if not wanted:
            return f"{metrics} unavailable"
        return f"{metrics} unavailable — looked for {wanted[0]}"

    def _on_resolve_prediction_files(self) -> None:
        """Show which files a method resolves to, before anything reads them.

        The engines index their samples differently and two of the naming
        conventions differ by a single character, so the failure this guards
        against is not an error message — it is a plausible number computed
        from a different sample's file.
        """
        model = self._current_model()
        if model is None:
            self._set_status("Open a structure first")
            return
        from ..adapters.model_context import structure_path
        from ..core.prediction import (
            expected_names,
            find_pae_file,
            find_summary_file,
        )
        from ..core.summary import parse as parse_summary

        predictor = self._predictor_combo.currentData()
        path = structure_path(model)
        rows = []
        # A file chosen by hand outranks the search, and the table says which
        # of the two it is looking at. Re-running the search used to silently
        # replace a chosen file with whatever discovery produced, so the panel
        # could show one file while the analysis read another.
        chosen_pae = getattr(self, "_pae_path", "")
        chosen_summary = getattr(self, "_summary_path", "")
        pae = chosen_pae or find_pae_file(path, predictor)
        rows.append(("PAE", Path(pae).name if pae else "not found",
                     ("chosen by hand" if chosen_pae else "matrix") if pae else
                     self._missing_status("ipSAE, pDockQ2 and LIS",
                                          expected_names(path, predictor, "pae"))))
        found = chosen_summary or find_summary_file(path, predictor)
        if found:
            try:
                report = parse_summary(found, Path(found).stem)
                status = (
                    f"{report.engine}, per chain pair" if report.has_pairwise
                    else f"{report.engine}, whole complex only"
                )
                if chosen_summary:
                    status = f"chosen by hand — {status}"
            except ValueError as error:
                status = str(error)[:60]
            rows.append(("Summary", Path(found).name, status))
        else:
            # Naming the file it wanted. "not found" on its own reads as a
            # wrong setting, and the usual cause is that the file was never
            # copied out of the prediction's output folder — AlphaFold 3 splits
            # its numbers in two and it is the summary that carries ipTM and
            # pTM, so a folder holding only <name>_confidences.json has the PAE
            # and can never have either.
            rows.append(("Summary", "not found",
                         self._missing_status(
                             "ipTM and pTM",
                             expected_names(path, predictor, "summary"))))

        self._file_table.setRowCount(len(rows))
        for index, (kind, name, status) in enumerate(rows):
            self._file_table.setItem(index, 0, QTableWidgetItem(f"{kind}  {name}"))
            self._file_table.setItem(index, 1, QTableWidgetItem(status))
        self._file_table.resizeColumnsToContents()
        self._pae_label.setText(
            f"Resolved against {Path(path).name} using "
            f"{self._predictor_combo.currentText().lower()}."
            if path else "This structure has no file on disk to look beside."
        )

    def _selected_chains(self, widget) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole) for item in widget.selectedItems()]

    def _on_criterion_changed(self, *_args) -> None:
        """The cutoff box means a distance for two criteria and an overlap for one.

        Under `vdw` the number is how far the two van der Waals spheres must
        come to overlapping — normally negative, so the range and the suffix
        both have to change with it, or the box would refuse the only values
        that make sense.
        """
        criterion = self._criterion_combo.currentData()
        if criterion == "vdw":
            self._distance.setRange(-2.0, 2.0)
            # Just the unit. " Å overlap" made a spin box look like a text
            # field; what the number means belongs in the label above it.
            self._distance.setSuffix(" Å")
            self._distance.setSingleStep(0.1)
            self._distance.setToolTip(
                "Contact when the two atoms' van der Waals spheres come within "
                "this of overlapping. Negative allows a gap; ChimeraX's own "
                "default is −0.4."
            )
        else:
            self._distance.setRange(2.0, 10.0)
            self._distance.setSuffix(" Å")
            self._distance.setSingleStep(0.5)
            self._distance.setToolTip("Centre-to-centre distance between atoms")
        self._cutoff_label.setText(
            "CRITERION · VDW OVERLAP" if criterion == "vdw" else "CRITERION · CUTOFF"
        )
        self._distance.setValue(_CRITERION_DEFAULT_CUTOFF.get(criterion, 4.5))

    def _clear_selection_preview(self) -> None:
        self._run_quiet("select clear")

    def _sync_group_exclusivity(self) -> None:
        """A chain on one side of the interface cannot also be on the other."""
        for source, other in ((self._group_a, self._group_b), (self._group_b, self._group_a)):
            taken = {item.data(Qt.ItemDataRole.UserRole) for item in source.selectedItems()}
            for row in range(other.count()):
                item = other.item(row)
                chain_id = item.data(Qt.ItemDataRole.UserRole)
                blocked = chain_id in taken
                flags = item.flags()
                if blocked:
                    item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
                    item.setSelected(False)
                else:
                    item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)

    def _on_chain_selection_preview(self) -> None:
        self._sync_group_exclusivity()
        model = self._current_model()
        if model is None:
            return
        ref = model_ref(model)
        chain_specs = {chain.chain_id: chain.atomspec for chain in ref.chains}
        chosen = {
            chain_id
            for widget in (self._group_a, self._group_b)
            for chain_id in self._selected_chains(widget)
            if chain_id in chain_specs
        }
        if chosen:
            spec = "|".join(chain_specs[chain_id] for chain_id in sorted(chosen))
            self._run_quiet(f"select {spec}")
        else:
            self._run_quiet("select clear")

    def _on_choose_pae(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            None, "Select the prediction's PAE matrix", "",
            "PAE matrices (*.json *.npz *.pkl *.pickle);;All files (*)",
        )
        if not path:
            return
        self._pae_path = path
        from pathlib import Path as _Path

        self._pae_label.setText(f"PAE: {_Path(path).name}")
        self._on_check_capabilities()

    def _on_choose_summary(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            None, "Select the prediction's ipTM/pTM summary", "",
            "Confidence summaries (*.json *.npz *.pkl *.pickle);;All files (*)",
        )
        if not path:
            return
        self._summary_path = path
        from pathlib import Path as _Path

        self._pae_label.setText(f"Summary: {_Path(path).name}")
        self._on_resolve_prediction_files()

    def _on_check_capabilities(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        command = f"molcompose capabilities model {spec}"
        predictor = self._predictor_combo.currentData()
        if predictor and predictor != "generic":
            command += f" predictor {predictor}"
        if self._pae_path:
            command += f" paeFile {quote_path(self._pae_path)}"
        if getattr(self, "_summary_path", ""):
            command += f" summaryFile {quote_path(self._summary_path)}"
        caps = self._run_command(command)
        if caps is None:
            return
        try:
            if caps.pae_file and not self._pae_path:
                from pathlib import Path as _Path

                self._pae_label.setText(f"PAE found: {_Path(caps.pae_file).name}")
            confidence = [
                metric
                for metric in caps.available
                if metric in ("pLDDT", "ipLDDT", "pDockQ", "ipSAE", "pDockQ2", "LIS")
            ]
            summary = f"{caps.kind.title()}"
            if caps.detail:
                summary += f" — {caps.detail}"
            summary += (
                f"\nConfidence metrics available: {', '.join(confidence)}"
                if confidence
                else "\nNo confidence metrics apply to this structure."
            )
            missing = [
                metric for metric in ("ipSAE", "pDockQ2", "LIS") if metric in caps.unavailable
            ]
            if missing and caps.is_predicted:
                summary += f"\n{', '.join(missing)} need a PAE matrix — choose one above."
            self._capability_label.setText(summary)
        except AttributeError:
            self._capability_label.setText("See the ChimeraX Log for the assessment")

    def _on_pick_chain_color(self) -> None:
        atomspec = self._chain_color_combo.currentData()
        if not atomspec:
            self._set_status("Open a protein structure first")
            return
        color = QColorDialog.getColor()
        if color is None or not color.isValid():
            return
        self._run_command(f"color {atomspec} {color.name().upper()} target c")
        # Painting a chain by hand overrides whatever scale was on it, so the
        # colour key has to go with it. This path does not run a preset, and
        # so does not pass through `reset_commands` where the key is otherwise
        # cleared: picking a chain colour after the pLDDT preset used to leave
        # the confidence scale standing beside a figure that no longer had any
        # confidence colouring in it.
        self._run_command("key delete")

    def _on_pick_group_color(self, side: str) -> None:
        color = QColorDialog.getColor()
        if color is None or not color.isValid():
            return
        hex_color = color.name().upper()
        button = self._color_a_button if side == "a" else self._color_b_button
        button.setStyleSheet(f"background: {hex_color}; color: white;")
        if side == "a":
            self._group_a_color = hex_color
        else:
            self._group_b_color = hex_color

    # -- results table -----------------------------------------------------

    def _set_table_columns(self, headers) -> None:
        self._results_table.setColumnCount(len(headers))
        self._results_table.setHorizontalHeaderLabels(list(headers))
        self._results_table.resizeColumnsToContents()
        self._results_table.horizontalHeader().setStretchLastSection(True)

    def _populate_interaction_table(self, interactions) -> None:
        self._set_table_columns(["Type", "Residues", "Distance"])
        self._results_table.setRowCount(len(interactions))
        for row, item in enumerate(interactions):
            kind_item = QTableWidgetItem(item.kind)
            kind_item.setData(
                Qt.ItemDataRole.UserRole, f"{item.a.atomspec}|{item.b.atomspec}"
            )
            self._results_table.setItem(row, 0, kind_item)
            self._results_table.setItem(
                row, 1,
                QTableWidgetItem(
                    f"{item.a.name}{item.a.chain_id}:{item.a.number} – "
                    f"{item.b.name}{item.b.chain_id}:{item.b.number}"
                ),
            )
            self._results_table.setItem(row, 2, QTableWidgetItem(f"{item.distance:.2f} Å"))
        self._table_mode = "interactions"

    def _populate_residue_table(self, result) -> None:
        rows = [("A", key) for key in result.group_a] + [("B", key) for key in result.group_b]
        self._set_table_columns(["Interface residue", "Side"])
        self._results_table.setRowCount(len(rows))
        for row, (side, key) in enumerate(rows):
            residue_item = QTableWidgetItem(f"{key.name} {key.chain_id}:{key.number}")
            residue_item.setData(Qt.ItemDataRole.UserRole, key.atomspec)
            self._results_table.setItem(row, 0, residue_item)
            self._results_table.setItem(row, 1, QTableWidgetItem(side))
        self._table_mode = "residues"

    def _populate_pairs_table(self, records) -> None:
        self._set_table_columns(["Chain pair", "Contacts"])
        self._results_table.setRowCount(len(records))
        for row, (chain_a, chain_b, result) in enumerate(records):
            pair_item = QTableWidgetItem(f"{chain_a} – {chain_b}")
            pair_item.setData(Qt.ItemDataRole.UserRole, (chain_a, chain_b))
            self._results_table.setItem(row, 0, pair_item)
            self._results_table.setItem(row, 1, QTableWidgetItem(str(len(result.contacts))))
        self._table_mode = "pairs"

    def _on_table_activated(self, row, _column) -> None:
        item = self._results_table.item(row, 0)
        if item is None:
            return
        if self._table_mode == "pairs":
            spec = self._current_model_spec()
            if spec is None:
                return
            chain_a, chain_b = item.data(Qt.ItemDataRole.UserRole)
            self._detect(spec, [chain_a], [chain_b])
            self._on_show_interface()
        elif self._table_mode in ("residues", "interactions"):
            atomspec = item.data(Qt.ItemDataRole.UserRole)
            self._run_quiet(f"select {atomspec}")
            self._run_quiet(f"view {atomspec}")

    def _on_copy_results(self) -> None:
        lines = []
        for row in range(self._results_table.rowCount()):
            cells = []
            for column in range(self._results_table.columnCount()):
                item = self._results_table.item(row, column)
                cells.append(item.text() if item is not None else "")
            lines.append("\t".join(cells))
        if lines:
            QApplication.clipboard().setText("\n".join(lines))
            self._set_status(f"Copied {len(lines)} rows to the clipboard")

    # -- actions -----------------------------------------------------------

    def _show_result_counts(self, result) -> None:
        try:
            self._interface_result.setText(
                f"Group A: {len(result.group_a)} residues · "
                f"Group B: {len(result.group_b)} residues · "
                f"{len(result.contacts)} contact pairs"
            )
            self._populate_residue_table(result)
            self._last_result = result
            # ΔSASA colouring becomes possible the moment an interface exists.
            self._color_dsasa_button.setEnabled(True)
            self._color_dsasa_button.setToolTip(
                "Colour interface residues by how much surface each buries"
            )
            self._enable_interface_views()
            self._refresh_structure_kind(self._current_model())
            self._set_metric("contacts", str(len(result.contacts)))
            self._set_metric(
                "residues", f"{len(result.group_a)}+{len(result.group_b)}"
            )
        except (AttributeError, TypeError):
            self._interface_result.setText("See the ChimeraX Log for interface counts")

    def _on_apply_style(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        self._run_command(style_command(spec, self._preset_combo.currentData()))

    def _detect(self, spec, group_a, group_b) -> None:
        try:
            command = interface_command(
                spec, group_a, group_b, self._distance.value(),
                self._criterion_combo.currentData(),
            )
        except ValueError as error:
            self._set_status(str(error))
            return
        result = self._run_command(command)
        self._clear_selection_preview()
        if result is None:
            return
        self._show_result_counts(result)
        if self._auto_analyse.isChecked():
            self._run_standard_analyses(spec)

    def _run_standard_analyses(self, spec: str) -> None:
        """Everything computable without further input, in one pass."""
        area = self._run_command(f"molcompose buriedarea model {spec}")
        if isinstance(area, (int, float)):
            self._set_tile_value("bsa", area)
        affinity = self._run_command(affinity_command(spec))
        if affinity is not None:
            try:
                self._set_tile_value("dg", affinity.delta_g)
                self._set_tile_value("kd", affinity.kd)
            except AttributeError:
                pass
        found = self._run_command(interactions_command(spec))
        if found:
            counts: dict[str, int] = {}
            for item in found:
                counts[item.kind] = counts.get(item.kind, 0) + 1
            self._set_chips(counts)
            self._interactions_shown = True
            self._interactions_button.setText("Hide Typed Interactions")
        self._set_status("")

    def _on_detect_interface(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        group_a = self._selected_chains(self._group_a)
        group_b = self._selected_chains(self._group_b)
        if not group_a or not group_b:
            self._set_status("Select chains for both Group A and Group B")
            return
        self._detect(spec, group_a, group_b)

    def _on_characterise(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        group_a = self._selected_chains(self._group_a)
        group_b = self._selected_chains(self._group_b)
        if not group_a or not group_b:
            self._set_status("Select chains for both Group A and Group B")
            return
        try:
            # style false: the numbers, not the look. Characterise used to
            # restyle the scene as its last step, which threw away whatever
            # the user had already set up — style elsewhere, characterise
            # here, and the style was gone. The figure now comes only from
            # the Interface figure card below, where it is asked for.
            command = characterise_command(
                spec, group_a, group_b, self._distance.value(),
                self._criterion_combo.currentData(), style=False,
                pae_file=getattr(self, "_pae_path", ""),
                summary_file=getattr(self, "_summary_path", ""),
            )
        except ValueError as error:
            self._set_status(str(error))
            return
        summary = self._run_command(command)
        self._clear_selection_preview()
        if not isinstance(summary, dict):
            return
        interface = summary.get("interface", {})
        self._set_metric("contacts", str(interface.get("contact_pairs", "—")))
        self._set_metric(
            "residues",
            f"{interface.get('residues_a', 0)}+{interface.get('residues_b', 0)}",
        )
        if summary.get("buried_area") is not None:
            self._set_tile_value("bsa", summary["buried_area"])
        affinity = summary.get("affinity")
        if affinity:
            self._set_tile_value("dg", affinity["delta_g"])
            self._set_tile_value("kd", affinity["kd"])
        # The PAE-based scores are the ones that answer "should I believe this
        # interface". `characterise` ran no PAE step at all until 2026-08-15,
        # so the panel had nowhere to show them and the button that promised
        # everything delivered only the geometry.
        self._show_interface_scores(summary.get("interface_scores") or [])
        self._set_chips(summary.get("interactions") or {})
        # Detection defined the four blocks; the rows have to be told.
        self._refresh_block_rows()
        self._enable_interface_views()
        self._color_dsasa_button.setEnabled(True)
        self._color_dsasa_button.setToolTip(
            "Colour interface residues by how much surface each buries"
        )
        hotspots = summary.get("hotspots") or []
        if hotspots:
            self._populate_hotspot_table(hotspots)
        skipped = summary.get("skipped") or {}
        done = ", ".join(summary.get("steps", []))
        self._interface_result.setText(
            f"Characterised: {done}"
            + (f"  ·  skipped: {', '.join(skipped)}" if skipped else "")
        )
        self._interactions_shown = True
        self._interactions_button.setText("Hide Typed Interactions")

    def _on_all_chain_pairs(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        distance = self._distance.value()
        criterion = self._criterion_combo.currentData()
        command = f"molcompose interface all model {spec} distance {distance:g}"
        if criterion != "heavy":
            command += f" criterion {criterion}"
        records = self._run_command(command) or ()
        self._populate_pairs_table(records)
        if not records:
            self._interface_result.setText("No contacting chain pairs found")
        else:
            self._interface_result.setText(
                f"{len(records)} contacting chain pairs — double-click one for its figure"
            )

    def _group_specs_from_result(self):
        if self._last_result is None:
            return None, None
        a_spec = compact_residue_spec(self._last_result.group_a)
        b_spec = compact_residue_spec(self._last_result.group_b)
        return a_spec, b_spec

    def _on_label_override(self) -> None:
        on = self._label_override.isChecked()
        self._label_count.setEnabled(on)
        # The unit greys out with the number it belongs to, or "per side" reads
        # as a live statement about a control that is doing nothing.
        self._label_unit.setEnabled(on)

    def _on_show_interface(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        slug = self._figure_preset_combo.currentData() or "interface-focus"
        labels = (self._label_count.value()
                  if self._label_override.isChecked() else None)
        result = self._run_command(style_command(spec, slug, labels))
        self._clear_selection_preview()
        if result is None:
            return
        a_spec, b_spec = self._group_specs_from_result()
        if a_spec and self._group_a_color:
            self._run_command(f"color {a_spec} {self._group_a_color}")
        if b_spec and self._group_b_color:
            self._run_command(f"color {b_spec} {self._group_b_color}")
        # The optional halo. Display state only, like the H-bond and contact
        # overlays, so it stays out of the recipe.
        #
        # Unless the preset draws a surface itself. This branch was written
        # when none did — "the preset builds no surface" was literally true —
        # so its else clause hid every surface in the model to clear a halo
        # left by a previous click. Once four surface styles existed, choosing
        # one from this very card built its surface and then had it torn down
        # one command later: the reported symptom was that the surface styles
        # showed no surface at all. Neither branch may run for a preset whose
        # surface *is* the figure — the halo would paint over its epitope
        # patch, and hiding would erase it.
        if get_preset(slug).geometry.draws_surface:
            return
        if self._surface_check.isChecked():
            partners = "|".join(part for part in (a_spec, b_spec) if part)
            if partners:
                self._run_quiet(f"surface {partners}")
                self._run_quiet(f"color {partners} {SURFACE_COLOR} target s")
                self._run_quiet(
                    f"transparency {partners} {SURFACE_TRANSPARENCY} target s"
                )
        else:
            self._run_quiet(f"hide {spec} surfaces")

    def _on_hotspot_figure(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        # No per-chain colour override here: the whole point is one scale
        # across both partners, and re-tinting by chain would undo it.
        if self._run_command(style_command(spec, "hotspot-focus")) is None:
            return
        self._clear_selection_preview()
        self._interface_result.setText(
            "Interface graded by buried area — one scale across both partners "
            "(see the Log for the most buried residues)"
        )

    def _on_toggle_hbonds(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        if self._hbonds_shown:
            self._run_command(hbonds_command(spec, off=True))
            self._hbonds_shown = False
            self._hbonds_button.setText("H-bonds")
        else:
            result = self._run_command(hbonds_command(spec))
            if result is not None:
                self._hbonds_shown = True
                self._hbonds_button.setText("Hide H-bonds")

    def _on_toggle_contacts(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        if self._contacts_shown:
            self._run_command(contacts_command(spec, off=True))
            self._contacts_shown = False
            self._contacts_button.setText("Contacts")
        else:
            result = self._run_command(contacts_command(spec))
            if result is not None:
                self._contacts_shown = True
                self._contacts_button.setText("Hide Contacts")

    def _on_toggle_interactions(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        if self._interactions_shown:
            self._run_command(interactions_command(spec, off=True))
            self._interactions_shown = False
            self._interactions_button.setText("Show Typed Interactions")
            return
        found = self._run_command(interactions_command(spec))
        if found is None:
            return
        self._interactions_shown = True
        self._interactions_button.setText("Hide Typed Interactions")
        try:
            counts: dict[str, int] = {}
            for item in found:
                counts[item.kind] = counts.get(item.kind, 0) + 1
            self._set_chips(counts)
            self._interface_result.setText(
                " · ".join(f"{kind} {count}" for kind, count in sorted(counts.items()))
                or "No typed interactions found"
            )
            self._populate_interaction_table(found)
        except (AttributeError, TypeError):
            self._interface_result.setText("See the ChimeraX Log for interaction counts")

    def _populate_value_table(self, headers, rows) -> None:
        """rows: (label, atomspec-or-None, value_text)."""
        self._set_table_columns(headers)
        self._results_table.setRowCount(len(rows))
        for index, (label, atomspec, value) in enumerate(rows):
            item = QTableWidgetItem(label)
            if atomspec:
                item.setData(Qt.ItemDataRole.UserRole, atomspec)
            self._results_table.setItem(index, 0, item)
            self._results_table.setItem(index, 1, QTableWidgetItem(value))
        self._table_mode = "residues" if rows and rows[0][1] else "none"

    def _on_hotspots(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        rows = self._run_command(hotspots_command(spec))
        if not rows:
            return
        try:
            self._populate_value_table(
                ["Interface residue", "Buried area"],
                [
                    (
                        f"{name} {chain}:{number}{icode}".strip(),
                        f"/{chain}:{number}{icode}".strip(),
                        f"{delta:.1f} Å²",
                    )
                    for (chain, number, icode), name, _a, _c, delta in rows
                ],
            )
            self._interface_result.setText(
                f"{len(rows)} residues bury ≥ 10 Å² — most buried: "
                f"{rows[0][1]} {rows[0][0][0]}:{rows[0][0][1]} ({rows[0][4]:.0f} Å²)"
            )
        except (AttributeError, IndexError, TypeError):
            self._interface_result.setText("See the ChimeraX Log for hot spots")

    def _populate_hotspot_table(self, hotspots) -> None:
        """Hot spots with predicted ΔΔG beside buried area, when both are known.

        Side by side because the two disagree informatively. On barnase–barstar
        Arg87 buries 3.7 Å² — 36th of 48 — while ranking second by predicted
        ΔΔG, since a salt bridge contributes electrostatically without burying
        much surface. Read either column alone and that residue is missed.
        """
        ddg = getattr(self, "_ddg_by_residue", {}) or {}
        rows = []
        for row in hotspots:
            label = row["residue"]
            value = ddg.get(self._residue_key_from_label(label))
            rows.append(
                (
                    label,
                    None,
                    f"{row['buried_area']:.1f} Å²"
                    + (f"   ·   ΔΔG {value:+.2f}" if value is not None else ""),
                )
            )
        header = "Buried area" + ("   ·   ΔΔG max" if ddg else "")
        self._populate_value_table(["Hot-spot residue", header], rows)

    @staticmethod
    def _residue_key_from_label(label: str):
        """"ARG A:59" -> ("A", 59); None when the label is not in that form."""
        try:
            _name, location = label.split(" ")
            chain, number = location.split(":")
            return chain, int("".join(c for c in number if c.isdigit() or c == "-"))
        except (AttributeError, IndexError, ValueError):
            return None

    def _on_load_flexibility(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        path, _selected = QFileDialog.getOpenFileName(
            None, "Load RMS fluctuation", "",
            "GROMACS xvg (*.xvg);;All files (*)",
        )
        if not path:
            return
        model = self._current_model()
        available = ", ".join(
            sorted({chain.chain_id for chain in getattr(model, "chains", ())})
        )
        chains, accepted = QInputDialog.getText(
            None,
            "Which chains, in which order?",
            "`gmx rmsf -res` restarts its numbering at each chain, so name one\n"
            "chain per block of the file, in the order the selection was\n"
            f"written.\n\nThis structure has: {available or 'no protein chains'}",
            text=available.replace(" ", ""),
        )
        if not accepted or not chains.strip():
            return
        if self._run_command(flexibility_command(spec, path, chains.strip())) is None:
            # Same move as the decomposition loader: the structure asked about
            # is the wrong one, and the one the file fits may already be open.
            if not self._retarget_flexibility(path, chains.strip()):
                return
        self._color_rmsf_button.setEnabled(True)
        self._color_rmsf_button.setToolTip("Paint each residue by how much it moves")

    def _next_step_after_retarget(self, moved) -> str:
        """What the user has to do next, when there is something.

        A structure that has just been switched to has not been analysed:
        its interface residues are its own and nothing has computed them. The
        values load, and then "Colour by" refuses with a message about
        detecting an interface — which is correct and arrives at the wrong
        moment, since the panel has just moved the ground underneath.

        Not detected automatically. The button pressed was a load, and
        detection is an analysis with its own cutoff and criterion sitting on
        another tab; running it unasked would put a result on screen the user
        did not request and might not have configured.
        """
        from ..commands import state_for

        if state_for(self.session).interfaces.get(moved.model_id):
            return ""
        return " Characterise Interface on it to colour by these values."

    def _retarget_flexibility(self, path, chains: str) -> bool:
        """Switch to an open structure whose chains fit this RMSF file.

        Weaker evidence than the decomposition's, and deliberately so: the
        file carries no residue names, only counts, so this can only ask
        whether the blocks line up. It is enough for the case it is for — the
        repaired structure has residues the deposited one does not, so the
        counts differ — and it does not pretend to more.
        """
        from ..commands import matching_open_model_for_blocks

        current = self._current_model()
        if current is None:
            return False
        target = matching_open_model_for_blocks(
            self.session, path, chains, model_ref(current).model_id
        )
        if target is None:
            return False
        self._model_button.value = target
        moved = model_ref(target)
        if self._run_command(
            flexibility_command(moved.model_id, path, chains)
        ) is None:
            return False
        self._set_status(
            f"Loaded onto {moved.name} ({moved.model_id}), whose chains fit "
            "the file — Current Structure moved with it."
            + self._next_step_after_retarget(moved)
        )
        return True

    def _retarget_to_matching(self, path, mapping: str, solvation: str):
        """Switch to an open structure the file describes, and load onto it.

        Returns `(result, spec)` on success, or None when there is nothing to
        switch to — in which case the original error stands, which is the
        right outcome: no structure here matches, and the file has to come
        from somewhere else.
        """
        # Imported here rather than at module scope: `commands` imports this
        # module for the panel class, so a top-level import would close the
        # loop.
        from ..commands import matching_open_model
        from ..core.mmpbsa import load as load_energies
        from ..core.mmpbsa import parse_chain_map, remap

        current = self._current_model()
        if current is None:
            return None
        try:
            energies = remap(
                load_energies(path, solvation or None), parse_chain_map(mapping)
            )
        except Exception:  # the load already failed; do not fail differently
            return None
        target = matching_open_model(
            self.session, energies, model_ref(current).model_id
        )
        if target is None:
            return None
        self._model_button.value = target
        moved = model_ref(target)
        result = self._run_command(
            energy_command(moved.model_id, path, mapping, solvation)
        )
        if result is None:
            return None
        self._set_status(
            f"Loaded onto {moved.name} ({moved.model_id}), which the file "
            "describes — Current Structure moved with it."
            + self._next_step_after_retarget(moved)
        )
        return result, moved.model_id

    def _chosen_solvation(self, path) -> str | None:
        """"gb", "pb", "" if the file carries one model — None if cancelled.

        Asked only when there is a choice. A file with one model gets no
        dialog, which is most of them; a file with both gets one, because the
        two disagree by several kcal/mol and reading whichever came first
        would put an unlabelled choice in the figure.
        """
        from ..core.mmpbsa import solvation_models

        models = solvation_models(path)
        if len(models) < 2:
            return ""
        choice, accepted = QInputDialog.getItem(
            None,
            "Which solvation model?",
            "This run computed both. They are different numbers — the gap "
            "between them\nis the error bar on the solvation treatment alone "
            "— so the choice is\nyours to state rather than ours to make.\n",
            models,
            0,
            False,
        )
        if not accepted:
            return None
        return "gb" if choice.lower().startswith("g") else "pb"

    def _on_load_energy(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        path, _selected = QFileDialog.getOpenFileName(
            None, "Load a gmx_MMPBSA decomposition", "",
            "gmx_MMPBSA decomposition (*.dat *.csv);;All files (*)",
        )
        if not path:
            return
        # Asked before the chain map, because reading the file's chains means
        # reading a decomposition, and a file carrying both solvation models
        # holds two.
        solvation = self._chosen_solvation(path)
        if solvation is None:
            return
        # The chain map cannot be guessed: GROMACS relabels chains when a
        # system is built, so the file's letters are usually not the
        # structure's, and getting it wrong attaches one partner's energies to
        # the other without any error. Offering the structure's own chains in
        # the prompt is as far as help can go.
        model = self._current_model()
        structure_chains = sorted(
            {chain.chain_id for chain in getattr(model, "chains", ())}
        )
        chains = ", ".join(structure_chains)
        # Built from this structure, not from 1BRS. The box used to be
        # pre-filled with "A:A,B:D" whatever was open — right for barnase and
        # barstar, wrong for every structure whose second chain is not D. The
        # error that followed named a residue the map had invented ("D:23 is
        # not in the structure"), which reads as a problem with the data
        # rather than with the answer already in the box.
        from ..core.mmpbsa import file_chains

        theirs = file_chains(path, solvation or None)
        suggestion = ",".join(
            f"{a}:{b}" for a, b in zip(theirs, structure_chains, strict=False)
        )
        mapping, accepted = QInputDialog.getText(
            None,
            "Which chain is which?",
            "Map the file's chains onto this structure's, as FILE:MODEL pairs.\n"
            f"The file has: {', '.join(theirs) or 'unreadable'}\n"
            f"This structure has: {chains or 'no protein chains'}\n\n"
            "Paired in order below, which is a guess — GROMACS renames chains "
            "when a\nsystem is built, so check it against how the run was set "
            "up:",
            text=suggestion or "A:A,B:B",
        )
        if not accepted or not mapping.strip():
            return
        command = energy_command(spec, path, mapping.strip(), solvation)
        loaded = self._run_command(command)
        if loaded is None:
            # The structure it was asked about is the wrong one, and the right
            # one may already be open — someone told to load the repaired
            # structure does exactly that, and the selector keeps pointing at
            # what it pointed at before, because following the newest model
            # would send this panel chasing every DockQ reference that is
            # opened. So the switch happens here, on this failure only, and
            # the status line says it happened rather than leaving the panel
            # quietly acting on a structure the user did not choose.
            switched = self._retarget_to_matching(path, mapping.strip(), solvation)
            if switched is None:
                return
            loaded, spec = switched
        self._color_energy_button.setEnabled(True)
        # Named once it is known. `gmx_MMPBSA` writes the same file name for
        # both models, so before a load the panel cannot say which method this
        # will be; after one it can, and saying "MM/PBSA" for a Generalized
        # Born run names the method that was not used.
        method = "MM/GBSA" if solvation == "gb" else (
            "MM/PBSA" if solvation == "pb" else "MM/GBSA or MM/PBSA"
        )
        if not solvation:
            from ..core.mmpbsa import solvation_models

            models = solvation_models(path)
            if len(models) == 1:
                method = (
                    "MM/GBSA" if models[0].lower().startswith("g") else "MM/PBSA"
                )
        self._color_energy_button.setText(f"Colour by {method}")
        self._color_energy_button.setToolTip(
            "Paint each residue by its contribution to binding"
        )

    def _on_load_ddg(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        path, _selected = QFileDialog.getOpenFileName(
            None, "Load predicted ΔΔG", "",
            "ΔΔG predictions (*.csv *.tsv *.xlsx *.txt);;All files (*)",
        )
        if not path:
            return
        # `max` ranks by the most disruptive substitution, which is the hot-spot
        # question. `min` would rank by the most stabilising one — a different
        # question, and the wrong default for an interface panel.
        rows = self._run_command(ddg_command(spec, path, statistic="max"))
        if not rows:
            return
        try:
            self._populate_value_table(
                ["Residue", "ΔΔG max (kcal/mol)"],
                [
                    (
                        f"{wild_type} {chain}:{number}",
                        f"/{chain}:{number}",
                        f"{value:+.2f} ({count} subs)",
                    )
                    for (chain, number), wild_type, value, count in rows
                ],
            )
            self._interface_result.setText(
                f"{len(rows)} interface residues with predicted ΔΔG — "
                f"most disruptive: {rows[0][1]} {rows[0][0][0]}:{rows[0][0][1]} "
                f"({rows[0][2]:+.2f} kcal/mol)"
            )
            self._color_ddg_button.setEnabled(True)
            self._color_ddg_button.setToolTip(
                "Colour interface residues by predicted ΔΔG "
                "(diverging scale, red = disruptive)"
            )
            self._ddg_loaded = True
            self._refresh_structure_kind(self._current_model())
            # Kept so the hot-spot table can show buried area and ΔΔG together.
            self._ddg_by_residue = {
                (chain, number): value
                for (chain, number), _wt, value, _count in rows
            }
        except (AttributeError, IndexError, TypeError):
            self._interface_result.setText("See the ChimeraX Log for ΔΔG values")

    def _on_color_by(self, metric: str) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        result = self._run_command(color_by_command(spec, metric))
        if result is None:
            return
        # The metrics do not return the same thing. ΔΔG and ΔSASA hand back a
        # ColorScale built from the data, B-factor a BFactorRange, and pLDDT a
        # ConfidenceReport whose scale is the published banding rather than
        # anything derived from this structure.
        #
        # pLDDT is the one that reports differently, so it branches; everything
        # else needs `.low` and `.high`, which is why BFactorRange is a named
        # tuple. The unit named here is a lookup rather than a conditional:
        # this line was `"ΔΔG" if metric == "ddg" else "buried area"`, and
        # adding B-factor as a fourth metric made it silently label a B-factor
        # map as buried area — after the same branch had already raised
        # AttributeError for the same reason when pLDDT was added.
        if metric == "plddt":
            self._interface_result.setText(
                f"Coloured by pLDDT — mean {result.normalized_mean:.1f} on the "
                f"{result.scale} scale (see the Log for the colour key)"
            )
            return
        label = METRIC_LABELS.get(metric, metric)
        self._interface_result.setText(
            f"Coloured by {label} — scale {result.low:+.2f} … {result.high:+.2f}, "
            "set from the data (see the Log for the colour key)"
        )

    def _on_open_reference(self) -> None:
        """Open a structure from disk and select it as the DockQ reference."""
        path, _selected = QFileDialog.getOpenFileName(
            None, "Open reference structure", "",
            "Structures (*.cif *.mmcif *.pdb *.ent *.pdb.gz *.cif.gz);;All files (*)",
        )
        if not path:
            return
        before = {id(model) for model in self.session.models.list()}
        if self._run_command(f"open {quote_path(path)}") is None:
            return
        opened = [model for model in self.session.models.list()
                  if id(model) not in before and hasattr(model, "chains")]
        if not opened:
            self._set_status(f"nothing openable in {Path(path).name}")
            return
        # Point the chooser at what was just opened, so the next click scores
        # against it rather than against whatever was selected before.
        self._reference_button.value = opened[-1]
        self._set_status("")

    def _on_dockq(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        reference = self._reference_button.value
        if reference is None:
            self._set_status("Open a reference complex and select it above")
            return
        reference_spec = model_ref(reference).model_id
        if reference_spec == spec:
            self._set_status("The reference must be a different structure")
            return
        result = self._run_command(dockq_command(spec, reference_spec))
        if result is None:
            return
        try:
            self._set_tile_value("dockq", result.dockq)
            self._interface_result.setText(
                f"DockQ {result.dockq:.3f} ({result.capri_class}) · "
                f"Fnat {result.fnat:.3f} · iRMSD {result.irmsd:.2f} Å · "
                f"LRMSD {result.lrmsd:.2f} Å"
            )
        except AttributeError:
            self._interface_result.setText("See the ChimeraX Log for DockQ")

    def _on_measure_bsa(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        area = self._run_command(f"molcompose buriedarea model {spec}")
        if isinstance(area, (int, float)):
            self._set_tile_value("bsa", area)
            self._interface_result.setText(
                f"Buried solvent-accessible area: {area:.0f} Å²"
            )

    def _on_report(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        path, _selected = QFileDialog.getSaveFileName(
            None, "Write interface report", "interface-report.md",
            "Markdown (*.md);;JSON (*.json);;CSV (*.csv)",
        )
        if not path:
            return
        written = self._run_command(report_command(path))
        if written is not None:
            self._set_status(f"Report written to {written}")

    def _on_affinity(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        result = self._run_command(affinity_command(spec))
        if result is None:
            return
        try:
            self._set_tile_value("dg", result.delta_g)
            self._set_tile_value("kd", result.kd)
            self._interface_result.setText(
                f"ΔG {result.delta_g:.2f} kcal/mol · Kd {result.kd:.2e} M "
                f"@ {result.temperature:g} °C · {result.contact_pairs} contacts"
            )
        except AttributeError:
            self._interface_result.setText("See the ChimeraX Log for the prediction")

    def _on_confidence(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        metrics = self._run_command(f"molcompose confidence model {spec}")
        if not isinstance(metrics, dict):
            return
        # pDockQ is not DockQ, and they used to share a tile. One is a
        # confidence estimate a prediction makes about itself; the other is
        # how far that prediction is from an experimental answer. Whichever
        # ran last owned the tile, and the caption said "ipSAE / DOCKQ".
        parts = [f"pLDDT {metrics['mean_plddt']:.1f} (scale {metrics['scale']})"]
        if metrics.get("iplddt") is not None:
            parts.append(f"ipLDDT {metrics['iplddt']:.1f}")
        if metrics.get("pdockq") is not None:
            parts.append(f"pDockQ {metrics['pdockq']:.3f}")
        else:
            parts.append("pDockQ needs a detected interface (cbeta, 8 Å)")
        self._interface_result.setText(" · ".join(parts))

    def _on_ipsae(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            None, "Choose the prediction's PAE file", "",
            "PAE files (*.json *.npz)",
        )
        if not path:
            return
        scores = self._run_command(f"molcompose ipsae {quote_path(path)} model {spec}")
        if not isinstance(scores, dict) or not scores:
            return
        ranked = sorted(scores.items(), key=lambda item: item[1]["max"], reverse=True)
        text = " · ".join(f"ipSAE {pair} {values['max']:.3f}" for pair, values in ranked[:3])
        self._interface_result.setText(text)

    def _on_toggle_rotation(self) -> None:
        if self._spinning:
            self._run_command("stop")
            self._spinning = False
            self._spin_button.setText("▶ Rotate")
        else:
            self._run_command("roll y 1")
            if not self._status.isVisible():
                self._spinning = True
                self._spin_button.setText("⏸ Stop")

    def _on_fit_view(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        self._run_command(focus_command(spec, "interface"))

    def _on_start_bridge(self) -> None:
        self._run_command("remotecontrol rest start port 3000 json true")

    def _on_print_size(self) -> None:
        """Keep the pixel width and the stated print size in agreement."""
        width_mm = self._print_size_combo.currentData() or 0.0
        dpi = self._dpi_combo.currentData() or 300
        if width_mm:
            width = pixels_for(width_mm, dpi)
            # The height follows the aspect ratio already set rather than a
            # second column figure: journals constrain width, and a height
            # chosen for the user is a crop they did not ask for.
            ratio = self._height_spin.value() / max(1, self._width_spin.value())
            self._width_spin.setValue(width)
            self._height_spin.setValue(max(1, round(width * ratio)))
        self._update_print_size_hint()

    def _update_print_size_hint(self) -> None:
        dpi = self._dpi_combo.currentData() or 300
        width_mm = self._width_spin.value() / dpi * MM_PER_INCH
        height_mm = self._height_spin.value() / dpi * MM_PER_INCH
        self._print_size_hint.setText(
            f"{width_mm:.0f} × {height_mm:.0f} mm at {dpi} dpi"
        )

    def _on_match_aspect(self) -> None:
        """Set the height from the graphics window's own aspect ratio."""
        try:
            view_width = self.session.main_view.window_size[0]
            view_height = self.session.main_view.window_size[1]
        except (AttributeError, IndexError, TypeError):
            self.session.logger.info(
                "MolCompose: the graphics window size is unavailable, so the "
                "export aspect ratio was left alone."
            )
            return
        if not view_width or not view_height:
            return
        self._height_spin.setValue(
            max(1, round(self._width_spin.value() * view_height / view_width))
        )
        self._update_print_size_hint()

    def _structure_stem(self) -> str:
        """The structure's name, safe for a filename. "figure" when unnamed.

        `_current_model`, not `_current_model_spec`: the spec is the string
        "#1", and asking a string for its `.name` returns nothing at all — so
        every figure was called "figure" and the fallback looked like a
        deliberate default rather than a seam that had come apart.
        """
        return structure_stem(self._current_model())

    def _suggested_filename(self) -> str:
        """`1brs_interface-focus.png` rather than `figure.png`.

        The default was the same name every time, so a second export either
        overwrote the first or made the user invent a name at the moment they
        were thinking about something else.
        """
        stem = self._structure_stem()
        preset = self._preset_combo.currentData()
        return f"{stem}_{preset}.png" if preset else f"{stem}.png"

    def _on_export(self) -> None:
        """Ask where to put it, then hand off. Nothing but the two dialogs.

        Split from `export_to` because a modal file dialog cannot be driven by
        a test or by a live check: everything below the dialogs was reachable
        only by a human clicking, which left the one path in this card that
        actually writes a file as the one path never exercised end to end.
        """
        spec = self._current_model_spec()
        if spec is None:
            return
        path, _selected_filter = QFileDialog.getSaveFileName(
            None,
            "Export image",
            self._suggested_filename(),
            "PNG images (*.png);;TIFF images (*.tif *.tiff)",
        )
        if not path:
            return
        from pathlib import Path

        target = Path(path)
        overwrite = False
        if target.exists():
            answer = QMessageBox.question(
                None,
                "Overwrite existing file?",
                f"{target} already exists. Overwrite it?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        self.export_to(target, overwrite=overwrite)

    def export_to(self, target, *, overwrite: bool = False):
        """Export to `target` with the card's current settings.

        Public because it is the whole of what the Export button does once the
        path is known, and a caller that already has a path — a test, a live
        check, a script driving the panel — should not have to fake a dialog to
        reach it. Returns the command's result, or None if it was refused.
        """
        if self._spinning:
            # A spinning model would be photographed mid-rotation, and the
            # exported frame would not be the one composed on screen.
            self._on_toggle_rotation()
        result = self._run_command(
            export_command(
                target,
                self._width_spin.value(),
                self._height_spin.value(),
                self._supersample_spin.value(),
                self._transparent_check.isChecked(),
                self._session_check.isChecked(),
                overwrite,
                self._dpi_combo.currentData() or 300,
                self._recipe_check.isChecked(),
                (None if self._key_font_spin.value() == DEFAULT_KEY_FONT
                 else self._key_font_spin.value()),
            )
        )
        if result is not None:
            self._last_export = Path(target)
            self._reveal_button.setEnabled(True)
        return result

    def _on_seqcolor_show(self) -> None:
        """Write somewhere temporary and open the viewer — no dialog."""
        import tempfile

        spec = self._current_model_spec()
        if spec is None:
            return
        source = self._seqcolor_combo.currentData() or "interface"
        # Named for the structure and what it shows. Deriving it from the
        # image filename dragged in the current *style* preset —
        # "1brs_clean-cartoon_interface.scf" — which has nothing to do with a
        # sequence colouring.
        target = Path(tempfile.gettempdir()) / f"{self._structure_stem()}_{source}.scf"
        self._run_command(seqcolor_command(spec, source, target))

    def _on_seqcolor(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        source = self._seqcolor_combo.currentData() or "interface"
        path, _selected = QFileDialog.getSaveFileName(
            None, "Save sequence colouring",
            f"{self._structure_stem()}_{source}.scf",
            "Sequence Coloring Format (*.scf)",
        )
        if not path:
            return
        self._run_command(seqcolor_command(spec, source, path))

    def _on_reveal_export(self) -> None:
        """Open the enclosing folder with the exported file selected."""
        target = getattr(self, "_last_export", None)
        if target is None or not target.exists():
            self._reveal_button.setEnabled(False)
            return
        if sys.platform == "darwin":
            subprocess.Popen(["/usr/bin/open", "-R", str(target)])  # noqa: S603
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(target)])  # noqa: S603, S607
        else:
            subprocess.Popen(["xdg-open", str(target.parent)])  # noqa: S603, S607

    def _on_reset(self) -> None:
        spec = self._current_model_spec()
        if spec is None:
            return
        self._run_command(reset_command(spec))
        self._hbonds_shown = False
        self._hbonds_button.setText("H-bonds")
        self._contacts_shown = False
        self._contacts_button.setText("Contacts")
        self._interactions_shown = False
        self._interactions_button.setText("Show Typed Interactions")
        if self._spinning:
            self._on_toggle_rotation()
        self._group_a_color = None
        self._group_b_color = None
        self._color_a_button.setStyleSheet("")
        self._color_b_button.setStyleSheet("")
