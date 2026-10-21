# Der f 7–binder2: run1 MD inputs and analysis outputs

This directory contains one MD result, run1 (R1), used for the supplementary
table and Figure S1. Filenames retain the historical `rep1` / `replicate-1`
identifiers. Other runs remain in the original local archive; this package
contains no across-run means or standard-deviation source tables.

The starting design complex has target chain A, residues 1–196, and binder
chain B, residues 1–87. The recorded setup uses AMBER99SB-ILDN, TIP3P water,
a dodecahedral box with 1.0 nm solute clearance, neutralization and 0.15 M
NaCl, 300 K and 1 bar. The included configuration files specify steepest
descent minimization (up to 50,000 steps), 100 ps restrained NVT with velocity
seed **20260821**, 1 ns restrained NPT, and **100 ns** production with a 2 fs
time step. Production coordinates were saved every 10 ps.

Analyses use the **20–100 ns** window. `rmsf-rep1.xvg` is the per-residue
Cα RMSF after PBC repair and Cα alignment. The raw XVG residue column runs
from 1–196 for chain A, then restarts at 1–87 for chain B. The source table's
derived global `residue_index` maps 1–196 to A:1–196 and 197–283 to B:1–87
(`global = 196 + B position`).
The raw RMSF unit is nm; multiply by 10 for Å (**0.1 nm = 1 Å**). The arithmetic
mean over the 42 static interface residues is 1.134238 Å, displayed as 1.13 Å.

`mmpbsa.in` specifies GB and PB calculations and `idecomp=2` decomposition
within 6 Å. For the extracted 20–100 ns trajectory, frames 1–8001 at interval
20 yield **401 energy frames** spaced 200 ps apart. The original
gmx_MMPBSA 1.6.5 outputs are `results-rep1.dat` and `decomp-rep1.dat`.
The total binding energy estimates are −82.87 kcal/mol (GB) and
−76.22 kcal/mol (PB). Per-residue source values use the `DELTAS` →
`Total Energy Decomposition` → `TOTAL` average, separately for GB and PB.
The SD/SEM fields retained in raw outputs describe within-run frame statistics.

All eight configuration/output files are byte-identical to their archived
originals. Historical executable, working-directory, topology and trajectory
paths in output headers are preserved as provenance; they are not portable
commands or references to files supplied here. This is a configuration and
analysis-output package. It does **not** include raw XTC trajectories, TPR
run inputs, or the complete topology/checkpoint set needed for a self-contained
MD rerun. The deposited source tables support inspection and figure
reproduction. These illustrative calculations are not experimental affinity
measurements.
