import pytest

from src.adapters.exporter import ExportOptions, build_export_commands, export_figure


def test_builds_png_command_with_defaults(tmp_path):
    options = ExportOptions(tmp_path / "figure.png")
    assert build_export_commands(options) == (
        "~select",
        f'save "{tmp_path / "figure.png"}" width 2400 height 1800 '
        "supersample 3 transparentBackground false",
    )


def test_the_selection_is_cleared_before_the_image_is_taken():
    """ChimeraX renders the selection highlight into saved images.

    Harmless while nothing in MolCompose selected anything; not harmless now
    that interface blocks and interaction chips are clickable selectors, since
    a green outline would land in the published figure.
    """
    from pathlib import Path as _Path

    commands = build_export_commands(ExportOptions(_Path("/tmp/x.png"), overwrite=True))
    assert commands[0] == "~select"
    assert commands[1].startswith("save ")


def test_builds_png_and_session_commands(tmp_path):
    options = ExportOptions(tmp_path / "figure.png", save_session=True)
    assert build_export_commands(options) == (
        "~select",
        f'save "{tmp_path / "figure.png"}" width 2400 height 1800 '
        "supersample 3 transparentBackground false",
        f'save "{tmp_path / "figure.cxs"}"',
    )


def test_transparent_flag_is_rendered(tmp_path):
    options = ExportOptions(tmp_path / "figure.png", transparent=True)
    _clear, command = build_export_commands(options)
    assert "transparentBackground true" in command


def test_rejects_a_format_no_journal_should_receive(tmp_path):
    """TIFF joined PNG; JPEG did not, and that is the point of the list.

    These figures are a hard silhouette on a white ground, which is where
    JPEG's ringing is most visible. Offering the format invites someone to
    submit one.
    """
    with pytest.raises(ValueError, match="must end in one of"):
        ExportOptions(tmp_path / "figure.jpg")
    assert ExportOptions(tmp_path / "figure.tiff").path.suffix == ".tiff"


def test_existing_file_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "figure.png"
    path.write_bytes(b"existing")
    with pytest.raises(FileExistsError, match="already exists"):
        build_export_commands(ExportOptions(path))


def test_existing_session_file_is_not_silently_overwritten(tmp_path):
    (tmp_path / "figure.cxs").write_bytes(b"existing")
    with pytest.raises(FileExistsError, match="already exists"):
        build_export_commands(ExportOptions(tmp_path / "figure.png", save_session=True))


def test_overwrite_flag_permits_existing_target(tmp_path):
    path = tmp_path / "figure.png"
    path.write_bytes(b"existing")
    commands = build_export_commands(ExportOptions(path, overwrite=True))
    assert len(commands) == 2


def test_rejects_missing_output_directory(tmp_path):
    with pytest.raises(ValueError, match="output directory does not exist"):
        build_export_commands(ExportOptions(tmp_path / "missing" / "figure.png"))


def test_rejects_directory_target(tmp_path):
    target = tmp_path / "figure.png"
    target.mkdir()
    with pytest.raises(ValueError, match="is a directory"):
        build_export_commands(ExportOptions(target))


@pytest.mark.parametrize(
    ("field", "value"),
    [("width", 0), ("height", 0), ("supersample", 0), ("supersample", 9)],
)
def test_rejects_invalid_dimensions(field, value, tmp_path):
    kwargs = {field: value}
    with pytest.raises(ValueError):
        ExportOptions(tmp_path / "figure.png", **kwargs)


def test_export_figure_runs_commands_and_reports_paths(tmp_path):
    calls = []

    def runner(session, command):
        calls.append((session, command))

    session = object()
    options = ExportOptions(tmp_path / "figure.png", save_session=True)
    png_path, session_path, commands, _recipe = export_figure(
        session, options, runner=runner
    )
    assert png_path == tmp_path / "figure.png"
    assert session_path == tmp_path / "figure.cxs"
    assert [command for _, command in calls] == list(commands)


