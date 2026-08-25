# molcompose skill

Domain judgement for agents driving `molcompose-mcp`. The MCP server says what
can be called; this says what to call, in what order, and which numbers not to
believe.

## Install

Copy `SKILL.md` into the skills directory your agent reads, for example:

```bash
cp skill/SKILL.md /path/to/your/skills/molcompose/SKILL.md
```

It is one file with no dependencies and no client-specific syntax. Where a
client has no skills directory, supply the file through that client's normal
instruction mechanism.

## Why a skill and not just the MCP server

The server validates arguments and refuses inapplicable metrics, which stops an
agent producing a wrong number. It cannot stop an agent producing an
*incomplete* one. Benchmarks of agent-driven protein work find that agents pick
appropriate tools and then evaluate too shallowly, rarely comparing
alternatives (Kim and Romero 2026). The judgement in `SKILL.md` — run the
battery, read the skipped block, treat metric disagreement as signal — is what
closes that gap.

## Status

Draft, 0.1.0. The guidance follows the validated tool contracts and the failure
modes covered by the test suite.
