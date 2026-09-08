---
name: molcompose
description: Analyse a protein-protein interface inside UCSF ChimeraX through the molcompose-mcp server — interface residues, typed non-covalent contacts, buried surface area, binding free energy, per-residue hot spots, AlphaFold-era confidence, MD-derived energetics and flexibility, and DockQ against a reference. Use whenever the user asks what an interface is made of, how strong it is, which residues matter, whether a predicted complex can be trusted, whether a designed binder lands on the intended epitope, or asks for a publication figure of an interface. Triggers on protein interface, binding interface, epitope, hot spot, buried surface area, binding affinity, interface energetics, pDockQ, ipSAE, LIS, DockQ, CAPRI class, MM/PBSA, RMSF.
version: 0.3.1
requires: molcompose-mcp connected to a running ChimeraX
---

# MolCompose — interface analysis

The tools are validated: arguments are range-checked before they reach
ChimeraX, and a metric whose assumptions the structure fails is refused rather
than estimated. What this skill adds is the judgement the tool surface cannot
carry — **which analysis answers which question, and which numbers not to
believe.**

## Respect the active tool profile

The focused `assistant` profile exposes `open_structure`, `inspect_session`,
`analyse_interface`, `compose_figure`, `render_preview`, `export_artifact` and
`load_external_evidence`. Stay within that interface and follow a completed
analysis's `next_steps`; do not guess an expert tool name that is not listed.
The `expert` and `all` profiles expose the original typed operations for
callers that deliberately want that larger surface. Expert-only examples below
are interpretation guidance, not permission to call a hidden tool.

## Start with inspection, then one analysis call

Call `inspect_session` first. It reports the live models, chains, current
interface state, applicable capabilities, and the server/bundle compatibility
handshake. If compatibility is false or unknown, show the warning instead of
guessing.

Then prefer `analyse_interface`. It chooses an interface only when the model
and chain pair are unambiguous and otherwise returns concrete choices to put
back to the user. Its completed path delegates to `characterise_interface`,
which runs the whole battery in one pass: interface
detection, typed contacts, buried area, ΔG and *K*d, hot spots, and confidence
where it applies.

**Prefer it over calling six tools yourself.** Agents given a free choice
reliably run too few analyses and stop early. The single call is the fix, not a
convenience.

It also *styles the view*, which is not the same as producing a figure: no file
is written until you call `export_artifact` (`export_figure` on the expert
surface). Do not tell the user a figure exists until one does.

In the `expert` or `all` profile, fall back to individual tools when a first
result raises a second question — whether a top-ranked residue forms a salt
bridge, whether a contact survives a stricter cutoff, or how an external ΔΔG
prediction scores that position. In the `assistant` profile, use the
machine-readable `next_steps` or ask the user to switch profiles.

## Read the `skipped` block first

Every summary lists analyses that did not run, with the reason. **A missing
metric is information, not an omission.** Report it rather than presenting a
partial answer as a whole one.

- *Experimentally determined structure* — confidence scores are refused. A
  crystallographic B-factor column is not pLDDT. Do not look for another way to
  produce one.
- *No PAE file beside the model* — ipSAE, pDockQ2 and LIS need it. Ask for the
  predictor's confidence JSON; do not substitute pLDDT.
- *Ligand or modified residues present* — the PAE matrix carries extra tokens
  and interface scores are rejected.

## Four things that will mislead you

**Rankings by different metrics disagree, and the disagreement is the point.**
A salt bridge contributes electrostatically while burying almost nothing: on
the 1BRS crystal structure at 4.5 Å, Arg87 is outside the top ten by buried
area and second by predicted ΔΔG. Never present a hot-spot list as *the* hot
spots; say which metric produced it.

**Atom pairs are not residue pairs.** Counts differ by roughly a factor of
three. The tools report residue pairs and name the criterion. If you are
tempted to count contacts yourself from raw output, do not.

**One confidence score does not establish that an interface is real.** Engines
disagree sharply on non-binders: a constructed pair scored interface pTM
0.73–0.83 by one predictor and 0.26–0.49 by another. Report several together,
and say which engine produced the model.

**DockQ near zero may be a numbering artefact.** Predictors number residues
sequentially; depositions often do not. `score_against_reference` pairs by
sequence alignment, but if a score is implausibly low, check the interface
residue lists before calling the model bad.

## How much to trust a confidence number

