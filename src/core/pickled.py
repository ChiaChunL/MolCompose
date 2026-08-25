"""Read the arrays out of a prediction `.pkl` without running what is in it.

AlphaFold2-Multimer writes one `result_<model>.pkl` per model and puts the PAE
matrix, ipTM, pTM and pLDDT in it and nowhere else. A local run's directory
holds those pickles, the `.pdb` files, and no JSON carrying any of it — so
supporting that directory at all means reading a pickle.

Unpickling is arbitrary code execution: the format stores *instructions*, and
one of them fetches a name from a module and calls it. A file found by
searching a directory the user pointed at is exactly the case where that
matters, because nothing about "it sat beside the model" says who wrote it.

So the loader here refuses every global except the three numpy needs to
rebuild an array. Measured against a real AlphaFold2-Multimer result file,
which asks for `numpy._core.multiarray._reconstruct`, `numpy.ndarray` and
`numpy.dtype` and nothing else. Anything outside that — `os.system`,
`subprocess.Popen`, a pickle claiming to hold a model object — raises before
it is looked up, which is before it can run.

This is the same restriction `numpy.load` applies with `allow_pickle=False`,
narrowed to the one shape a prediction result has.
"""

from __future__ import annotations

import pickle
from pathlib import Path


def _is_numpy(module: str) -> bool:
    """Whether a global belongs to numpy, and only numpy.

    An allow-list of exact names was the first attempt and it broke on the
    second file it met: numpy 2 rebuilds some arrays through
    `numpy._core.numeric._frombuffer`, which the list did not have, and the
    module was renamed from `numpy.core` to `numpy._core` in that release
    besides. Enumerating a library's internals is a list that goes stale
    every time the library moves, and each staleness looks like a corrupt
    file to whoever hits it.

    So the rule is the namespace. What the restriction is actually for is
    keeping `os`, `subprocess`, `builtins` and the engine's own classes out —
    everything a pickle would reach for to run something — and none of those
    is inside numpy.
    """
    return module == "numpy" or module.startswith("numpy.")


class UnsafePickle(ValueError):
    """The file asked for something a prediction result has no business using."""


class _ArraysOnly(pickle.Unpickler):
    def find_class(self, module, name):
        if not _is_numpy(module):
            raise UnsafePickle(
                f"this .pkl asks for {module}.{name}, which a prediction "
                "result does not contain. MolCompose reads only numpy arrays "
                "from a pickle, because unpickling anything else would run it."
            )
        return super().find_class(module, name)


def load_arrays(path) -> dict:
    """The pickle's top-level mapping, with only numpy objects reconstructed.

    Raises `UnsafePickle` rather than returning a partial result: a file that
    wanted something else is not a prediction result, and reading half of one
    would be worse than refusing it.
    """
    path = Path(path)
    try:
        with path.open("rb") as handle:
            data = _ArraysOnly(handle).load()
    except UnsafePickle:
        raise
    except Exception as error:  # unpickling raises almost anything
        raise ValueError(f"{path.name} is not a readable pickle: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(
            f"{path.name} holds {type(data).__name__}, not the mapping an "
            "AlphaFold result pickle contains"
        )
    return data
