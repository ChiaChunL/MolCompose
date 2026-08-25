# MolCompose examples

One worked case, small enough to clone and run in a couple of minutes: the
barnase–barstar complex (PDB [1BRS](https://www.rcsb.org/structure/1BRS),
chains A and D), with the files each analysis needs and nothing else.

The full dataset — three complexes, six prediction engines each, the Pythia
saturation scans, the MD trajectories' derived results — is archived on Zenodo
rather than kept here. It is data, it does not change when the code does, and
most of it is far larger than a repository should carry.

> **Full example dataset:** <https://doi.org/10.5281/zenodo.22047284>

## Quick start

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

> <https://doi.org/10.5281/zenodo.22047284>
