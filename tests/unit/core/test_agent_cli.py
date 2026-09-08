import json

import pytest

from src.core import agent_cli
from src.core.agent_cli import (
    AGENTS,
    ALLOWED_TOOL_PREFIX,
    SERVER_NAME,
    build_command,
    find_agents,
    get_agent,
    locate,
    mcp_config,
    readiness,
    write_mcp_config,
)


def test_known_agents_are_claude_and_codex():
    assert {agent.key for agent in AGENTS} == {"claude", "codex"}
    assert get_agent("claude").label == "Claude Code"
    with pytest.raises(ValueError, match="unknown agent CLI"):
        get_agent("bard")


def test_find_agents_reports_only_what_is_available():
    assert find_agents(which=lambda name: None, extra_dirs=()) == ()
    found = find_agents(
        which=lambda name: f"/opt/bin/{name}" if name == "claude" else None,
        extra_dirs=(),
    )
    assert len(found) == 1
    agent, resolved = found[0]
    assert agent.key == "claude" and resolved == "/opt/bin/claude"


def test_locate_falls_back_to_well_known_directories(tmp_path):
    # A Dock-launched macOS app has a minimal PATH, so `which` finds nothing.
    tool = tmp_path / "claude"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    assert locate("claude", which=lambda name: None, extra_dirs=()) is None
    assert locate("claude", which=lambda name: None, extra_dirs=(str(tmp_path),)) == str(tool)


def test_locate_prefers_path_when_available(tmp_path):
    assert locate(
        "claude", which=lambda name: "/from/path/claude", extra_dirs=(str(tmp_path),)
    ) == "/from/path/claude"


def test_agents_found_outside_path_are_run_by_full_path():
    agent = get_agent("codex")
    argv = build_command(
        agent,
        "hello",
        executable="/Users/me/.local/bin/codex",
        server_executable="/opt/bin/molcompose-mcp",
    )
    assert argv[0] == "/Users/me/.local/bin/codex"


def test_mcp_config_points_the_agent_at_this_session():
    config = mcp_config("/opt/bin/molcompose-mcp", "http://127.0.0.1:3100")
    server = config["mcpServers"][SERVER_NAME]
    assert server["command"] == "/opt/bin/molcompose-mcp"
    assert server["args"] == [
        "--chimerax-url", "http://127.0.0.1:3100",
        "--profile", "assistant",
    ]


def test_write_mcp_config_round_trips(tmp_path):
    target = tmp_path / "mcp.json"
    write_mcp_config(target, "/opt/bin/molcompose-mcp")
    assert json.loads(target.read_text())["mcpServers"][SERVER_NAME]["command"].endswith(
        "molcompose-mcp"
    )


