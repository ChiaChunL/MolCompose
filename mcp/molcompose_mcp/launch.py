"""Start ChimeraX when nothing is listening, so a person does not have to.

The bridge this server talks to is ChimeraX's own `remotecontrol rest`, which
can only be started from inside ChimeraX. That put two manual steps in front of
`pip install molcompose-mcp`: open the application, then type a command into it
that most users would have to be told about. Both can be removed, because
ChimeraX accepts the command at launch:

    ChimeraX --cmd "remotecontrol rest start port 3000 json true"

What this does not remove is installing the bundle. `toolshed install` needs a
restart to take effect, and a restart in the middle of an agent's turn is worse
than a clear message, so a ChimeraX without MolCompose is reported rather than
repaired.

The launched process is deliberately left running when this server exits. A
person is usually looking at what was drawn, and killing the window they are
reading is a poor way to end a conversation. It is also why an existing
ChimeraX is reused rather than a second one started.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

#: Where the application lands on each platform, most specific first. A version
#: in the name is normal on macOS, so the glob comes before the bare path.
CANDIDATES = {
    "darwin": (
        "/Applications/ChimeraX*.app/Contents/bin/ChimeraX",
        str(Path.home() / "Applications/ChimeraX*.app/Contents/bin/ChimeraX"),
    ),
    "linux": (
        "/usr/bin/chimerax",
        "/usr/local/bin/chimerax",
        "/opt/UCSF/ChimeraX*/bin/ChimeraX",
        str(Path.home() / ".local/bin/chimerax"),
    ),
    "win32": (
        r"C:\Program Files\ChimeraX*\bin\ChimeraX.exe",
        r"C:\Program Files (x86)\ChimeraX*\bin\ChimeraX.exe",
    ),
}


class ChimeraXNotFound(RuntimeError):
    """No ChimeraX executable on this machine, or none where we looked."""


_CHIMERAX_VERSION = re.compile(
    r"ChimeraX[^0-9/\\]*([0-9]+(?:\.[0-9]+)*)",
    re.IGNORECASE,
)


def _installed_version(path: str) -> tuple[int, ...] | None:
    """Return the numeric version encoded in a ChimeraX install path.

    Official macOS, Linux, and Windows install names place a dotted version
    after ``ChimeraX``. A bare ``ChimeraX.app`` carries no ordering evidence;
    it remains a deterministic fallback when no versioned match exists.
    """
    match = _CHIMERAX_VERSION.search(path)
    if match is None:
        return None
    return tuple(int(component) for component in match.group(1).split("."))


def _newest_match(matches: list[str]) -> str:
    """Choose the numerically newest version, or a stable bare-path fallback."""
    versioned = [
        (version, path)
        for path in matches
        if (version := _installed_version(path)) is not None
    ]
    if versioned:
        return max(versioned)[1]
    return min(matches)


def find_executable(platform: str | None = None, exists=None) -> str | None:
    """The ChimeraX to launch, or None.

    `CHIMERAX_EXECUTABLE` wins: a person with two versions installed, or one in
    a place this does not know about, should not have to argue with a search
    path.
    """
    override = os.environ.get("CHIMERAX_EXECUTABLE", "").strip()
    if override:
        return override

    import glob
    import shutil

    for name in ("ChimeraX", "chimerax"):
        found = shutil.which(name)
        if found:
            return found

    for pattern in CANDIDATES.get(platform or sys.platform, ()):
        matches = glob.glob(pattern)
        if matches:
            return _newest_match(matches)
    return None


def bridge_is_up(base_url: str, timeout: float = 3.0) -> bool:
    """Whether something answers ChimeraX's REST bridge at this address."""
    url = f"{base_url.rstrip('/')}/run?{urlencode({'command': 'version'})}"
    try:
        with urlopen(url, timeout=timeout):  # noqa: S310 - localhost bridge
            return True
    except (URLError, OSError):
        return False


def port_of(base_url: str) -> int:
    """The port in a base URL, defaulting to ChimeraX's own default."""
    _, _, tail = base_url.rstrip("/").rpartition(":")
    try:
        return int(tail)
    except ValueError:
        return 3000


def start(base_url: str, wait: float = 90.0, spawn=subprocess.Popen,
          probe=bridge_is_up, sleep=time.sleep, platform: str | None = None) -> bool:
    """Launch ChimeraX with the bridge open. True once it answers.

    Windowed, not `--nogui`: a headless session has no OpenGL, so every image
    export would fail — and exporting the figure is most of what this server is
    for. The window appearing is the honest signal that a molecular viewer is
    now running.
    """
    if probe(base_url):
        return True

    executable = find_executable(platform)
    if not executable:
        raise ChimeraXNotFound(
            "No ChimeraX found. Install it from "
            "https://www.rbvi.ucsf.edu/chimerax/download.html, or set "
            "CHIMERAX_EXECUTABLE to its path."
        )

    port = port_of(base_url)
    spawn(
        [executable, "--cmd", f"remotecontrol rest start port {port} json true"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # outlives this server, which is the point
    )

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        sleep(1.0)
        if probe(base_url):
            return True
    return False


BUNDLE_MISSING = (
    "ChimeraX is running but the MolCompose bundle is not installed in it. "
    "In ChimeraX's command line run `toolshed install ChimeraX_MolCompose`, "
    "then quit ChimeraX and start it again — a running session keeps the "
    "modules it already loaded."
)


def bundle_is_missing(run) -> bool:
    """True only when ChimeraX positively says it has no such command.

    Asked once, before the first real command, so a missing install reads as a
    sentence about installing a bundle rather than a stack trace from a command
    the session has never heard of.

    Anything else — an unreachable bridge, a payload this does not recognise —
    is "cannot tell", and cannot tell must not block. Refusing to work because
    a probe was inconclusive would turn a working session into a support
    request, which is a worse failure than the one this exists to report.
    """
    try:
        payload = run("usage molcompose")
    except Exception:  # noqa: BLE001 - unreachable is a different failure
        return False
    return "unknown command" in str(payload).lower()
