"""Run in a NEW empty ChimeraX session with MolCompose installed.

ChimeraX command: open /path/to/case-derf7-binder2/recipes/reproduce_analysis.py
This reads archived structures/results; it does not run prediction or MD.
"""
import dataclasses
import json
import tempfile
from pathlib import Path
from chimerax.core.commands import run, StringArg
from chimerax.core.errors import UserError

CASE = Path(__file__).resolve().parents[1]
if session.models.list():
    raise UserError('Please open this script in a new, empty ChimeraX session.')
output_root = CASE / 'outputs'
output_root.mkdir(exist_ok=True)
OUTPUT = Path(tempfile.mkdtemp(prefix='analysis-', dir=output_root))
results = {}

def quote(path):
    return StringArg.unparse(str(path))

def execute(label, command, record=True):
    result = run(session, command)
    if record:
        results[label] = result
    return result

def serialize(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if hasattr(value, 'tolist'):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f'Unsupported result type: {type(value).__name__}')

execute('design', 'open ' + quote(CASE / 'inputs/DerF7_b2.pdb'), False)
execute('reference', 'open ' + quote(CASE / 'inputs/9HAE.cif'), False)
execute('af3', 'open ' + quote(CASE / 'inputs/derf7_binder2_template_free_model.cif'), False)
execute('design_characterise', 'molcompose characterise A B model #1 distance 4.5 criterion heavy style false')
execute('design_dockq', 'molcompose dockq #2 model #1 chainMap A:A,B:B')
execute('design_ddg', 'molcompose ddg ' + quote(CASE / 'source_data/pythia_ppi_all_mutations.csv')
        + ' model #1 format pythia-ppi statistic max top 15 interfaceOnly true')
execute('design_rmsf', 'molcompose flexibility ' + quote(CASE / 'md/results/rmsf-rep1.xvg')
        + ' model #1 chains A,B')
for solvation in ['gb', 'pb']:
    execute('design_energy_' + solvation,
            'molcompose energy ' + quote(CASE / 'md/results/decomp-rep1.dat')
            + ' model #1 chains A:A,B:B top 10 solvation ' + solvation)
    execute('report_' + solvation, 'molcompose report ' + quote(OUTPUT / ('design_' + solvation + '.json'))
            + ' model #1 format json', False)
execute('af3_characterise', 'molcompose characterise A B model #3 distance 4.5 criterion heavy style false'
        + ' paeFile ' + quote(CASE / 'inputs/derf7_binder2_template_free_confidences.json')
        + ' summaryFile ' + quote(CASE / 'inputs/derf7_binder2_template_free_summary_confidences.json'))
execute('af3_confidence', 'molcompose confidence model #3')
execute('af3_ipsae', 'molcompose ipsae ' + quote(CASE / 'inputs/derf7_binder2_template_free_confidences.json')
        + ' model #3 predictor alphafold3 summaryFile '
        + quote(CASE / 'inputs/derf7_binder2_template_free_summary_confidences.json'))
execute('af3_dockq', 'molcompose dockq #2 model #3 chainMap A:A,B:B')
execute('report_af3', 'molcompose report ' + quote(OUTPUT / 'af3.json') + ' model #3 format json', False)
(OUTPUT / 'analysis-results.json').write_text(json.dumps(results, default=serialize, indent=2) + '\n')
session.logger.info('Reproduction outputs: ' + str(OUTPUT))
print('REPRODUCTION_OUTPUT ' + str(OUTPUT), flush=True)
