"""No argument may end one ChimeraX command and begin another.

The bridge splits on `;`. Verified against ChimeraX 1.12: sending
`version; open 1crn` runs both, and the second opens a model. So a value
spliced into a command line unquoted *is* a command line, whatever the
signature calls it — and it bypasses run_native's whitelist entirely, since
these tools do not go through run_native at all.

Most arguments were already safe: chain identifiers, model specifiers,
criteria, presets and statistics are checked against closed sets or patterns,
and paths are quoted (a path containing `;` becomes a file with `;` in its
name, which is inert). `format`, `source` and `chains` were not.
"""

import pytest
from molcompose_mcp import server as S
from molcompose_mcp.validate import InvalidArgument

#: Each ends the current command and starts another under ChimeraX's parser.
PAYLOADS = ("A; open 1crn", "A\nopen 1crn", "A\ropen 1crn", "; close session")


@pytest.mark.parametrize("payload", PAYLOADS)
def test_chain_groups_reject_a_second_command(payload):
    with pytest.raises((InvalidArgument, ValueError)):
        S.build_interface_command([payload], ["D"], None, 4.5, "heavy")
    with pytest.raises((InvalidArgument, ValueError)):
        S.build_interface_command(["A"], [payload], None, 4.5, "heavy")


@pytest.mark.parametrize("payload", PAYLOADS)
def test_the_enumerated_arguments_reject_a_second_command(payload):
    with pytest.raises((InvalidArgument, ValueError)):
        S.build_interface_command(["A"], ["D"], None, 4.5, payload)      # criterion
    with pytest.raises((InvalidArgument, ValueError)):
        S.build_interface_command(["A"], ["D"], payload, 4.5, "heavy")   # model
    with pytest.raises((InvalidArgument, ValueError)):
        S.build_style_command(payload, None, None, None, None, None)     # preset
    with pytest.raises((InvalidArgument, ValueError)):
        S.one_of(payload, S.REPORT_FORMATS, "format")
    with pytest.raises((InvalidArgument, ValueError)):
        S.one_of(payload, S.DDG_FORMATS, "format")


@pytest.mark.parametrize("payload", PAYLOADS)
def test_the_free_form_arguments_reject_a_second_command(payload):
    """`source` and `chains` are not closed sets, and were interpolated raw.

    `source` is the provenance label the panel passes; `chains` maps a
    GROMACS file's chain letters onto the structure's. Neither could be an
    enum, and neither was checked.
    """
    with pytest.raises(InvalidArgument):
        S.token(payload, "source")
    with pytest.raises(InvalidArgument):
        S.validate_chain_map(payload, "chains")


@pytest.mark.parametrize("payload", PAYLOADS)
def test_a_path_carrying_a_separator_stays_a_path(payload):
    """Quoted, so `;` inside it is a character in a filename and inert.

    Checked against real ChimeraX: exporting to "/tmp/mc; close all.png"
    wrote a file with that name and left every model open.
    """
    command = S.build_export_command(
        f"/tmp/{payload}.png", None, None, None, None, None, None, None, None
    )
    assert command.count('"') >= 2
    quoted = command.split('"')[1]
    # Whatever survives quoting is inside the quotes, and newlines do not
    # survive at all — quote_path turns them into spaces, since a command line
    # is one line and a path that spans two would break out of it.
    assert "\n" not in command and "\r" not in command
    assert ";" not in command.replace(quoted, "")


def test_the_legitimate_values_still_pass():
    """A guard that also refuses correct input is a different bug."""
    assert S.one_of("md", S.REPORT_FORMATS, "format") == "md"
    assert S.one_of("pythia-ppi", S.DDG_FORMATS, "format") == "pythia-ppi"
    assert S.token("agent:codex", "source") == "agent:codex"
    assert S.validate_chain_map("A:A,B:D", "chains") == "A:A,B:D"
    # `heavy` is the default and is left off the command rather than restated.
    built = S.build_interface_command(["A"], ["D"], "#1", 4.5, "heavy")
    assert built == "molcompose interface A D model #1 distance 4.5"
    assert "criterion cbeta" in S.build_interface_command(["A"], ["D"], "#1", 4.5, "cbeta")
