"""Starting ChimeraX so a person does not have to."""

import subprocess

import pytest
from molcompose_mcp import launch


def test_an_explicit_executable_wins_over_searching(monkeypatch):
    """Two versions installed, or one somewhere unusual, is not an argument."""
    monkeypatch.setenv("CHIMERAX_EXECUTABLE", "/opt/mine/ChimeraX")
    assert launch.find_executable() == "/opt/mine/ChimeraX"


def test_the_newest_version_is_chosen_when_several_match(monkeypatch, tmp_path):
    """macOS puts the version in the app name, so several can sit side by side.

    Version components have to be compared as numbers: lexical ordering would
    incorrectly choose 1.9 over 1.12.
    """
    monkeypatch.delenv("CHIMERAX_EXECUTABLE", raising=False)
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    for version in ("1.9", "1.12"):
        app = tmp_path / f"ChimeraX-{version}.app/Contents/bin"
        app.mkdir(parents=True)
        (app / "ChimeraX").write_text("")
    monkeypatch.setattr(
        launch, "CANDIDATES",
        {"darwin": (str(tmp_path / "ChimeraX*.app/Contents/bin/ChimeraX"),)},
    )
    assert "1.12" in launch.find_executable("darwin")


def test_a_versioned_install_wins_over_the_unversioned_fallback(monkeypatch, tmp_path):
    """A bare ChimeraX.app remains usable, but is not evidence of being newer."""
    monkeypatch.delenv("CHIMERAX_EXECUTABLE", raising=False)
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    for app_name in ("ChimeraX.app", "ChimeraX-1.12.app"):
        app = tmp_path / app_name / "Contents/bin"
        app.mkdir(parents=True)
        (app / "ChimeraX").write_text("")
    monkeypatch.setattr(
        launch,
        "CANDIDATES",
        {"darwin": (str(tmp_path / "ChimeraX*.app/Contents/bin/ChimeraX"),)},
    )
    assert "ChimeraX-1.12.app" in launch.find_executable("darwin")


def test_a_running_bridge_is_reused_rather_than_a_second_chimerax_started():
    """Two viewers for one conversation is worse than none."""
    spawned = []
    assert launch.start(
        "http://127.0.0.1:3000",
        spawn=lambda *a, **k: spawned.append(a),
        probe=lambda *_a, **_k: True,
    )
    assert spawned == []


def test_the_launch_is_windowed_and_outlives_this_process(monkeypatch):
    """`--nogui` has no OpenGL, so every image export would fail.

    And the process is detached: a person is usually looking at what was
    drawn, so killing the window when the conversation ends is a poor way to
    end it.
    """
    monkeypatch.setenv("CHIMERAX_EXECUTABLE", "/opt/ChimeraX")
    calls = {}

    def fake_spawn(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs

    answered = iter([False, True])
    assert launch.start(
        "http://127.0.0.1:3010",
        spawn=fake_spawn,
        probe=lambda *_a, **_k: next(answered),
        sleep=lambda _s: None,
    )
    assert "--nogui" not in calls["argv"]
    assert calls["argv"][:2] == ["/opt/ChimeraX", "--cmd"]
    assert "port 3010" in calls["argv"][2]
    assert calls["kwargs"]["start_new_session"] is True
    assert calls["kwargs"]["stdout"] is subprocess.DEVNULL


def test_no_chimerax_is_a_sentence_not_a_stack_trace(monkeypatch):
    monkeypatch.delenv("CHIMERAX_EXECUTABLE", raising=False)
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(launch, "CANDIDATES", {})
    with pytest.raises(launch.ChimeraXNotFound) as caught:
        launch.start("http://127.0.0.1:3000", probe=lambda *_a, **_k: False)
    assert "CHIMERAX_EXECUTABLE" in str(caught.value)


def test_the_url_decides_the_port_it_asks_for():
    assert launch.port_of("http://127.0.0.1:3010") == 3010
    assert launch.port_of("http://127.0.0.1:3010/") == 3010
    # No port in the URL is ChimeraX's own default rather than an error.
    assert launch.port_of("http://localhost") == 3000


def test_a_chimerax_without_the_bundle_is_named_as_such():
    """The failure is a missing install, and the message says how to fix it.

    Without this the first real command comes back as ChimeraX complaining
    about an unknown command, which reads like the server is broken.

    It reports only what it can prove. Anything it does not recognise is
    "cannot tell", and cannot tell must not block: refusing to work because a
    probe was inconclusive turns a working session into a support request,
    which is worse than the failure this exists to report.
    """
    assert launch.bundle_is_missing(lambda _c: {"raw": "Unknown command: molcompose"})
    assert not launch.bundle_is_missing(lambda _c: {"raw": "Usage: molcompose interface ..."})

    def boom(_c):
        raise OSError("connection refused")

    assert not launch.bundle_is_missing(boom)          # unreachable, not missing
    assert not launch.bundle_is_missing(lambda _c: {})  # unrecognised, not missing
    assert "toolshed install" in launch.BUNDLE_MISSING


def test_the_printed_config_names_this_install_not_a_bare_command():
    """A client launches the string it is given, in its own environment.

    `molcompose-mcp` on its own resolves from pipx and fails from a virtualenv
    nobody activated — the commonest way a correct-looking registration still
    does not run. Printing the resolved path is what makes the registration
    copy-and-paste rather than copy-and-debug.
    """
    import json
    import sys
    from pathlib import Path

    from molcompose_mcp import server

    text = server.config_json("http://127.0.0.1:3010")
    entry = json.loads(text)["mcpServers"]["molcompose"]

    assert Path(entry["command"]).is_absolute(), entry["command"]
    assert entry["args"] == ["--chimerax-url", "http://127.0.0.1:3010"]

    # The default source is what the server already uses, so naming it would
    # be noise in a config a person has to read.
    assert "--source" not in entry["args"]
    named = json.loads(server.config_json("http://127.0.0.1:3000", "agent:codex"))
    assert named["mcpServers"]["molcompose"]["args"][-2:] == ["--source", "agent:codex"]

    assistant = json.loads(
        server.config_json("http://127.0.0.1:3000", profile="assistant")
    )
    assert assistant["mcpServers"]["molcompose"]["args"][-2:] == [
        "--profile", "assistant",
    ]

    assert sys.executable  # the fallback path is exercised by own_executable
