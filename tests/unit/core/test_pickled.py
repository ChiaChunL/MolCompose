"""Reading arrays out of a prediction pickle without running what is in it."""

import pickle

import pytest

from src.core.pickled import UnsafePickle, load_arrays


class _CallsOut:
    """A pickle that runs a command when loaded, which is the normal case.

    Not a contrived attack: `__reduce__` is how pickle stores any object it
    cannot represent structurally, so a file that wants to run something looks
    exactly like a file that wants to rebuild an object. That is why the
    loader decides by name before looking anything up.
    """

    def __reduce__(self):
        import os

        return (os.system, ("true",))


def test_a_pickle_that_wants_to_run_something_is_refused(tmp_path):
    path = tmp_path / "evil.pkl"
    path.write_bytes(pickle.dumps(_CallsOut()))
    with pytest.raises(UnsafePickle, match="does not contain"):
        load_arrays(path)


def test_numpy_arrays_come_back(tmp_path):
    numpy = pytest.importorskip("numpy")
    path = tmp_path / "result.pkl"
    written = {"predicted_aligned_error": numpy.zeros((4, 4)), "iptm": numpy.float32(0.5)}
    path.write_bytes(pickle.dumps(written))
    read = load_arrays(path)
    assert read["predicted_aligned_error"].shape == (4, 4)
    assert float(read["iptm"]) == pytest.approx(0.5)


def test_a_pickle_holding_something_other_than_a_mapping_is_refused(tmp_path):
    path = tmp_path / "list.pkl"
    path.write_bytes(pickle.dumps([1, 2, 3]))
    with pytest.raises(ValueError, match="not the mapping"):
        load_arrays(path)
