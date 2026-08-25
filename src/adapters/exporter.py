"""Validate export options and invoke native ChimeraX PNG and session saves."""

from dataclasses import dataclass
from pathlib import Path

from ..core.presets import key_clearance_y

# What a journal will accept from a rendered 3D scene. PNG for everything
# (lossless, small, universally accepted) and TIFF because several publishers
# still ask for it by name in their artwork specification.
#
# JPEG is deliberately absent. It is lossy on exactly the content these
# figures are made of — a hard silhouette on a white ground is where its
# ringing artefacts are most visible — and offering it invites someone to
# submit one.
IMAGE_SUFFIXES = (".png", ".tif", ".tiff")

# Print sizes journals specify, in millimetres. They are quoted in mm and the
# save command wants pixels, so the panel converts; the numbers live here so
# the command line and the panel agree on what "single column" means.
COLUMN_MM = {"single": 85.0, "double": 174.0}
MM_PER_INCH = 25.4


def pixels_for(width_mm: float, dpi: int) -> int:
    """Pixel width of a figure `width_mm` wide printed at `dpi`."""
    return max(1, round(width_mm / MM_PER_INCH * dpi))


@dataclass(frozen=True)
class ExportOptions:
    path: Path
    width: int = 2400
    height: int = 1800
    supersample: int = 3
    transparent: bool = False
    save_session: bool = False
    overwrite: bool = False
    # Written into the file's own metadata after the save. ChimeraX writes
    # pixels and no resolution, so a 2400 px figure arrives at a publisher as
    # a figure of unknown physical size — which is what "please resupply at
    # 300 dpi" means when it comes back. The pixels are unchanged; this only
    # records what they are worth in print.
    dpi: int = 300
    # Write the command recipe beside the image. The claim this project makes
    # is that a figure can be replayed; a recipe that only exists in the
    # ChimeraX Log stops being true the moment the session closes, and a
    # figure emailed to a collaborator arrives with nothing attached.
    save_recipe: bool = False
    # The colour key's font is in pixels of the exported image, so what it
    # comes out as in print depends entirely on how wide that image is placed.
    # The shipped default suits one panel across two columns; the same panel
    # as one cell of four needs a larger number, and no single default serves
    # both. This lets the caller who knows the final layout say so, for one
    # export, without moving everyone's default.
    key_font_size: int | None = None

    def __post_init__(self):
        object.__setattr__(self, "path", Path(self.path))
        if self.path.suffix.lower() not in IMAGE_SUFFIXES:
            allowed = ", ".join(IMAGE_SUFFIXES)
            raise ValueError(f"MolCompose export path must end in one of: {allowed}")
        if not 1 <= self.width <= 16384 or not 1 <= self.height <= 16384:
            raise ValueError("image width and height must be between 1 and 16384 pixels")
        if not 1 <= self.supersample <= 8:
            raise ValueError("supersample must be between 1 and 8")
        # 0 turns the stamp off; anything else has to be a plausible print
        # resolution rather than a number that will silently mislabel a file.
        if self.dpi and not 72 <= self.dpi <= 2400:
            raise ValueError("dpi must be 0 (unstamped) or between 72 and 2400")
        if self.key_font_size is not None and not 4 <= self.key_font_size <= 400:
            raise ValueError("keyFontSize must be between 4 and 400 pixels")

    @property
    def session_path(self) -> Path:
        return self.path.with_suffix(".cxs")

    @property
    def recipe_path(self) -> Path:
        return self.path.with_suffix(".cxc")

    @property
    def print_size_mm(self) -> tuple[float, float]:
        """What the pixel dimensions come to on paper at the stamped dpi."""
        dpi = self.dpi or 300
        return (self.width / dpi * MM_PER_INCH, self.height / dpi * MM_PER_INCH)


def quote_path(path) -> str:
    text = str(path)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("\n", " ").replace("\r", " ")
    return f'"{text}"'


