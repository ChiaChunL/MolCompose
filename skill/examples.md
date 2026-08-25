# Worked exchanges

Six requests and what a correct response looks like. Each shows the tool
sequence, the judgement the skill adds, and what a wrong answer would have
looked like.

---

## 1. What is this interface made of?

> Open 1BRS and characterise the interface between chains A and D.

```
open_structure(path_or_id="1brs")
characterise_interface(group_a=["A"], group_b=["D"])
```

Report the residue counts with their criterion, not on their own: *19 and 16
residues at a 4.5 Å heavy-atom cutoff, 43 contacting pairs, 1129 Å² buried,
predicted ΔG −10.63 kcal/mol.*

Then read the `skipped` block aloud. Here it names the confidence scores,
because 1BRS is a crystal structure. Say so. A user who is not told will assume
the model was simply not confident.

**Wrong answer:** quoting 19 and 16 without the cutoff. The same interface is
25 and 21 residues at the 5.5 Å cutoff the affinity model uses, and both
numbers appear in the output.

---

## 2. Which residue matters most?

> Which single residue is most important at this interface?

One call is not enough, and this is the case that proves it.

```
rank_hotspots(model="#1")                 # buried area
analyze_interactions(model="#1")          # chemistry
load_ddg(path="pythia_ppi_ddg.csv")       # energetics, if the user has it
```

The three rank differently. On barnase–barstar, Arg87 is 36th of 48 by buried
area at 3.7 Å² and second by predicted ΔΔG, because a salt bridge contributes
electrostatically without burying much.

Answer with the disagreement, not around it: *by buried area, Arg59; by
predicted ΔΔG, His102 then Arg87; interaction typing puts Arg87 in the triple
salt bridge holding Asp39. The three metrics answer different questions, and
Arg87 is the residue a burial-only ranking would miss.*

**Wrong answer:** picking whichever metric was computed first and calling it
*the* most important residue.

---

## 3. Can I trust this predicted complex?

> I have an AlphaFold model of this complex. Is the interface real?

```
open_structure(path_or_id="model.cif")
check_capabilities(model="#1")            # is a PAE file present?
compute_ipsae(model="#1")
get_confidence(model="#1")
```

If `check_capabilities` reports no PAE file, stop and ask for the predictor's
confidence JSON. Do not answer from pLDDT: it describes local geometry, not
whether two chains belong together.

With scores in hand, report several and name the engine. One number does not
settle it. A constructed non-binder has scored interface pTM 0.73–0.83 from one
predictor and 0.26–0.49 from another on the same input, and the first is above
the 0.7 that is often read as credible.

**Wrong answer:** *ipTM is 0.8, so the complex is real.*

---

## 4. Did my designed binder land on the epitope?

> Here is my designed binder against the target. Does it bind where I intended?

```
detect_interface(group_a=["A"], group_b=["B"])
```

The interface comes back as an explicit residue list. Compare it with the
epitope, functional site or active site the design targeted, and answer in
those terms: *the predicted interface covers 9 of the 12 epitope residues and
adds 4 outside it.*

Confidence scores do not answer this question. A model can be confident and
still be in the wrong place.

**Wrong answer:** reporting ipSAE and leaving the user to work out whether the
site is correct.

---

## 5. How close is the model to the crystal structure?

> Score my prediction against the deposited structure.

```
score_against_reference(model="#1", reference="#2")
```

If DockQ comes back near zero, do not report a failed prediction yet. Check the
interface residue lists first. Predictors number residues sequentially and
depositions often do not; a chymotrypsin-numbered reference against a
sequentially numbered model scores 0.031 while the model is in fact accurate.

Say which structure was the reference. Fnat is the fraction of the
*reference's* contacts recovered, so the score is not symmetric.

**Wrong answer:** *DockQ 0.03, the prediction is incorrect.*

---

## 6. Make me a figure

> Make a publication figure of this interface.

```
apply_style(preset="interface-focus")
focus(target="interface")
export_figure(path="interface.png", width=2400, height=1800, supersample=3)
```

Ask the target width before exporting if the user has a journal in mind;
single-column and double-column differ enough that a figure sized wrong is
remade rather than rescaled.

Tell the user the export carries a command recipe and an agent-provenance record.
They should learn that from you, not from opening the file.

---

## When to stop and ask

- The user names a metric the structure cannot support. Explain why it is
  refused rather than finding a substitute.
- A cutoff is not stated and the answer depends on it.
- A reference structure is needed and none is loaded.
- The result contradicts what the user expects. Say so plainly, and give the
  criterion that produced it, before they build on it.

## 7. Read what an MD run says

> I ran a simulation of this complex. Which residues actually contribute?

```
load_energy(path="FINAL_DECOMP_MMPBSA.dat", chains="A:A,B:D")
rank_hotspots(metric="energy")
```

The chain map is not optional and must not be guessed: GROMACS renames chains
when it builds a system, so a decomposition of 1BRS arrives as A and B where
the structure has A and D. Ask the user which is which if the file's labels do
not obviously match. Load it onto the structure the simulation ran on — the
repaired PDB, not the deposited entry.

Report with the sign convention attached, because it is the opposite of ΔΔG's:
*Asp39 contributes −10.30 ± 0.45 kcal/mol, the most of any residue; negative is
favourable here.*

The overall MM/PBSA total is printed for reference. It is not the interface's
ΔG — no entropy term, and it moves with the dielectric — so do not put it
beside PRODIGY's number as though they were the same quantity.

`load_flexibility(path="rmsf.xvg", chains="A,D")` adds how much each residue
moves. Chains in the order the selection was written, because `gmx rmsf -res`
restarts its numbering at each one. Movement is not contribution: a mobile
residue may be a loop far from the interface.
