"""Map a structure's residues onto the alignment columns SCF talks in.

The one hazard this exists to remove: **a residue number is not a column
number**. SCF positions index the sequence as the Sequence Viewer lays it out,
1-based from the start of the chain's sequence, while a PDB residue number
starts wherever the depositor started it and skips whatever the crystal did not
resolve. 1BRS chain A starts at residue 3; 1ACB chain E starts at 16 and has
breaks at 13→16 and 146→149. Treating the residue number as a column shifts the
entire colouring — silently, since every line still parses.

ChimeraX gives the mapping directly: a `Chain` has `.characters` and
`.residues` of equal length, with `None` where the sequence has a residue the
structure does not. The index of a residue in `.residues`, plus one, is its
column.
"""


def chain_columns(chain) -> dict[tuple[str, int, str], int]:
    """`{(chain_id, residue_number, insertion_code): column}` for one chain.

    Missing residues contribute nothing, so a caller that colours "every
    residue in this chain" simply never names the columns the structure has no
    residue for — which is what the sequence should show.
    """
    columns: dict[tuple[str, int, str], int] = {}
    residues = getattr(chain, "residues", None)
    if residues is None:
        return columns
    for index, residue in enumerate(residues):
        if residue is None:
            continue
        chain_id = getattr(residue, "chain_id", None) or chain.chain_id
        insertion = (getattr(residue, "insertion_code", "") or "").strip()
        columns[(chain_id, int(residue.number), insertion)] = index + 1
    return columns


def model_columns(model) -> dict[str, dict[tuple[str, int, str], int]]:
    """`chain_id -> {residue key: column}` for every chain of a structure.

    One mapping per chain because SCF columns are per sequence: chain B's
    column 1 is its own first residue, not a continuation of chain A.
    """
    return {chain.chain_id: chain_columns(chain) for chain in model.chains}
