# molcompose-mcp

An agent-safe [MCP](https://modelcontextprotocol.io) server that exposes the
MolCompose figure workflow in UCSF ChimeraX as typed tools. Agents call the
same canonical `molcompose` commands as the GUI panel — versioned presets,
validated inputs, and a complete provenance record for every exported figure.

## Requirements

1. UCSF ChimeraX 1.12 with the ChimeraX-MolCompose bundle installed.
2. Start the REST bridge inside ChimeraX:

```
remotecontrol rest start port 3000 json true
```

(Image export requires a windowed ChimeraX on macOS; analysis tools also work
with `--nogui`.)

## Run

```bash
pip install molcompose-mcp
molcompose-mcp --chimerax-url http://127.0.0.1:3000
```

Register the command above as an MCP stdio server in whichever client you use.
The protocol is open and this server is not written against any one client; a
command-line client is enough.

Most clients take the same shape of config:

```json
{
  "mcpServers": {
    "molcompose": {
      "command": "molcompose-mcp",
      "args": ["--chimerax-url", "http://127.0.0.1:3000"]
    }
  }
}
```

Check your client's documentation for its configuration-file location rather
than trusting a path written here, since client conventions change.

## Optional: PythiaStudio ΔΔG

`predict_ddg_pythiastudio` fetches binding/stability ΔΔG from the
[PythiaStudio](https://pythiastudio.wulab.xyz) REST API and writes a tabular
file that `load_ddg` then loads into ChimeraX. This is the **only networked
tool** — the bundle itself never calls out, which keeps its zero-service
dependency profile intact while the agent acts as the integration layer.
Set `PYTHIASTUDIO_API_KEY` or pass a key explicitly.

## Safety model

- Figure work goes through the typed `molcompose` tools only.
- Native passthrough is limited to an enumerated display-only whitelist
  (`open`, `close`, `view`, `select`, `color`, `show`, `hide`, ...).
- Coordinate- or file-modifying commands are rejected with a structured error.
- Every export writes `<figure>.provenance.json` with the client identity,
  timestamps, and the full command recipe.
