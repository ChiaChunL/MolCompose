"""The REST client's flattening of a ChimeraX log into agent-readable text."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "mcp"))

from molcompose_mcp.chimerax import log_text, unlink  # noqa: E402

# One pseudobond exactly as ChimeraX logs it: the command echoed twice, first
# with only the verb linked to its help page, then whole inside a cxcmd href.
# Copied from a recorded session rather than written by hand — the wrapping,
# including the hyphen ChimeraX inserts mid-token, is what the parser meets.
LOGGED_PBOND = """[pbond](help:user/commands/pbond.html) /A:27@NZ|/D:38@NE1 name mc-cation-pi
color #4A9BB5 dashes 4 radius 0.18 showDist false reveal true

[pbond /A:27@NZ|/D:38@NE1 name mc-cation-pi color #4A9BB5 dashes 4 radius 0.18
showDist false reveal true](cxcmd:pbond /A:27@NZ|/D:38@NE1 name mc-cation-pi
color #4A9BB5 dashes 4 radius 0.18 showDist false reveal true)"""


def test_the_duplicated_echo_collapses_to_one_command():
    result = unlink(LOGGED_PBOND)
    assert result.count("mc-cation-pi") == 1
    assert result.startswith("pbond /A:27@NZ|/D:38@NE1 name mc-cation-pi")


def test_no_link_syntax_survives():
    result = unlink(LOGGED_PBOND)
    assert "cxcmd:" not in result
    assert "help:user" not in result
    assert "](" not in result


def test_the_command_itself_is_never_lost():
    """Stripping markup must not strip content: an agent may replay these."""
    for fragment in ("/A:27@NZ|/D:38@NE1", "color #4A9BB5", "radius 0.18", "reveal true"):
        assert fragment in unlink(LOGGED_PBOND)


def test_plain_text_is_returned_unchanged():
    plain = "Group A: 19 residues, Group B: 16 residues, 43 contact pairs"
    assert unlink(plain) == plain


def test_two_different_commands_are_both_kept():
    """Only exact repeats are dropped — never a second, similar command."""
    text = (
        "[pbond](help:user/commands/pbond.html) /A:1@N name mc-salt-bridge\n\n"
        "[pbond](help:user/commands/pbond.html) /A:2@N name mc-salt-bridge"
    )
    assert unlink(text).count("pbond") == 2


def test_a_repeat_wrapped_differently_is_still_a_repeat():
    """The case that survived the first version of this function.

    ChimeraX wraps each copy to the panel width independently and hyphenates
    an over-long token to do it, so the same pbond reached the agent twice:
    once as ``mc-pi-\\nstacking`` and once as ``mc-pi-stacking``.
    """
    text = (
        "[pbond](help:user/commands/pbond.html) /A:102@CD2|/D:29@CE1 name mc-pi-\n"
        "stacking color #7B68A6 dashes 4\n\n"
        "[pbond /A:102@CD2|/D:29@CE1 name mc-pi-stacking color #7B68A6 dashes\n"
        "4](cxcmd:pbond /A:102@CD2|/D:29@CE1 name mc-pi-stacking color #7B68A6 dashes 4)"
    )
    assert unlink(text).count("/A:102@CD2") == 1


def test_a_repeat_that_is_not_adjacent_is_kept():
    """Identical commands separated by other output are two real events."""
    text = "color red\n\nselect /A\n\ncolor red"
    assert unlink(text).count("color red") == 2


def test_log_text_flattens_every_level_and_unlinks():
    payload = {
        "log messages": {
            "note": ["[pbond](help:user/commands/pbond.html) /A:1@N\n"],
            "warning": ["chain B has no atoms\n"],
            "error": [],
        }
    }
    result = log_text(payload)
    assert "pbond /A:1@N" in result
    assert "chain B has no atoms" in result
    assert "help:" not in result


def test_a_non_json_reply_passes_through():
    assert log_text({"raw": "plain text reply"}) == "plain text reply"


def test_an_error_payload_reaches_the_agent():
    payload = {"log messages": {}, "error": {"type": "UserError", "message": "no interface"}}
    assert "no interface" in log_text(payload)


@pytest.mark.parametrize("blank", ["", "\n\n", "   \n  \n"])
def test_empty_logs_do_not_raise(blank):
    assert unlink(blank) == ""
