"""What an agent is allowed to put inside a ChimeraX command.

Every typed tool in `server.py` builds a command string by interpolation, and
until 2026-08-21 it interpolated whatever the agent sent. `model="#1; delete
all"` was a working way to run `delete all`, and the same shape existed on the
reference, the chain map and the chain groups. The server's own instructions
say agents get "typed tools"; without this module the types were names for
free text.

The rule here is allow-listing by shape, not escaping. Escaping is a promise
that the escaper understands every metacharacter of a language it does not
own; ChimeraX commands are separated by `;`, take quoted and unquoted
arguments, and expand `$`-prefixed names. A model specifier is `#1` or `#1.2`,
a chain is a short alphanumeric label, and anything that is not exactly that
shape is a mistake worth naming rather than a string worth sanitising.

Paths are the exception and go through `quote_path` in `server.py`: they are
user data with legitimate spaces and punctuation, so they are quoted, and the
tools that take them refuse suffixes ChimeraX would execute.
"""

import re
from collections.abc import Collection, Sequence

# `#1`, `#1.2`, `#1.2.3`, and comma-separated lists of those. Ranges (`#1-3`)
# are deliberately absent: no typed tool needs one, and every character not
# needed is a character not to reason about.
_MODEL_SPEC = re.compile(r"#\d+(?:\.\d+)*")
_MODEL_LIST = re.compile(rf"^{_MODEL_SPEC.pattern}(?:,{_MODEL_SPEC.pattern})*$")

# ChimeraX chain IDs come from mmCIF `label_asym_id` and are short and
# alphanumeric. Four characters is the PDB limit.
_CHAIN = re.compile(r"^[A-Za-z0-9]{1,4}$")
_CHAIN_MAP = re.compile(r"^[A-Za-z0-9]{1,4}:[A-Za-z0-9]{1,4}"
                        r"(?:,[A-Za-z0-9]{1,4}:[A-Za-z0-9]{1,4})*$")

# Suffixes ChimeraX opens by *running*. `open` is how a structure arrives and
# also how a script does, which is why `open_structure` is a typed tool and
# `open` is not on the native whitelist.
EXECUTABLE_SUFFIXES = (".cxc", ".cmd", ".py", ".pyc", ".pyo", ".pyw", ".cxs")

# ChimeraX 1.12's registered molecular coordinate readers. Its format manager
# removes ONE compression suffix before choosing the reader; match that rule.
STRUCTURE_SUFFIXES = (".pdb", ".pdb1", ".ent", ".pqr", ".cif", ".mmcif",
                      ".mol2", ".sdf", ".mol")
_COMPRESSION_SUFFIXES = (".gz", ".bz2", ".xz")
_PDB_ID = re.compile(r"(?:pdb:)?[1-9][A-Za-z0-9]{3}", re.IGNORECASE)


class InvalidArgument(ValueError):
    """An argument that is not the shape its parameter promises."""


def model_spec(value, what: str = "model") -> str | None:
    """A ChimeraX model specifier, or None if none was given."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not _MODEL_LIST.match(text):
        raise InvalidArgument(
            f"{what} must be a ChimeraX model specifier such as '#1' or "
            f"'#1,#2', not {value!r}"
        )
    return text


def chain_id(value, what: str = "chain") -> str:
    text = str(value).strip()
    if not _CHAIN.match(text):
        raise InvalidArgument(
            f"{what} must be a chain identifier of up to four letters or "
            f"digits, not {value!r}"
        )
    return text


def chain_ids(values, what: str = "chain") -> list[str]:
    if isinstance(values, str):
        values = [part for part in values.split(",") if part.strip()]
    if not values:
        raise InvalidArgument(f"{what} is empty")
    return [chain_id(value, what) for value in values]


def chain_map(value, what: str = "chain_map") -> str | None:
    """`A:A,B:D` -- the reference's chain letters against the model's."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not _CHAIN_MAP.match(text):
        raise InvalidArgument(
            f"{what} must map chain to chain, as in 'A:A,B:D', not {value!r}"
        )
    return text


