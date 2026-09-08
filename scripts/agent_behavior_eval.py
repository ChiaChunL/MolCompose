"""Run signed-in agent CLIs against MolCompose's assistant MCP profile."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ASSISTANT_TOOLS = frozenset({
    "open_structure",
    "inspect_session",
    "analyse_interface",
    "compose_figure",
    "render_preview",
    "export_artifact",
    "load_external_evidence",
})
MCP_PROTOCOL_HELPERS = frozenset({
    "list_mcp_resources",
    "read_mcp_resource",
    "list_mcp_resource_templates",
})
_REFUSAL_FRAGMENTS = ("无法回答", "没法回答", "cannot answer", "can't answer")
_UNAVAILABLE_FRAGMENTS = (
    ("session limit", "session limit"),
    ("rate limit", "rate limit"),
    ("usage limit", "usage limit"),
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

_INTERFACE_ANSWER_CONCEPTS = (
    ("heavy", "重原子"),
    ("4.5 Å", "4.5 A", "4.5 angstrom", "4.5 埃"),
    ("residue pair", "残基对", "对接触残基"),
    ("skipped", "跳过", "不适用", "拒绝", "无法计算", "未计算", "未分析"),
)
_FIGURE_ANSWER_CONCEPTS = (
    ("heavy", "重原子"),
    ("4.5 Å", "4.5 A", "4.5 angstrom", "4.5 埃"),
    ("residue pair", "残基对", "对接触残基"),
    ("preview", "预览", "visual", "视觉"),
    (".png", "PNG"),
)
_FOLLOW_UP_FIGURE_CONCEPTS = (
    ("preview", "预览", "visual", "视觉"),
    (".png", "PNG"),
)
_AFFINITY_DISCLOSURE = (
    ("ΔG", "K_d", "Kd", "affinity", "亲和力"),
    ("estimate", "estimated", "估计", "估算"),
)
_DEFAULT_INTERFACE_ARGUMENTS = (
    ("analyse_interface", "criterion", (None, "heavy")),
    ("analyse_interface", "distance", (None, 4.5)),
)


@dataclass(frozen=True)
class EvalScenario:
    name: str
    prompt: str
    required_subsequence: tuple[str, ...]
    max_calls: int
    required_answer_concepts: tuple[tuple[str, ...], ...] = ()
    conditional_answer_concepts: tuple[
        tuple[tuple[str, ...], tuple[str, ...]], ...
    ] = ()
    tool_argument_constraints: tuple[
        tuple[str, str, tuple[object, ...]], ...
    ] = ()
    forbidden_tools: tuple[str, ...] = ()
    forbidden_answer_concepts: tuple[str, ...] = ()
    follow_up: EvalScenario | None = None
    fixture: str = "experimental"


DEFAULT_SCENARIOS = (
    EvalScenario(
        name="explicit-interface",
        prompt="1BRS 的 A 链和 D 链主要靠什么相互作用结合？请基于当前 ChimeraX 会话回答。",
        required_subsequence=("inspect_session", "analyse_interface"),
        max_calls=3,
        required_answer_concepts=_INTERFACE_ANSWER_CONCEPTS,
        conditional_answer_concepts=(_AFFINITY_DISCLOSURE,),
        tool_argument_constraints=_DEFAULT_INTERFACE_ARGUMENTS,
    ),
    EvalScenario(
        name="implicit-interface",
        prompt="分析当前打开的这个复合物界面，并解释它主要靠什么结合。",
        required_subsequence=("inspect_session", "analyse_interface"),
        max_calls=3,
        required_answer_concepts=_INTERFACE_ANSWER_CONCEPTS,
        conditional_answer_concepts=(_AFFINITY_DISCLOSURE,),
        tool_argument_constraints=_DEFAULT_INTERFACE_ARGUMENTS,
    ),
    EvalScenario(
        name="hotspot-figure",
        prompt=(
            "把当前复合物的界面热点做成图；如果还没分析界面，请先完成必要分析，"
            "并把 PNG 导出到 agent-eval-hotspot.png。"
        ),
        required_subsequence=(
            "inspect_session",
            "analyse_interface",
            "compose_figure",
            "render_preview",
            "export_artifact",
        ),
        max_calls=6,
        required_answer_concepts=_FIGURE_ANSWER_CONCEPTS,
        conditional_answer_concepts=(_AFFINITY_DISCLOSURE,),
        tool_argument_constraints=_DEFAULT_INTERFACE_ARGUMENTS,
    ),
    EvalScenario(
        name="multiturn-hotspot",
        prompt=(
            "分析当前 1BRS 的 A 链和 D 链界面，说明主要相互作用；"
            "暂时不要出图。"
        ),
        required_subsequence=("inspect_session", "analyse_interface"),
        max_calls=3,
        required_answer_concepts=_INTERFACE_ANSWER_CONCEPTS,
        conditional_answer_concepts=(_AFFINITY_DISCLOSURE,),
        tool_argument_constraints=_DEFAULT_INTERFACE_ARGUMENTS,
        follow_up=EvalScenario(
            name="multiturn-hotspot-follow-up",
            prompt=(
                "把刚才那个界面做成热点图，预览确认没有裁切后，"
                "导出到 agent-eval-follow-up.png。"
            ),
            required_subsequence=(
                "compose_figure",
                "render_preview",
                "export_artifact",
            ),
            max_calls=4,
            required_answer_concepts=_FOLLOW_UP_FIGURE_CONCEPTS,
        ),
    ),
    EvalScenario(
        name="ambiguous-models",
        prompt=(
            "分析当前打开的复合物界面。若有多个模型，不要替我猜，"
            "请列出选择并让我确认。"
        ),
        required_subsequence=("inspect_session",),
        max_calls=2,
        required_answer_concepts=(
            ("#1", "model 1", "模型 1", "模型#1"),
            ("#2", "model 2", "模型 2", "模型#2"),
            ("choose", "which", "选择", "指定", "确认"),
        ),
        tool_argument_constraints=(("analyse_interface", "model", (None,)),),
        forbidden_tools=("compose_figure", "export_artifact"),
        fixture="ambiguous-models",
    ),
    EvalScenario(
        name="recoverable-failure",
        prompt=(
            "检查当前 ChimeraX 会话。如果连接或工具暂时失败，请说明如何恢复，"
            "不要推测结构内容。"
        ),
        required_subsequence=("inspect_session",),
        max_calls=2,
        required_answer_concepts=(
            ("retry", "again", "重试", "再试", "再次", "重新开始"),
            ("temporary", "unavailable", "暂时", "不可用", "失败", "中断"),
        ),
        forbidden_tools=(
            "analyse_interface",
            "compose_figure",
            "export_artifact",
        ),
        forbidden_answer_concepts=(
            "Å²",
            "kcal/mol",
            "hydrogen bond",
            "氢键",
            "salt bridge",
            "盐桥",
            "buried area",
            "埋藏面积",
            "residue pair",
            "残基对",
        ),
        fixture="recoverable-failure",
    ),
    EvalScenario(
        name="cropped-preview",
        prompt=(
            "把当前复合物做成界面概览图并准备导出到 "
            "agent-eval-cropped.png。导出前必须预览；如果主体明显被裁切，"
            "请停止并说明问题，不要导出。"
        ),
        required_subsequence=(
            "inspect_session",
            "analyse_interface",
            "compose_figure",
            "render_preview",
        ),
        max_calls=6,
        required_answer_concepts=(
            ("cropped", "clipped", "裁切", "裁掉", "截断"),
            ("not export", "not exported", "未导出", "没有导出", "停止导出"),
        ),
        tool_argument_constraints=_DEFAULT_INTERFACE_ARGUMENTS,
        forbidden_tools=("export_artifact",),
        fixture="cropped-preview",
    ),
)


def _arguments(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def extract_tool_calls(lines, protocol):
    """MolCompose MCP calls from one Codex or Claude JSONL event stream."""
    calls = []
    seen = set()
    for line in lines:
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        candidates = []
        if protocol == "codex-jsonl":
            item = event.get("item")
            if (
                isinstance(item, dict)
                and item.get("type") == "mcp_tool_call"
                and item.get("server") == "molcompose"
            ):
                candidates.append((
                    item.get("id"),
                    item.get("tool") or item.get("name"),
                    item.get("arguments"),
                ))
        elif protocol == "claude-stream-json":
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = str(block.get("name", ""))
                    prefix = "mcp__molcompose__"
                    if name.startswith(prefix):
                        candidates.append((
                            block.get("id"), name[len(prefix):], block.get("input")
                        ))
        else:
            raise ValueError(f"unsupported agent event protocol: {protocol}")

        for call_id, name, arguments in candidates:
            if not isinstance(name, str) or not name:
                continue
            identity = call_id or (name, json.dumps(arguments, sort_keys=True, default=str))
            if identity in seen:
                continue
            seen.add(identity)
            calls.append({"name": name, "arguments": _arguments(arguments)})
    return calls


def _session_id_from_stream(protocol: str, stdout: str) -> str | None:
    """The resumable conversation identifier emitted by a signed-in CLI."""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        if protocol == "codex-jsonl":
            value = event.get("thread_id") if event.get("type") == "thread.started" else None
        elif protocol == "claude-stream-json":
            value = event.get("session_id")
        else:
            value = None
        if value:
            return str(value)
    return None


def _contains_subsequence(values: list[str], wanted: tuple[str, ...]) -> bool:
    position = 0
    for value in values:
        if position < len(wanted) and value == wanted[position]:
            position += 1
    return position == len(wanted)


def score_tool_calls(scenario, calls):
    """Apply user-experience gates to an observed MCP call sequence."""
    names = [call["name"] for call in calls]
    reasons = []
    if len(names) > scenario.max_calls:
        reasons.append(
            f"{len(names)} MCP calls exceeded the limit of {scenario.max_calls}"
        )
    unexpected = sorted(set(names) - ASSISTANT_TOOLS - MCP_PROTOCOL_HELPERS)
    if unexpected:
        reasons.append("expert-only tools were used: " + ", ".join(unexpected))
    forbidden = sorted(set(names) & set(scenario.forbidden_tools))
    if forbidden:
        reasons.append("forbidden tools were used: " + ", ".join(forbidden))
    if not _contains_subsequence(names, scenario.required_subsequence):
        reasons.append(
            "required tool order not observed: "
            + " -> ".join(scenario.required_subsequence)
        )
    for tool, argument, allowed in scenario.tool_argument_constraints:
        for call in calls:
            if call["name"] != tool:
                continue
            value = call["arguments"].get(argument)
            if value not in allowed:
                choices = " or ".join(
                    "omitted" if item is None else str(item) for item in allowed
                )
                reasons.append(
                    f"{tool}.{argument} used {value!r}; allowed: {choices}"
                )
    return {"passed": not reasons, "reasons": reasons}


def score_answer(scenario: EvalScenario, answer: str) -> list[str]:
    """Name required scientific concepts missing from the final answer."""
    folded = answer.casefold()
    reasons = [
        "agent answer omitted required concept: " + " | ".join(alternatives)
        for alternatives in scenario.required_answer_concepts
        if not any(term.casefold() in folded for term in alternatives)
    ]
    for triggers, alternatives in scenario.conditional_answer_concepts:
        if (
            any(term.casefold() in folded for term in triggers)
            and not any(term.casefold() in folded for term in alternatives)
        ):
            reasons.append(
                "agent answer omitted required concept: "
                + " | ".join(alternatives)
            )
    reasons.extend(
        "agent answer included forbidden concept after failure: " + term
        for term in scenario.forbidden_answer_concepts
        if term.casefold() in folded
    )
    return reasons


def evaluate_stream(scenario, protocol, stdout, *, returncode):
    lines = stdout.splitlines()
    calls = extract_tool_calls(lines, protocol)
    final_answer = ""
    for line in lines:
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        if protocol == "codex-jsonl":
            item = event.get("item")
            if (
                event.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "agent_message"
                and item.get("text")
            ):
                final_answer = str(item["text"]).strip()
        elif protocol == "claude-stream-json":
            if event.get("type") == "result" and event.get("result"):
                final_answer = str(event["result"]).strip()
    reasons = []
    if returncode:
        reasons.append(f"agent process exited with code {returncode}")
    if not final_answer:
        reasons.append("agent returned no final answer")
    folded_answer = final_answer.casefold()
    for fragment, label in _UNAVAILABLE_FRAGMENTS:
        if fragment in folded_answer:
            reasons.append(f"agent unavailable: {label}")
            return {
                "passed": False,
                "reasons": reasons,
                "tool_calls": calls,
                "final_answer": final_answer,
            }
    for line in lines:
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and block.get("is_error") is True
                ):
                    detail = str(block.get("content", "tool failed")).strip()
                    reasons.append("tool error: " + detail[:500])
        item = event.get("item")
        if (
            isinstance(item, dict)
            and item.get("type") == "mcp_tool_call"
            and item.get("error")
        ):
            reasons.append("tool error: " + str(item["error"])[:500])
    for fragment in _REFUSAL_FRAGMENTS:
        if fragment.casefold() in folded_answer:
            reasons.append(f"agent answer indicates refusal: {fragment}")
            break
    reasons.extend(score_answer(scenario, final_answer))
    sequence = score_tool_calls(scenario, calls)
    reasons.extend(sequence["reasons"])
    return {
        "passed": not reasons,
        "reasons": reasons,
        "tool_calls": calls,
        "final_answer": final_answer,
    }


def evaluate_conversation_streams(
    scenario: EvalScenario,
    protocol: str,
    streams: list[tuple[str, int]],
) -> dict:
    """Score every turn and require a real resumable session between them."""
    turns = []
    reasons = []
    current: EvalScenario | None = scenario
    session_id: str | None = None
    turn_number = 1
    for stdout, returncode in streams:
        if current is None:
            break
        evaluated = evaluate_stream(
            current, protocol, stdout, returncode=returncode
        )
        evaluated = {
            "name": current.name,
            "prompt": current.prompt,
            **evaluated,
        }
        turns.append(evaluated)
        reasons.extend(
            f"turn {turn_number}: {reason}" for reason in evaluated["reasons"]
        )
        if current.follow_up is not None and session_id is None:
            session_id = _session_id_from_stream(protocol, stdout)
            if session_id is None:
                reasons.append(
                    f"turn {turn_number} did not emit a resumable session id"
                )
        current = current.follow_up
        turn_number += 1

    while current is not None:
        reasons.append(f"turn {turn_number} was not run")
        current = current.follow_up
        turn_number += 1

    return {
        "passed": not reasons,
        "reasons": reasons,
        "turns": turns,
        "session_id": session_id,
    }


def _payload(value=None, *, error=None, log="") -> dict:
    return {
        "json values": [] if value is None else [value],
        "python values": [],
        "log messages": {"info": [log]} if log else {},
        "error": error,
    }


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))


def _preview_png(width: int, height: int, *, cropped: bool = False) -> bytes:
    """A deterministic interface-like PNG, large enough for visual validation."""
    width = max(1, min(width, 3000))
    height = max(1, min(height, 3000))
    if cropped:
        left_x, right_x = width * 5 // 4, width * 3 // 2
        radius_x = max(1, width // 2)
    else:
        left_x, right_x = width * 2 // 5, width * 3 // 5
        radius_x = max(1, width // 4)
    center_y = height // 2
    radius_y = max(1, height // 3)
    hotspot_radius = max(3, min(width, height) // 45)
    hotspots = [] if cropped else [
        (width // 2, height * fraction // 10) for fraction in (3, 4, 5, 6, 7)
    ]
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            left = (
                (x - left_x) ** 2 * radius_y**2
                + (y - center_y) ** 2 * radius_x**2
                <= radius_x**2 * radius_y**2
            )
            right = (
                (x - right_x) ** 2 * radius_y**2
                + (y - center_y) ** 2 * radius_x**2
                <= radius_x**2 * radius_y**2
            )
            hotspot = any(
                (x - hx) ** 2 + (y - hy) ** 2 <= hotspot_radius**2
                for hx, hy in hotspots
            )
            if hotspot:
                colour = (211, 47, 47)
            elif left and right:
                colour = (126, 87, 194)
            elif left:
                colour = (66, 133, 244)
            elif right:
                colour = (255, 167, 38)
            else:
                colour = (246, 247, 250)
            raw.extend(colour)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
        + _png_chunk(b"IEND", b"")
    )


def _option(tokens: list[str], name: str, default):
    try:
        return tokens[tokens.index(name) + 1]
    except (ValueError, IndexError):
        return default


class _ScenarioBackend:
    def __init__(self, fixture: str = "experimental"):
        self.fixture = fixture
        self.interface_ready = False
        self.commands = []
        self.created_paths: set[Path] = set()

    def _write(self, target: Path, payload: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target not in self.created_paths:
            raise FileExistsError(f"eval fixture will not overwrite {target}")
        target.write_bytes(payload)
        self.created_paths.add(target)

    def _write_preview(self, target: Path, width: int, height: int) -> None:
        self._write(
            target,
            _preview_png(
                width,
                height,
                cropped=self.fixture == "cropped-preview",
            ),
        )

    def run(self, command: str) -> dict:  # noqa: PLR0911 - explicit protocol fixture
        self.commands.append(command)
        if command in {"version", "usage molcompose"}:
            return _payload(log="MolCompose command available")
        if command.startswith("molcompose source "):
            return _payload()
        if command == "info models":
            if self.fixture == "recoverable-failure":
                return _payload(error={
                    "type": "UserError",
                    "message": (
                        "Temporary ChimeraX bridge interruption; "
                        "retry inspect_session."
                    ),
                })
            if self.fixture == "ambiguous-models":
                return _payload([
                    {
                        "spec": "#1",
                        "value": "candidate-1.pdb",
                        "class": "AtomicStructure",
                    },
                    {
                        "spec": "#2",
                        "value": "candidate-2.pdb",
                        "class": "AtomicStructure",
                    },
                ])
            return _payload([{
                "spec": "#1", "value": "1brs.pdb", "class": "AtomicStructure"
            }])
        if command == "info chains":
            if self.fixture == "ambiguous-models":
                return _payload([
                    {
                        "spec": f"#{model}/{chain}",
                        "value": chain,
                        "polymer type": "protein",
                        "sequence": "A" * length,
                    }
                    for model in (1, 2)
                    for chain, length in (("A", 110), ("D", 89))
                ])
            return _payload([
                {
                    "spec": "#1/A",
                    "value": "A",
                    "polymer type": "protein",
                    "sequence": "A" * 110,
                },
                {
                    "spec": "#1/D",
                    "value": "D",
                    "polymer type": "protein",
                    "sequence": "A" * 89,
                },
            ])
        if command.startswith("toolshed list installed"):
            return _payload(log="MolCompose (0.1.2)")
        if command.startswith("molcompose capabilities"):
            reason = (
                "experimental structure: B-factors are temperature factors, "
                "not prediction confidence"
            )
            return _payload({
                "kind": "experimental",
                "detail": "X-RAY DIFFRACTION",
                "available": ["interface", "interactions", "buried_area", "affinity"],
                "unavailable": {
                    metric: reason
                    for metric in ("pLDDT", "ipLDDT", "pDockQ", "ipSAE", "pDockQ2", "LIS")
                },
            })
        if command.startswith("molcompose blocks"):
            if not self.interface_ready:
                return _payload(error={
                    "type": "UserError",
                    "message": "Detect an interface first for model #1",
                })
            return _payload([
                {"kind": "groupA", "name": "groupA", "label": "Group A", "count": 110},
                {"kind": "groupB", "name": "groupB", "label": "Group B", "count": 89},
                {"kind": "ifaceA", "name": "ifaceA", "label": "Interface A", "count": 19},
                {"kind": "ifaceB", "name": "ifaceB", "label": "Interface B", "count": 16},
            ])
        if command.startswith("molcompose characterise"):
            self.interface_ready = True
            tokens = shlex.split(command)
            cutoff = float(_option(tokens, "distance", 4.5))
            return _payload({
                "model": "#1",
                "steps": ["interface", "interactions", "buried_area", "affinity"],
                "skipped": {
                    "confidence": "experimental structure",
                    "interface_scores": "no PAE file applies to this structure",
                },
                "interface": {
                    "chains_a": ["A"],
                    "chains_b": ["D"],
                    "criterion": "heavy",
                    "cutoff": cutoff,
                    "residues_a": 19,
                    "residues_b": 16,
                    "contact_pairs": 43,
                },
                "interactions": {
                    "salt_bridges": 2,
                    "hydrogen_bonds": 8,
                    "hydrophobic_contacts": 14,
                },
                "buried_area": 937.5757528846134,
                "affinity": {"delta_g_kcal_mol": -12.4, "kd_molar": 8.1e-10},
            })
        if command.startswith("molcompose style "):
            return _payload(["hide", "cartoon", "view"])
        if command.startswith("molcompose export "):
            try:
                tokens = shlex.split(command)
                target = Path(tokens[2])
                width = int(_option(tokens, "width", 2400))
                height = int(_option(tokens, "height", 1800))
                self._write_preview(target, width, height)
                if str(_option(tokens, "saveRecipe", "false")).lower() == "true":
                    self._write(
                        target.with_suffix(".cxc"),
                        (
                            b"molcompose interface A D model #1 distance 4.5\n"
                            b"molcompose style hotspot-focus model #1 labels 6\n"
                        ),
                    )
                if str(_option(tokens, "saveSession", "false")).lower() == "true":
                    self._write(target.with_suffix(".cxs"), b"MolCompose eval session\n")
                # export_figure writes this sidecar after the REST command returns.
                self.created_paths.add(target.with_suffix(".provenance.json"))
            except (IndexError, OSError, ValueError) as error:
                return _payload(error={"type": "UserError", "message": str(error)})
            return _payload(log=f"Exported {target}")
        if command.startswith("save "):
            try:
                tokens = shlex.split(command)
                target = Path(tokens[1])
                width = int(_option(tokens, "width", 800))
                height = int(_option(tokens, "height", 800))
                self._write_preview(target, width, height)
            except (IndexError, OSError, ValueError) as error:
                return _payload(error={"type": "UserError", "message": str(error)})
            return _payload(log=f"Saved {target}")
        if command.startswith("molcompose interface all"):
            return _payload([{"chain_a": "A", "chain_b": "D", "contacts": 43}])
        return _payload(error={
            "type": "UserError",
            "message": f"The eval fixture does not support: {command}",
        })


class ScenarioRestServer:
    def __init__(self, fixture: str = "experimental"):
        self.backend = _ScenarioBackend(fixture)
        backend = self.backend

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
                query = parse_qs(urlparse(self.path).query)
                command = query.get("command", [""])[0]
                body = json.dumps(backend.run(command)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self):
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_args):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
        for path in self.backend.created_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _repository_imports():
    """Load the Qt-independent panel adapters without importing ChimeraX."""
    package_name = "_molcompose_eval_core"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(REPOSITORY_ROOT / "src" / "core")]
        package.__package__ = package_name
        sys.modules[package_name] = package
    agent_cli = importlib.import_module(f"{package_name}.agent_cli")
    agent_session = importlib.import_module(f"{package_name}.agent_session")

    get_agent = agent_cli.get_agent
    locate = agent_cli.locate
    write_mcp_config = agent_cli.write_mcp_config
    TurnContext = agent_session.TurnContext
    adapter_for = agent_session.adapter_for
    redact_sensitive_text = agent_session.redact_sensitive_text
    AgentConversation = agent_session.AgentConversation

    return (
        get_agent,
        locate,
        write_mcp_config,
        TurnContext,
        adapter_for,
        redact_sensitive_text,
        AgentConversation,
    )


def _follow_up_turn(
    adapter,
    context,
    scenario: EvalScenario,
    first_stdout: str,
    conversation_type,
):
    """Build the next process from the first process's real session id."""
    if scenario.follow_up is None:
        return None
    session_id = _session_id_from_stream(adapter.protocol, first_stdout)
    if session_id is None:
        return None
    conversation = conversation_type(
        context.agent.key,
        session_id,
        0,
        context.binding,
    )
    return adapter.resume_turn(scenario.follow_up.prompt, conversation, context)