def test_export_figure_without_session(tmp_path):
    options = ExportOptions(tmp_path / "figure.png")
    _, session_path, commands, _recipe = export_figure(
        object(), options, runner=lambda s, c: None
    )
    assert session_path is None
    assert len(commands) == 2


def test_the_recipe_travels_with_the_figure(tmp_path):
    """A recipe that lives only in the Log is gone when the session closes.

    The manuscript's claim is that a figure can be replayed. A figure emailed
    to a collaborator has to carry the commands with it for that to be true of
    anything but the machine it was made on.
    """
    options = ExportOptions(tmp_path / "figure.png", save_recipe=True, dpi=600)
    recipe = ("molcompose interface A D", "molcompose style interface-focus")
    _, _, _, recipe_path = export_figure(
        object(), options, runner=lambda s, c: None, recipe=recipe
    )
    assert recipe_path == tmp_path / "figure.cxc"
    text = recipe_path.read_text()
    assert "molcompose interface A D" in text
    assert "molcompose style interface-focus" in text
    # The header states the size the pixels are worth in print, since that is
    # the number a publisher asks about and the file name does not carry it.
    assert "600 dpi" in text
    assert all(line.startswith("#") or line.startswith("molcompose")
               for line in text.splitlines() if line)


def test_the_recipe_names_the_build_that_made_the_figure(tmp_path):
    """The one fact a replay cannot recover for itself.

    The same commands render differently across preset versions — every
    preset carries its own version because they do — so a recipe without a
    build is a recipe that reproduces some figure rather than this one.
    The version reached the JSON report and not the file people send to each
    other, which is the one that has to carry it.
    """
    from src import __version__

    options = ExportOptions(tmp_path / "figure.png", save_recipe=True)
    _, _, _, recipe_path = export_figure(
        object(), options, runner=lambda s, c: None,
        recipe=("molcompose interface A D",),
    )
    header = [line for line in recipe_path.read_text().splitlines()
              if line.startswith("#")]
    assert any(f"MolCompose {__version__}" in line for line in header)
    assert any("UCSF ChimeraX" in line for line in header)


def test_a_recipe_sidecar_is_not_silently_overwritten(tmp_path):
    """The image is guarded; the file beside it has to be guarded too."""
    (tmp_path / "figure.cxc").write_text("earlier work")
    options = ExportOptions(tmp_path / "figure.png", save_recipe=True)
    with pytest.raises(FileExistsError, match="already exists"):
        build_export_commands(options)


def test_a_sidecar_collision_says_which_sidecar_and_why(tmp_path):
    """The user named a .tif; the refusal was about a .cxc they never asked for.

    The recipe's name comes from the image's stem, so it collides across
    formats: export figure.png, then figure.tif, and the second is refused
    over figure.cxc. True, and baffling without the role spelled out.
    """
    (tmp_path / "figure.cxc").write_text("earlier work")
    options = ExportOptions(tmp_path / "figure.tif", save_recipe=True)
    with pytest.raises(FileExistsError, match="command recipe this export") as raised:
        build_export_commands(options)
    assert "figure.cxc" in str(raised.value)
    assert "overwrite true" in str(raised.value)

    (tmp_path / "other.cxs").write_text("earlier session")
    with pytest.raises(FileExistsError, match="ChimeraX session this export"):
        build_export_commands(
            ExportOptions(tmp_path / "other.tif", save_session=True)
        )


def test_the_image_itself_still_refuses_plainly(tmp_path):
    """No role prefix on the file the user actually named."""
    (tmp_path / "figure.png").write_bytes(b"x")
    with pytest.raises(FileExistsError, match=r"^output file already exists"):
        build_export_commands(ExportOptions(tmp_path / "figure.png"))


