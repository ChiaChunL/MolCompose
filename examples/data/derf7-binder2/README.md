# Der f 7–binder2 case

Der f 7–binder2 is the designed-binder case analysed in the MolCompose
application note. `DerF7_b2.pdb` is the BindCraft design deposited by its
authors at https://doi.org/10.5281/zenodo.14249738; the experimental reference
is PDB 9HAE. Chain A is Der f 7 and chain B is binder2 throughout.

> **Archived copy (all versions):** <https://doi.org/10.5281/zenodo.22047283>,
> file `molcompose-case-derf7-binder2-0.1.3.tar.gz`.

- `inputs/` — design PDB, sequences, 9HAE, and the selected AF3 model with its
  confidence and summary files.
- `prediction/af3-template-free/` — the AF3 input and all 15 candidate models
  with their native ranking. The selected model is seed 2066, sample 2.
- `md/` — MD parameter files, and the RMSF and gmx_MMPBSA outputs of run 1.
- `source_data/` — the full Pythia-PPI scan and the tables behind Table S1 and
  Figure S1.
- `derived/` — MolCompose results computed from these inputs.
- `recipes/` — scripts that replay the analysis and render the structure panels.

See the [source-data guide](source_data/README.md) for units and residue mappings,
the [MD guide](md/README.md) for simulation settings, and the
[AF3 guide](prediction/af3-template-free/README.md) for model selection.

## Quick start

With ChimeraX 1.12 and MolCompose 0.1.3, open a **new, empty ChimeraX session**.
Run the script inside ChimeraX, not standalone Python. From the repository root:

```text
open examples/data/derf7-binder2/recipes/reproduce_analysis.py
```

From an unpacked Zenodo archive, replace the case path with its local directory.
Reports go into a new `outputs/analysis-*` directory inside the case. The script
imports saved results; it does not rerun AF3, MD or Pythia-PPI.

To render the molecular panels of Figure 1, use a new graphical session:

```text
open examples/data/derf7-binder2/recipes/render_structure_panels.py
```

The panels use run 1 for RMSF and MM/PBSA and 9HAE as the reference. Rendering
resets the session between panels and writes to `outputs/structure-panels-*`.
It does not assemble the final Figure 1 layout.

The [analysis script](recipes/reproduce_analysis.py) lists the individual
MolCompose commands. To verify the case files, run this in a terminal from the
case directory:

```bash
shasum -a 256 -c SHA256SUMS.txt
```

## Scope and terms

MD trajectories, full topologies and AF3 model weights are not included.

AF3 outputs, and metrics and views derived from them, are subject to the
AlphaFold 3 output terms in [AF3_OUTPUT_TERMS_OF_USE.md](AF3_OUTPUT_TERMS_OF_USE.md)
and [AF3_LEGALLY_BINDING_TERMS.txt](AF3_LEGALLY_BINDING_TERMS.txt); see
[NOTICE.md](NOTICE.md). [LICENSE-CODE.txt](LICENSE-CODE.txt) (BSD-3-Clause) covers
the MolCompose scripts. File inventories and checksums are in
[manifest.tsv](manifest.tsv) and [SHA256SUMS.txt](SHA256SUMS.txt).