def _decoded(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _version(executable: str) -> str:
    result = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return (result.stdout or result.stderr).strip()


def _run_cli_turn(turn, *, timeout: float, pythonpath: str, redact) -> dict:
    """Run one disposable CLI process and retain its protocol evidence."""
    started = time.monotonic()
    try:
        process = subprocess.run(
            turn.argv,
            input=turn.stdin,
            capture_output=True,
            cwd=REPOSITORY_ROOT,
            env={**os.environ, "NO_COLOR": "1", "PYTHONPATH": pythonpath},
            timeout=timeout,
            check=False,
        )
        returncode = process.returncode
        stdout = _decoded(process.stdout)
        stderr = redact(_decoded(process.stderr))
        timed_out = False
    except subprocess.TimeoutExpired as error:
        returncode = 124
        stdout = _decoded(error.stdout)
        stderr = redact(_decoded(error.stderr))
        timed_out = True
    return {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def _should_run_follow_up(current: EvalScenario, outcome: dict) -> bool:
    """A failed disposable process must not consume another agent turn."""
    return (
        current.follow_up is not None
        and outcome["returncode"] == 0
        and not outcome["timed_out"]
    )


def run_agent_scenario(
    agent_key: str,
    scenario: EvalScenario,
    *,
    server_executable: str,
    timeout: float,
) -> dict:
    """Run one signed-in CLI against a fresh deterministic REST scenario."""
    (
        get_agent,
        locate,
        write_mcp_config,
        TurnContext,
        adapter_for,
        redact_sensitive_text,
        AgentConversation,
    ) = _repository_imports()
    agent = get_agent(agent_key)
    executable = locate(agent.executable)
    if not executable:
        return {
            "agent": agent_key,
            "scenario": scenario.name,
            "passed": False,
            "reasons": [f"{agent.executable} executable was not found"],
            "tool_calls": [],
            "final_answer": "",
        }

    with ScenarioRestServer(
        fixture=scenario.fixture
    ) as rest, tempfile.TemporaryDirectory(prefix="molcompose-agent-eval-") as folder:
        folder_path = Path(folder)
        config_path = folder_path / "mcp.json"
        answer_path = folder_path / "answer.md"
        if agent.supports_mcp_config:
            write_mcp_config(
                config_path,
                server_executable,
                rest.url,
                source=f"agent:eval-{agent_key}",
            )
            configured = str(config_path)
        else:
            configured = None
        context = TurnContext(
            agent=agent,
            executable=executable,
            config_path=configured,
            answer_path=str(answer_path) if agent.final_message_arguments else None,
            server_executable=server_executable,
            chimerax_url=rest.url,
            source=f"agent:eval-{agent_key}",
        )
        adapter = adapter_for(agent)
        turn = adapter.start_turn(scenario.prompt, context)
        started = time.monotonic()
        inherited_pythonpath = os.environ.get("PYTHONPATH", "")
        pythonpath = str(REPOSITORY_ROOT / "mcp")
        if inherited_pythonpath:
            pythonpath += os.pathsep + inherited_pythonpath
        outcomes = []
        streams = []
        current: EvalScenario | None = scenario
        while current is not None:
            outcome = _run_cli_turn(
                turn,
                timeout=timeout,
                pythonpath=pythonpath,
                redact=redact_sensitive_text,
            )
            outcomes.append(outcome)
            streams.append((outcome["stdout"], outcome["returncode"]))
            if not _should_run_follow_up(current, outcome):
                break
            following = _follow_up_turn(
                adapter,
                context,
                current,
                outcome["stdout"],
                AgentConversation,
            )
            if following is None:
                break
            turn = following
            current = current.follow_up

        if scenario.follow_up is None:
            evaluated = evaluate_stream(
                scenario,
                adapter.protocol,
                outcomes[0]["stdout"],
                returncode=outcomes[0]["returncode"],
            )
            turns = None
            session_id = None
        else:
            conversation = evaluate_conversation_streams(
                scenario,
                adapter.protocol,
                streams,
            )
            evaluated = {
                "passed": conversation["passed"],
                "reasons": conversation["reasons"],
                "tool_calls": [
                    call
                    for evaluated_turn in conversation["turns"]
                    for call in evaluated_turn["tool_calls"]
                ],
                "final_answer": (
                    conversation["turns"][-1]["final_answer"]
                    if conversation["turns"]
                    else ""
                ),
            }
            turns = conversation["turns"]
            session_id = conversation["session_id"]
        for index, outcome in enumerate(outcomes, start=1):
            if outcome["timed_out"]:
                label = f"turn {index}: " if scenario.follow_up else ""
                evaluated["reasons"].insert(
                    0, f"{label}agent exceeded {timeout:g} seconds"
                )
                evaluated["passed"] = False

        result = {
            "agent": agent_key,
            "agent_version": _version(executable),
            "scenario": scenario.name,
            "prompt": scenario.prompt,
            "passed": evaluated["passed"],
            "reasons": evaluated["reasons"],
            "tool_calls": evaluated["tool_calls"],
            "final_answer": evaluated["final_answer"],
            "returncode": outcomes[-1]["returncode"],
            "duration_seconds": round(time.monotonic() - started, 3),
            "stderr_tail": (
                ""
                if evaluated["passed"]
                else "\n".join(outcome["stderr"] for outcome in outcomes)[-2000:]
            ),
            "backend_commands": rest.backend.commands,
        }
        if turns is not None:
            result["turns"] = turns
            result["session_id"] = session_id
            result["returncodes"] = [
                outcome["returncode"] for outcome in outcomes
            ]
        return result


def run_evaluation(
    agent_keys: list[str],
    scenarios: list[EvalScenario],
    *,
    server_executable: str,
    timeout: float,
) -> dict:
    results = [
        run_agent_scenario(
            agent_key,
            scenario,
            server_executable=server_executable,
            timeout=timeout,
        )
        for agent_key in agent_keys
        for scenario in scenarios
    ]
    scenario_by_name = {scenario.name: scenario for scenario in scenarios}
    for result in results:
        scenario = scenario_by_name[result["scenario"]]
        expected_turns = 0
        current: EvalScenario | None = scenario
        while current is not None:
            expected_turns += 1
            current = current.follow_up
        if (
            result["passed"]
            and expected_turns > 1
            and len(result.get("turns", ())) != expected_turns
        ):
            result["passed"] = False
            result.setdefault("reasons", []).append(
                "multiturn scenario did not run every turn"
            )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mcp_profile": "assistant",
        "passed": all(result["passed"] for result in results),
        "results": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run real signed-in agent CLIs against deterministic MolCompose "
            "assistant-profile scenarios. This may use model quota."
        )
    )
    parser.add_argument(
        "--agent",
        action="append",
        choices=("claude", "codex"),
        help="CLI to evaluate; repeat for both (default: both)",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=tuple(scenario.name for scenario in DEFAULT_SCENARIOS),
        help="Scenario to run; repeat as needed (default: all)",
    )
    parser.add_argument(
        "--server-executable",
        help="molcompose-mcp executable (default: auto-detect)",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--output", type=Path, help="Write the JSON report here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    server = args.server_executable or shutil.which("molcompose-mcp")
    if not server:
        candidate = Path(sys.executable).with_name("molcompose-mcp")
        server = str(candidate) if candidate.is_file() else None
    if not server:
        raise SystemExit(
            "molcompose-mcp was not found; install it or pass --server-executable"
        )
    selected = set(args.scenario or ())
    scenarios = [
        scenario
        for scenario in DEFAULT_SCENARIOS
        if not selected or scenario.name in selected
    ]
    report = run_evaluation(
        args.agent or ["claude", "codex"],
        scenarios,
        server_executable=server,
        timeout=args.timeout,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