def test_print_size_is_what_the_journal_asked_for():
    """85 mm at 600 dpi, which is what "single column" means in pixels."""
    from src.adapters.exporter import COLUMN_MM, pixels_for

    assert pixels_for(COLUMN_MM["single"], 600) == 2008
    assert pixels_for(COLUMN_MM["double"], 300) == 2055


@pytest.mark.parametrize("dpi", [1, 71, 2401])
def test_rejects_a_dpi_that_would_mislabel_the_file(dpi, tmp_path):
    with pytest.raises(ValueError, match="dpi must be"):
        ExportOptions(tmp_path / "figure.png", dpi=dpi)


def test_dpi_zero_means_leave_the_file_unstamped(tmp_path):
    assert ExportOptions(tmp_path / "figure.png", dpi=0).dpi == 0


class _Key:
    """Stands in for chimerax.color_key.model.ColorKeyModel."""

    def __init__(self, font_size=42, pos=(0.3, 0.055)):
        self.font_size = font_size
        self.pos = pos


_Key.__name__ = "ColorKeyModel"


class _Models:
    def __init__(self, models):
        self._models = models

    def list(self):
        return self._models


class _Session:
    def __init__(self, models=()):
        self.models = _Models(list(models))


def test_key_font_size_brackets_the_save_and_puts_the_size_back(tmp_path):
    """The option describes the exported file, not the scene.

    A viewport left at a size chosen for one figure's final layout is how the
    next export goes out wrong without anyone touching a setting.
    """
    ran = []
    options = ExportOptions(tmp_path / "figure.png", key_font_size=96)
    export_figure(_Session([_Key(font_size=42)]), options,
                  runner=lambda _session, command: ran.append(command))
    assert ran[0] == "key fontSize 96"
    assert "key fontSize 42" in ran, "the scene's own size is not put back"
    save = next(i for i, command in enumerate(ran) if command.startswith("save "))
    assert all(command.startswith("key ") for command in ran[:save] if command != "~select")
    assert all(command.startswith("key ") for command in ran[save + 1:])


def test_key_font_size_is_refused_when_there_is_no_key_to_resize(tmp_path):
    """`key` without colours draws ChimeraX's generic blue-to-red bar, which
    would label the figure with a scale it was not painted with."""
    ran = []
    options = ExportOptions(tmp_path / "figure.png", key_font_size=96)
    with pytest.raises(ValueError, match="no colour key"):
        export_figure(_Session([]), options,
                      runner=lambda _session, command: ran.append(command))
    assert ran == []


def test_export_without_the_option_leaves_the_font_alone(tmp_path):
    """The size is the caller's business; the position is not, because a key
    clipped off the bottom edge is nobody's intention."""
    ran = []
    options = ExportOptions(tmp_path / "figure.png")
    export_figure(_Session([_Key()]), options,
                  runner=lambda _session, command: ran.append(command))
    assert not any(command.startswith("key fontSize") for command in ran)


@pytest.mark.parametrize("size", [3, 401])
def test_key_font_size_outside_a_plausible_range_is_refused(tmp_path, size):
    with pytest.raises(ValueError, match="keyFontSize"):
        ExportOptions(tmp_path / "figure.png", key_font_size=size)


def test_a_short_export_lifts_the_key_clear_of_its_own_labels(tmp_path):
    """The key is placed when a preset is applied or a metric coloured, long
    before anyone says how tall the image will be — so export is the only
    place the height is known. At 900 px the shipped position leaves the
    numbers 1 px from the edge; below that they are cut off entirely."""
    ran = []
    options = ExportOptions(tmp_path / "figure.png", width=1600, height=900)
    export_figure(_Session([_Key(font_size=42, pos=(0.3, 0.055))]), options,
                  runner=lambda _session, command: ran.append(command))
    lift = next(c for c in ran if c.startswith("key pos") and "0.055" not in c)
    assert float(lift.split(",")[1]) * 900 >= 42 * 1.6
    assert ran[-1] == "key pos 0.3,0.055", "the scene's own position is not put back"


