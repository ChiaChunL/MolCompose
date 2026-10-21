# AlphaFold 3 template-free prediction: Der f 7–binder2

The AF3 input and complete native output for the complex predicted from its two
sequences. Both chains use `templates: []`; the data pipeline generated MSAs as
usual. Chain A has 196 residues and chain B has 87 (283 in total).

`input.json` is the AF3 input, and `input/derf7_binder2_af3.json` is the same
file as submitted. `output/derf7_binder2_template_free/` contains the
data-pipeline JSON, the ranking CSV, the top-ranked files, AF3's
`TERMS_OF_USE.md`, and all 15 candidates: seeds 318, 1030 and 2066, samples
0–4, each with its model CIF, full confidence JSON (including the 283 × 283 PAE
matrix) and summary JSON.

The model was selected by AF3 ranking score alone, before any comparison with
9HAE: seed **2066**, sample **2**, score **0.856**. The ranking CSV gives the
score in full precision. The top-level CIF is this model; it differs from the
seed-specific copy only in a timestamp.

[af3-selection-summary.json](af3-selection-summary.json) and
[af3_prediction_summary.tsv](af3_prediction_summary.tsv) summarize the selection
and confidence metrics. [molcompose-af3-analysis.json](molcompose-af3-analysis.json)
holds the MolCompose 0.1.3 results. The reference comparison uses
[9HAE.cif](../../inputs/9HAE.cif) with chain map `A:A,B:B`.

pLDDT is on the 0–100 scale and averaged per residue from heavy-atom B factors;
interface pLDDT uses the 4.5 Å heavy-atom interface. pDockQ2 uses its own 8 Å
Cβ interface (Cα for glycine) and a PAE scale of 10 Å. Full-precision values
are in the JSON files.

File checksums are in [SHA256SUMS.txt](../../SHA256SUMS.txt).

AF3 outputs and material derived from them are subject to the AF3 terms in
[TERMS_OF_USE.md](output/derf7_binder2_template_free/TERMS_OF_USE.md); the MolCompose code
licence does not apply to them.
