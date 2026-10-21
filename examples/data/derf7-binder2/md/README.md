# Der f 7–binder2: MD parameters and analysis outputs

This directory holds the parameter files and analysis outputs of run 1, one of
three independently seeded 100-ns simulations of the design complex and the
run reported in Table S1 and Figure S1. Runs 2 and 3 are not included. File
names use the identifiers `rep1` and `replicate-1` for this run.

The starting structure is the design complex, with chain A (Der f 7) residues
1–196 and chain B (binder2) residues 1–87. The system uses AMBER99SB-ILDN and
TIP3P water in a dodecahedral box with 1.0 nm solute clearance, neutralized and
brought to 0.15 M NaCl, at 300 K and 1 bar. The `.mdp` files specify
steepest-descent minimization (up to 50,000 steps), 100 ps of restrained NVT
with velocity seed **20260821**, 1 ns of restrained NPT, and **100 ns** of
production with a 2 fs time step. Coordinates were saved every 10 ps.

Analyses use the **20–100 ns** window. `rmsf-rep1.xvg` is the per-residue Cα
RMSF after PBC correction and Cα alignment, in nm (multiply by 10 for Å). Its
residue column runs 1–196 for chain A, then restarts at 1–87 for chain B; the
source tables use a global `residue_index` with B residues at 197–283
(`global = 196 + B position`). The mean over the 42 interface residues is
1.13 Å.

`mmpbsa.in` specifies GB and PB calculations with `idecomp=2` decomposition
for residues within 6 Å of the partner. Frames 1–8001 of the 20–100 ns
trajectory at interval 20 give **401 frames**, 200 ps apart. The gmx_MMPBSA
1.6.5 outputs are `results-rep1.dat` and `decomp-rep1.dat`. The total binding
energy estimates are −82.87 kcal/mol (GB) and −76.22 kcal/mol (PB).
Per-residue values are the `DELTAS` → `Total Energy Decomposition` → `TOTAL`
averages, for GB and PB separately; the SD and SEM columns describe frame
statistics within the run.

Paths in the output headers refer to the original compute environment.
Trajectories, TPR files and full topologies are not included. MM/GBSA and
MM/PBSA totals are end-state estimates, not experimental binding free energies.
