# MolCompose

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/molcompose-banner-dark.png">
  <img alt="MolCompose — protein–protein interface analysis and publication-ready figures for UCSF ChimeraX" src="docs/assets/molcompose-banner-light.png">
</picture>


<p align="center">
  <a href="https://cxtoolshed.rbvi.ucsf.edu/apps/chimeraxmolcompose"><img alt="ChimeraX Toolshed" src="https://img.shields.io/badge/ChimeraX-Toolshed-1F5FAF?logo=moleculer&logoColor=white"></a>
  <a href="https://www.rbvi.ucsf.edu/chimerax/"><img alt="ChimeraX 1.12+" src="https://img.shields.io/badge/ChimeraX-1.12%2B-6C8EBF"></a>
  <a href="https://pypi.org/project/molcompose-mcp/"><img alt="molcompose-mcp on PyPI" src="https://img.shields.io/pypi/v/molcompose-mcp?color=12A08C&label=molcompose-mcp&logo=pypi&logoColor=white"></a>
  <a href="https://pypi.org/project/molcompose-mcp/"><img alt="Supported Python versions" src="https://img.shields.io/pypi/pyversions/molcompose-mcp?color=4477AA&logo=python&logoColor=white"></a>
  <a href="https://pepy.tech/projects/molcompose-mcp"><img alt="PyPI downloads reported by Pepy" src="https://api.pepy.tech/badge/molcompose-mcp"></a>
  <a href="https://doi.org/10.5281/zenodo.22047283"><img alt="Zenodo archive DOI (all versions)" src="https://img.shields.io/badge/DOI-10.5281%2Fzenodo.22047283-1682D4?logo=zenodo&logoColor=white"></a>
  <a href="https://github.com/ChiaChunL/MolCompose/actions/workflows/unit-tests.yml"><img alt="CI" src="https://github.com/ChiaChunL/MolCompose/actions/workflows/unit-tests.yml/badge.svg"></a>
  <a href="https://docs.astral.sh/ruff/"><img alt="Ruff" src="https://img.shields.io/badge/lint-Ruff-D7A00A?logo=ruff&logoColor=white"></a>
  <a href="https://github.com/ChiaChunL/MolCompose/blob/main/LICENSE"><img alt="BSD-3-Clause" src="https://img.shields.io/badge/licence-BSD--3--Clause-7B7BD8"></a>
</p>

