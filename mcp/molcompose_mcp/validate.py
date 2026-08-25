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
EXECUTABLE_SUFFIXES = (".cxc", ".cmd", ".py", ".pyc", ".pyw")


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

    Refuses the suffixes ChimeraX executes rather than parses. `open` is a
    single command with two jobs -- fetch a structure, or run a script -- and
    only the first one is what a tool called `open_structure` offers.
    """
    text = str(value).strip()
    if not text:
        raise InvalidArgument(f"{what} is empty")
    lowered = text.lower()
    for suffix in EXECUTABLE_SUFFIXES:
        if lowered.endswith(suffix):
            raise InvalidArgument(
                f"{what} ends in {suffix}, which ChimeraX runs rather than "
                "opens. This tool opens structures; run commands through the "
                "typed tools instead."
            )
    return text