def _validate_targets(options: ExportOptions) -> None:
    parent = options.path.parent
    if not parent.is_dir():
        raise ValueError(f"output directory does not exist: {parent}")
    if options.path.is_dir():
        raise ValueError(f"export target is a directory: {options.path}")
    # Each target carries what it is for, because two of the three are files
    # the user did not name. Exporting figure.tif after figure.png refused with
    # "output file already exists: figure.cxc" — true, and baffling: the .cxc
    # is the recipe sidecar, whose name comes from the image's stem and so
    # collides across formats. Naming the role makes the refusal actionable.
    targets = [(options.path, "")]
    if options.save_session:
        targets.append((options.session_path, "the ChimeraX session this export "
                                              "would also write"))
    if options.save_recipe:
        targets.append((options.recipe_path, "the command recipe this export "
                                             "would also write"))
    if not options.overwrite:
        for target, role in targets:
            if not target.exists():
                continue
            if role:
                raise FileExistsError(
                    f"{role} already exists: {target} — pass 'overwrite true', "
                    f"choose another name, or turn that sidecar off"
                )
            raise FileExistsError(f"output file already exists: {target}")


def build_export_commands(options: ExportOptions) -> tuple[str, ...]:
    _validate_targets(options)
    transparent = "true" if options.transparent else "false"
    commands = [
        # ChimeraX renders the selection highlight into saved images, so
        # anything selected when the user hits export lands in the figure as a
        # green outline. That was harmless while nothing in MolCompose
        # selected anything; it stops being harmless the moment interface
        # blocks and interaction chips become clickable selectors.
        "~select",
        f"save {quote_path(options.path)} width {options.width} height {options.height} "
        f"supersample {options.supersample} transparentBackground {transparent}"
    ]
    if options.save_session:
        commands.append(f"save {quote_path(options.session_path)}")
    return tuple(commands)


def stamp_resolution(path: Path, dpi: int) -> bool:
    """Record the print resolution in the saved image. True if it was written.

    Best-effort on purpose. The figure is already on disk and correct at this
    point; a missing imaging library is a reason to leave the metadata off,
    not to fail an export that has succeeded.
    """
    if not dpi:
        return False
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        with Image.open(path) as image:
            image.load()
            # `save` back to the same path, which is safe here because both
            # supported formats are lossless — re-encoding costs nothing but
            # time. This would be a real loss of quality on a JPEG, which is
            # one more reason the suffix list does not include it.
            image.save(path, dpi=(dpi, dpi))
    except (OSError, ValueError):
        return False
    return True


def software_line() -> str:
    """`MolCompose 0.1.2, UCSF ChimeraX 1.12` — who made the figure.

    The recipe exists so a published figure can be replayed, and until now it
    said everything about the figure except which build produced it. That is
    the one fact a replay cannot recover for itself: the same commands render
    differently across preset versions, and every preset carries its own
    version precisely because they do. The version reached the JSON report
    and not the file people actually send to each other.
    """
    from .. import __version__

    chimerax = "unknown"
    try:  # pragma: no cover - depends on the host ChimeraX
        from chimerax.core import buildinfo

        chimerax = str(buildinfo.version)
    except Exception:
        pass
    return f"MolCompose {__version__}, UCSF ChimeraX {chimerax}"


def write_recipe(path: Path, commands, header=()) -> None:
    """Write the recipe as a ChimeraX command file that replays the figure."""
    lines = [f"# {line}" for line in header]
    lines.extend(commands)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# How far the export's proportions may differ from the window's before the
# colour key drifts visibly. Measured on one machine by exporting the same
# scene across aspects: at 0.75x and 0.78x of the window's aspect the key sat
# comfortably clear, at 1.08x it was tight, and at 1.39x its labels were gone
# off the bottom. The threshold is deliberately a warning and not a
# correction: the relationship is a property of how ChimeraX lays the key out
# against the window, and a fitted constant would only be right on the window
# it was fitted to.
ASPECT_DRIFT_WARNING = 1.15


def window_size(session):
    """The graphics window's (width, height), or None if it cannot be read."""
    view = getattr(session, "main_view", None)
    size = getattr(view, "window_size", None)
    if not size or len(size) != 2 or not all(size):
        return None
    return (int(size[0]), int(size[1]))


