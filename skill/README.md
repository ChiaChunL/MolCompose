# molcompose skill

Domain judgement for agents driving `molcompose-mcp`. The MCP server says what
can be called; this says what to call, in what order, and which numbers not to
believe.

## Nothing to install

`molcompose-mcp` ships this file and serves it as the `molcompose://skill`
resource, so an agent reads it when it needs it and a person never has to know
it exists. The rules it gets wrong without being told — prefer
`characterise_interface`, read the `skipped` block before the numbers, never
report a count without its criterion and cutoff — arrive earlier still, in the
server's connect-time instructions.

The copy inside the package is kept byte-identical to this one by a test.

## Why a skill and not just the MCP server

The server validates arguments and refuses inapplicable metrics, which stops an
agent producing a wrong number. It cannot stop an agent producing an
*incomplete* one. Benchmarks of agent-driven protein work find that agents pick
appropriate tools and then evaluate too shallowly, rarely comparing
alternatives (Kim and Romero 2026). The judgement here — run the battery, read
the skipped block, treat metric disagreement as signal — is what closes that
gap.
