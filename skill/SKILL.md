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

## Start with one call

`characterise_interface` runs the whole battery in one pass: interface
detection, typed contacts, buried area, ΔG and *K*d, hot spots, and confidence
where it applies.

**Prefer it over calling six tools yourself.** Agents given a free choice
reliably run too few analyses and stop early. The single call is the fix, not a
convenience.

It also *styles the view*, which is not the same as producing a figure: no file
is written until you call `export_figure`. Do not tell the user a figure exists
until one does.

Fall back to individual tools when a first result raises a second question —
whether a top-ranked residue forms a salt bridge, whether a contact survives a
stricter cutoff, how an external ΔΔG prediction scores that position.

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

## Cutoffs are not interchangeable

Detection defaults to heavy atoms at 4.5 Å. PRODIGY counts contacts at 5.5 Å,
and pDockQ is defined at Cβ 8 Å — both measure their own, whatever is on
screen. All three appear in output. **Always state the criterion and cutoff
with the number**, because 19+16 residues and 25+21 residues are the same
interface measured two ways.

## Data the user brings

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

When the design has a solved or predicted structure to be checked against,
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

`export_figure` writes the file and records the command recipe. Ask for the
target width if a journal is in mind; single- and double-column differ enough
to matter. Every export carries an agent-provenance record — say so rather than
letting the user find it. `list_blocks` gives the named selections
(`mc1_ifaceA` and the rest) if you want to colour one part yourself.

## Report numbers at the precision they were measured to

The tools return full floats, because an API that rounds cannot be used for
anything else. Prose is not an API. Write buried area to the nearest Å², ΔG to
two decimals, *K*d in scientific notation to two, distances to one — which is
what MolCompose's own Log prints, so an answer and the Log agree instead of
disagreeing in the digits. "Buried area: 937.5757528846134 Å²" claims a
precision no surface calculation has and reads as though nobody looked at it.

## Never

- Report a number without its criterion and cutoff.
- Present a refused metric as if it were merely absent.
- Compute a metric yourself from raw coordinates when a tool exists for it.
- Claim a predicted interface is real on the strength of one score.
- Say a figure was produced when only the view was styled.