def structure_path(value, what: str = "path") -> str:
    """A path or PDB ID to open as a structure.

    Allow known coordinate readers (optionally compressed) and PDB IDs.
    Other fetch schemes, format overrides, globs and executable/session files
    are outside this tool's contract. This is a dispatch boundary, not a
    sandbox for malicious file contents or modified host format providers.
    """
    text = str(value).strip()
    if not text:
        raise InvalidArgument(f"{what} is empty")
    if any(ord(char) < 32 or ord(char) == 127 for char in str(value)):
        raise InvalidArgument(f"{what} may not contain control characters")
    if _PDB_ID.fullmatch(text):
        return text
    if any(char in text for char in ';:\"\'`$*?[]'):
        raise InvalidArgument(f"{what} must be one local structure path or PDB ID")
    lowered = text.lower()
    for compression in _COMPRESSION_SUFFIXES:
        if lowered.endswith(compression):
            lowered = lowered[:-len(compression)]
            break
    for suffix in EXECUTABLE_SUFFIXES:
        if lowered.endswith(suffix):
            raise InvalidArgument(
                f"{what} ends in {suffix}, which ChimeraX runs rather than "
                "opens. This tool opens structures; run commands through the "
                "typed tools instead."
            )
    if not lowered.endswith(STRUCTURE_SUFFIXES):
        raise InvalidArgument(
            f"{what} must use a supported structure suffix "
            f"({', '.join(STRUCTURE_SUFFIXES)}), optionally .gz/.bz2/.xz, "
            "or be a PDB ID"
        )
    return text


#: Anything that could end one ChimeraX command and begin another. The bridge
#: splits on `;` — verified against ChimeraX 1.12, where `version; open 1crn`
#: opens a model — so a string reaching a command line unquoted is a command
#: line, whatever it was called in the signature.
_COMMAND_BREAKERS = (";", "\n", "\r")


def enum_value(value, allowed: Collection[str], what: str) -> str | None:
    """A value from a fixed set, or a refusal naming the set.

    Every enumerated argument used to be interpolated into a command as it
    arrived. Most were already checked somewhere; `format`, `source` and
    `chains` were not, and an argument that reaches a ChimeraX command line
    unquoted *is* a ChimeraX command line.
    """
    if value is None:
        return None
    text = str(value)
    if text not in allowed:
        raise InvalidArgument(
            f"{what} must be one of {', '.join(sorted(allowed))}, not {text!r}"
        )
    return text


def one_of(value, allowed, what: str):
    """Backward-compatible name for :func:`enum_value`."""
    return enum_value(value, allowed, what)


def command_token(
    value,
    what: str,
    *,
    pattern: str = r"[A-Za-z0-9_.:,+-]{1,64}",
) -> str | None:
    """A bare word safe to interpolate: no separators, no whitespace, bounded.

    For the arguments that are not a closed set but still must not be able to
    start a second command.
    """
    if value is None:
        return None
    text = str(value)
    for breaker in _COMMAND_BREAKERS:
        if breaker in text:
            raise InvalidArgument(
                f"{what} may not contain {breaker!r}: a value spliced into a "
                "ChimeraX command line can end it and begin another"
            )
    if not re.fullmatch(pattern, text):
        raise InvalidArgument(f"{what} is not a plain value: {text!r}")
    return text


def token(value, what: str, pattern: str = r"[A-Za-z0-9_.:,+-]{1,64}") -> str | None:
    """Backward-compatible name for :func:`command_token`."""
    return command_token(value, what, pattern=pattern)


def token_list(
    value: str | Sequence[str],
    allowed: Collection[str],
    what: str,
) -> tuple[str, ...]:
    """A comma-separated subset of a closed set, safe for a bare argument."""
    if isinstance(value, str):
        parts = tuple(part.strip() for part in value.split(",") if part.strip())
    else:
        parts = tuple(str(part).strip() for part in value if str(part).strip())
    if not parts:
        raise InvalidArgument(f"{what} is empty")
    return tuple(enum_value(part, allowed, what) for part in parts)
