from pathlib import Path

ROOT = Path(__file__).parents[2]

COMMAND_NAMES = (
    "molcompose style",
    "molcompose interface",
    "molcompose interface all",
    "molcompose focus",
    "molcompose export",
    "molcompose reset",
)


def test_installed_help_pages_exist():
    assert (ROOT / "src/docs/user/commands/molcompose.html").is_file()
    assert (ROOT / "src/docs/user/tools/molcompose.html").is_file()


def test_readme_documents_every_command():
    readme = (ROOT / "README.md").read_text()
    for name in COMMAND_NAMES:
        assert name in readme, name


def test_contributing_states_public_layout_and_governance():
    contributing = (ROOT / "CONTRIBUTING.md").read_text()
    # The published top level. `scripts/` was here until the build tools and
    # the figure pipeline moved out of the repository; a list that still named
    # it would have this test insisting on a directory that no longer ships.
    for directory in ("docs", "examples", "mcp", "src", "tests"):
        assert directory in contributing
    assert "utils.py" in contributing  # vague-module prohibition
    assert "public purpose" in contributing


def test_smoke_script_covers_reference_structures_and_commands():
    script = (ROOT / "tests/integration/molcompose_smoke.cxc").read_text().lower()
    assert "1crn" in script
    assert "1brs" in script
    assert "molcompose style" in script
    assert "molcompose interface" in script
    assert "molcompose export" in script


# A menu path is not the name of anything in the panel; it is checked against
# pyproject.toml instead, by the test below.
def _menu_path_names(page: str) -> set[str]:
    import html
    import re

    return {
        re.sub(r"\s+", " ", html.unescape(match)).strip()
        for match in re.findall(r"<b>([^<]*&rarr;[^<]*)</b>", page, re.S)
    }


def _panel_names() -> set[str]:
    """Every string the panel puts in front of a user.

    Read out of the source rather than by building the widgets, so the test
    runs without Qt and without ChimeraX.
    """
    import re

    source = (ROOT / "src/ui/tool.py").read_text()
    names = {"Compose", "Interface", "Export", "Agent"}
    for pattern in (
        r'QPushButton\(\s*"([^"]{2,70})"',
        r'QLabel\(\s*"([^"]{2,70})"',
        r'QCheckBox\(\s*"([^"]{2,70})"',
        r'QGroupBox\(\s*"([^"]{2,70})"',
        r'setTitle\(\s*"([^"]{2,70})"',
        r'_card\(\s*"([^"]{2,70})"',
        # The small headings inside a card — PRINT SIZE, SUPERSAMPLE — are the
        # panel's own words too, and were the one kind this missed.
        r'_section\(\s*"([^"]{2,70})"',
        r'addItem\(\s*"([^"]{2,70})"',
        # Disclosure labels are built empty and filled by `setText`, so an
        # entire class of panel wording — every "▸ …" fold — was invisible
        # here. The help page could name one and this test would call it a
        # name the panel does not use.
        r'setText\(\s*"([^"]{2,70})"',
        # A fold's two labels sit in a conditional expression, so only the
        # first branch follows `setText(` directly. They all start with the
        # arrow, which is what makes them findable wherever they sit.
        r'"[\u25b8\u25be]\s*([^"]{2,70})"',
        r'\(\s*"([^"]{2,70})",\s*"[a-z_]+"\)',
    ):
        names.update(
            # The arrow is decoration on a fold, not part of the name.
            match.strip().lstrip("▸▾ ").strip()
            for match in re.findall(pattern, source)
        )

    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    import chimerax_stubs

    chimerax_stubs.install()
    from src.core.presets import PRESETS

    names.update(preset.display_name for preset in PRESETS.values())
    return names


def test_the_help_page_calls_things_what_the_panel_calls_them():
    """Names in the tool help must exist in the panel.

    The Toolshed reviewer who approved the bundle found the help page naming
    "Current Structure", "Detect Interface" and "Export PNG" for what the
    panel by then called Structure, Detect and Export Image: the interface had
    raced ahead of its documentation. A person reading the help cannot tell a
    renamed button from a missing one, so this fails the build instead.

    The convention it rests on: in the tool help, <b> means "this is what the
    panel says". A method or software name -- somebody else's, and appearing
    nowhere in the interface -- is <em>.
    """
    import html
    import re

    page = (ROOT / "src/docs/user/tools/molcompose.html").read_text()
    named = {
        re.sub(r"\s+", " ", html.unescape(match)).strip()
        for match in re.findall(r"<b>([^<]{2,70})</b>", page, re.S)
    }
    panel = _panel_names()
    unknown = sorted(
        name for name in named - _menu_path_names(page)
        if name not in panel and not any(name in label for label in panel)
    )
    assert not unknown, (
        "the tool help names these, and the panel does not: " + ", ".join(unknown)
    )


