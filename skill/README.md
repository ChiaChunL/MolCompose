# molcompose skill

Domain judgement for agents driving `molcompose-mcp`. The MCP server says what
can be called; this says what to call, in what order, and which numbers not to
believe.

## Install

One file, no dependencies, no client-specific syntax. Drop it wherever your
agent reads skills from — for Claude Code that is `~/.claude/skills/`:

```bash
mkdir -p ~/.claude/skills/molcompose
curl -fsSL -o ~/.claude/skills/molcompose/SKILL.md \
  https://raw.githubusercontent.com/ChiaChunL/MolCompose/main/skill/SKILL.md
```

Where a client has no skills directory, supply the file through whatever
instruction mechanism it does have.

**You may not need to.** The server sends the rules an agent gets wrong without
being told — prefer `characterise_interface`, read the `skipped` block, never
report a number without its criterion and cutoff — to every client on connect,
whatever it is and with nothing installed. This file is the long form: which
analysis answers which question, and how to read a disagreement between two of
them.

## Why a skill and not just the MCP server

The server validates arguments and refuses inapplicable metrics, which stops an
agent producing a wrong number. It cannot stop an agent producing an
*incomplete* one. Benchmarks of agent-driven protein work find that agents pick
appropriate tools and then evaluate too shallowly, rarely comparing
alternatives (Kim and Romero 2026). The judgement here — run the battery, read
the skipped block, treat metric disagreement as signal — is what closes that
gap.
