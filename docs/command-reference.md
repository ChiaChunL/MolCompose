# MolCompose command reference

Every `molcompose` command, its arguments and what it returns.

Arguments in **bold** are required; the rest are keywords with defaults. Every
command writes itself to the ChimeraX Log, so any analysis can be replayed.


26 commands.

| Command | Category | Arguments | Does |
|---|---|---|---|
| `molcompose` | Structure Analysis | — | List the MolCompose commands |
| `molcompose affinity` | Structure Analysis | model *object*, temperature *float* | Predict binding free energy and Kd (PRODIGY IC-NIS) |
| `molcompose blocks` | Structure Analysis | model *object* | List the four named parts of a characterised complex |
| `molcompose buriedarea` | Structure Analysis | model *object* | Buried surface area of the detected interface |
| `molcompose capabilities` | Structure Analysis | model *object*, predictor *string*, paeFile *string* | Report which analyses this structure supports |
| `molcompose characterise` | Structure Analysis | **group_a**, **group_b**, model *object*, distance *float*, criterion *string*, style *bool* | Run the full interface characterisation in one call |
| `molcompose color by` | Depiction | **metric**, model *object*, statistic *string*, scope *string* | Colour residues by a per-residue metric |
| `molcompose confidence` | Structure Analysis | model *object* | Report pLDDT, ipLDDT, and pDockQ for a predicted model |
| `molcompose contacts` | Structure Analysis | model *object*, off *bool* | Show close contacts across the detected interface |
| `molcompose ddg` | Structure Analysis | **path**, interfaceOnly *bool*, model *object*, format *string*, statistic *string*, top *int* | Load predicted mutation effects (ΔΔG) from a predictor |
| `molcompose dockq` | Structure Analysis | **reference**, model *object*, chainMap *string* | DockQ and CAPRI components against a reference complex |
| `molcompose energy` | Structure Analysis | **path**, chains *string*, model *object*, top *int*, solvation *string* | Load a per-residue MM/PBSA decomposition |
| `molcompose export` | Depiction | **path**, width *int*, height *int*, supersample *int*, transparent *bool*, saveSession *bool*, overwrite *bool*, dpi *int*, saveRecipe *bool*, keyFontSize *int* | Export a publication image, with print resolution, and optionally the session and command recipe |
| `molcompose flexibility` | Structure Analysis | **path**, chains *string*, model *object* | Load per-residue RMS fluctuation from a trajectory |
| `molcompose focus` | Depiction | target *string*, model *object* | Fit the view to a model or detected interface |
| `molcompose hbonds` | Structure Analysis | model *object*, off *bool* | Show hydrogen bonds across the detected interface |
| `molcompose hotspots` | Structure Analysis | metric *string*, model *object*, minArea *float*, top *int* | Rank interface residues by buried surface area |
| `molcompose interactions` | Structure Analysis | model *object*, types *string*, off *bool*, saltBridge *float*, hydrophobic *float*, piStacking *float*, cationPi *float* | Detect typed non-covalent interactions across the interface |
| `molcompose interface` | Structure Analysis | **group_a**, **group_b**, model *object*, distance *float*, criterion *string* | Detect an interface between two protein chain groups |
| `molcompose interface all` | Structure Analysis | model *object*, distance *float*, criterion *string* | Detect every contacting protein chain pair |
| `molcompose ipsae` | Structure Analysis | path *string*, model *object*, paeCutoff *float*, predictor *string* | ipSAE interface scores from a prediction PAE file |
| `molcompose report` | Structure Analysis | **path**, model *object*, format *string* | Write a complete interface characterization report |
| `molcompose reset` | Depiction | model *object* | Reset a model to the MolCompose neutral baseline |
| `molcompose seqcolor` | Structure Analysis | path *string*, model *object*, source *string*, statistic *string*, load *bool* | Export the per-residue colouring as SCF for the Sequence Viewer |
| `molcompose source` | Structure Analysis | **name** | Declare who issues the next command, for the recipe's source attribution |
| `molcompose style` | Depiction | **preset**, model *object*, labels *int*, rankBy *string*, references *string*, align *string*, partner *string* | Apply a versioned MolCompose visual preset |

## Reading the table

`model` defaults to the only open structure, or must be given when several are
open. Commands that need an interface will say so rather than guessing: run
`molcompose interface` first, or `molcompose characterise`, which runs the
whole battery and names anything it could not compute.

Nothing here needs network access, and no command estimates a metric whose
assumptions the structure does not satisfy — a confidence score asked of a
crystal structure is reported as skipped, by name.
