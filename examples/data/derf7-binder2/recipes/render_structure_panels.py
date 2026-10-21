"""Open in a NEW empty graphical ChimeraX session with MolCompose installed.

Renders eight molecular panels to a unique directory; does not assemble Figure 1.
"""
import tempfile
from pathlib import Path
from chimerax.core.commands import run
from chimerax.core.errors import UserError

CASE = Path(__file__).resolve().parents[1]
if not session.ui.is_gui:
    raise UserError('Molecular rendering requires the graphical ChimeraX application.')
if session.models.list():
    raise UserError('Please use a new, empty ChimeraX session; panel recipes reset it.')
if any(char in str(CASE) for char in ['"', '\n', '\r']):
    raise UserError('Extract the data to a path without quotes or newline characters.')
output_root = CASE / 'outputs'
output_root.mkdir(exist_ok=True)
output = Path(tempfile.mkdtemp(prefix='structure-panels-', dir=output_root))
for template in sorted((CASE / 'recipes/structure-panels').glob('D*.cxc.in')):
    body = template.read_text().replace('@CASE@', str(CASE)).replace('@OUTPUT@', str(output))
    resolved = output / template.name.removesuffix('.in')
    resolved.write_text(body)
    for line in body.splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            run(session, line)
session.logger.info('Structure panels and resolved commands: ' + str(output))
