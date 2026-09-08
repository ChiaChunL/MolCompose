import json

import pytest

from src.core.report import (
    FORMATS,
    ReportData,
    as_dict,
    disclosure_text,
    methods_paragraph,
    render,
    render_csv,
    render_markdown,
)


def make_report(**overrides):
    base = dict(
        model_id="#1",
        model_name="1brs",
        chains_a=("A",),
        chains_b=("D",),
        criterion="heavy",
        cutoff=4.5,
        residues_a=19,
        residues_b=16,
        contact_pairs=43,
        interface_residues=(("A", "ARG A:59"), ("B", "ASP D:39")),
        interactions=(
            {
                "kind": "salt-bridge",
                "residue_a": "ARG A:59",
                "residue_b": "GLU D:76",
                "distance": 2.97,
                "detail": "NH1–OE1",
            },
        ),
        interaction_counts={"salt-bridge": 4, "hydrophobic": 2},
        buried_area=1129.4,
        affinity={"delta_g": -10.63, "kd": 1.6e-08, "temperature": 25.0},
        commands=("molcompose interface A D model #1", "molcompose affinity model #1"),
        software={"molcompose": "0.1.0", "chimerax": "1.12"},
    )
    base.update(overrides)
    return ReportData(**base)


def test_generated_at_is_filled_automatically():
    assert make_report().generated_at


def test_dict_form_carries_every_section():
    data = as_dict(make_report())
    assert data["model"]["id"] == "#1"
    assert data["interface"]["contact_pairs"] == 43
    assert data["interface"]["buried_area"] == pytest.approx(1129.4)
    assert data["interactions"]["counts"]["salt-bridge"] == 4
    assert data["affinity"]["delta_g"] == pytest.approx(-10.63)
    assert data["methods"]
    assert data["commands"][0].startswith("molcompose interface")


def test_methods_paragraph_states_the_actual_numbers():
    text = methods_paragraph(make_report())
    assert "MolCompose v0.1.0" in text
    assert "UCSF ChimeraX 1.12" in text
    assert "chains A and D" in text
    assert "heavy-atom" in text and "4.5 Å" in text
    assert "19 and 16 residues" in text
    assert "43 contacting residue pairs" in text
    assert "1129 Å²" in text
    assert "4 salt bridge" in text
    assert "-10.63 kcal/mol" in text
    assert "PRODIGY" in text


def test_methods_paragraph_describes_cbeta_criterion():
    text = methods_paragraph(make_report(criterion="cbeta", cutoff=8.0))
    assert "Cβ (Cα for glycine)" in text
    assert "8 Å" in text


def test_methods_paragraph_omits_absent_sections():
    text = methods_paragraph(
        make_report(buried_area=None, affinity=None, interaction_counts={})
    )
    assert "buries" not in text
    assert "PRODIGY" not in text
    assert "Typed non-covalent" not in text


def test_methods_paragraph_flags_predicted_models():
    text = methods_paragraph(
        make_report(
            confidence={"mean_plddt": 87.3, "iplddt": 85.1, "pdockq": 0.412}
        )
    )
    assert "mean pLDDT is 87.3" in text
    assert "interface pLDDT is 85.1" in text
    assert "pDockQ is 0.412" in text
    assert "predicted model" in text


def test_markdown_has_tables_methods_and_recipe():
    text = render_markdown(make_report())
    assert text.startswith("# Interface report — 1brs (#1)")
    assert "| Contacting residue pairs | 43 |" in text
    assert "| Buried surface area | 1129 Å² |" in text
    assert "| Predicted ΔG | -10.63 kcal/mol |" in text
    assert "## Typed interactions" in text
    assert "| salt-bridge | 4 |" in text
    assert "ARG A:59" in text
    assert "## Methods" in text
    assert "## Command recipe" in text
    assert "molcompose affinity model #1" in text


def test_csv_is_parseable_and_carries_sections():
    text = render_csv(make_report())
    rows = [line.split(",") for line in text.splitlines() if line]
    assert rows[0][:3] == ["section", "key", "value"]
    flat = text.replace('"', "")
    assert "interface,contact_pairs,43" in flat
    assert "interaction_counts,salt-bridge,4" in flat
    assert "affinity,delta_g,-10.63" in flat
    assert "salt-bridge" in flat


def test_json_round_trips():
    parsed = json.loads(render(make_report(), "json"))
    assert parsed["interface"]["residues_a"] == 19


@pytest.mark.parametrize("fmt", FORMATS)
def test_every_format_renders_non_empty_text(fmt):
    assert render(make_report(), fmt).strip()


def test_unknown_format_is_rejected():
    with pytest.raises(ValueError, match="report format must be"):
        render(make_report(), "pdf")


# -- provenance and disclosure ------------------------------------------------

AGENT_LOG = (
    {
        "command": "molcompose interface A D model #1",
        "timestamp": "2026-08-14T12:00:00+00:00",
        "source": "agent",
    },
    {
        "command": "molcompose affinity model #1",
        "timestamp": "2026-08-14T12:00:04+00:00",
        "source": "agent",
    },
)

USER_LOG = tuple(dict(entry, source="session") for entry in AGENT_LOG)


