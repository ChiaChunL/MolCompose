"""Qt-independent conversation adapters for the Agent panel.

The panel still starts one non-interactive CLI process per turn.  The process
is deliberately disposable; the conversation is not.  Supported CLIs persist
their own context and expose a session identifier that the next process can
resume, while custom commands retain their established one-shot behaviour.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .agent_cli import AgentCli, _effective_prompt, build_command

Protocol = Literal["codex-jsonl", "claude-stream-json", "plain"]
EventKind = Literal["session", "phase", "final", "diagnostic", "warning"]
TerminalState = Literal[
    "succeeded", "failed", "start_failed", "timed_out", "cancelled"
]


def redact_sensitive_text(text: str) -> str:
    """Redact credential-shaped values from unstructured process output."""
    return re.sub(
        r'''(?ix)
        (["']?(?:api[_-]?key|apikey|authorization)["']?\s*[:=]\s*)
        ("[^"]*"|'[^']*'|Bearer\s+[^\s,}\r\n]+|[^\s,}]+)
        ''',
        r'\1"[REDACTED]"',
        text,
    )


@dataclass(frozen=True)
class AgentEvent:
    kind: EventKind
    value: str


@dataclass(frozen=True)
class TerminalEvent:
    state: TerminalState
    detail: str = ""


class TurnLifecycle:
    """Own one turn's cleanup and make every terminal path idempotent."""

    def __init__(self):
        self.active = False
        self.terminal_event: TerminalEvent | None = None
        self._callbacks: tuple[Callable[[], None], ...] = ()

    def begin(
        self,
        *,
        close_stdin: Callable[[], None] | None = None,
        stop_timer: Callable[[], None] | None = None,
        cleanup: Callable[[], None] | None = None,
    ) -> None:
        if self.active:
            raise RuntimeError("an Agent turn is already active")
        self.active = True
        self.terminal_event = None
        self._callbacks = tuple(
            callback
            for callback in (close_stdin, stop_timer, cleanup)
            if callback is not None
        )

    def finish(
        self, state: TerminalState, detail: str = ""
    ) -> TerminalEvent | None:
        if not self.active:
            return None
        self.active = False
        event = TerminalEvent(state, detail)
        self.terminal_event = event
        callbacks, self._callbacks = self._callbacks, ()
        for callback in callbacks:
            try:
                callback()
            except Exception:  # noqa: BLE001 - cleanup must continue to completion
                continue
        return event


@dataclass(frozen=True)
class TurnSpec:
    argv: tuple[str, ...]
    stdin: bytes | None
    answer_path: str | None
    protocol: Protocol
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnContext:
    agent: AgentCli
    executable: str
    config_path: str | None = None
    answer_path: str | None = None
    server_executable: str | None = None
    chimerax_url: str = "http://127.0.0.1:3000"
    source: str = ""

    @property
    def binding(self) -> str:
        """Everything whose change makes an old CLI session unsafe to resume."""
        return repr((
            self.agent.key,
            self.executable,
            self.server_executable,
            self.chimerax_url,
            self.source,
        ))


@dataclass(frozen=True)
class AgentConversation:
    agent_key: str
    session_id: str | None
    generation: int
    binding: str = ""

    def reset(self) -> AgentConversation:
        return AgentConversation(
            self.agent_key, None, self.generation + 1, self.binding
        )

    def with_session(self, session_id: str) -> AgentConversation:
        return AgentConversation(
            self.agent_key, session_id, self.generation, self.binding
        )


def conversation_for(
    current: AgentConversation | None, context: TurnContext
) -> AgentConversation:
    """Keep a compatible conversation or start a new generation."""
    if (
        current is not None
        and current.agent_key == context.agent.key
        and current.binding == context.binding
    ):
        return current
    generation = 0 if current is None else current.generation + 1
    return AgentConversation(context.agent.key, None, generation, context.binding)


class _Adapter:
    protocol: Protocol = "plain"

    def __init__(self, agent: AgentCli):
        self.agent = agent

    def start_turn(self, prompt: str, context: TurnContext) -> TurnSpec:
        raise NotImplementedError

    def resume_turn(
        self,
        prompt: str,
        conversation: AgentConversation,
        context: TurnContext,
    ) -> TurnSpec:
        raise NotImplementedError

    def consume_line(self, line: str) -> tuple[AgentEvent, ...]:
        raise NotImplementedError

    def _first_argv(self, prompt: str, context: TurnContext) -> list[str]:
        return build_command(
            self.agent,
            prompt,
            context.config_path,
            context.executable,
            context.answer_path,
            server_executable=context.server_executable,
            chimerax_url=context.chimerax_url,
            source=context.source,
        )


class _JsonAdapter(_Adapter):
    def _object(self, line: str) -> dict | AgentEvent:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return AgentEvent(
                "warning",
                f"Unrecognised protocol output: {redact_sensitive_text(line)}",
            )
        if not isinstance(value, dict):
            return AgentEvent(
                "warning",
                f"Unrecognised protocol output: {redact_sensitive_text(line)}",
            )
        return value

    @staticmethod
    def _diagnostic(value: dict) -> AgentEvent:
        sensitive = {"api_key", "apikey", "authorization"}

        def redact(item):
            if isinstance(item, dict):
                return {
                    key: "[REDACTED]" if key.lower() in sensitive else redact(child)
                    for key, child in item.items()
                }
            if isinstance(item, list):
                return [redact(child) for child in item]
            return item

        return AgentEvent(
            "diagnostic", json.dumps(redact(value), ensure_ascii=False)
        )


