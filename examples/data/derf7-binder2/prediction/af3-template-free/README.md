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

`af3-selection-summary.json` and `af3_prediction_summary.tsv` summarize the
selection and the confidence metrics, and `molcompose-af3-analysis.json` holds
the MolCompose 0.1.3 results. The reference comparison uses
`../../inputs/9HAE.cif` with chain map `A:A,B:B`.

| Metric | Value |
| --- | ---: |
| pDockQ2 | 0.740 |
| ipSAE | 0.696 |
| LIS | 0.536 |
| Mean pLDDT | 88.4 |
| Interface pLDDT | 91.8 |

pLDDT is on the 0–100 scale and averaged per residue from heavy-atom B factors;
interface pLDDT uses the 4.5 Å heavy-atom interface. pDockQ2 uses its own 8 Å
Cβ interface (Cα for glycine) and a PAE scale of 10 Å. Full-precision values
are in the JSON files.

SHA-256 of the selected files in `output/derf7_binder2_template_free/`:

| File | SHA-256 |
| --- | --- |
| `derf7_binder2_template_free_model.cif` | `438483cdf83ddc8ac277e866b28d412468900516e5ca63451208dad0ad95f4e2` |
| `derf7_binder2_template_free_confidences.json` (includes PAE) | `ba9b9cf4d59949f5f1c43369d14795b53d4af5bf69515f71dfb3d947411ee46f` |
| `derf7_binder2_template_free_summary_confidences.json` | `873f51a25ffcda0301bf4addc0a8c1974eb35ac9666b58a8eea3769138203910` |

AF3 outputs and material derived from them are subject to the AF3 terms in
`output/derf7_binder2_template_free/TERMS_OF_USE.md`; the MolCompose code
licence does not apply to them.