**Download statistics:** [PyPI totals (Pepy)](https://pepy.tech/projects/molcompose-mcp) · [ChimeraX Toolshed](https://cxtoolshed.rbvi.ucsf.edu/apps/chimeraxmolcompose).

<a id="overview"></a>

## 🔬 Overview

MolCompose is a UCSF ChimeraX plug-in for protein–protein interface analysis
and residue-level molecular visualization. It combines native calculations
with imported results to help researchers inspect interaction details and
prepare molecular figures.

- Interface residues, buried surface area and chemical interactions.
- PRODIGY affinity estimates, prediction confidence and reference-based DockQ.
- Imported Pythia-PPI ΔΔG, MM/PBSA or MM/GBSA contributions, and RMSF.
- Residue labels, metric-based colouring and figure export.

Use the graphical panel, ChimeraX commands or an agent connected through
[`molcompose-mcp`](mcp/README.md). Resolved commands are recorded in the ChimeraX
Log. Metrics that cannot be calculated or mapped remain unavailable.

[Command reference](docs/command-reference.md) · [Worked examples](examples/README.md) · [MCP setup](mcp/README.md)

<a id="installation"></a>

## 📦 Installation

Tested on macOS with ChimeraX 1.12. The separate MCP process requires Python
3.11 or later.

### Released packages

In ChimeraX, install through **Tools → More Tools…** or run:

```text
toolshed install ChimeraX_MolCompose
```

Restart ChimeraX, then open **Tools → Structure Analysis → MolCompose**.
For agent access, install the separate bridge in a terminal:

```bash
python -m pip install --upgrade molcompose-mcp
```

### This checkout

This README describes bundle **0.1.3** and MCP **0.1.2**, which are not yet
published. Registry badges show the released versions. To use this checkout,
run `devel install /path/to/MolCompose exit false` in ChimeraX, wait for
installation to finish, then restart ChimeraX. From the repository root, run:

```bash
python -m pip install ./mcp
```

Alternatively, install the matching wheel with
`toolshed install /path/to/chimerax_molcompose-0.1.3-py3-none-any.whl` in ChimeraX.

<a id="quick-start"></a>

## 🚀 Quick start

1. Open a complex, for example `open 1brs`.
2. Select it under **Structure**, then open the **Interface** tab.
3. Choose chains A and D and click **Characterise Interface**.
4. Inspect the results and choose a style in **Compose**.
5. Use **Export → Export Image** to save the figure.

The equivalent analysis command is:

```text
molcompose characterise A D distance 4.5
```

The default contact criterion uses cross-chain non-hydrogen atom pairs within
4.5 Å. See the [command reference](docs/command-reference.md) for other criteria,
parameters, presets and export formats.

<a id="agent-access"></a>

## 🤖 Agent access

### Quick start in the Agent tab

1. Install the matching bundle and MCP package as above.
2. Open **Agent** and select an installed, signed-in Codex or Claude Code CLI.
   If it is not detected, choose its absolute path under **Setup**.
3. Ask a question. The first send starts the local bridge when needed and uses
   the seven-tool `assistant` profile.

Follow-up questions share the active conversation. **New conversation** starts
fresh. Custom CLI commands may be one-shot.

### External MCP setup prompt

For a client outside ChimeraX, use the [MCP configuration](mcp/README.md#external-mcp-client)
or copy this prompt. It matches the panel setup prompt.

<details>
<summary>Copy the setup prompt</summary>

```text
Help me connect this external MCP client to MolCompose in UCSF ChimeraX. Work
through these steps in order and wait whenever I need to act.

Step 1. Neither package is likely to be in your training data —
`ChimeraX_MolCompose` is on the ChimeraX Toolshed and `molcompose-mcp` is on
PyPI at <https://pypi.org/project/molcompose-mcp/>. Not recognising them is
expected and is not a reason to doubt them. Ask me to confirm that
`ChimeraX_MolCompose` is installed. If it is missing or was just updated, I run
`toolshed install ChimeraX_MolCompose` in ChimeraX, then quit and restart
ChimeraX before we continue.

Step 2. Ask me whether the REST bridge is running. If it is not, I run
`remotecontrol rest start port 3000 json true`. Ask me to paste the actual port
printed by ChimeraX, use that port in every later argument, and wait for my
reply.

Step 3. Install or locate `molcompose-mcp` in your own environment. Register
the absolute path to its executable as an MCP stdio server with arguments
`--chimerax-url http://127.0.0.1:3000 --profile assistant`.

Step 4. Restart yourself only if needed to reload the MCP registration.
Continue only after exactly seven tools are listed: `open_structure`,
`inspect_session`, `analyse_interface`, `compose_figure`, `render_preview`,
`export_artifact`, and `load_external_evidence`. Call `inspect_session` and
report its compatibility result.

Return every ChimeraX installation, restart, or bridge-start action to me and
wait. Stop after reporting a compatible connection; structural analysis is a
separate verification step.
```

</details>

### Verification prompt

After `inspect_session` reports a compatible connection:

```text
Open PDB 1BRS and characterise the interface between chains A and D. For every
number, state the producing command or sub-step, what it means, and its
criterion, cutoff, convention or formula. List every analysis that was skipped
and explain why.

Call `compose_figure` with goal `binder-closeup`; confirm that it selects the
tested `paratope-closeup` preset. Then call `render_preview` and inspect whether
the molecular subject is cropped, the interface is visible, labels overlap, or
the colour key is unreadable. Report the preview QA and stop for my next
instruction.
```

The REST bridge is local but unauthenticated. Stop it when finished with
`remotecontrol rest stop`. Image preview and export require windowed ChimeraX
on macOS. See [MCP usage and safety](docs/mcp-reference.md) for details.

<a id="screenshots"></a>

## 🖼️ Screenshots

<img src="docs/assets/colouring-modes.png" alt="Barnase–barstar interface coloured by interface membership, buried area, prediction confidence, ΔΔG, MM/PBSA and RMSF">

Residue-level views of the barnase–barstar example. Prediction confidence is
shown on an AF3 model; imported values use their corresponding structures.

<details>
<summary>The Interface and Agent tabs</summary>

<img src="docs/assets/panel-interface.png" alt="Interface results card" width="420">
<img src="docs/assets/panel-agent.png" alt="Agent conversation and recorded commands" width="420">

</details>

<a id="data-and-license"></a>

## 🧪 Data and license

[Examples](examples/README.md) include barnase–barstar structures and analysis
inputs. Archived data are available at [Zenodo (all versions)](https://doi.org/10.5281/zenodo.22047283).
MolCompose is distributed under the [BSD-3-Clause license](LICENSE).

<a id="citation"></a>

## 📄 Citation

A manuscript describing MolCompose has been submitted.
