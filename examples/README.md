# MolCompose examples

Two cases live here, each small enough to clone and run in a couple of minutes:

- [`data/1brs/`](data/1brs/) — a worked tour of every import, on the
  barnase–barstar complex (PDB [1BRS](https://www.rcsb.org/structure/1BRS),
  chains A and D), with the files each analysis needs and nothing else.
- [`data/derf7-binder2/`](data/derf7-binder2/) — the Der f 7–binder2 case
  analysed in the MolCompose application note, as archived on Zenodo. See
  [its quick start](#manuscript-case) below.

The full dataset — three complexes, six prediction engines each, the
Pythia saturation scans, the MD trajectories' derived results — is archived on
Zenodo rather than kept here. It is data, it does not change when the code
does, and most of it is far larger than a repository should carry.

> **Full example dataset (all versions):** <https://doi.org/10.5281/zenodo.22047283>

<a id="quick-start"></a>

## Quick start: 1BRS

Run these from the repository root in a windowed ChimeraX session. Replace
`#1` if ChimeraX assigns a different model ID.

### Interface, and colouring by predicted ΔΔG

```chimerax
open examples/data/1brs/pythia_ppi_input.pdb
molcompose interface A D model #1
molcompose ddg examples/data/1brs/pythia_ppi_ddg.csv model #1 format pythia-ppi statistic max top 10 interfaceOnly true
molcompose color by ddg model #1
```

`statistic max` ranks the most binding-disruptive substitution at each
residue. A positive Pythia-PPI ΔΔG means the mutation weakens binding; `min`
asks the different question of which substitution is most stabilising.

### MM/PBSA decomposition and RMSF, on the MD structure

Load these onto the *repaired* structure, not the Pythia input: MD repair
fills in missing residues, and everything after the first gap is renumbered.
The decomposition file carries both GB and PB results, so name which one.

```chimerax
open examples/data/1brs/1brs_AD_repaired.pdb
molcompose interface A D model #1
molcompose energy examples/data/1brs/FINAL_DECOMP_MMPBSA.dat chains A:A,B:D model #1 solvation gb
molcompose color by energy model #1
```

```chimerax
molcompose flexibility examples/data/1brs/rmsf_complex_CA.xvg model #1
molcompose color by flexibility model #1
```

### A prediction, read where the engine left it

Point MolCompose at the model file. The confidence and PAE files AlphaFold 3
wrote beside it share its long stem, so they are found by name — nothing to
rename, convert, or point at separately.

```chimerax
open examples/data/1brs/predictions/af3/1brs_barnase_barstar_seed-1030_sample-2_model.cif
molcompose characterise A D model #1
```

The chains are A and D as in the deposited entry, but the residues are
renumbered from 1, which is why the Pythia and MD files above will refuse to
load onto this model. That refusal is the point: see the table below.

## Matching a result to its structure

These files inherit the chain IDs and residue numbering of the structure that
produced them. Prediction models are often renumbered from 1, so loading an
experimental Pythia file onto a predicted model may correctly fail with "only
4% of its residues match". Do not edit the raw files to force a match.

| Result | Correct structure |
|---|---|
| Pythia-PPI ΔΔG | `pythia_ppi_input.pdb`, or the repaired PDB |
| MM/PBSA and RMSF | `1brs_AD_repaired.pdb` |
| Prediction PAE and confidence | the prediction model beside them |

## What each file is

| File | Stage | Meaning and correct use |
|---|---|---|
| `pythia_ppi_input.pdb` | prepared input | The two biological partner chains, protein `ATOM` records only, with source chain IDs and residue numbering kept. This is the exact structure submitted to Pythia-PPI. |
| `pythia_ppi_ddg.csv` | Pythia result | Full-precision binding ΔΔG saturation scan. The canonical file for `molcompose ddg`. |
| `1brs_AD_repaired.pdb` | MD mapping structure | Repaired heavy-atom structure the trajectory was built from. RMSF and MM/PBSA use its numbering. |
| `FINAL_DECOMP_MMPBSA.dat` | MD result | Per-residue MM/PBSA decomposition, `idecomp = 2`, both GB and PB. Keep the original basename — the summary beside it is found by name. |
| `FINAL_RESULTS_MMPBSA.dat` | MD result | Overall binding-energy summary written by `gmx_MMPBSA`, discovered beside the decomposition. |
| `rmsf_complex_CA.xvg` | MD result | Per-residue Cα RMSF from the fitted trajectory. Residue indexing restarts for each chain. |
| `chain_map.json` | provenance | Source PDB hash, selected chains, interface groups, prediction chain order, and the GROMACS-to-source chain mapping. |
| `af3_input.fasta` | prediction input | The two submitted sequences, with their source chain IDs. |
| `af3_job.json` | prediction input | The AlphaFold 3 task JSON, exactly as submitted. |
| `predictions/af3/` | prediction result | One AlphaFold 3 sample as the server wrote it — model, PAE and per-atom confidence, whole-complex and chain-pair ipTM/pTM. Nothing here has been renamed, which is what makes the companion-file discovery worth demonstrating. |

The Zenodo record holds the same roles for all three complexes, plus the
AlphaFold 2 Multimer, Boltz-2, Chai-1, ColabFold and Protenix outputs, the
remaining AlphaFold 3 seeds and samples, the deposited reference structures,
the MD start and end frames, and the repair reports. Its own README documents
how each was produced — engine versions, seeds, force field and MD protocol,
and the `gmx_MMPBSA` settings.

> <https://doi.org/10.5281/zenodo.22047283>

<a id="manuscript-case"></a>

## The Der f 7–binder2 case

The case analysed in the application note: the BindCraft authors' deposited
design `DerF7_b2.pdb`, compared with the crystal structure PDB
[9HAE](https://www.rcsb.org/structure/9HAE) and with a local, template-free
AlphaFold 3 prediction. Chain A is Der f 7 and chain B is binder2 in every
file. The directory holds the data and scripts of
`molcompose-case-derf7-binder2-0.1.3.tar.gz` from Zenodo, with its READMEs
written for the repository and without the two spreadsheet exports of the
Pythia-PPI scan, which `source_data/pythia_ppi_all_mutations.csv` already
holds. Its [README](data/derf7-binder2/README.md) covers each file, the AF3
model selection and the MD protocol.

### Replay the MolCompose analysis

Use ChimeraX 1.12 with MolCompose 0.1.3 installed. In a new, empty ChimeraX
session, from the repository root:

```chimerax
open examples/data/derf7-binder2/recipes/reproduce_analysis.py
```

This replays MolCompose analysis on the archived inputs and writes JSON reports
to a new `outputs/analysis-*` folder inside the case directory. It imports the
saved prediction and MD results; it does not rerun AlphaFold 3, MD or Pythia-PPI.
Run the script inside ChimeraX, not with standalone Python.

To render the eight molecular panels, use another new, empty **graphical**
ChimeraX session, from the repository root:

```text
open examples/data/derf7-binder2/recipes/render_structure_panels.py
```

Rendering resets the disposable session between panels and writes to a new
`outputs/structure-panels-*` folder. It does not assemble the final Figure 1 layout.

To verify all case files, run this in a terminal:

```bash
cd /path/to/MolCompose/examples/data/derf7-binder2
shasum -a 256 -c SHA256SUMS.txt
```

### Or step by step

The same commands, as the recipe issues them. Open the three structures first,
so the design is `#1`, 9HAE is `#2` and the AF3 model is `#3`.

```chimerax
open examples/data/derf7-binder2/inputs/DerF7_b2.pdb
open examples/data/derf7-binder2/inputs/9HAE.cif
open examples/data/derf7-binder2/inputs/derf7_binder2_template_free_model.cif
molcompose characterise A B model #1 distance 4.5 criterion heavy style false
molcompose dockq #2 model #1 chainMap A:A,B:B
```

Pythia-PPI ΔΔG, MD flexibility and MM/PBSA decomposition all map onto the
design (`#1`), whose numbering they share:

```chimerax
molcompose ddg examples/data/derf7-binder2/source_data/pythia_ppi_all_mutations.csv model #1 format pythia-ppi statistic max top 15 interfaceOnly true
molcompose flexibility examples/data/derf7-binder2/md/results/rmsf-rep1.xvg model #1 chains A,B
molcompose energy examples/data/derf7-binder2/md/results/decomp-rep1.dat model #1 chains A:A,B:B top 10 solvation pb
```

For the AF3 model (`#3`), the recipe names its PAE and summary files
explicitly:

```chimerax
molcompose characterise A B model #3 distance 4.5 criterion heavy style false paeFile examples/data/derf7-binder2/inputs/derf7_binder2_template_free_confidences.json summaryFile examples/data/derf7-binder2/inputs/derf7_binder2_template_free_summary_confidences.json
molcompose ipsae examples/data/derf7-binder2/inputs/derf7_binder2_template_free_confidences.json model #3 predictor alphafold3 summaryFile examples/data/derf7-binder2/inputs/derf7_binder2_template_free_summary_confidences.json
molcompose dockq #2 model #3 chainMap A:A,B:B
```

The AF3 files carry AlphaFold 3's own output terms, which also cover metrics
derived from them; see `NOTICE.md` in the case directory.

> **Archived copy (all versions):** <https://doi.org/10.5281/zenodo.22047283>
