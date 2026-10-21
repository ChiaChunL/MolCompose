# Source data for the Der f 7–binder2 case

CSV/TSV files are unchanged copies of the recorded source datasets, except
`reference_agreement_9HAE.tsv`, which retains the two 9HAE comparison rows
from the original reference-agreement table without changing their values.
Chain A is Der f 7 (positions 1–196); chain B is binder2 (positions 1–87).
`position` is a one-based, chain-local residue number. Energies are kcal/mol;
distances/RMSF are Å; solvent-accessible surface-area differences are Å².
Column names retain the original plotting contract.

| File | Rows (excluding header) | Content and use |
| --- | ---: | --- |
| `Table_S1_with_mutations.tsv` | 42 | Current Table S1 source, with the mutant producing each Pythia maximum. |
| `Table_S1_R1.tsv` | 42 | Original numeric Table S1 and Figure S1C input; all its fields are identical in the extended table. |
| `source_S1A_R1_rmsf.tsv` | 283 | Figure S1A: chain, position, global `residue_index`, and `rmsf_A`. |
| `source_energy_R1_GB_PB.tsv` | 42 | Interface residue identity and `gb_rep1_kcal_mol` / `pb_rep1_kcal_mol`; Figure S1C values. |
| `R1_total_energy_estimates.tsv` | 2 | Method, run identifier, 401 frames, 20–100 ns window, and total binding-energy estimate. |
| `source_contact_53_pairs.tsv` | 53 | Contacting residue pairs at a minimum non-hydrogen atom distance ≤4.5 Å. |
| `source_contact_all_residue_pairs.tsv` | 17,052 | All 196 × 87 cross-chain residue pairs, minimum distances, and binary `contact` values. |
| `source_contact_matrix.tsv` | 21 | Figure S1B: a 21 × 21 binary matrix; A residues in rows and B residues in columns. |
| `design_dsasa.tsv` | 51 | Original design-complex residue ΔSASA export. This source list is broader than the 42 contact-interface residues. |
| `pythia_ppi_all_mutations.csv` | 5,377 | Complete existing Pythia-PPI scan: 283 residues × 19 non-wild-type substitutions. |
| `reference_agreement_9HAE.tsv` | 2 | Design and AF3 comparisons with 9HAE; filtered from the frozen reference-agreement table. |

The 42 table residues (21 on each chain) are the residue union of the 53
static contact pairs. The contact-list columns `chain_a`, `residue_a`,
`residue_name_a`, `chain_b`, `residue_b`, and `residue_name_b` identify a pair;
`minimum_heavy_atom_distance_A` is its minimum atom distance and `contact`
is 0 or 1 at the 4.5 Å cutoff. The matrix labels have the form `A:V45` and
`B:Y34`.

In Table S1, `residue` is a three-letter wild-type amino-acid code;
`interaction_types` preserves the original assigned interaction categories
(including `none`); `dsasa_A2` is the recorded residue ΔSASA of the design
complex. `pythia_ddg_max_kcal_mol` is the largest recorded prediction among
the 19 substitutions at that residue. `pythia_mutant_at_max` supplies its
one-letter mutant, `pythia_substitution_at_max` gives the full substitution
(for example, `B:L22P`), and `pythia_display` gives the value rounded to three
decimals followed by that mutant in parentheses. Values are retained with
their original signs and precision. Maxima are unique for all 42 residues;
the highest is B:L22P, 6.017086982727051 kcal/mol.

The full scan columns are `Mutation`, `Chain`, `Position`, and `DDG`.
`Mutation` encodes `wildtype_chain_position_mutant`, for example `D_A_1_C`.
There are 798 scan entries mapping to the 42 interface residues. The complete
5,377-row file is preserved, including all entries outside that interface;
it has not been replaced by a selected or filtered scan.

The MD columns `gb_rep1_kcal_mol`, `pb_rep1_kcal_mol`, and `rmsf_rep1_A`
refer only to run1. RMSF is Cα RMSF from the 20–100 ns analysis window of the
100 ns trajectory. `residue_index` uses A:1–196 followed by B:1–87 (global
index = 196 + B position). The raw XVG instead restarts its residue numbers
at 1 for chain B; its 283 rows are mapped in chain A then chain B order.
Raw nm values were multiplied by 10 to obtain Å.
The 42-residue arithmetic mean is 1.134238 Å, displayed as 1.13 Å. Energy
values match the GB/PB `DELTAS` total-residue averages in
`../md/results/decomp-rep1.dat`; whole-complex binding estimates −82.87 (GB)
and −76.22 (PB) are from `../md/results/results-rep1.dat`. These totals are
separate from the displayed 42-residue subset. See `../md/README.md` for
simulation settings and the limits of MD rerun reproducibility.

Provenance: the seven R1/contact TSVs were copied from the frozen
`supplementary-font-update-20260907/source_data` dataset. The extended table
was copied from `supplement-pythia-update-20260908/Table_S1_with_mutations.tsv`;
its added fields identify the already recorded Pythia maxima. The original
scan and ΔSASA table were copied from `internal/cases/derf7-binder2/source_data`
and also match the copies in the original `zenodo-0.1.2` case staging. The
raw MD files come from that original staging. Only run1 is included here;
other runs remain in the original local archive. No across-run averages,
standard-deviation tables, or modified scientific values are introduced.
The reference-agreement extract is from the frozen figure-pipeline case
`reference_agreement.tsv`; its two retained rows were also confirmed by
rerunning MolCompose on the bundled structures.