def test_a_tall_export_leaves_the_key_where_it_is(tmp_path):
    """Every figure drawn so far had room; none of them moves."""
    ran = []
    options = ExportOptions(tmp_path / "figure.png", width=1600, height=2000)
    export_figure(_Session([_Key()]), options,
                  runner=lambda _session, command: ran.append(command))
    assert not any(command.startswith("key ") for command in ran)


class _View:
    def __init__(self, size):
        self.window_size = size


class _SessionWithWindow(_Session):
    def __init__(self, models=(), window=(1984, 1204), warnings=None):
        super().__init__(models)
        self.main_view = _View(window)
        self.logger = _Logger(warnings if warnings is not None else [])


class _Logger:
    def __init__(self, warnings):
        self.warnings = warnings

    def warning(self, text):
        self.warnings.append(text)

    def info(self, text):
        pass


class TestAspectDrift:
    """ChimeraX places the key against the graphics window, not the saved
    frame, so an export shaped very differently from the window moves it.
    Measured across aspects on one machine: comfortable at 0.75x and 0.78x of
    the window's aspect, tight at 1.08x, labels gone at 1.39x."""

    def _drift(self, width, height, window=(1984, 1204)):
        from src.adapters.exporter import key_aspect_drift

        return key_aspect_drift(_SessionWithWindow(window=window), width, height)

    def test_a_window_shaped_export_is_silent(self):
        assert self._drift(1600, 900) is None      # 1.08x, tight but not warned
        assert self._drift(900, 700) is None       # 0.78x
        assert self._drift(700, 1300) is None      # 0.33x, tall: key floats high

    def test_a_much_wider_export_is_named(self):
        drift = self._drift(1600, 700)             # 1.39x, labels clipped
        assert drift is not None
        assert drift == pytest.approx(1.39, abs=0.01)

    def test_no_window_no_warning(self):
        """A headless session cannot be measured, and a warning that fires
        there helps nobody."""
        from src.adapters.exporter import key_aspect_drift

        assert key_aspect_drift(_Session([]), 1600, 700) is None

    def test_the_window_takes_the_export_s_shape_and_is_put_back(self, tmp_path):
        """Verified on screen: at 1600x700 from a 1984x1204 window the labels
        are off the bottom edge, and with the window set to the same shape
        first they are whole."""
        ran = []
        session = _SessionWithWindow([_Key()])
        options = ExportOptions(tmp_path / "wide.png", width=1600, height=700)
        export_figure(session, options, runner=lambda _s, c: ran.append(c))
        assert ran[0] == "windowsize 1984 868", "the export's shape, fitted"
        assert ran[-1] == "windowsize 1984 1204", "the window is not put back"
        save = next(i for i, c in enumerate(ran) if c.startswith("save "))
        assert 0 < save < len(ran) - 1

    def test_a_window_shaped_export_leaves_the_window_alone(self, tmp_path):
        ran = []
        session = _SessionWithWindow([_Key()])
        options = ExportOptions(tmp_path / "ok.png", width=1600, height=900)
        export_figure(session, options, runner=lambda _s, c: ran.append(c))
        assert not any(c.startswith("windowsize") for c in ran)

    def test_no_key_leaves_the_window_alone(self, tmp_path):
        """Nothing to place, so nothing to correct for."""
        ran = []
        session = _SessionWithWindow([])
        options = ExportOptions(tmp_path / "wide.png", width=1600, height=700)
        export_figure(session, options, runner=lambda _s, c: ran.append(c))
        assert not any(c.startswith("windowsize") for c in ran)


class TestWindowMatching:
    def test_fits_inside_the_window_it_replaces(self):
        from src.adapters.exporter import window_matching

        for width, height in ((1600, 700), (700, 1600), (1000, 1000)):
            w, h = window_matching((1984, 1204), width, height)
            assert w <= 1984 and h <= 1204, "a larger window can be clamped"
            assert w / h == pytest.approx(width / height, rel=0.01)