Interpret the score at the scope it actually measures. ipTM is one
whole-complex placement score; in a complex with several chains it can look
healthy while one chain-pair interface is poor. pDockQ2 and ipSAE use PAE to
score a particular chain-pair interface, while pLDDT is local and cannot
establish that two chains are correctly placed. The multichain motivation for
pDockQ2 is documented in the
[original evaluation](https://academic.oup.com/bioinformatics/article/39/7/btad424/7219714),
and ipSAE's current definition and supported predictor formats are maintained
by the [Dunbrack Lab implementation](https://github.com/DunbrackLab/IPSAE).

Do not turn a threshold calibrated on one predictor, oligomeric state or
benchmark into a universal law. Name the predictor and assembly composition;
use a published band only in its calibration context. Across a single design
set made by the same engine, say “higher within this set” when that is all the
evidence supports.

When ipTM, pDockQ2, ipSAE or LIS disagree, **do not average them and do not
silently crown a winner.** Report the disagreement, identify the chain pair,
inspect how much of its interface is supported by low inter-chain PAE, and ask
whether independent models or seeds converge on the same pose. A disagreement
is often the warning the user needed, not noise to remove.

Interface residue count or buried area alone cannot label a contact as crystal
packing. Crystal contacts can also bury substantial area
([Janin & Rodier, 1995](https://pubmed.ncbi.nlm.nih.gov/8749854/)). Treat a
small or unusual interface as a prompt to check the biological assembly,
symmetry mates, conservation, repeated prediction and interface chemistry —
not as a verdict.

## Cutoffs are not interchangeable

Detection defaults to heavy atoms at 4.5 Å. PRODIGY counts contacts at 5.5 Å,
and pDockQ is defined at Cβ 8 Å — both measure their own, whatever is on
screen. All three appear in output. **Always state the criterion and cutoff
with the number**, because 19+16 residues and 25+21 residues are the same
interface measured two ways.

## Data the user brings

In the `assistant` profile, route all four kinds through
`load_external_evidence`; it handles local evidence and keeps external upload
confirmation explicit. The individual loader names below are the corresponding
`expert`/`all` operations.

Four tools read files the user computed elsewhere. None of them guesses, and
all of them refuse rather than mislead:

- `load_ddg` — a predicted mutation scan. There is no ΔΔG file *format*: it
  reads a generic table, Pythia's mask output, or a PythiaStudio workbook, and
  anything else needs reshaping first.
- `load_energy` — `gmx_MMPBSA`'s per-residue decomposition, a residue's
  contribution to binding. **Negative where a residue matters**, the opposite
  sign to ΔΔG. Needs a chain map (`A:A,B:D`) because GROMACS renames chains.
  A run that computed both Generalized Born and Poisson Boltzmann writes the
  decomposition twice, and then `solvation` ('gb' or 'pb') is required: the
  two disagree by several kcal/mol, so there is nothing to average and the
  tool will not pick. Say which one you read when you report the number.
  The overall MM/PBSA total is printed for reference and is *not* comparable
  with the predicted ΔG — no entropy term, and it moves with the dielectric.
- `load_flexibility` — `gmx rmsf -res` output, how much each residue moves.
  Needs the chains in order, because gmx restarts its numbering at each one.
  Not a contribution: a mobile residue may be a loop far from the interface.
- Both MD loaders want the structure the simulation ran on — the repaired PDB,
  not the deposited entry, whose gaps make the residues disagree.

With a decomposition loaded, `rank_hotspots(metric='energy')` answers "which
residue matters" a third way, alongside buried area and ΔΔG.

## Designed binders

The interface comes back as an explicit residue list, so compare it with the
epitope or active site the design targeted. That comparison answers "did it
land where I meant it to" — the interface scores do not.

In the `expert` or `all` profile, when the design has a solved or predicted
structure to be checked against,
`apply_style('design-reference', references='#2,#3', align='A', partner='B')`
overlays them: open the references first, `align` is the chain they are
superposed on (the target), `partner` the chain being compared across them
(the binder). It takes all three or it refuses, and it is the only preset that
takes any of them. The epitope comes from the interface already detected, so
no residue number is named and nothing has to be re-typed when the interface
is redetected at another cutoff. Two references is the most it draws — a third
would repeat a colour, and it refuses rather than putting two structures on
one plate in the same colour.

Pair it with `score_against_reference` rather than using it alone: the overlay
shows *where* the design and the reference differ, DockQ says how much. One
without the other is a picture with no number, or a number with no picture.

## Figures

Prefer `export_artifact`: it asks before overwriting the image or any sidecar
and always saves the canonical recipe and provenance sidecar. `export_figure`
and `list_blocks` remain expert operations when every export option has already
been decided. Ask for the
target width if a journal is in mind; single- and double-column differ enough
to matter. Every export carries an agent-provenance record — say so rather than
letting the user find it. In the expert surface, `list_blocks` gives the named
selections (`mc1_ifaceA` and the rest) if you want to colour one part yourself.

For an agent-driven figure, call `render_preview` after `compose_figure` and
before `export_artifact`. Inspect whether the subject is cropped, the intended
interface is visible, labels overlap, or a colour key is unreadable. If the
preview is unavailable or ambiguous, say that visual review could not be
completed; do not claim the figure passed self-check. Use another tested figure
goal when a different composition is needed — never invent an arbitrary
ChimeraX command sequence.

## Report numbers at the precision they were measured to

Analysis tools retain full floats in their existing fields and under `raw`,
and provide deterministic prose values under `display`. Use `display` in the
answer; use `raw` when exact data or reproducibility details are requested.
The display contract writes buried area to the nearest Å², ΔG to two decimals,
*K*d in scientific notation to two, and distances to one. "Buried area:
937.5757528846134 Å²" claims a precision no surface calculation has and reads
as though nobody looked at it.

## Never

- Report a number without its criterion and cutoff.
- Present a refused metric as if it were merely absent.
- Compute a metric yourself from raw coordinates when a tool exists for it.
- Claim a predicted interface is real on the strength of one score.
- Say a figure was produced when only the view was styled.
