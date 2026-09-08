"""Drive a locally installed agent CLI, following the codex-for-pymol pattern.

MolCompose never embeds a language model and never holds an API key. If the
user already has an agent CLI installed and authenticated, the panel can hand
it a prompt and let it drive this ChimeraX session through the MolCompose MCP
server. If no CLI is present the feature simply does not appear.

Three things must line up for a prompt to work, and each has its own failure
message so the user is told which one is missing:

1. an agent CLI on PATH (``claude`` or ``codex``),
2. the ``molcompose-mcp`` server on PATH,
3. the ChimeraX REST bridge running (started from the Agent tab).
"""

import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_CHIMERAX_URL = "http://127.0.0.1:3000"
SERVER_NAME = "molcompose"
ALLOWED_TOOL_PREFIX = f"mcp__{SERVER_NAME}"
CUSTOM_KEY = "custom"

LIVE_CHIMERAX_CONTRACT = (
    "You are operating the currently open ChimeraX session through the "
    "molcompose MCP server. Treat that live session as the sole source of truth "
    "for the structure in this window.\n\n"
    "Before answering any question about an open structure, call "
    "inspect_session first and respect its compatibility result. It includes "
    "the current list_models view and the assistant contract version. "
    "The assistant profile has no MCP resources: do not call "
    "list_mcp_resources or read_mcp_resource for routine structure questions. "
    "Use inspect_session and analyse_interface directly. "
    "Use molcompose MCP tools for structure discovery, analysis, measurements, "
    "and visual changes in this session. Do not search the filesystem, inspect "
    "saved reports or session files, or run a shell command or another ChimeraX "
    "process. Do not fetch structures or other data from the network unless the "
    "user explicitly asks you to. If the required model is not open or an MCP "
    "call fails, say so instead of substituting stale or external data. Use "
    "the returned `display` values in prose, and preserve `raw` values when "
    "the user asks for exact data or reproducibility details.\n\n"
    "Unless the user asks for another interface definition, keep the default "
    "heavy criterion and 4.5 Å cutoff. When reporting `contact_pairs`, call "
    "them contacting residue pairs, never atom pairs. Read and report the "
    "returned `skipped` reasons in an analysis answer. If you report affinity, "
    "ΔG or Kd, label it as an estimate rather than an experimental value.\n\n"
    "For a figure request, use only a tested `compose_figure` goal, then call "
    "`render_preview` before `export_artifact`. Inspect whether the subject is "
    "cropped, labels overlap, or a colour key is unreadable. If the preview "
    "is unavailable or ambiguous, state that you cannot visually verify the "
    "figure instead of claiming it passed review.\n\n"
    "User request:\n"
)


@dataclass(frozen=True)
class AgentCli:
    key: str
    label: str
    executable: str
    # `{prompt}` and `{config}` are substituted when the command is built.
    arguments: tuple[str, ...]
    supports_mcp_config: bool = True
    # Pass the prompt on stdin rather than as an argument. Necessary for CLIs
    # whose options take a variable number of values (claude's --mcp-config
    # accepts several files, so a trailing prompt is swallowed as another one).
    prompt_via_stdin: bool = False
    # How to start the same CLI as a conversation in a terminal, rather than
    # as one turn in this panel. Empty means the panel offers no such command
    # for this agent. See `interactive_command` for why the two differ.
    interactive_arguments: tuple[str, ...] = ()
    # Optional CLI arguments that write only the final assistant message to a
    # file, keeping startup diagnostics and hook output out of the answer UI.
    final_message_arguments: tuple[str, ...] = ()
    # Codex has no CLI tool allow-list equivalent to Claude's --allowedTools.
    # Bind its prompt to the live session and verify the resulting operations
    # in the panel instead of silently letting a filesystem answer look live.
    live_session_contract: bool = False
    # Codex accepts MCP server settings as TOML command-line overrides. This
    # binds a turn to the server executable discovered by this panel and to
    # this window's REST URL, without relying on the user's global config.
    inline_mcp_config: bool = False
    # Argument-driven Codex waits while QProcess leaves stdin open. Other
    # argument-driven/custom CLIs keep their existing stdin lifecycle.
    close_stdin_after_prompt: bool = False


