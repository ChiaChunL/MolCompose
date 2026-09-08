# molcompose-mcp

<p align="center">
  <a href="https://pypi.org/project/molcompose-mcp/"><img alt="molcompose-mcp on PyPI" src="https://img.shields.io/pypi/v/molcompose-mcp?color=12A08C&label=molcompose-mcp&logo=pypi&logoColor=white"></a>
  <a href="https://pypi.org/project/molcompose-mcp/"><img alt="Supported Python versions" src="https://img.shields.io/pypi/pyversions/molcompose-mcp?color=4477AA&logo=python&logoColor=white"></a>
  <a href="https://pepy.tech/projects/molcompose-mcp"><img alt="PyPI downloads reported by Pepy" src="https://api.pepy.tech/badge/molcompose-mcp"></a>
  <a href="https://github.com/ChiaChunL/MolCompose/actions/workflows/unit-tests.yml"><img alt="CI" src="https://github.com/ChiaChunL/MolCompose/actions/workflows/unit-tests.yml/badge.svg"></a>
  <a href="https://github.com/ChiaChunL/MolCompose/blob/main/LICENSE"><img alt="BSD-3-Clause" src="https://img.shields.io/badge/licence-BSD--3--Clause-7B7BD8"></a>
</p>

**Download statistics:** [Totals (Pepy)](https://pepy.tech/projects/molcompose-mcp).
These are package downloads, not unique users or MCP calls.

An MCP stdio server for protein-interface analysis and molecular visualization
in UCSF ChimeraX. Agents use the same MolCompose commands as the graphical panel.

## Installation

Requires Python 3.11+, ChimeraX 1.12 and the
[MolCompose bundle](https://cxtoolshed.rbvi.ucsf.edu/apps/chimeraxmolcompose).
Install the latest published bridge:

```bash
python -m pip install --upgrade molcompose-mcp
```

This README describes MCP **0.1.2** with bundle **0.1.3**, not yet published.
For this checkout, run `python -m pip install ./mcp` from the repository root
and install the matching bundle using the
[checkout instructions](https://github.com/ChiaChunL/MolCompose#this-checkout).

## In the MolCompose Agent tab

Open **Tools → Structure Analysis → MolCompose**, then select the **Agent** tab.
Select an installed, signed-in Codex or Claude Code CLI, then ask a question.
The tab starts the local bridge when needed and selects `--profile assistant`
automatically.

## External MCP client

Start the REST bridge in ChimeraX:

```text
remotecontrol rest start port 3000 json true
```

Use the actual port printed by ChimeraX. Register this command in your MCP client:

```text
molcompose-mcp --chimerax-url http://127.0.0.1:3000 --profile assistant
```

```json
{
  "mcpServers": {
    "molcompose": {
      "command": "molcompose-mcp",
      "args": [
        "--chimerax-url", "http://127.0.0.1:3000",
        "--profile", "assistant"
      ]
    }
  }
}
```

Use the executable's absolute path if your client cannot find it. To generate
configuration with the resolved path, run:

```bash
molcompose-mcp --chimerax-url http://127.0.0.1:3000 --profile assistant --print-config
```

**Copyable prompts:** [Connection setup](https://github.com/ChiaChunL/MolCompose#external-mcp-setup-prompt) · [Verify analysis and preview](https://github.com/ChiaChunL/MolCompose#verification-prompt).

## Assistant workflow

| Tool | Use |
|---|---|
| `open_structure` | Open a supported coordinate file or PDB ID |
| `inspect_session` | Inspect models, chains and version compatibility first |
| `analyse_interface` | Analyse a chain pair or request clarification |
| `load_external_evidence` | Import ΔΔG, energy or RMSF data |
| `compose_figure` | Apply a preset for the requested view |
| `render_preview` | Inspect the image before exporting |
| `export_artifact` | Save the figure, recipe and provenance, with overwrite confirmation |

For structured results, continue only after `status: completed`; resolve
`needs_input`, `needs_confirmation` or `failed` before retrying. `render_preview`
returns an image instead, which requires visual inspection. Successful export
alone does not establish figure quality.

For advanced integrations, use `--profile expert` (29 tools). Omitting
`--profile` selects `all` (34 tools). The `assistant` profile has 7 tools.
See the [MCP reference](https://github.com/ChiaChunL/MolCompose/blob/main/docs/mcp-reference.md)
for individual tools, result fields and safety restrictions.

## Importing energy data

Both `load_energy` and `load_external_evidence` accept `solvation: "pb"` or
`solvation: "gb"`. A file containing both methods requires a choice:

```json
{"kind": "energy", "path": "/data/decomp.dat", "model": "#1", "chains": "A:A,B:B", "solvation": "pb"}
```

This example is for `load_external_evidence`; omit `kind` for `load_energy`.
Match the chain mapping to your structure. Imported energies are not recalculated.

## Troubleshooting

- **Connection:** keep ChimeraX open and use its actual REST port. Call
  `inspect_session` to check bundle/bridge compatibility.
- **Preview or export:** use windowed ChimeraX on macOS, not `--nogui`.
- **Missing metric:** check `skipped` and the required structure or input files.
- **Overwrite or upload:** assistant tools ask for confirmation. For PythiaStudio,
  configure `PYTHIASTUDIO_API_KEY`; local imports are not uploaded.
- **Local access:** the REST bridge is unauthenticated. Stop it with
  `remotecontrol rest stop` when finished. MCP input validation is not a host sandbox.

[Source and documentation](https://github.com/ChiaChunL/MolCompose) · [BSD-3-Clause license](https://github.com/ChiaChunL/MolCompose/blob/main/LICENSE)
