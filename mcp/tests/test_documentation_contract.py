import re
from pathlib import Path

from molcompose_mcp.server import NATIVE_WHITELIST

ROOT = Path(__file__).parents[2]
MCP_README = ROOT / "mcp" / "README.md"
ROOT_README = ROOT / "README.md"
MCP_REFERENCE = ROOT / "docs" / "mcp-reference.md"
PACKAGED_SKILL = ROOT / "mcp" / "molcompose_mcp" / "SKILL.md"
SOURCE_SKILL = ROOT / "skill" / "SKILL.md"

ASSISTANT_TOOLS = {
    "open_structure",
    "inspect_session",
    "analyse_interface",
    "compose_figure",
    "render_preview",
    "export_artifact",
    "load_external_evidence",
}


def _documented_native_verbs(text: str) -> set[str]:
    match = re.search(r"Current native verbs:\s*([^\n]+)", text)
    assert match, "MCP reference must carry a machine-checked native verb line"
    return set(re.findall(r"`([^`]+)`", match.group(1)))


def test_mcp_readme_matches_the_registered_safety_and_assistant_contract():
    text = MCP_README.read_text(encoding="utf-8")
    assert "https://github.com/ChiaChunL/MolCompose/blob/main/docs/mcp-reference.md" in text
    reference = MCP_REFERENCE.read_text(encoding="utf-8")

    assert _documented_native_verbs(reference) == set(NATIVE_WHITELIST)
    assert "`open`, `close`" not in text
    assert ASSISTANT_TOOLS <= set(re.findall(r"`([a-z_]+)`", text))
    assert "## Assistant workflow" in text
    assert "## Troubleshooting" in text
    for term in ("`raw`", "`display`", 'recipe_scope: "session"', "process", "unknown"):
        assert term in reference


def test_docs_do_not_call_process_local_history_complete_or_scientifically_verified():
    mcp_text = MCP_README.read_text(encoding="utf-8")
    root_text = ROOT_README.read_text(encoding="utf-8")

    assert "complete provenance record" not in mcp_text.lower()
    assert "full command recipe" not in mcp_text.lower()
    assert "operations it verified" not in root_text.lower()
    assert "follow-up" in root_text.lower()


def test_skill_copies_remain_byte_identical_and_name_the_assistant_entrypoint():
    packaged = PACKAGED_SKILL.read_bytes()
    source = SOURCE_SKILL.read_bytes()

    assert packaged == source
    text = packaged.decode("utf-8")
    assert "`inspect_session`" in text
    assert "`analyse_interface`" in text
    assert "`display`" in text and "`raw`" in text


def test_mcp_readme_preserves_the_existing_stdio_invocation():
    text = MCP_README.read_text(encoding="utf-8")
    assert "molcompose-mcp --chimerax-url http://127.0.0.1:3000" in text
    assert '"command": "molcompose-mcp"' in text
    assert "--profile assistant" in text
    assert "--profile expert" in text
    assert "native image content" in MCP_REFERENCE.read_text(encoding="utf-8")


def test_readmes_link_download_statistics_separately_from_package_installation():
    root = ROOT_README.read_text(encoding="utf-8")
    mcp = MCP_README.read_text(encoding="utf-8")

    shared_badges = (
        "img.shields.io/pypi/v/molcompose-mcp",
        "img.shields.io/pypi/pyversions/molcompose-mcp",
    )
    for badge in shared_badges:
        assert badge in root
        assert badge in mcp
    assert "img.shields.io/github/downloads/" not in root
    assert "visitor-badge.laobi.icu" not in root
    for text in (root, mcp):
        assert "img.shields.io/pypi/dm/molcompose-mcp" not in text
        assert "pypistats.org" not in text
        assert "https://pepy.tech/projects/molcompose-mcp" in text
        downloads = re.findall(
            r'<a href="([^"]+)"><img alt="[^"]*[Dd]ownloads[^"]*" src="([^"]+)"', text
        )
        assert any(
            target == "https://pepy.tech/projects/molcompose-mcp" and "pepy.tech/" in source
            for target, source in downloads
        )


def test_root_readme_decorations_preserve_section_links():
    text = ROOT_README.read_text(encoding="utf-8")
    for anchor, heading in (
        ("overview", "🔬 Overview"),
        ("installation", "📦 Installation"),
        ("quick-start", "🚀 Quick start"),
        ("agent-access", "🤖 Agent access"),
        ("screenshots", "🖼️ Screenshots"),
        ("data-and-license", "🧪 Data and license"),
        ("citation", "📄 Citation"),
    ):
        assert f'<a id="{anchor}"></a>\n\n## {heading}' in text
    for heading in ("This checkout", "External MCP setup prompt", "Verification prompt"):
        assert f"### {heading}" in text
    assert "A manuscript describing MolCompose has been submitted." in text


def test_mcp_copyable_configuration_matches_the_cli_parser(monkeypatch, capsys):
    import json
    import sys

    from molcompose_mcp.server import main

    text = MCP_README.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
    configurations = [json.loads(block) for block in blocks if '"mcpServers"' in block]
    assert len(configurations) == 1
    entry = configurations[0]["mcpServers"]["molcompose"]
    monkeypatch.setattr(sys, "argv", [entry["command"], *entry["args"], "--print-config"])
    main()
    actual = json.loads(capsys.readouterr().out)["mcpServers"]["molcompose"]
    assert actual["args"] == [
        "--chimerax-url", "http://127.0.0.1:3000", "--profile", "assistant",
    ]