def key_aspect_drift(session, width, height):
    """How much wider in proportion this export is than the window, or None.

    None when it is within tolerance, or when the window size cannot be read —
    on a headless session there is nothing to correct against.
    """
    if not (width and height):
        return None
    size = window_size(session)
    if size is None:
        return None
    ratio = (width / height) / (size[0] / size[1])
    return ratio if ratio > ASPECT_DRIFT_WARNING else None


def window_matching(size, width, height):
    """A window of the export's shape that fits inside the one there now.

    Never larger, so the request cannot be clamped by the screen and come back
    a shape nobody asked for.
    """
    aspect = width / height
    if size[0] / aspect <= size[1]:
        return (size[0], max(1, round(size[0] / aspect)))
    return (max(1, round(size[1] * aspect)), size[1])


def color_key(session):
    """The colour key in the scene, or None if nothing has drawn one.

    Matched on the class name rather than imported, because
    `chimerax.color_key` is a bundle that need not be present, and because the
    unit tests run without ChimeraX at all.
    """
    models = getattr(session, "models", None)
    if models is None:
        return None
    for model in models.list():
        if type(model).__name__ == "ColorKeyModel":
            return model
    return None


def export_figure(session, options: ExportOptions, runner=None, recipe=()):
    if runner is None:
        from chimerax.core.commands import run as runner
    commands = build_export_commands(options)
    key = color_key(session)
    if options.key_font_size is not None and key is None:
        raise ValueError(
            "keyFontSize was given but the scene has no colour key. Apply "
            "a preset that draws one, or colour by a metric, first. "
            "Asking ChimeraX for a key that does not exist draws its "
            "generic blue-to-red bar, which would label the figure with a "
            "scale it was not painted with."
        )
    if key is not None:
        # Read before anything changes them, and put back after the save: these
        # describe the file, not the scene. A viewport left at a size picked
        # for one figure's final layout is how the next export goes out wrong
        # without anyone touching a setting.
        before, after = [], []
        font = key.font_size
        if options.key_font_size is not None:
            before.append(f"key fontSize {options.key_font_size}")
            after.append(f"key fontSize {font}")
            font = options.key_font_size
        # Export is the only place the height is actually known: the key is
        # drawn when a preset is applied or a metric coloured, long before
        # anyone says how tall the image will be.
        x, y = key.pos
        lifted = key_clearance_y(y, font, options.height)
        if lifted > y:
            before.append(f"key pos {x:.4g},{lifted:.4g}")
            after.append(f"key pos {x:.4g},{y:.4g}")
        # ChimeraX lays the key out against the graphics window, not the saved
        # frame, so an export shaped very differently from the window moves it
        # — far enough past about 1.4x to lose its labels off the bottom. The
        # window is briefly given the export's shape so the two agree, and put
        # back afterwards. Bracketed like everything else here: what the file
        # needs is not a change to the session.
        drift = key_aspect_drift(session, options.width, options.height)
        current = window_size(session) if drift is not None else None
        if current is not None:
            # Outermost, and before the key is placed: the position is
            # relative to a window that is about to change shape.
            matched = window_matching(current, options.width, options.height)
            before.insert(0, f"windowsize {matched[0]} {matched[1]}")
            after.append(f"windowsize {current[0]} {current[1]}")
            session.logger.info(
                f"MolCompose export: this image is {drift:.1f}x wider in "
                "proportion than the window, which is where ChimeraX places "
                f"the colour key, so the window was set to {matched[0]}x"
                f"{matched[1]} for the save and put back."
            )
        commands = (*before, *commands, *after)
    for command in commands:
        runner(session, command)
    stamp_resolution(options.path, options.dpi)
    session_path = options.session_path if options.save_session else None
    recipe_path = None
    if options.save_recipe:
        width_mm, height_mm = options.print_size_mm
        write_recipe(
            options.recipe_path,
            recipe,
            header=(
                f"MolCompose recipe for {options.path.name}",
                software_line(),
                f"{options.width}x{options.height} px"
                + (f", {options.dpi} dpi ({width_mm:.0f}x{height_mm:.0f} mm)"
                   if options.dpi else ""),
                "Replay with: open this file in ChimeraX, or `open <this file>`.",
            ),
        )
        recipe_path = options.recipe_path
    return options.path, session_path, commands, recipe_path