class CodexAdapter(_JsonAdapter):
    protocol: Protocol = "codex-jsonl"

    def start_turn(self, prompt: str, context: TurnContext) -> TurnSpec:
        argv = self._first_argv(prompt, context)
        argv.insert(2, "--json")
        return TurnSpec(tuple(argv), None, context.answer_path, self.protocol)

    def resume_turn(
        self,
        prompt: str,
        conversation: AgentConversation,
        context: TurnContext,
    ) -> TurnSpec:
        if not conversation.session_id:
            return self.start_turn(prompt, context)
        first = list(self.start_turn(prompt, context).argv)
        effective_prompt = first.pop()
        argv = [first[0], first[1], "resume", *first[2:]]
        argv.extend((conversation.session_id, effective_prompt))
        return TurnSpec(tuple(argv), None, context.answer_path, self.protocol)

    def consume_line(self, line: str) -> tuple[AgentEvent, ...]:
        value = self._object(line)
        if isinstance(value, AgentEvent):
            return (value,)
        if value.get("type") == "thread.started" and value.get("thread_id"):
            return (AgentEvent("session", str(value["thread_id"])),)
        item = value.get("item")
        if (
            value.get("type") == "item.started"
            and isinstance(item, dict)
            and item.get("type") == "mcp_tool_call"
        ):
            return (AgentEvent("phase", "Executing in ChimeraX…"),)
        if value.get("type") == "item.completed" and isinstance(item, dict):
            if item.get("type") == "agent_message" and item.get("text"):
                return (AgentEvent("final", str(item["text"])),)
        return (self._diagnostic(value),)


class ClaudeAdapter(_JsonAdapter):
    protocol: Protocol = "claude-stream-json"

    def __init__(self, agent: AgentCli, uuid_factory: Callable[[], str] | None = None):
        super().__init__(agent)
        self._uuid_factory = uuid_factory or (lambda: str(uuid.uuid4()))

    def _stream_argv(self, prompt: str, context: TurnContext) -> list[str]:
        argv = self._first_argv(prompt, context)
        argv.extend(("--output-format", "stream-json", "--verbose"))
        return argv

    def start_turn(self, prompt: str, context: TurnContext) -> TurnSpec:
        argv = self._stream_argv(prompt, context)
        argv.extend(("--session-id", self._uuid_factory()))
        stdin = _effective_prompt(self.agent, prompt).encode("utf-8")
        return TurnSpec(tuple(argv), stdin, context.answer_path, self.protocol)

    def resume_turn(
        self,
        prompt: str,
        conversation: AgentConversation,
        context: TurnContext,
    ) -> TurnSpec:
        if not conversation.session_id:
            return self.start_turn(prompt, context)
        argv = self._stream_argv(prompt, context)
        argv.extend(("--resume", conversation.session_id))
        stdin = _effective_prompt(self.agent, prompt).encode("utf-8")
        return TurnSpec(tuple(argv), stdin, context.answer_path, self.protocol)

    def consume_line(self, line: str) -> tuple[AgentEvent, ...]:
        value = self._object(line)
        if isinstance(value, AgentEvent):
            return (value,)
        events = []
        session_id = value.get("session_id")
        if session_id:
            events.append(AgentEvent("session", str(session_id)))
        if value.get("type") == "result" and value.get("result"):
            events.append(AgentEvent("final", str(value["result"])))
        message = value.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list) and any(
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and str(block.get("name", "")).startswith("mcp__molcompose")
            for block in content
        ):
            events.append(AgentEvent("phase", "Executing in ChimeraX…"))
        if not events:
            events.append(self._diagnostic(value))
        return tuple(events)


class PlainAdapter(_Adapter):
    protocol: Protocol = "plain"
    _WARNING = (
        "This custom command has no conversation adapter; each turn starts fresh."
    )

    def start_turn(self, prompt: str, context: TurnContext) -> TurnSpec:
        argv = self._first_argv(prompt, context)
        stdin = (
            _effective_prompt(self.agent, prompt).encode("utf-8")
            if self.agent.prompt_via_stdin
            else None
        )
        return TurnSpec(tuple(argv), stdin, context.answer_path, self.protocol,
                        (self._WARNING,))

    def resume_turn(
        self,
        prompt: str,
        conversation: AgentConversation,
        context: TurnContext,
    ) -> TurnSpec:
        return self.start_turn(prompt, context)

    def consume_line(self, line: str) -> tuple[AgentEvent, ...]:
        return (AgentEvent("final", line),) if line else ()


def adapter_for(
    agent: AgentCli, *, uuid_factory: Callable[[], str] | None = None
) -> _Adapter:
    if agent.key == "codex":
        return CodexAdapter(agent)
    if agent.key == "claude":
        return ClaudeAdapter(agent, uuid_factory)
    return PlainAdapter(agent)
