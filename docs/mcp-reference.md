# MolCompose MCP reference

For installation, configuration and the seven-tool assistant workflow, see the
[MCP README](../mcp/README.md).

## Profiles and expert tools

The `assistant` profile embeds routine guidance in its seven tools. The `expert`
and default `all` profiles also expose the `molcompose://skill` resource for
low-level workflows; its source is [SKILL.md](../skill/SKILL.md).

The 29 expert tools are:

- Discovery: `list_models`, `open_structure`, `list_blocks`, `check_capabilities`,
  `get_confidence`, `get_recipe`.
- Analysis: `characterise_interface`, `detect_interface`, `detect_all_interfaces`,
  `measure_buried_area`, `predict_affinity`, `rank_hotspots`, `analyze_interactions`,
  `compute_ipsae`, `score_against_reference`.
- Views: `apply_style`, `focus`, `show_contacts`, `show_hbonds`, `reset`,
  `run_native`, `render_preview`.
- Data and export: `load_energy`, `load_flexibility`, `load_ddg`, `write_report`,
  `export_figure`, `export_sequence_coloring`.
- External prediction: `predict_ddg_pythiastudio`.

Tool schemas define finite choices and numeric bounds. `render_preview` returns
MCP native image content rather than a JSON result. Preview-before-export is
an agent workflow rule, not a server-side export lock.

## Results and precision

Analysis results retain machine values in their existing fields and under `raw`.
Use `display` for formatted summaries and `raw` for downstream computation.
The `skipped` block explains unavailable analyses. Different metrics retain
their own definitions and scales; they are not combined into a universal score.

`inspect_session` reports bundle/server compatibility. An unknown version or
compatibility warning requires investigation, not an assumption of compatibility.

## Side effects and confirmation

Tool annotations distinguish session changes, local file writes and external
requests. They do not replace application-level checks.

- `export_artifact` asks before replacing an image or requested sidecar, including
  symbolic links. Its file QA checks existence and non-empty content, not visual
  quality or scientific validity.
- Expert `export_figure` refuses existing targets with `overwrite=false`.
  A new provenance sidecar is created exclusively. Multi-file export is not
  atomic: a late failure can leave an already written image.
- `load_external_evidence(kind="pythiastudio", ...)` separately confirms structure
  upload and any overwrite of the local output. The expert
  `predict_ddg_pythiastudio` is an explicit upload operation. Configure the key
  with `PYTHIASTUDIO_API_KEY`; its explicit key argument is a deprecated fallback.
- Local ΔΔG, energy and RMSF imports are not uploaded. Opening a PDB identifier
  can fetch a structure from the network.

## Provenance scopes

With recipe saving enabled, figure export writes a canonical ChimeraX `.cxc`
sidecar and marks the provenance `recipe_scope: "session"`. This recipe can
include earlier panel, command-line and MCP operations.

`get_recipe` instead returns commands observed by the current MCP process.
Without a canonical recipe, provenance is process-scoped and is not a complete
session record. Repeated command text cannot identify a particular occurrence:
uncertain canonical sources remain `unknown` and timestamps remain missing.
The separate process history preserves its observations.

## Native command restrictions

`run_native` accepts reviewed forms, not every option within a verb family.
Examples include `view #1`, `turn y 30`, `color #1/A red` and `info models`.
Coordinate/model-transform edits, saved-view restoration, file writes,
notifications, abbreviated keywords, quoted tokens and command separators are
rejected. Targeted view framing requires an explicit model selector; bare `view`
frames all models.

Current native verbs: `color`, `graphics`, `hide`, `info`, `lighting`, `measure`, `rock`, `roll`, `select`, `show`, `stop`, `turn`, `version`, `view`, `zoom`

`open_structure` accepts four-character PDB identifiers (optionally prefixed with
`pdb:`) and local `.pdb`, `.pdb1`, `.ent`, `.pqr`, `.cif`, `.mmcif`, `.mol2`, `.sdf`
or `.mol` files, optionally compressed once with `.gz`, `.bz2` or `.xz`.
URLs, scripts, sessions, unknown formats and format overrides are rejected.

Validation constrains command dispatch; it is not a sandbox for a modified host,
redefined aliases or malicious files exploiting a native parser. The localhost
REST bridge is unauthenticated. Stop it with `remotecontrol rest stop` when done.

## Testing

From the repository root, run `pytest -q tests mcp/tests`. The deterministic
assistant scenarios in `mcp/tests/test_agent_scenarios.py` use a REST fixture.
They test tool behavior, not an LLM's performance.

For actual CLI-agent evaluation, see `python scripts/agent_behavior_eval.py --help`.
That runner uses installed, signed-in clients and may consume model quota.
