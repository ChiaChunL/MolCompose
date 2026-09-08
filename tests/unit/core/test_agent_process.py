import signal

import pytest

from src.core.agent_process import descendant_pids, terminate_process_tree
from src.core.agent_session import TurnLifecycle


def test_descendants_are_returned_deepest_child_first():
    rows = ((10, 1), (11, 10), (12, 10), (13, 11), (20, 1))
    assert descendant_pids(10, rows) == (13, 11, 12)


def test_descendants_tolerate_missing_root_and_cycles():
    assert descendant_pids(99, ((10, 1), (11, 10))) == ()
    assert descendant_pids(10, ((10, 11), (11, 10))) == (11,)


class _PsResult:
    stdout = "10 1\n11 10\n12 11\n"


def test_process_tree_gets_term_child_first_and_kill_only_for_survivors():
    calls = []
    alive = {10, 12}

    def send(pid, sig):
        calls.append((pid, sig))
        if sig == 0 and pid not in alive:
            raise ProcessLookupError

    terminate_process_tree(
        10,
        grace_seconds=0,
        runner=lambda *args, **kwargs: _PsResult(),
        send_signal=send,
        sleeper=lambda _seconds: None,
    )

    assert calls[:3] == [
        (12, signal.SIGTERM),
        (11, signal.SIGTERM),
        (10, signal.SIGTERM),
    ]
    assert (12, signal.SIGKILL) in calls
    assert (10, signal.SIGKILL) in calls
    assert (11, signal.SIGKILL) not in calls


def test_process_tree_treats_already_exited_processes_as_success():
    def missing(_pid, _sig):
        raise ProcessLookupError

    terminate_process_tree(
        999,
        grace_seconds=0,
        runner=lambda *args, **kwargs: type("Result", (), {"stdout": ""})(),
        send_signal=missing,
        sleeper=lambda _seconds: None,
    )


@pytest.mark.parametrize(
    "state", ["failed", "start_failed", "timed_out", "cancelled"]
)
def test_each_failure_path_cleans_once_and_allows_a_successful_retry(state):
    calls = []
    lifecycle = TurnLifecycle()

    lifecycle.begin(
        close_stdin=lambda: calls.append("stdin"),
        stop_timer=lambda: calls.append("timer"),
        cleanup=lambda: calls.append("cleanup"),
    )
    event = lifecycle.finish(state, "details")
    assert event.state == state
    assert event.detail == "details"
    assert calls == ["stdin", "timer", "cleanup"]
    assert lifecycle.finish(state) is None
    assert calls == ["stdin", "timer", "cleanup"]

    lifecycle.begin(cleanup=lambda: calls.append("retry cleanup"))
    retry = lifecycle.finish("succeeded")
    assert retry.state == "succeeded"
    assert calls[-1] == "retry cleanup"


def test_lifecycle_refuses_overlapping_turns():
    lifecycle = TurnLifecycle()
    lifecycle.begin()
    with pytest.raises(RuntimeError, match="already active"):
        lifecycle.begin()
