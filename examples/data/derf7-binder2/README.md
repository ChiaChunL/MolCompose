# Der f 7–binder2 case

Der f 7–binder2 is the designed-binder case analysed in the MolCompose
application note. `DerF7_b2.pdb` is the BindCraft design deposited by its
authors at https://doi.org/10.5281/zenodo.14249738; the experimental reference
is PDB 9HAE. Chain A is Der f 7 and chain B is binder2 throughout.

> **Archived copy (all versions):** <https://doi.org/10.5281/zenodo.22047283>,
> file `molcompose-case-derf7-binder2-0.1.3.tar.gz`. The same data are in the
> MolCompose repository under `examples/data/derf7-binder2/`.

- `inputs/` — design PDB, sequences, 9HAE, and the selected AF3 model with its
  confidence and summary files.
- `prediction/af3-template-free/` — the AF3 input and all 15 candidate models
  with their native ranking. The selected model is seed 2066, sample 2.
- `md/` — MD parameter files, and the RMSF and gmx_MMPBSA outputs of run 1.
- `source_data/` — the full Pythia-PPI scan and the tables behind Table S1 and
  Figure S1.
- `derived/` — MolCompose results computed from these inputs.
- `recipes/` — scripts that replay the analysis and render the structure panels.

Against 9HAE, the design and the AF3 model reach DockQ 0.901 and 0.921. The
design interface has 53 contact pairs between 42 residues; their mean Cα RMSF
in run 1 is 1.13 Å. The MM/GBSA and MM/PBSA totals are −82.87 and
−76.22 kcal/mol. Units, residue mappings and definitions are in the
`source_data/` and `md/` READMEs.

## Quick start

With ChimeraX 1.12 and MolCompose 0.1.3, open a **new, empty ChimeraX session**.
From the root of the MolCompose repository:

```text
open examples/data/derf7-binder2/recipes/reproduce_analysis.py
```

From the unpacked Zenodo archive, use its directory instead:

```text
open /path/to/case-derf7-binder2/recipes/reproduce_analysis.py
```

Reports go into a new `outputs/analysis-*` directory. The script imports the
saved prediction and MD results rather than rerunning AF3 or MD.

To render the molecular panels of Figure 1, use a new graphical session:

```text
open examples/data/derf7-binder2/recipes/render_structure_panels.py
```

The panels use run 1 for RMSF and MM/PBSA and 9HAE as the reference. The script
resets the session between panels and writes to a new output directory.

For the analyses one command at a time, see `examples/README.md`.

## Scope and terms

MD trajectories, full topologies and AF3 model weights are not included.

AF3 outputs, and metrics and views derived from them, are subject to the
AlphaFold 3 output terms in `AF3_OUTPUT_TERMS_OF_USE.md` and
`AF3_LEGALLY_BINDING_TERMS.txt`; see `NOTICE.md`. `LICENSE-CODE.txt`
(BSD-3-Clause) covers the MolCompose scripts. `SHA256SUMS.txt` and
`manifest.tsv` give a checksum for every file.