def test_claude_takes_the_prompt_on_stdin_not_as_an_argument():
    agent = get_agent("claude")
    argv = build_command(agent, "show the A-D interface", "/tmp/mcp.json")
    assert argv[0] == "claude"
    assert "--print" in argv
    # --mcp-config accepts several files, so a trailing prompt would be read as
    # another config path; it must go on stdin instead.
    assert argv[-1] == "/tmp/mcp.json"
    assert "show the A-D interface" not in argv
    assert agent.prompt_via_stdin is True
    # Headless mode cannot prompt for tool permission, and the allow-list is
    # scoped to this server so the agent gets no other tools.
    assert argv[argv.index("--allowedTools") + 1] == ALLOWED_TOOL_PREFIX
    assert argv[argv.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert ALLOWED_TOOL_PREFIX == "mcp__molcompose"


def test_codex_takes_the_prompt_as_an_argument():
    assert get_agent("codex").prompt_via_stdin is False


class _ProcessInput:
    def __init__(self):
        self.writes = []
        self.close_count = 0

    def write(self, payload):
        self.writes.append(payload)

    def closeWriteChannel(self):  # noqa: N802 - Qt API spelling
        self.close_count += 1


def test_claude_writes_the_prompt_to_stdin_then_closes_it():
    process = _ProcessInput()

    agent_cli.finish_process_input(process, get_agent("claude"), "characterise it")

    assert process.writes == [b"characterise it"]
    assert process.close_count == 1


def test_codex_closes_stdin_without_writing():
    process = _ProcessInput()

    agent_cli.finish_process_input(process, get_agent("codex"), "characterise it")

    assert process.writes == []
    assert process.close_count == 1


def test_argument_driven_custom_agent_keeps_its_existing_stdin_protocol():
    process = _ProcessInput()

    agent_cli.finish_process_input(
        process,
        agent_cli.custom_agent("/opt/bin/another-agent", "run {prompt}"),
        "characterise it",
    )

    assert process.writes == []
    assert process.close_count == 0


def test_command_for_codex_binds_this_server_and_live_url_inline():
    argv = build_command(
        get_agent("codex"),
        "describe this interface",
        server_executable="/opt/homebrew/bin/molcompose-mcp",
        chimerax_url="http://127.0.0.1:3100",
    )

    assert "exec" in argv
    assert "--skip-git-repo-check" in argv
    assert 'mcp_servers.molcompose.default_tools_approval_mode="approve"' in argv
    assert (
        'mcp_servers.molcompose.command="/opt/homebrew/bin/molcompose-mcp"'
        in argv
    )
    assert (
        'mcp_servers.molcompose.args=["--chimerax-url","http://127.0.0.1:3100",'
        '"--profile","assistant"]'
        in argv
    )


def test_codex_requires_the_discovered_mcp_server():
    with pytest.raises(ValueError, match="molcompose-mcp executable"):
        build_command(get_agent("codex"), "describe this interface")


def test_codex_turn_is_bound_to_the_live_chimerax_session():
    argv = build_command(
        get_agent("codex"),
        "Characterise the interface and report the returned numbers.",
        server_executable="/opt/bin/molcompose-mcp",
    )
    effective_prompt = argv[-1]

    assert "molcompose MCP server" in effective_prompt
    assert "list_models" in effective_prompt
    assert "currently open ChimeraX session" in effective_prompt
    assert "Do not search the filesystem" in effective_prompt
    assert "Do not fetch" in effective_prompt
    assert effective_prompt.endswith(
        "Characterise the interface and report the returned numbers."
    )


def test_live_contract_uses_server_display_values_without_discarding_raw_precision():
    argv = build_command(
        get_agent("codex"),
        "Report the interface.",
        server_executable="/opt/bin/molcompose-mcp",
    )
    effective_prompt = argv[-1]

    assert "Use the returned `display` values in prose" in effective_prompt
    assert "preserve `raw` values" in effective_prompt
    assert "measured values exactly as" not in effective_prompt


def test_live_contract_keeps_default_interface_semantics_explicit():
    argv = build_command(
        get_agent("codex"),
        "Report the interface.",
        server_executable="/opt/bin/molcompose-mcp",
    )
    effective_prompt = argv[-1]

    assert "default heavy criterion and 4.5 Å cutoff" in effective_prompt
    assert "contacting residue pairs" in effective_prompt
    assert "Read and report the returned `skipped`" in effective_prompt
    assert "label it as an estimate" in effective_prompt


def test_live_contract_starts_with_the_assistant_session_handshake():
    argv = build_command(
        get_agent("codex"),
        "Report the interface.",
        server_executable="/opt/bin/molcompose-mcp",
    )

    assert "call inspect_session first" in argv[-1]
    assert "compatibility" in argv[-1]


def test_live_contract_does_not_let_codex_skip_figure_review():
    argv = build_command(
        get_agent("codex"),
        "Make and export a figure.",
        server_executable="/opt/bin/molcompose-mcp",
    )
    prompt = argv[-1]

    assert prompt.index("render_preview") < prompt.index("export_artifact")
    assert "cropped" in prompt
    assert "colour key" in prompt
    assert "cannot visually verify" in prompt


def test_claude_prompt_is_not_changed_by_the_codex_live_session_contract():
    process = _ProcessInput()

    agent_cli.finish_process_input(process, get_agent("claude"), "describe it")

    assert process.writes == [b"describe it"]


def test_codex_can_capture_the_final_answer_separately_from_run_details():
    argv = build_command(
        get_agent("codex"),
        "describe this interface",
        output_path="/tmp/molcompose-answer.md",
        server_executable="/opt/bin/molcompose-mcp",
    )

    assert argv[-3:] == [
        "--output-last-message",
        "/tmp/molcompose-answer.md",
        argv[-1],
    ]
    assert argv[-1].endswith("describe this interface")


def test_claude_keeps_its_existing_output_protocol_when_given_an_output_path():
    argv = build_command(
        get_agent("claude"),
        "describe this interface",
        "/tmp/mcp.json",
        output_path="/tmp/molcompose-answer.md",
    )

    assert "--output-last-message" not in argv
    assert "/tmp/molcompose-answer.md" not in argv


def test_command_rejects_an_empty_prompt():
    with pytest.raises(ValueError, match="prompt is empty"):
        build_command(get_agent("codex"), "   ")


def test_claude_requires_a_config_path():
    with pytest.raises(ValueError, match="needs an MCP config"):
        build_command(get_agent("claude"), "hello")


def test_readiness_names_the_first_missing_prerequisite():
    agents = ((get_agent("claude"), "/opt/bin/claude"),)
    assert "No agent CLI found" in readiness((), "/opt/bin/molcompose-mcp", True)
    assert "molcompose-mcp is not on PATH" in readiness(agents, None, True)
    assert "Start the agent bridge" in readiness(agents, "/opt/bin/molcompose-mcp", False)
    assert readiness(agents, "/opt/bin/molcompose-mcp", True) is None


def test_a_custom_agent_can_be_any_binary_the_user_points_at():
    """The two names this panel knows are not the two agents that exist.

    Someone using a third CLI — or one of these two installed where `locate`
    does not look — used to have no way in at all.
    """
    from src.core.agent_cli import custom_agent

    agent = custom_agent("/opt/tools/gemini", "--yolo")
    assert agent.executable == "/opt/tools/gemini"
    assert agent.label == "gemini"
    assert build_command(agent, "detect the interface") == [
        "/opt/tools/gemini", "--yolo", "detect the interface",
    ]


def test_a_custom_agent_gets_the_prompt_even_without_the_placeholder():
    """Omitting {prompt} is the likely mistake, and it fails silently.

    Without this the CLI is started with no question in it at all, which
    looks like the agent ignoring the user rather than a template typo.
    """
    from src.core.agent_cli import custom_agent

    assert build_command(custom_agent("/bin/agent", "chat"), "hello") == [
        "/bin/agent", "chat", "hello",
    ]
    # An explicit placeholder is honoured where it was put, not appended.
    assert build_command(custom_agent("/bin/agent", "run {prompt} --now"), "hi") == [
        "/bin/agent", "run", "hi", "--now",
    ]


def test_a_custom_agent_needs_a_config_only_when_its_template_asks_for_one():
    from src.core.agent_cli import custom_agent

    plain = custom_agent("/bin/agent", "chat")
    assert plain.supports_mcp_config is False
    build_command(plain, "hello")  # no config path required

    wired = custom_agent("/bin/agent", "--mcp-config {config}")
    assert wired.supports_mcp_config is True
    with pytest.raises(ValueError, match="needs an MCP config"):
        build_command(wired, "hello")


def test_the_interactive_command_drops_what_makes_the_panel_turn_safe():
    """The panel's turn and a terminal's session are different trades.

    --print cannot stop to ask whether a tool call is allowed, so the panel
    pre-approves the MolCompose tools and nothing else. A terminal can ask,
    so it gets neither the flag nor the allow-list — and stating that is the
    honest answer to "shouldn't it be interactive?", rather than adding a
    flag that would make the panel's own turns hang waiting for a prompt
    nobody can answer.
    """
    from src.core.agent_cli import interactive_command

    argv = interactive_command(get_agent("claude"), "/tmp/mcp.json", "/opt/bin/claude")
    assert argv == ["/opt/bin/claude", "--mcp-config", "/tmp/mcp.json"]
    assert "--print" not in argv
    assert ALLOWED_TOOL_PREFIX not in argv
    # Non-interactive turns keep both.
    turn = build_command(get_agent("claude"), "hi", "/tmp/mcp.json", "/opt/bin/claude")
    assert "--print" in turn and ALLOWED_TOOL_PREFIX in turn


def test_agents_without_an_interactive_form_say_so_instead_of_guessing():
    from src.core.agent_cli import interactive_command

    assert interactive_command(get_agent("codex"), "/tmp/mcp.json") is None


def test_the_config_says_which_client_will_be_issuing():
    """Two agents in one session recorded as one thing.

    The provenance record has three sources — session, panel, agent — so a
    session that used Claude Code and then Codex could not be told apart
    afterwards. The server cannot help: it is a stdio server and the client
    that launched it is its parent process. The panel launched it and knows
    which, so it writes the name into the config.

    The name is the CLI, not the model. Which model a CLI ran is inside that
    CLI, and recording a guess would be worse than recording the tool.
    """
    from src.core.agent_cli import mcp_config

    plain = mcp_config("molcompose-mcp", "http://127.0.0.1:3010")
    assert "--source" not in plain["mcpServers"]["molcompose"]["args"]

    named = mcp_config("molcompose-mcp", "http://127.0.0.1:3010", "agent:codex")
    args = named["mcpServers"]["molcompose"]["args"]
    assert args[-2:] == ["--source", "agent:codex"]
    assert args[2:4] == ["--profile", "assistant"]
    assert "http://127.0.0.1:3010" in args


def test_the_cli_that_ignores_the_config_file_is_told_as_well():
    """Codex takes the server on the command line, not from the config.

    Threading the source into `mcp_config` alone would have left Codex turns
    recorded as the generic "agent" while Claude Code turns named themselves —
    a record that looks complete and is wrong, which is worse than one that
    plainly says "agent" for both. The port has the same shape of problem:
    the panel knows which one the bridge answers on, and the inline arguments
    are the only place Codex can learn it.
    """
    from src.core.agent_cli import AGENTS, build_command

    codex = next(a for a in AGENTS if a.inline_mcp_config)
    argv = build_command(
        codex, "characterise the interface",
        config_path="/tmp/mcp.json",
        server_executable="/opt/bin/molcompose-mcp",
        chimerax_url="http://127.0.0.1:3010",
        source="agent:codex",
    )
    inline = " ".join(argv)
    assert '"--source","agent:codex"' in inline
    assert '"--chimerax-url","http://127.0.0.1:3010"' in inline
    assert '"--profile","assistant"' in inline
