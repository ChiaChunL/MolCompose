# case-derf7-binder2/

Der f 7–binder2 is the designed-binder case reported in the MolCompose
Application Note. `DerF7_b2.pdb` is the BindCraft authors' deposited model
from https://doi.org/10.5281/zenodo.14249738, used here as an external input.
The structural comparison uses PDB 9HAE.

- `inputs/` — design PDB, sequences, 9HAE CIF, selected AF3 model and matching
  confidence/summary JSONs.
- `prediction/af3-template-free/` — native AF3 inputs, all 15 candidate sets,
  native ranking and corrected derived summary. Selection used the maximum
  native ranking score: seed 2066, sample 2, score 0.8560384195236908.
- `md/` — run1 configuration and original analysis outputs, using 20–100 ns
  of a 100-ns trajectory. No across-run averages are included.
- `source_data/` — the full Pythia-PPI scan and numeric source tables,
  including the 42-residue table with maximum ΔΔG and the corresponding mutant.
- `derived/` — numerical MolCompose results checked against these inputs.
- `recipes/` — portable MolCompose analysis and molecular-rendering commands.
- `DerF7_b2.csv`, `pythia_ppi_results.xlsx` — original Pythia-PPI export files.

The selected AF3 CIF and native confidence files are unchanged. The derived
summary reports pDockQ2 = 0.7399037639795328. Design and AF3 DockQ values
against 9HAE are 0.9014969620 and 0.9212407050. The design interface has
53 contact pairs and 42 residues. Run1 mean interface Cα RMSF is 1.134238 Å;
the MM/GBSA and MM/PBSA total estimates are −82.87 and −76.22 kcal/mol.
See the source-data and MD READMEs for units, mappings and definitions.

## Replay

With MolCompose installed, use a **new, empty ChimeraX session**:

```text
open /path/to/case-derf7-binder2/recipes/reproduce_analysis.py
```

Reports go into a new `outputs/analysis-*` directory. This imports existing
results; it does not rerun MD or AF3. The analysis was tested with ChimeraX
1.12 and MolCompose 0.1.3 source.

To render individual molecular panels in a new graphical session:

```text
open /path/to/case-derf7-binder2/recipes/render_structure_panels.py
```

The templates use run1 for RMSF/PB decomposition and compare only with 9HAE.
They reset the disposable session and write to a unique output directory.
The portable wrapper was statically checked in this refresh, not rerun
graphically. Final manual Figure 1 composition is outside its scope.
No Figure S1 image or plotting script is included.

## Scope and terms

This package contains configurations and analysis outputs, not the raw MD
trajectory, full topology/checkpoint set, prediction databases or AF3 weights.
It supports inspection, reimport and presentation of the reported results,
not a self-contained rerun of all simulations and predictions.

AF3 outputs and substantially derived metrics/views retain the original
`AF3_OUTPUT_TERMS_OF_USE.md`; see `AF3_LEGALLY_BINDING_TERMS.txt` and `NOTICE.md`.
`LICENSE-CODE.txt` applies to MolCompose code, not to all third-party data.
Original native files and terms are unchanged. `manifest.tsv` and
`SHA256SUMS.txt` provide file-level integrity checks.