def test_the_command_page_documents_every_registered_subcommand():
    """A command ChimeraX accepts and the help does not mention is invisible.

    `blocks`, `color by` and `source` were all registered and all missing when
    the Toolshed reviewer wrote about the tool page; nobody had looked at the
    command page. The registry that matters is `pyproject.toml` — see
    test_bundle_metadata — so that is what this reads.
    """
    import re

    page = (ROOT / "src/docs/user/commands/molcompose.html").read_text()
    declared = set(re.findall(
        r'^\[tool\.chimerax\.command\."(molcompose [a-z0-9 ]+)"\]',
        (ROOT / "pyproject.toml").read_text(), re.M,
    ))
    assert declared, "no commands found in pyproject.toml"
    missing = sorted(name for name in declared if name not in page)
    assert not missing, "registered but undocumented: " + ", ".join(missing)


def test_the_command_page_documents_every_export_keyword():
    """An export option nobody can find is an option nobody has."""
    import re

    page = (ROOT / "src/docs/user/commands/molcompose.html").read_text()
    source = (ROOT / "src/commands.py").read_text()
    block = source[source.index('"molcompose export": ('):]
    keywords = re.findall(r'\("(\w+)",\s*\w+Arg\)', block[:block.index("synopsis")])
    assert "keyFontSize" in keywords, "the export block moved; fix this test"
    missing = sorted(name for name in keywords if name not in page)
    assert not missing, "export takes these and the help omits them: " + ", ".join(missing)


def test_the_help_page_puts_the_panel_in_the_menu_it_is_actually_in():
    """The help said Tools → Depiction long after the panel moved.

    The category in pyproject.toml is what ChimeraX reads, so it is what this
    reads too: the panel sits under Structure Analysis, where someone looking
    for interface analysis looks first, and a help page that sends them to
    Depiction sends them to an empty menu.
    """
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    category = data["tool"]["chimerax"]["tool"]["MolCompose"]["category"]
    page = (ROOT / "src/docs/user/tools/molcompose.html").read_text()
    paths = _menu_path_names(page)
    assert paths, "the help no longer says where the panel is in the menu"
    for path in paths:
        assert category in path, f"help says {path!r}, pyproject says {category!r}"


def test_the_help_page_s_images_ship_and_exist():
    """Non-code files are shipped only if declared: a help page whose image is
    not in package-data renders a broken icon on every machine but this one."""
    import re
    import tomllib

    page_dir = ROOT / "src/docs/user/tools"
    page = (page_dir / "molcompose.html").read_text()
    images = re.findall(r'<img[^>]+src="([^"]+)"', page)
    assert images, "the tool help no longer shows the panel"
    for name in images:
        assert (page_dir / name).is_file(), f"help references a missing image: {name}"

    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())
    patterns = declared["tool"]["chimerax"]["package-data"]["src/docs"]
    assert any(pattern.endswith(".png") for pattern in patterns), (
        "the help now has images and src/docs still ships only HTML"
    )


def test_no_published_text_claims_the_agent_is_confined():
    """A claim this project withdrew, and the REST bridge is why.

    The panel, the help page and the README all said an agent "cannot modify
    coordinates or run arbitrary ChimeraX commands". While the bridge is up
    ChimeraX accepts commands on 127.0.0.1 without authentication, from the
    agent and from anything else on the machine, so the confinement was never
    the tool's to promise. The honest form is what the panel says now: the
    commands are validated and logged, and the panel reports what it verified
    rather than the agent's account of it.

    Checked across everything that ships, because the sentence was corrected
    in the panel first and survived in two other files for weeks.
    """
    withdrawn = (
        "cannot modify coordinates",
        "arbitrary ChimeraX commands",
        "can only use the same validated",
    )
    offenders = []
    for path in sorted(ROOT.glob("**/*.md")) + sorted(ROOT.glob("src/**/*.html")):
        # Only what ships. `internal/` is excluded from git, `.claude/` and
        # `.worktrees/` are local scratch, and a stale copy of the manuscript
        # under one of them is not published text.
        if not {"internal", ".worktrees", ".claude", "build", "dist"}.isdisjoint(
            path.parts
        ):
            continue
        text = path.read_text(errors="replace")
        for phrase in withdrawn:
            if phrase in text:
                offenders.append(f"{path.name}: {phrase}")
    assert not offenders, offenders


def test_no_document_points_at_an_example_that_is_not_there():
    """The examples were three complete cases and are now one.

    Trimming them to what a person can clone in a minute meant deleting 102
    files, and every path in the README, the examples guide and the tool help
    that named one of them became a broken promise — a command block that
    cannot run, in the document whose whole job is to be runnable. The full
    dataset moved to Zenodo, so this will happen again the next time the split
    is adjusted.
    """
    import re

    documents = list(ROOT.glob("*.md")) + list((ROOT / "examples").glob("*.md"))
    documents += list((ROOT / "docs").glob("*.md"))
    documents += list((ROOT / "src/docs").rglob("*.html"))

    missing = []
    for document in documents:
        for path in re.findall(r"examples/data/[A-Za-z0-9_/.\-]+", document.read_text()):
            if not (ROOT / path).exists():
                missing.append(f"{document.relative_to(ROOT)} -> {path}")
    assert not missing, (
        "documents naming example files that do not exist:\n  "
        + "\n  ".join(missing)
    )
