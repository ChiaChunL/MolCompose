# Source data for the Der f 7–binder2 case

The tables behind Table S1, Figure S1 and the comparison with 9HAE. Chain A is
Der f 7 (positions 1–196) and chain B is binder2 (positions 1–87); `position`
is a one-based, chain-local residue number. Energies are in kcal/mol, distances
and RMSF in Å, and solvent-accessible surface-area differences in Å².

| File | Rows (excluding header) | Content |
| --- | ---: | --- |
| `Table_S1_with_mutations.tsv` | 42 | Table S1, including the mutant at each Pythia-PPI maximum. |
| `Table_S1_R1.tsv` | 42 | Table S1 without the mutant columns; the input to Figure S1C. |
| `source_S1A_R1_rmsf.tsv` | 283 | Figure S1A: chain, position, global `residue_index` and `rmsf_A`. |
| `source_energy_R1_GB_PB.tsv` | 42 | Figure S1C: per-residue `gb_rep1_kcal_mol` and `pb_rep1_kcal_mol`. |
| `R1_total_energy_estimates.tsv` | 2 | MM/GBSA and MM/PBSA totals, with run, frame count and time window. |
| `source_contact_53_pairs.tsv` | 53 | Residue pairs with a minimum non-hydrogen atom distance ≤4.5 Å. |
| `source_contact_all_residue_pairs.tsv` | 17,052 | All 196 × 87 cross-chain residue pairs, with minimum distance and `contact`. |
| `source_contact_matrix.tsv` | 21 | Figure S1B: 21 × 21 binary matrix, A residues in rows and B residues in columns. |
| `design_dsasa.tsv` | 51 | Per-residue ΔSASA of the design complex; includes all 42 residues of Table S1. |
| `pythia_ppi_all_mutations.csv` | 5,377 | The full Pythia-PPI scan: 283 residues × 19 substitutions. |
| `reference_agreement_9HAE.tsv` | 2 | Design and AF3 model compared with 9HAE. |

The 42 residues of Table S1 (21 on each chain) are those in the 53 contact
pairs. In the contact tables, `chain_a`, `residue_a`, `residue_name_a`,
`chain_b`, `residue_b` and `residue_name_b` identify a pair,
`minimum_heavy_atom_distance_A` is its minimum atom distance, and `contact` is
1 within the 4.5 Å cutoff. Matrix labels have the form `A:V45` and `B:Y34`.

In Table S1, `residue` is the three-letter wild-type code, `interaction_types`
lists the assigned interaction categories (or `none`), and `dsasa_A2` is the
residue ΔSASA in the design complex. `pythia_ddg_max_kcal_mol` is the largest
prediction among the 19 substitutions at the residue, `pythia_mutant_at_max`
its one-letter mutant, `pythia_substitution_at_max` the full substitution (for
example `B:L22P`), and `pythia_display` the value to three decimals with the
mutant in parentheses. The largest value is B:L22P, 6.017 kcal/mol.

The scan columns are `Mutation`, `Chain`, `Position` and `DDG`, with `Mutation`
written as `wildtype_chain_position_mutant` (for example `D_A_1_C`). Of the
5,377 entries, 798 fall on the 42 interface residues.

The MD columns `gb_rep1_kcal_mol`, `pb_rep1_kcal_mol` and `rmsf_rep1_A` come
from run 1, over the 20–100 ns window of the 100-ns trajectory. `residue_index`
numbers A:1–196 then B:1–87 (`global = 196 + B position`), and RMSF is
converted from nm to Å. The 42-residue mean RMSF is 1.13 Å. Per-residue
energies are the GB and PB `DELTAS` totals in `../md/results/decomp-rep1.dat`;
the whole-complex totals, −82.87 (GB) and −76.22 (PB) kcal/mol, are from
`../md/results/results-rep1.dat`. Simulation settings are in
`../md/README.md`.

The two rows of `reference_agreement_9HAE.tsv` are reproduced by running
MolCompose on the structures in `../inputs/`.
