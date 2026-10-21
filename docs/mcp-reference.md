# MolCompose MCP reference

For installation, configuration and the assistant workflow, see the
[MCP README](../mcp/README.md).

## Profiles and expert tools

The `assistant` profile embeds routine guidance in its tools. The `expert`
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

Use `raw` for computation, `display` for formatted summaries, and `skipped` for
unavailable analyses.

## Side effects and confirmation

Assistant tools request confirmation before overwriting files or uploading
structures to PythiaStudio. Local data imports do not upload files. Expert tools
use explicit overwrite and upload operations. Opening a PDB identifier fetches
the structure from the network if needed.

## Provenance scopes

With recipe saving enabled, figure export includes a ChimeraX session recipe
(`.cxc`). `get_recipe` returns only commands recorded by the current MCP process.

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