AGENTS = (
    AgentCli(
        key="claude",
        label="Claude Code",
        executable="claude",
        # --print is non-interactive, so tool permissions cannot be granted by
        # prompting: the MolCompose tools must be allowed up front. Hide the
        # built-in tools and ignore user-level MCP servers so this subprocess
        # sees only the validated surface configured for the live session.
        arguments=(
            "--print",
            "--tools",
            "",
            "--strict-mcp-config",
            "--allowedTools",
            ALLOWED_TOOL_PREFIX,
            "--mcp-config",
            "{config}",
        ),
        prompt_via_stdin=True,
        # No --print and no allow-list: in a terminal the CLI can ask before
        # each tool call, which is the thing --print cannot do.
        interactive_arguments=("--mcp-config", "{config}"),
    ),
    AgentCli(
        key="codex",
        label="Codex",
        executable="codex",
        # `codex exec` cannot stop for approval. Pre-approve only this bundle's
        # validated MCP surface for this subprocess; every other tool keeps the
        # CLI's non-interactive approval policy.
        arguments=(
            "exec",
            "--skip-git-repo-check",
            "-c",
            f'mcp_servers.{SERVER_NAME}.default_tools_approval_mode="approve"',
            "{prompt}",
        ),
        supports_mcp_config=False,
        interactive_arguments=(),
        final_message_arguments=("--output-last-message", "{output}"),
        live_session_contract=True,
        inline_mcp_config=True,
        close_stdin_after_prompt=True,
    ),
)

# Chosen from the panel when the CLI is not one of the two above, or is one of
# them installed somewhere `locate` does not look. The arguments are the
# user's to supply, since only they know what their CLI expects; the default
# is the shape most agent CLIs take.
CUSTOM_AGENT = AgentCli(
    key=CUSTOM_KEY,
    label="Custom command",
    executable="",
    arguments=("{prompt}",),
    supports_mcp_config=False,
)


def custom_agent(executable: str, arguments: str = "", label: str = "") -> AgentCli:
    """An agent definition from a path and an argument template the user typed.

    `{prompt}` and `{config}` are substituted as they are for the built-in
    agents. An argument string with neither is taken to want the prompt last,
    which is what `codex exec`, `gemini` and most others do — getting that
    wrong silently sends an empty turn, so it is worth guessing rather than
    requiring the placeholder.
    """
    parts = tuple(shlex.split(arguments)) if arguments.strip() else ()
    if not any("{prompt}" in part for part in parts):
        parts = (*parts, "{prompt}")
    return replace(
        CUSTOM_AGENT,
        executable=executable,
        arguments=parts,
        supports_mcp_config=any("{config}" in part for part in parts),
        label=label or Path(executable).name or CUSTOM_AGENT.label,
    )


# A GUI application launched from the Dock or Finder on macOS does not inherit
# the shell's PATH, so tools installed by Homebrew, pipx or npm are invisible to
# `shutil.which`. Look in the usual places as well before giving up.
EXTRA_BIN_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "~/.local/bin",
    "~/bin",
    "~/.npm-global/bin",
    "~/.bun/bin",
    "~/.cargo/bin",
)


def _interpreter_bin_dir() -> str:
    """The bin directory of the running interpreter (finds pip-installed tools)."""
    return str(Path(sys.executable).parent)


def locate(executable: str, which=shutil.which, extra_dirs=None) -> str | None:
    """Resolve an executable from PATH, then from well-known install locations."""
    resolved = which(executable)
    if resolved:
        return resolved
    candidates = list(extra_dirs) if extra_dirs is not None else list(EXTRA_BIN_DIRS)
    candidates.append(_interpreter_bin_dir())
    for folder in candidates:
        candidate = Path(os.path.expanduser(folder)) / executable
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def find_agents(which=shutil.which, extra_dirs=None) -> tuple[tuple[AgentCli, str], ...]:
    """Agent CLIs available to this process, as (definition, executable path)."""
    found = []
    for agent in AGENTS:
        resolved = locate(agent.executable, which, extra_dirs)
        if resolved:
            found.append((agent, resolved))
    return tuple(found)


def get_agent(key: str) -> AgentCli:
    for agent in AGENTS:
        if agent.key == key:
            return agent
    raise ValueError(f"unknown agent CLI: {key}")


def mcp_config(server_executable: str, chimerax_url: str = DEFAULT_CHIMERAX_URL,
               source: str = "") -> dict:
    """The MCP client configuration that points an agent at this ChimeraX session.

    `source` is how the bundle will attribute the commands this client issues.
    The server cannot work it out — it is a stdio server and its client is its
    parent process — but the panel launched that client and knows which one it
    is, so it says. Without it every client records as "agent" and a session
    that used two of them cannot be told apart afterwards.
    """
    args = [
        "--chimerax-url", chimerax_url,
        "--profile", "assistant",
    ]
    if source:
        args += ["--source", source]
    return {"mcpServers": {SERVER_NAME: {"command": server_executable, "args": args}}}


def write_mcp_config(path, server_executable: str,
                     chimerax_url: str = DEFAULT_CHIMERAX_URL,
                     source: str = "") -> str:
    text = json.dumps(mcp_config(server_executable, chimerax_url, source), indent=2)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return text


