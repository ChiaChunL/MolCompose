"""Residue correspondence between a model and a reference by sequence alignment.

A predicted complex and its experimental reference rarely agree on residue
numbering. Predictors emit sequential numbering from 1; depositors use whatever
convention the field settled on — chymotrypsinogen numbering for the serine
proteases (3SGB chain E runs 16-242 with insertion codes 192A/192B), Kabat or
IMGT for antibodies, and mmCIF carries both an author and a label scheme that
need not agree. Pairing residues by number across such a pair silently compares
unrelated residues: the geometry can be perfect and the score still near zero.

So the correspondence is established the way the official DockQ package
establishes it, by aligning the two chains' sequences and pairing the residues
that align. Numbering is then never consulted — a residue key is only ever a
label, and insertion codes need no special handling because they are carried
along inside the key rather than parsed.

The alignment is Needleman-Wunsch with free end gaps (a "semi-global"
alignment): internal gaps are penalised, because a missing loop is real
evidence about the correspondence, but leading and trailing gaps are free,
because a reference that lacks its first six disordered residues should still
align cleanly against a model that predicts them.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# Identity scoring on three-letter residue names. A substitution matrix would
# buy nothing here: the two sequences are the same protein, so the alignment is
# decided by where the gaps fall, not by how conservative a mismatch is.
MATCH = 2
MISMATCH = -1
GAP = -2

# Modified residues that are the standard amino acid for alignment purposes.
# Selenomethionine in particular is routine in experimental structures and must
# not read as a mismatch against the methionine a predictor emits.
CANONICAL = {
    "MSE": "MET",  # selenomethionine
    "SEC": "CYS",  # selenocysteine
    "PYL": "LYS",  # pyrrolysine
    "HYP": "PRO",  # hydroxyproline
    "PCA": "GLU",  # pyroglutamate
    "CSO": "CYS",  # oxidised cysteine
    "MLY": "LYS",  # methyllysine
    "SEP": "SER",  # phosphoserine
    "TPO": "THR",  # phosphothreonine
    "PTR": "TYR",  # phosphotyrosine
}


def canonical_name(name: str) -> str:
    """Three-letter residue name with common modifications folded to the parent."""
    return CANONICAL.get(name.upper(), name.upper())


@dataclass(frozen=True)
class ChainAlignment:
    """The residue correspondence found between one model chain and one reference chain."""

    model_chain: str
    reference_chain: str
    # (model key, reference key) for each aligned position, in sequence order.
    pairs: tuple[tuple[tuple, tuple], ...]
    identities: int
    model_length: int
    reference_length: int

    @property
    def aligned(self) -> int:
        return len(self.pairs)

    @property
    def identity(self) -> float:
        """Identical aligned residues over the shorter chain.

        Measured against the shorter chain rather than the alignment length so
        that a reference covering half the modelled construct still reads as a
        full-identity match, which is what a truncated construct is.
        """
        shorter = min(self.model_length, self.reference_length)
        return self.identities / shorter if shorter else 0.0


def align_sequences(
    model_sequence: Sequence[tuple], reference_sequence: Sequence[tuple]
) -> tuple[tuple[tuple, tuple], ...]:
    """Pair up two [(key, residue name), ...] sequences by semi-global alignment.

    Returns the aligned (model key, reference key) pairs in sequence order.
    Positions where one side has a gap are simply absent from the result.
    """
    n, m = len(model_sequence), len(reference_sequence)
    if n == 0 or m == 0:
        return ()

    model_names = [canonical_name(name) for _key, name in model_sequence]
    reference_names = [canonical_name(name) for _key, name in reference_sequence]

    # score[i][j] scores the best alignment of the first i model residues
    # against the first j reference residues. Row 0 and column 0 stay at zero,
    # which is what makes the leading end gaps free.
    score = [[0] * (m + 1) for _ in range(n + 1)]
    # 0 = diagonal (aligned pair), 1 = up (gap in reference), 2 = left (gap in model).
    step = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        step[i][0] = 1
    for j in range(1, m + 1):
        step[0][j] = 2

    for i in range(1, n + 1):
        row, previous = score[i], score[i - 1]
        step_row = step[i]
        name_i = model_names[i - 1]
        for j in range(1, m + 1):
            diagonal = previous[j - 1] + (
                MATCH if name_i == reference_names[j - 1] else MISMATCH
            )
            up = previous[j] + GAP
            left = row[j - 1] + GAP
            best = diagonal
            choice = 0
            if up > best:
                best, choice = up, 1
            if left > best:
                best, choice = left, 2
            row[j] = best
            step_row[j] = choice

    # Trailing end gaps are free too, so the traceback starts wherever the last
    # row or last column peaks rather than always at the bottom-right corner.
    i, j = n, m
    best = score[n][m]
    for candidate in range(m + 1):
        if score[n][candidate] > best:
            best, i, j = score[n][candidate], n, candidate
    for candidate in range(n + 1):
        if score[candidate][m] > best:
            best, i, j = score[candidate][m], candidate, m

    pairs = []
    while i > 0 and j > 0:
        choice = step[i][j]
        if choice == 0:
            pairs.append((model_sequence[i - 1][0], reference_sequence[j - 1][0]))
            i, j = i - 1, j - 1
        elif choice == 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return tuple(pairs)


def align_chain(
    model_sequence: Sequence[tuple],
    reference_sequence: Sequence[tuple],
    model_chain: str,
    reference_chain: str,
) -> ChainAlignment:
    """Align one model chain against one reference chain."""
    pairs = align_sequences(model_sequence, reference_sequence)
    model_names = {key: canonical_name(name) for key, name in model_sequence}
    reference_names = {key: canonical_name(name) for key, name in reference_sequence}
    identities = sum(
        1
        for model_key, reference_key in pairs
        if model_names[model_key] == reference_names[reference_key]
    )
    return ChainAlignment(
        model_chain=model_chain,
        reference_chain=reference_chain,
        pairs=pairs,
        identities=identities,
        model_length=len(model_sequence),
        reference_length=len(reference_sequence),
    )


def align_chains(
    model_sequences: dict, reference_sequences: dict, chain_pairs: Iterable[tuple[str, str]]
) -> tuple[ChainAlignment, ...]:
    """Align each (model chain, reference chain) pair, skipping any chain that is absent."""
    alignments = []
    for model_chain, reference_chain in chain_pairs:
        model_sequence = model_sequences.get(model_chain, ())
        reference_sequence = reference_sequences.get(reference_chain, ())
        if not model_sequence or not reference_sequence:
            continue
        alignments.append(
            align_chain(model_sequence, reference_sequence, model_chain, reference_chain)
        )
    return tuple(alignments)


def residue_mapping(alignments: Iterable[ChainAlignment]) -> dict:
    """{model residue key: reference residue key} over every aligned position."""
    mapping = {}
    for alignment in alignments:
        for model_key, reference_key in alignment.pairs:
            mapping[model_key] = reference_key
    return mapping


def relabel(residues: dict, mapping: dict) -> dict:
    """Rekey a model's {residue key: value} dict into the reference's key space.

    Residues with no aligned counterpart are dropped rather than carried over
    under their own key: keeping them would let a model residue collide with an
    unrelated reference residue that happens to share a number, which is the
    very failure this module exists to prevent.
    """
    return {
        mapping[key]: value for key, value in residues.items() if key in mapping
    }
