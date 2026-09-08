"""Executable checks for the exact MCP artifacts a release may publish."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[2]
VALIDATOR = ROOT / "scripts" / "validate_release_artifacts.py"


def _write_wheel(path: Path, *, metadata_version: str = "0.1.2") -> None:
    dist_info = f"molcompose_mcp-{metadata_version}.dist-info"
    metadata = (
        "Metadata-Version: 2.3\n"
        "Name: molcompose-mcp\n"
        f"Version: {metadata_version}\n"
        "\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        member = zipfile.ZipInfo(f"{dist_info}/METADATA", (2024, 1, 1, 0, 0, 0))
        archive.writestr(member, metadata)


def _write_sdist(
    path: Path,
    *,
    metadata_version: str = "0.1.2",
    include_egg_info: bool = False,
    duplicate_top_level: bool = False,
    extra_archive_root: bool = False,
) -> None:
    metadata = (
        "Metadata-Version: 2.3\n"
        "Name: molcompose-mcp\n"
        f"Version: {metadata_version}\n"
        "\n"
    ).encode()
    member = tarfile.TarInfo(f"molcompose_mcp-{metadata_version}/PKG-INFO")
    member.size = len(metadata)
    member.mtime = 0
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(member, io.BytesIO(metadata))
        if include_egg_info:
            egg_info = tarfile.TarInfo(
                f"molcompose_mcp-{metadata_version}/molcompose_mcp.egg-info/PKG-INFO"
            )
            egg_info.size = len(metadata)
            egg_info.mtime = 0
            archive.addfile(egg_info, io.BytesIO(metadata))
        if duplicate_top_level:
            duplicate = tarfile.TarInfo(
                f"molcompose_mcp-{metadata_version}/PKG-INFO"
            )
            duplicate.size = len(metadata)
            duplicate.mtime = 0
            archive.addfile(duplicate, io.BytesIO(metadata))
        if extra_archive_root:
            extra = tarfile.TarInfo("unexpected-root/README")
            extra.size = 0
            extra.mtime = 0
            archive.addfile(extra, io.BytesIO(b""))


def _run_validator(
    dist: Path,
    github_output: Path,
    *,
    pypi_json: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = [
        sys.executable,
        str(VALIDATOR),
        "--dist-dir",
        str(dist),
        "--expected-name",
        "molcompose-mcp",
        "--expected-version",
        "0.1.2",
        "--github-output",
        str(github_output),
    ]
    if pypi_json is not None:
        argv.extend(("--pypi-json", str(pypi_json)))
    return subprocess.run(
        argv,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_validator_reports_the_exact_versioned_artifacts_and_hashes(tmp_path):
    """Wrong artifact selection, metadata, or digest must stop a release."""
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "molcompose_mcp-0.1.2-py3-none-any.whl"
    sdist = dist / "molcompose_mcp-0.1.2.tar.gz"
    _write_wheel(wheel)
    _write_sdist(sdist)
    github_output = tmp_path / "github-output"

    completed = _run_validator(dist, github_output)

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report == {
        "artifacts": [
            {
                "filename": "molcompose_mcp-0.1.2-py3-none-any.whl",
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            },
            {
                "filename": "molcompose_mcp-0.1.2.tar.gz",
                "sha256": hashlib.sha256(sdist.read_bytes()).hexdigest(),
            },
        ],
        "package": "molcompose-mcp",
        "version": "0.1.2",
    }
    assert github_output.read_text().splitlines() == [
        "version=0.1.2",
        "wheel=molcompose_mcp-0.1.2-py3-none-any.whl",
        "sdist=molcompose_mcp-0.1.2.tar.gz",
    ]


def test_validator_rejects_a_wheel_whose_metadata_disagrees(tmp_path):
    """A filename cannot make mismatched wheel metadata safe to publish."""
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_wheel(
        dist / "molcompose_mcp-0.1.2-py3-none-any.whl",
        metadata_version="0.1.1",
    )
    _write_sdist(dist / "molcompose_mcp-0.1.2.tar.gz")

    completed = _run_validator(dist, tmp_path / "github-output")

    assert completed.returncode != 0
    assert "wheel metadata version is 0.1.1, expected 0.1.2" in completed.stderr


def test_validator_rejects_more_than_one_built_wheel(tmp_path):
    """A broad artifact glob must not silently publish stale build output."""
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_wheel(dist / "molcompose_mcp-0.1.2-py3-none-any.whl")
    _write_wheel(dist / "molcompose_mcp-0.1.2-1-py3-none-any.whl")
    _write_sdist(dist / "molcompose_mcp-0.1.2.tar.gz")

    completed = _run_validator(dist, tmp_path / "github-output")

    assert completed.returncode != 0
    assert "exactly one wheel and one sdist" in completed.stderr


def test_validator_uses_the_top_level_metadata_in_a_setuptools_sdist(tmp_path):
    """Nested egg-info metadata is normal and must not look like ambiguity."""
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_wheel(dist / "molcompose_mcp-0.1.2-py3-none-any.whl")
    _write_sdist(
        dist / "molcompose_mcp-0.1.2.tar.gz",
        include_egg_info=True,
    )

    completed = _run_validator(dist, tmp_path / "github-output")

    assert completed.returncode == 0, completed.stderr


def test_validator_rejects_duplicate_top_level_sdist_metadata(tmp_path):
    """Two authoritative root metadata members make the archive ambiguous."""
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_wheel(dist / "molcompose_mcp-0.1.2-py3-none-any.whl")
    _write_sdist(
        dist / "molcompose_mcp-0.1.2.tar.gz",
        duplicate_top_level=True,
    )

    completed = _run_validator(dist, tmp_path / "github-output")

    assert completed.returncode != 0
    assert "2 top-level PKG-INFO files" in completed.stderr


def test_validator_rejects_more_than_one_sdist_archive_root(tmp_path):
    """All members must belong to the single root named by the sdist."""
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_wheel(dist / "molcompose_mcp-0.1.2-py3-none-any.whl")
    _write_sdist(
        dist / "molcompose_mcp-0.1.2.tar.gz",
        extra_archive_root=True,
    )

    completed = _run_validator(dist, tmp_path / "github-output")

    assert completed.returncode != 0
    assert "one archive root matching its filename" in completed.stderr


def test_validator_accepts_matching_pypi_artifact_hashes(tmp_path):
    """An immutable PyPI version is reusable only when every byte matches."""
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "molcompose_mcp-0.1.2-py3-none-any.whl"
    sdist = dist / "molcompose_mcp-0.1.2.tar.gz"
    _write_wheel(wheel)
    _write_sdist(sdist)
    pypi_json = tmp_path / "pypi.json"
    pypi_json.write_text(
        json.dumps(
            {
                "urls": [
                    {
                        "filename": wheel.name,
                        "packagetype": "bdist_wheel",
                        "digests": {"sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()},
                    },
                    {
                        "filename": sdist.name,
                        "packagetype": "sdist",
                        "digests": {"sha256": hashlib.sha256(sdist.read_bytes()).hexdigest()},
                    },
                ]
            }
        )
    )

    completed = _run_validator(
        dist,
        tmp_path / "github-output",
        pypi_json=pypi_json,
    )

    assert completed.returncode == 0, completed.stderr


def test_validator_rejects_a_different_pypi_artifact_hash(tmp_path):
    """A rerun cannot pair rebuilt GitHub bytes with frozen PyPI bytes."""
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "molcompose_mcp-0.1.2-py3-none-any.whl"
    sdist = dist / "molcompose_mcp-0.1.2.tar.gz"
    _write_wheel(wheel)
    _write_sdist(sdist)
    pypi_json = tmp_path / "pypi.json"
    pypi_json.write_text(
        json.dumps(
            {
                "urls": [
                    {
                        "filename": wheel.name,
                        "packagetype": "bdist_wheel",
                        "digests": {"sha256": "0" * 64},
                    },
                    {
                        "filename": sdist.name,
                        "packagetype": "sdist",
                        "digests": {"sha256": hashlib.sha256(sdist.read_bytes()).hexdigest()},
                    },
                ]
            }
        )
    )

    completed = _run_validator(
        dist,
        tmp_path / "github-output",
        pypi_json=pypi_json,
    )

    assert completed.returncode != 0
    assert f"PyPI sha256 for {wheel.name} does not match the local artifact" in completed.stderr
