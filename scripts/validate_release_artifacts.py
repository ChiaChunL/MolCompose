#!/usr/bin/env python3
"""Validate and identify the exact wheel/sdist pair for an MCP release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path


class ArtifactError(ValueError):
    """A built artifact set is unsafe to publish."""


def _normalise_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_wheel_metadata(wheel: Path) -> tuple[str, str]:
    with zipfile.ZipFile(wheel) as archive:
        members = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(members) != 1:
            raise ArtifactError(f"wheel contains {len(members)} METADATA files, expected one")
        message = Parser().parsestr(archive.read(members[0]).decode("utf-8"))
    return message.get("Name", ""), message.get("Version", "")


def _read_sdist_metadata(sdist: Path) -> tuple[str, str]:
    expected_root = sdist.name.removesuffix(".tar.gz")
    with tarfile.open(sdist, "r:gz") as archive:
        archive_members = archive.getmembers()
        roots = {
            member.name.split("/", 1)[0]
            for member in archive_members
            if member.name not in {"", "."}
        }
        if roots != {expected_root}:
            raise ArtifactError(
                "sdist must contain one archive root matching its filename; "
                f"expected {expected_root}, found {sorted(roots)}"
            )
        members = [
            member
            for member in archive_members
            if member.isfile() and member.name == f"{expected_root}/PKG-INFO"
        ]
        if len(members) != 1:
            raise ArtifactError(
                f"sdist contains {len(members)} top-level PKG-INFO files, expected one"
            )
        extracted = archive.extractfile(members[0])
        if extracted is None:
            raise ArtifactError("sdist PKG-INFO could not be read")
        message = Parser().parsestr(extracted.read().decode("utf-8"))
    return message.get("Name", ""), message.get("Version", "")


def _check_metadata(
    kind: str,
    actual: tuple[str, str],
    *,
    expected_name: str,
    expected_version: str,
) -> None:
    name, version = actual
    if _normalise_name(name) != _normalise_name(expected_name):
        raise ArtifactError(f"{kind} metadata name is {name}, expected {expected_name}")
    if version != expected_version:
        raise ArtifactError(
            f"{kind} metadata version is {version}, expected {expected_version}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(dist_dir: Path, expected_name: str, expected_version: str) -> dict[str, object]:
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ArtifactError(
            "release directory must contain exactly one wheel and one sdist; "
            f"found {len(wheels)} wheel(s) and {len(sdists)} sdist(s)"
        )

    wheel, sdist = wheels[0], sdists[0]
    filename_name = re.sub(r"[-_.]+", "_", expected_name).lower()
    if not wheel.name.startswith(f"{filename_name}-{expected_version}-"):
        raise ArtifactError(
            f"wheel filename {wheel.name} does not encode version {expected_version}"
        )
    if sdist.name != f"{filename_name}-{expected_version}.tar.gz":
        raise ArtifactError(
            f"sdist filename {sdist.name} does not encode version {expected_version}"
        )

    _check_metadata(
        "wheel",
        _read_wheel_metadata(wheel),
        expected_name=expected_name,
        expected_version=expected_version,
    )
    _check_metadata(
        "sdist",
        _read_sdist_metadata(sdist),
        expected_name=expected_name,
        expected_version=expected_version,
    )

    return {
        "artifacts": [
            {"filename": wheel.name, "sha256": _sha256(wheel)},
            {"filename": sdist.name, "sha256": _sha256(sdist)},
        ],
        "package": expected_name,
        "version": expected_version,
    }


def compare_pypi_hashes(report: dict[str, object], pypi_json: Path) -> None:
    """Require PyPI's immutable files to be byte-identical to this artifact set."""
    try:
        payload = json.loads(pypi_json.read_text(encoding="utf-8"))
        urls = payload["urls"]
        remote = {
            item["filename"]: item["digests"]["sha256"]
            for item in urls
            if item["packagetype"] in {"bdist_wheel", "sdist"}
        }
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ArtifactError(f"invalid PyPI release JSON: {exc}") from exc

    artifacts = report["artifacts"]
    assert isinstance(artifacts, list)
    local = {item["filename"]: item["sha256"] for item in artifacts}
    if remote.keys() != local.keys():
        raise ArtifactError(
            "PyPI artifact filenames do not match the validated local set: "
            f"PyPI={sorted(remote)} local={sorted(local)}"
        )
    for filename, digest in local.items():
        if remote[filename] != digest:
            raise ArtifactError(
                f"PyPI sha256 for {filename} does not match the local artifact"
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", required=True, type=Path)
    parser.add_argument("--expected-name", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--pypi-json",
        type=Path,
        help="compare against JSON from PyPI's version endpoint",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = validate(args.dist_dir, args.expected_name, args.expected_version)
        if args.pypi_json is not None:
            compare_pypi_hashes(report, args.pypi_json)
    except (ArtifactError, OSError, tarfile.TarError, zipfile.BadZipFile, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.github_output is not None:
        artifacts = report["artifacts"]
        assert isinstance(artifacts, list)
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"version={report['version']}\n")
            stream.write(f"wheel={artifacts[0]['filename']}\n")
            stream.write(f"sdist={artifacts[1]['filename']}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
