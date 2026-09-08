import json

from src.core.agent_cli import ALLOWED_TOOL_PREFIX, custom_agent, get_agent
from src.core.agent_session import (
    AgentConversation,
    TurnContext,
    adapter_for,
    conversation_for,
)


def _context(agent_key: str, **changes) -> TurnContext:
    values = {
        "agent": get_agent(agent_key),
        "executable": f"/opt/bin/{agent_key}",
        "config_path": "/tmp/molcompose-mcp.json",
        "answer_path": "/tmp/answer.md",
        "server_executable": "/opt/bin/molcompose-mcp",
        "chimerax_url": "http://127.0.0.1:3010",
        "source": f"agent:{agent_key}",
    }
    values.update(changes)
    return TurnContext(**values)


def test_codex_two_turns_resume_the_captured_thread_with_the_same_mcp_binding():
    context = _context("codex")
    adapter = adapter_for(context.agent)

    first = adapter.start_turn("characterise it", context)
    assert first.protocol == "codex-jsonl"
    assert first.argv[:2] == ("/opt/bin/codex", "exec")
    assert "--json" in first.argv
    assert "resume" not in first.argv

    events = adapter.consume_line(
        json.dumps({"type": "thread.started", "thread_id": "thread-123"})
    )
    assert [(event.kind, event.value) for event in events] == [
        ("session", "thread-123")
    ]
    conversation = AgentConversation("codex", "thread-123", 0)
    second = adapter.resume_turn("mark those hotspots", conversation, context)

    assert second.argv[:3] == ("/opt/bin/codex", "exec", "resume")
    assert second.argv[-2:] == ("thread-123", second.argv[-1])
    assert second.argv[-1].endswith("mark those hotspots")
    joined = " ".join(second.argv)
    assert 'mcp_servers.molcompose.command="/opt/bin/molcompose-mcp"' in joined
    assert '"--chimerax-url","http://127.0.0.1:3010"' in joined
    assert '"--source","agent:codex"' in joined


def test_claude_two_turns_use_generated_session_then_resume_it():
    context = _context("claude", answer_path=None)
    adapter = adapter_for(
        context.agent,
        uuid_factory=lambda: "12345678-1234-4234-8234-123456789abc",
    )

    first = adapter.start_turn("characterise it", context)
    assert first.protocol == "claude-stream-json"
    assert first.stdin == b"characterise it"
    assert first.argv[first.argv.index("--session-id") + 1] == (
        "12345678-1234-4234-8234-123456789abc"
    )
    assert first.argv[first.argv.index("--output-format") + 1] == "stream-json"
    assert first.argv[first.argv.index("--allowedTools") + 1] == ALLOWED_TOOL_PREFIX

    conversation = AgentConversation(
        "claude", "12345678-1234-4234-8234-123456789abc", 0
    )
    second = adapter.resume_turn("mark those hotspots", conversation, context)
    assert "--session-id" not in second.argv
    assert second.argv[second.argv.index("--resume") + 1] == conversation.session_id
    assert second.argv[second.argv.index("--mcp-config") + 1] == context.config_path
    assert second.argv[second.argv.index("--allowedTools") + 1] == ALLOWED_TOOL_PREFIX
    assert second.stdin == b"mark those hotspots"


def test_protocol_events_keep_final_answers_separate_from_diagnostics():
    codex = adapter_for(get_agent("codex"))
    final = codex.consume_line(json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "Done."},
    }))
    diagnostic = codex.consume_line(json.dumps({
        "type": "item.completed",
        "item": {"type": "command_execution", "command": "ignored"},
    }))
    assert [(event.kind, event.value) for event in final] == [("final", "Done.")]
    assert diagnostic[0].kind == "diagnostic"

    claude = adapter_for(get_agent("claude"))
    result = claude.consume_line(json.dumps({
        "type": "result",
        "subtype": "success",
        "session_id": "12345678-1234-4234-8234-123456789abc",
        "result": "Also done.",
    }))
    assert [(event.kind, event.value) for event in result] == [
        ("session", "12345678-1234-4234-8234-123456789abc"),
        ("final", "Also done."),
    ]


def test_mcp_tool_events_drive_the_executing_phase():
    codex = adapter_for(get_agent("codex"))
    codex_events = codex.consume_line(json.dumps({
        "type": "item.started",
        "item": {"type": "mcp_tool_call", "server": "molcompose"},
    }))
    assert [(event.kind, event.value) for event in codex_events] == [
        ("phase", "Executing in ChimeraX…")
    ]

    claude = adapter_for(get_agent("claude"))
    claude_events = claude.consume_line(json.dumps({
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "mcp__molcompose__inspect_session"}]
        },
    }))
    assert [(event.kind, event.value) for event in claude_events] == [
        ("phase", "Executing in ChimeraX…")
    ]


def test_protocol_diagnostics_redact_api_keys_recursively():
    secret = "top-secret-value"
    codex = adapter_for(get_agent("codex"))
    events = codex.consume_line(json.dumps({
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "arguments": {"api_key": secret, "nested": {"authorization": secret}},
        },
    }))

    assert events[0].kind == "diagnostic"
    assert secret not in events[0].value
    assert events[0].value.count("[REDACTED]") == 2


def test_malformed_protocol_warnings_still_redact_api_keys():
    secret = "top-secret-value"
    events = adapter_for(get_agent("codex")).consume_line(
        f'{{"api_key": "{secret}"'
    )

    assert events[0].kind == "warning"
    assert secret not in events[0].value
    assert "[REDACTED]" in events[0].value


def test_malformed_protocol_json_becomes_a_warning_instead_of_crashing():
    for key in ("codex", "claude"):
        events = adapter_for(get_agent(key)).consume_line("{not json")
        assert len(events) == 1
        assert events[0].kind == "warning"
        assert "{not json" in events[0].value


def test_conversation_resets_when_agent_or_live_binding_changes():
    current = conversation_for(None, _context("codex"))
    current = AgentConversation(
        current.agent_key, "thread-123", current.generation, current.binding
    )

    assert conversation_for(current, _context("codex")) is current
    # A fresh temporary config file with the same server binding is equivalent.
    assert conversation_for(
        current, _context("codex", config_path="/tmp/next-turn.json")
    ) is current
    for changed in (
        _context("claude", answer_path=None),
        _context("codex", chimerax_url="http://127.0.0.1:3020"),
        _context("codex", server_executable="/other/molcompose-mcp"),
        _context("codex", executable="/other/codex"),
    ):
        reset = conversation_for(current, changed)
        assert reset.session_id is None
        assert reset.generation == current.generation + 1


def test_explicit_new_conversation_increments_generation_and_drops_session_id():
    current = AgentConversation("codex", "thread-123", 4, "binding")
    reset = current.reset()
    assert reset == AgentConversation("codex", None, 5, "binding")


def test_custom_commands_keep_their_existing_one_shot_protocol_and_warn():
    agent = custom_agent("/opt/bin/other", "run {prompt}")
    context = TurnContext(agent=agent, executable=agent.executable)
    adapter = adapter_for(agent)

    first = adapter.start_turn("hello", context)
    assert first.argv == ("/opt/bin/other", "run", "hello")
    assert first.protocol == "plain"
    assert first.warnings == (
        "This custom command has no conversation adapter; each turn starts fresh.",
    )
    conversation = AgentConversation(agent.key, "not-supported", 0)
    second = adapter.resume_turn("again", conversation, context)
    assert second.argv == ("/opt/bin/other", "run", "again")
