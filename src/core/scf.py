"""Write Sequence Coloring Format files, so a colouring reaches the sequence.

SCF is what ChimeraX's Sequence Viewer reads to paint columns of an alignment.
It exists here for one reason: the same per-residue quantity that colours the
structure — interface membership, pLDDT, ΔΔG, buried area — is often easier to
read along the sequence, where "which stretch of chain carries this interface"
is a shape rather than a scatter of highlighted side chains.

The format, as ChimeraX's own parser accepts it
(`chimerax/seq_view/region_browser.py`, `load_scf_file`):

    pos1 pos2 seq1 seq2 r g b        # seven integers: a run of columns
    pos seq r g b                    # five: one column

* `pos` are **alignment column numbers**, 1-based and inclusive — *not* PDB
  residue numbers. Getting that wrong is the failure this module's caller has
  to avoid; see `sequence.chain_columns`.
* `seq` numbers sequences within the alignment, 1-based; 0 means every
  sequence, and -1 makes the parser skip the line.
* `r g b` are 0–255.
* A trailing `# text` names the region. The parser groups lines by
  `((r, g, b), comment)`, so lines sharing a colour *and* a comment become one
  named region — which is why the labels here are worth choosing: they are what
  the Sequence Viewer's region browser will list.

Two properties of that parser shape this writer:

1. **Never indent a line.** Line 791 reads `line.strip()` without assigning the
   result, so a comment with leading whitespace fails the `line[0] == '#'` test
   and is then parsed as data — "Bad format ... [not 5 or 7 integers]". Every
   line written here starts at column zero.
2. **Runs, not per-residue lines.** Consecutive columns sharing a colour and a
   label are emitted as one seven-integer line. A 400-residue chain becomes a
   handful of lines instead of 400, and the region browser lists bands rather
   than hundreds of one-column regions.
"""

from collections.abc import Iterable, Sequence


def rgb255(hex_color: str) -> tuple[int, int, int]:
    """`#RRGGBB` (or `RRGGBB`) to the integer triple SCF wants."""
    value = hex_color.lstrip("#").strip()
    if len(value) != 6:
        raise ValueError(f"not a six-digit hex colour: {hex_color!r}")
    try:
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError as error:
        raise ValueError(f"not a hex colour: {hex_color!r}") from error


def runs(entries: Iterable[tuple[int, str, str]]) -> list[tuple[int, int, str, str]]:
    """Merge consecutive columns sharing a colour and a label into runs.

    `entries` are `(column, hex_colour, label)`, in any order. Returns
    `(first_column, last_column, hex_colour, label)`, sorted by column.

    Consecutive means consecutive *columns*: a gap in the numbering ends the
    run, because the columns between were not given this colour and must not
    be swept into it. That is what makes a missing residue safe here — the
    caller simply never emits a column for it.
    """
    ordered = sorted(entries, key=lambda item: item[0])
    merged: list[list] = []
    for column, colour, label in ordered:
        if merged:
            previous = merged[-1]
            if (previous[1] == column - 1 and previous[2] == colour
                    and previous[3] == label):
                previous[1] = column
                continue
        merged.append([column, column, colour, label])
    return [tuple(run) for run in merged]


def scf_text(
    entries: Iterable[tuple[int, str, str]],
    header: Sequence[str] = (),
    sequence_index: int = 1,
) -> str:
    """A complete SCF file for one sequence of an alignment.

    `sequence_index` is 1-based; the default writes the colouring for the first
    sequence, which is what an alignment opened from a single chain contains.
    """
    if sequence_index < 1:
        raise ValueError("sequence index is 1-based")
    lines = [f"# {line}" for line in header]
    for first, last, colour, label in runs(entries):
        red, green, blue = rgb255(colour)
        line = (f"{first} {last} {sequence_index} {sequence_index} "
                f"{red} {green} {blue}")
        lines.append(f"{line}  # {label}" if label else line)
    return "\n".join(lines) + "\n"
