"""A deliberately small, complete grammar for native display commands.

ChimeraX 1.12 expands command and keyword prefixes and unquotes tokens before
matching them. Checking a verb plus forbidden literal words therefore cannot
protect coordinates or files. These rules instead accept complete supported
forms, with exact keywords and a limited atom-spec grammar. New host options
and subcommands are unavailable until explicitly reviewed here.

This is a dispatch boundary for a standard host, not a sandbox against a
modified ChimeraX installation, command aliases, or hostile structure data.
"""

import re

_NUMBER = r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"
_POSITIVE_INT = r"[1-9][0-9]*"
_BOOL = r"(?:true|false)"
# Match the host's actual atomspec grammar, not merely its character set.
# Invalid ObjectsArg input falls back to NamedViewArg in `view`, potentially
# restoring model placements. Model components are 1–5 ASCII digits; native
# multi-model forms are #1,2 and #1#2, NOT #1,#2.
_MODEL_COMPONENT = r"[0-9]{1,5}"
_MODEL = rf"#{_MODEL_COMPONENT}(?:\.{_MODEL_COMPONENT})*"
_MODEL_LEVEL = rf"{_MODEL_COMPONENT}(?:,{_MODEL_COMPONENT})*"
_MODEL_HIERARCHY = rf"#{_MODEL_LEVEL}(?:\.{_MODEL_LEVEL})*"
_NAME_LIST = r"[A-Za-z0-9]+(?:,[A-Za-z0-9]+)*"
_RESIDUE = r"-?[0-9]+(?:--?[0-9]+)?"
_OBJECT_SPEC = (
    rf"{_MODEL_HIERARCHY}(?:{_MODEL_HIERARCHY})*(?:/{_NAME_LIST})?"
    rf"(?::{_RESIDUE}(?:,{_RESIDUE})*)?(?:@{_NAME_LIST})?"
)
# Selector registration is case-sensitive in ChimeraX. View framing below
# requires explicit # selectors so its success never depends on registration.
_SPEC = rf"(?:{_OBJECT_SPEC}|(?-i:all|sel|protein|nucleic|ligand|solvent|ions))"
_VECTOR = rf"{_NUMBER},{_NUMBER},{_NUMBER}"
_AXIS = rf"(?:x|y|z|{_VECTOR})"
_COLOR = r"(?:[A-Za-z]+|#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?)"
_WHAT = r"(?:atoms|bonds|cartoons|ribbons|surfaces|models|pseudobonds)"
_TARGET = r"[abcspflmr]+"


def _options(options):
    """Zero or more exact keyword/value pairs from a reviewed mapping."""
    return "(?: (?:" + "|".join(
        f"{key} {value}" if value else key for key, value in options.items()
    ) + "))*"


_CAMERA_OPTIONS = {
    "center": rf"(?:{_VECTOR}|{_SPEC})", "coordinateSystem": _MODEL,
}
_MOTION = rf"(?: {_AXIS}(?: {_NUMBER}(?: {_POSITIVE_INT})?)?)?"
_RULES = [
    # A bare numeric argument can itself be a saved view name, so frames are
    # accepted only after an explicit valid objectspec. Bare `view` frames all.
    rf"view(?: {_OBJECT_SPEC}(?: {_POSITIVE_INT})?)?" + _options({
        "clip": _BOOL, "cofr": _BOOL, "orient": "", "pad": _NUMBER,
        "zalign": _SPEC, "inFrontOf": _SPEC,
    }),
    "view list",
    rf"(?:turn|roll){_MOTION}" + _options({
        **_CAMERA_OPTIONS, "rock": _POSITIVE_INT, "wobble": _POSITIVE_INT,
        "wobbleAspect": _NUMBER,
    }),
    rf"rock{_MOTION}" + _options({**_CAMERA_OPTIONS, "cycle": _POSITIVE_INT}),
    rf"zoom(?: {_NUMBER}(?: {_POSITIVE_INT})?)?" + _options({"pixelSize": _NUMBER}),
    r"select (?:clear|up|down)",
    rf"select(?: (?:add|subtract|intersect))?(?: {_SPEC})?"
    + _options({"residues": _BOOL}),
    rf"(?:show|hide)(?: {_SPEC})?(?: {_WHAT}(?:,{_WHAT})*)?"
    + _options({"target": _TARGET}),
    rf"color {_SPEC} {_COLOR}(?: {_WHAT}(?:,{_WHAT})*)?"
    + _options({"target": _TARGET, "transparency": _NUMBER, "halfbond": _BOOL}),
    # Explicit read-only info subcommands; no notify or saveFile variants.
    rf"info(?: (?:models|chains|polymers|residues|atoms|bounds))?(?: {_SPEC})?",
    r"info (?:atomattr|bondattr|resattr)",
    r"version(?: (?:verbose|bundles|packages))?",
    r"lighting(?: (?:default|full|soft|gentle|simple|flat))?" + _options({
        "direction": _VECTOR, "intensity": _NUMBER, "color": _COLOR,
        "fillDirection": _VECTOR, "fillIntensity": _NUMBER, "fillColor": _COLOR,
        "ambientIntensity": _NUMBER, "ambientColor": _COLOR,
        "depthCue": _BOOL, "depthCueStart": _NUMBER, "depthCueEnd": _NUMBER,
        "depthCueColor": _COLOR, "moveWithCamera": _BOOL, "shadows": _BOOL,
        "qualityOfShadows": r"(?:coarse|low|medium|fine|finer)",
        "depthBias": _NUMBER, "multiShadow": r"[0-9]+", "msMapSize": _POSITIVE_INT,
        "msDepthBias": _NUMBER,
    }),
    r"graphics" + _options({"backgroundColor": _COLOR, "bgColor": _COLOR}),
    rf"graphics quality(?: {_NUMBER})?",
    rf"graphics silhouettes(?: {_BOOL})?"
    + _options({"width": _NUMBER, "color": _COLOR, "depthJump": _NUMBER}),
    r"graphics selection" + _options({"width": _NUMBER, "color": _COLOR}),
    rf"measure (?:length|weight) {_SPEC}",
    r"stop",
]
_ALLOWED = tuple(re.compile(rule, re.IGNORECASE | re.ASCII) for rule in _RULES)


def native_allowed(command: str) -> bool:
    """Whether the entire command is an explicitly supported native form."""
    if not isinstance(command, str) or any(
        ord(char) < 32 or ord(char) == 127 for char in command
    ):
        return False
    # Do not reinterpret quotes, escapes, aliases, or command separators.
    if any(char in command for char in ';\"\'\\`$'):
        return False
    # Normalize ordinary spaces only, after checking controls on raw input.
    text = re.sub(" +", " ", command.strip())
    return any(rule.fullmatch(text) is not None for rule in _ALLOWED)
