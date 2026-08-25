import pytest


def test_the_panels_metric_whitelist_matches_the_command_layer():
    """They drifted, and the panel raised on every click of a button it drew.

    pLDDT moved into the panel's metric row while this list still read
    ("ddg", "dsasa"), so the button existed, was enabled on predicted
    structures, and raised ValueError from the panel's own command builder
    before a command was ever issued.
    """
    from src.commands import COLOR_METRICS as COMMAND_METRICS
    from src.ui.tool import COLOR_METRICS as PANEL_METRICS

    assert set(PANEL_METRICS) == set(COMMAND_METRICS)


def test_every_panel_metric_builds_a_command():
    from src.ui.tool import COLOR_METRICS, color_by_command

    for metric in COLOR_METRICS:
        assert color_by_command("#1", metric) == f"molcompose color by {metric} model #1"


def test_scope_reaches_only_the_metric_that_can_use_it():
    """pLDDT and B-factor are whole-model by nature; the keyword is rejected.

    ΔΔG is the one metric with a genuine choice — the loaded data is usually
    whole-chain while the question is usually about the interface — so it is
    the only one that carries a scope onto the command line.
    """
    from src.ui.tool import color_by_command

    assert color_by_command("#1", "ddg", "all").endswith(" scope all")
    assert "scope" not in color_by_command("#1", "ddg")
    # A whole-model metric does not gain a keyword it cannot honour.
    assert "scope" not in color_by_command("#1", "bfactor", "all")


def test_an_unknown_scope_is_refused():
    from src.ui.tool import color_by_command

    with pytest.raises(ValueError, match="scope must be interface or all"):
        color_by_command("#1", "ddg", "everywhere")


def test_every_metric_has_a_label_and_a_uniform_result_shape():
    """Two bugs, one place, twice — so the drift is asserted rather than hoped.

    Adding pLDDT made the panel read `.low` off a ConfidenceReport and raise
    AttributeError. Adding B-factor made it read `.low` off a plain tuple and
    raise again, and its label conditional silently called a B-factor map
    "buried area". Both were the same failure: a metric added without the code
    that reports the result being told.
    """
    from src.commands import COLOR_METRICS as COMMAND_METRICS
    from src.ui.tool import METRIC_LABELS

    assert set(METRIC_LABELS) == set(COMMAND_METRICS)
    assert all(METRIC_LABELS[m] for m in COMMAND_METRICS)


def test_the_bfactor_result_carries_the_attributes_the_panel_reads():
    """The panel reads `.low` and `.high` off every non-pLDDT metric."""
    from src.commands import BFactorRange

    span = BFactorRange(6.2, 38.0, 69.9)
    assert (span.low, span.high) == (6.2, 69.9)
    # Still a tuple, so anything unpacking it keeps working.
    low, middle, high = span
    assert (low, middle, high) == (6.2, 38.0, 69.9)
