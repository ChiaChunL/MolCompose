# Contributing to MolCompose

## Repository layout

The public top level contains the product code, compact examples and
documentation, and nothing else. New top-level directories should have a stable
public purpose and be documented here before code lands.

- `src/` is the ChimeraX bundle source, installed as `chimerax.molcompose`.
- `src/core/` holds host-light logic; it must not import ChimeraX GUI modules.
- `src/adapters/` holds all direct ChimeraX session/rendering/saving calls.
- `src/ui/` is a thin Qt client over the canonical commands.
- `tests/` holds host-light unit tests and the ChimeraX integration smoke
  script. `docs/` holds public user and developer documentation.
- `mcp/` is the separately installable `molcompose-mcp` package: an MCP server
  exposing the canonical commands to agents over the ChimeraX REST bridge.
  The bundle never imports it; it is a client of the commands, like the GUI.
- `examples/` contains compact, self-contained demonstrations.

Modules named `utils.py`, `helpers.py`, `misc.py`, or similarly vague names
are prohibited. Generated `build/`, `dist/`, cache, coverage, and
local-environment files are never committed.