def test_markdown_carries_a_provenance_table():
    text = render_markdown(make_report(command_log=USER_LOG))
    assert "## Provenance" in text
    assert "| # | Command | Issued | Source |" in text
    assert "2026-08-14T12:00:04+00:00" in text
    assert "| session |" in text


def test_disclosure_states_agent_involvement_when_there_was_any():
    text = disclosure_text(make_report(command_log=AGENT_LOG))
    assert "molcompose-mcp agent interface" in text
    assert "large language model client" in text


def test_disclosure_does_not_invent_agent_involvement():
    """Claiming an AI was involved when none was is as wrong as hiding it."""
    text = disclosure_text(make_report(command_log=USER_LOG))
    assert "language model" not in text
    assert "agent interface" in text  # named, but as what did *not* happen
    assert "No command in this record was issued through" in text


def test_disclosure_does_not_claim_a_human_typed_it_either():
    """The sentence goes into a Methods section, so it must not overstate.

    It used to end "All commands were issued directly by the user", which
    MolCompose cannot know: ChimeraX's REST bridge carries no identity, so a
    command recorded as "session" was typed, scripted, or sent by a client that
    did not identify itself. Only the agent bridge declares a source, so the
    honest claim is that none declared one.
    """
    text = disclosure_text(make_report(command_log=USER_LOG))
    assert "directly by the user" not in text
    assert "identifies itself as its source" in text


def test_the_command_count_reads_as_a_sentence():
    """It appears verbatim in a Methods section, so "1 commands" will not do."""
    assert "(1 command)" in disclosure_text(make_report(commands=("molcompose reset",)))
    assert "(2 commands)" in disclosure_text(
        make_report(commands=("molcompose reset", "molcompose buriedarea"))
    )


def test_disclosure_names_the_canonical_recipe_as_session_scoped():
    text = disclosure_text(make_report(command_log=AGENT_LOG))
    assert "The canonical ChimeraX session recipe" in text
    assert "The complete command recipe" not in text
    assert "not limited to the current MCP connection" in text


def test_disclosure_survives_a_report_with_no_command_log():
    text = disclosure_text(make_report(command_log=()))
    assert "MolCompose" in text
    assert "language model" not in text


def test_an_empty_recipe_cannot_claim_to_reproduce_anything():
    """The sentence must not be able to lie about the record it sits in.

    A report whose recipe came out empty still printed "The complete command
    recipe (0 commands) is included in this record and reproduces every value
    reported here" over a fully populated analysis — a claim refuted by the
    same file, on the point the note is about. Whatever upstream fault empties
    the recipe, the sentence has to stay true of what was actually written.
    """
    text = disclosure_text(make_report(commands=(), command_log=()))
    assert "(0 commands)" not in text
    assert "reproduces every value reported here" not in text
    assert "No command recipe was recorded" in text
    # It must still say what produced the numbers.
    assert "MolCompose v0.1.0" in text
    assert "ChimeraX 1.12" in text


def test_an_empty_recipe_does_not_claim_the_user_issued_the_commands():
    """There are no commands to attribute, to a user or to an agent."""
    assert "issued directly by the user" not in disclosure_text(
        make_report(commands=(), command_log=())
    )
    assert "language model" not in disclosure_text(
        make_report(commands=(), command_log=AGENT_LOG)
    )


def test_json_exposes_the_provenance_block():
    payload = as_dict(make_report(command_log=AGENT_LOG))
    assert payload["provenance"]["command_log"] == list(AGENT_LOG)
    assert "disclosure_text" in payload["provenance"]
    # The replayable list stays separate from the annotated log.
    assert payload["commands"] == list(make_report().commands)


def test_a_named_client_still_counts_as_an_agent():
    """The disclosure must not fail closed when the bridge says which CLI it is.

    The bridge declared itself as exactly "agent" until it began naming the
    client — "agent:codex" — so that a session which used two of them could be
    told apart. Every `source == "agent"` test stopped matching. Here the
    consequence was not a missing feature but a false sentence: the report
    went on to state that no command was issued through the agent interface,
    in a paragraph written for direct inclusion in a Methods section.

    Nothing raised and nothing looked wrong. That is why this is a test rather
    than a comment.
    """
    from src.core.report import ReportData, disclosure_text, is_agent

    assert is_agent("agent")
    assert is_agent("agent:codex")
    assert is_agent("agent:claude")
    assert not is_agent("session")
    assert not is_agent("panel")
    assert not is_agent("server")
    # Not a prefix match on the bare word: a source that merely starts with
    # those letters is a different source.
    assert not is_agent("agentic-script")

    for source in ("agent", "agent:codex", "agent:claude"):
        data = ReportData(
            model_id="#1", model_name="1brs",
            chains_a=("A",), chains_b=("D",),
            residues_a=(), residues_b=(), contact_pairs=(),
            criterion="heavy", cutoff=4.5,
            commands=("molcompose interface A D model #1",),
            command_log=({"command": "molcompose interface A D model #1",
                          "timestamp": "2026-08-25T00:00:00+00:00",
                          "source": source},),
            software={"molcompose": "0.1.2", "chimerax": "1.12"},
        )
        text = disclosure_text(data)
        assert "were issued through the molcompose-mcp agent interface" in text, source
        assert "No command in this record was issued through" not in text, source
