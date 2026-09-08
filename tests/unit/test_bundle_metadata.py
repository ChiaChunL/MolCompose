import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_pyproject_declares_one_pure_chimerax_bundle():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["build-system"]["build-backend"] == "chimerax.bundle_builder.cx_pep517"
    assert data["project"]["name"] == "ChimeraX-MolCompose"
    assert data["tool"]["chimerax"]["pure"] is True
    assert data["tool"]["chimerax"]["module-name-override"] == "molcompose"
    assert not (ROOT / "bundle_info.xml").exists()


def test_pyproject_declares_all_public_commands_and_tool():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    commands = data["tool"]["chimerax"]["command"]
    assert set(commands) == {
        "molcompose",
        "molcompose style",
        "molcompose interface",
        "molcompose interface all",
        "molcompose blocks",
        "molcompose focus",
        "molcompose export",
        "molcompose capabilities",
        "molcompose color by",
        "molcompose energy",
        "molcompose flexibility",
        "molcompose confidence",
        "molcompose affinity",
        "molcompose buriedarea",
        "molcompose characterise",
        "molcompose ddg",
        "molcompose dockq",
        "molcompose hotspots",
        "molcompose report",
        "molcompose interactions",
        "molcompose ipsae",
        "molcompose contacts",
        "molcompose hbonds",
        "molcompose reset",
        "molcompose source",
        "molcompose seqcolor",
    }
    assert set(data["tool"]["chimerax"]["tool"]) == {"MolCompose"}


def test_the_installed_version_and_the_reported_version_are_the_same():
    """One fact, two files, and nothing keeping them equal until now.

    `pyproject.toml` decides which version the Toolshed serves and which one
    ChimeraX offers as an update. `src/__init__.py` decides the string that
    goes into every provenance record and Methods paragraph. Bump one and
    forget the other and a figure claims to have been made by a version that
    was never released — which is precisely the claim the record exists to
    support.
    """
    import re

    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    source = (ROOT / "src" / "__init__.py").read_text()
    reported = re.search(r'^__version__ = "([^"]+)"', source, re.M)
    assert reported is not None, "src/__init__.py must declare __version__"
    assert reported.group(1) == declared, (
        f"pyproject says {declared}, the bundle reports {reported.group(1)}"
    )


def test_the_mcp_declared_and_reported_versions_are_the_same():
    """PyPI metadata and the server's runtime handshake must agree."""
    import re

    declared = tomllib.loads((ROOT / "mcp" / "pyproject.toml").read_text())[
        "project"
    ]["version"]
    source = (ROOT / "mcp" / "molcompose_mcp" / "__init__.py").read_text()
    reported = re.search(r'^__version__ = "([^"]+)"', source, re.M)
    assert reported is not None, "mcp/molcompose_mcp/__init__.py must declare __version__"
    assert reported.group(1) == declared, (
        f"mcp/pyproject says {declared}, the server reports {reported.group(1)}"
    )


def test_current_bundle_and_mcp_versions_are_a_supported_pair():
    """Independent package versions must still pass the runtime handshake."""
    from molcompose_mcp.assistant import compatibility_status

    bundle = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "version"
    ]
    mcp = tomllib.loads((ROOT / "mcp" / "pyproject.toml").read_text())[
        "project"
    ]["version"]

    status = compatibility_status(mcp, bundle)
    assert status["server_version"] == mcp
    assert status["bundle_version"] == bundle
    assert status["compatible"] is True, status["warning"]


def test_the_tab_icons_are_declared_as_package_data():
    """Non-code files ship only if declared, and these are not code.

    Building without the declaration produces a wheel with every .py in place
    and 24 fewer PNGs, measured both ways. The set is checked here too: four
    tabs, two colours, three sizes.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["tool"]["chimerax"]["package-data"]["src/icons"] == ["*.png"]

    icons = {path.name for path in (ROOT / "src" / "icons").glob("*.png")}
    expected = {
        f"{name}-{variant}-{size}.png"
        for name in ("compose", "interface", "export", "agent")
        for variant in ("dark", "light")
        for size in (16, 32, 64)
    }
    assert icons == expected, (
        "the shipped tab icons no longer match the tabs; they are generated, "
        "so regenerate them rather than adding a file by hand"
    )
