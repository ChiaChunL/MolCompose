# AlphaFold 3 template-free prediction: Der f 7–binder2

This directory preserves the AF3 input and complete native output for one
sequence-based reconstruction. Chain A has 196 residues and chain B has 87
residues (283 total). Both input proteins explicitly use `templates: []`.
The data pipeline generated MSAs, so this prediction still uses sequence
information and learned structural priors.

`input.json` and `input/derf7_binder2_af3.json` are identical native inputs.
`output/derf7_binder2_template_free/` contains the pipeline data JSON, all 15
candidate sets (model CIF, full confidence JSON and native summary JSON), the
ranking CSV, selected top-level files and original output terms. Each of seeds
318, 1030 and 2066 has five samples, indexed 0–4. The full confidence JSONs
contain 283 × 283 PAE matrices; the selected file also has 2,311 atom pLDDT
values.

Selection used the maximum native ranking score before reference comparison:
seed **2066**, sample **2**, score **0.8560384195236908**. The ranking CSV retains
this precision; native summary JSON stores the score as `0.86`. The selected
top-level CIF and seed-specific CIF differ only by a one-second model-group
timestamp. Their coordinates and confidence data are unchanged.

`af3-selection-summary.json` is a derived summary. Native AF3 confidence fields
are separate from MolCompose-derived metrics. `af3_prediction_summary.tsv`
preserves the precise frozen values, and `molcompose-af3-analysis.json` contains
the corresponding numerical results from MolCompose 0.1.3 / ChimeraX 1.12
validation. The current comparison uses only the experimental reference at
`../../inputs/9HAE.cif`, with chain mapping `A:A,B:B`; it did not select the AF3
candidate.

The corrected derived values include pDockQ2 **0.7399037639795328**, ipSAE
**0.6962484546205062**, LIS **0.5363920575994447**, mean residue pLDDT
**88.37743062093358** and interface pLDDT **91.83108235805167**. pLDDT is on the
0–100 scale and is averaged by residue from heavy-atom B factors. The reported
interface pLDDT uses the 4.5 Å heavy-atom interface. pDockQ2 uses its own 8 Å
C-beta interface (C-alpha fallback for glycine), whose mean residue pLDDT is
**91.15850101182643**. Its PAE scaling parameter is 10 Å. The JSON records the
ipSAE and LIS conventions and retains the tiny final-digit difference between
frozen and current pDockQ values in separate source records.

This replaces an earlier derived confidence summary and clarifies its metric
conventions. Native inputs, all native prediction outputs and their terms were
copied byte-for-byte. Runtime logs, container inspection and the private launch
script are outside this research-data package. This single case illustrates
analysis and reference comparison; it is not a structure-prediction benchmark.

SHA-256 for selected files under `output/derf7_binder2_template_free/`:

| File | SHA-256 |
| --- | --- |
| `derf7_binder2_template_free_model.cif` | `438483cdf83ddc8ac277e866b28d412468900516e5ca63451208dad0ad95f4e2` |
| `derf7_binder2_template_free_confidences.json` (includes PAE) | `ba9b9cf4d59949f5f1c43369d14795b53d4af5bf69515f71dfb3d947411ee46f` |
| `derf7_binder2_template_free_summary_confidences.json` | `873f51a25ffcda0301bf4addc0a8c1974eb35ac9666b58a8eea3769138203910` |

The original `output/derf7_binder2_template_free/TERMS_OF_USE.md` is preserved.
AF3 output and substantially derived material remain subject to the applicable
third-party terms; inclusion here does not relicense them under a package-level
license.