def build_command(
    agent: AgentCli,
    prompt: str,
    config_path: str | None = None,
    executable: str | None = None,
    output_path: str | None = None,
    server_executable: str | None = None,
    chimerax_url: str = DEFAULT_CHIMERAX_URL,
    source: str = "",
) -> list[str]:
    """Full argv for one non-interactive agent turn."""
    if not prompt.strip():
        raise ValueError("the prompt is empty")
    if agent.supports_mcp_config and not config_path:
        raise ValueError(f"{agent.label} needs an MCP config file path")
    if agent.inline_mcp_config and not server_executable:
        raise ValueError(f"{agent.label} needs the molcompose-mcp executable")
    effective_prompt = _effective_prompt(agent, prompt)
    argv = [executable or agent.executable]
    for argument in agent.arguments:
        if agent.inline_mcp_config and "{prompt}" in argument:
            argv.extend(
                _inline_mcp_arguments(server_executable or "", chimerax_url, source)
            )
        if output_path and "{prompt}" in argument:
            argv.extend(
                item.format(output=output_path)
                for item in agent.final_message_arguments
            )
        if agent.prompt_via_stdin and "{prompt}" in argument:
            continue
        argv.append(argument.format(prompt=effective_prompt, config=config_path or ""))
    return argv


def _inline_mcp_arguments(server_executable: str, chimerax_url: str,
                          source: str = "") -> tuple[str, ...]:
    """Codex TOML overrides for this exact server process and viewer URL.

    Codex never reads the config file the panel writes — it takes the server
    on the command line — so `source` has to be threaded here as well. Setting
    it in one place only would have left every Codex turn recorded as the
    generic "agent" while Claude Code turns named themselves, which is worse
    than neither doing it: the record would look complete and be wrong.
    """
    command = json.dumps(server_executable)
    arguments = [
        "--chimerax-url", chimerax_url,
        "--profile", "assistant",
    ]
    if source:
        arguments += ["--source", source]
    args = json.dumps(arguments, separators=(",", ":"))
    return (
        "-c",
        f"mcp_servers.{SERVER_NAME}.command={command}",
        "-c",
        f"mcp_servers.{SERVER_NAME}.args={args}",
    )


def _effective_prompt(agent: AgentCli, prompt: str) -> str:
    """Add the live-window contract only to agents that need the safeguard."""
    if not agent.live_session_contract:
        return prompt
    return f"{LIVE_CHIMERAX_CONTRACT}{prompt}"


def finish_process_input(process, agent: AgentCli, prompt: str) -> None:
    """Send any stdin prompt and always tell the CLI there is no more input.

    QProcess opens a writable stdin pipe for every child. Codex receives its
    prompt in argv, but still detects that open pipe and waits for an EOF before
    starting the turn. Claude receives its prompt through the pipe instead; it
    needs the same EOF after the bytes have been written. Closing unconditionally
    preserves both input conventions and prevents argument-driven CLIs from
    waiting for a second prompt that will never arrive.
    """
    if agent.prompt_via_stdin:
        process.write(_effective_prompt(agent, prompt).encode("utf-8"))
        process.closeWriteChannel()
    elif agent.close_stdin_after_prompt:
        process.closeWriteChannel()


def interactive_command(
    agent: AgentCli, config_path: str | None = None, executable: str | None = None
) -> list[str] | None:
    """Argv that starts the same agent as a conversation, or None if it can't.

    The panel's own turns are non-interactive on purpose: `claude --print`
    cannot stop and ask whether a tool call is allowed, so the MolCompose
    tools are permitted up front and nothing else is. That is the right trade
    for a chat box inside a figure panel, and it is also the reason the panel
    cannot answer a follow-up question — each turn is a fresh process.

    A terminal is where the other trade belongs. The same CLI, pointed at the
    same session through the same MCP config, asks before each tool call and
    keeps its context between questions. So the panel hands over the command
    instead of pretending to be a terminal.
    """
    if not agent.interactive_arguments:
        return None
    if not config_path:
        raise ValueError(f"{agent.label} needs an MCP config file path")
    return [executable or agent.executable,
            *(argument.format(config=config_path)
              for argument in agent.interactive_arguments)]


def readiness(
    agents_found: tuple, server_executable: str | None, bridge_running: bool
) -> str | None:
    """The first unmet prerequisite, as a message, or None when ready."""
    if not agents_found:
        names = ", ".join(agent.executable for agent in AGENTS)
        return (
            f"No agent CLI found (looked for {names} on PATH and in "
            f"{', '.join(EXTRA_BIN_DIRS[:3])}…). Install and sign in to one, "
            "then reopen this panel."
        )
    if not server_executable:
        return (
            "molcompose-mcp is not on PATH. Install it with "
            "`pip install molcompose-mcp` so the agent can reach ChimeraX."
        )
    if not bridge_running:
        return "Start the agent bridge first — the button above this box."
    return None
