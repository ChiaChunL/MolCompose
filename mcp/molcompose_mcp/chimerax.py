"""Minimal HTTP client for the ChimeraX ``remotecontrol rest`` bridge."""

import json
import re
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

# ChimeraX writes its log for a GUI panel: every command it echoes is wrapped
# in a clickable link, and the whole command text is repeated inside the href.
# In a `characterise` on 1BRS that markup is 56% of the reply — 6.2 kB of
# duplicated pbond syntax an agent must read past to reach the findings.
_LOG_LINK = re.compile(r"\[(?P<label>[^\]]*)\]\((?:cxcmd|help):[^)]*\)", re.DOTALL)


class ChimeraXUnavailable(RuntimeError):
    """Raised when the ChimeraX REST bridge cannot be reached."""


class ChimeraXCommandError(RuntimeError):
    """Raised when the bridge ran a command but ChimeraX rejected it."""

    def __init__(self, command: str, message: str):
        super().__init__(message)
        self.command = command


class ChimeraXClient:
    def __init__(self, base_url: str = "http://127.0.0.1:3000", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def run(self, command: str) -> dict:
        """Run one ChimeraX command; return parsed JSON or {'raw': text}."""
        url = f"{self.base_url}/run?{urlencode({'command': command})}"
        try:
            with urlopen(url, timeout=self.timeout) as response:  # noqa: S310 - localhost bridge
                text = response.read().decode("utf-8", errors="replace")
        except (URLError, OSError) as error:
            raise ChimeraXUnavailable(
                "Cannot reach ChimeraX. Start ChimeraX (windowed for image export), "
                "make sure ChimeraX-MolCompose is installed, and run: "
                "remotecontrol rest start port 3000 json true "
                f"(tried {self.base_url}; error: {error})"
            ) from error
        try:
            return json.loads(text)
        except ValueError:
            return {"raw": text}


#: What `command_value` returns when the bridge cannot supply a return value.
#: Distinct from ``None``, which is a return value a command may legitimately
#: have — telling the two apart is the difference between "this command
#: reported nothing" and "this bridge cannot report anything".
NO_VALUE = object()


def error_text(error: object) -> str:
    """Return the human message from ChimeraX's string or object error form."""
    if isinstance(error, dict):
        message = error.get("message")
        if message:
            return str(message)
    return str(error)


def log_text(payload: dict) -> str:
    """Flatten whatever log structure the REST bridge returned into one string.

    The command's *return value* is deliberately not folded in here. It used to
    be, as ``str(payload["python values"])``, which put a Python repr of the
    result on the end of the log — duplicating findings the command had already
    logged, and leaving the structured value reachable only by parsing it back
    out again. `command_value` returns it as data instead.
    """
    if "raw" in payload:
        return str(payload["raw"])
    parts = []
    messages = payload.get("log messages")
    if isinstance(messages, dict):
        for level_messages in messages.values():
            if isinstance(level_messages, list):
                parts.extend(str(message) for message in level_messages)
    elif isinstance(messages, list):
        parts.extend(str(message) for message in messages)
    error = payload.get("error")
    if error:
        parts.append(error_text(error))
    return unlink("\n".join(parts))


def command_value(payload: dict):
    """The command's return value, as data, or `NO_VALUE` if none is available.

    ChimeraX's REST bridge serialises each command's return value when it is
    started with ``json true`` — ``remotecontrol rest start port 3000 json
    true``, which is what the docked panel and every documented launch line
    use. A bridge started without it replies in plain text, there is no return
    value to be had, and callers get `NO_VALUE` rather than a fabricated one.

    Two keys can carry it. ``json values`` holds the JSON form of commands that
    opt into ChimeraX's ``JSONResult`` protocol, and is preferred; ``python
    values`` holds everything else, run through the bridge's own
    ``make_json_friendly``, which recurses into dicts, lists and tuples. Both
    are lists, one entry per command in the request, and MolCompose sends one
    command per request.
    """
    if "raw" in payload:
        return NO_VALUE
    for key in ("json values", "python values"):
        values = payload.get(key)
        if isinstance(values, list) and len(values) == 1 and values[0] is not None:
            return values[0]
    return NO_VALUE


def unlink(text: str) -> str:
    """Strip the ChimeraX log's link markup and the repetition it creates.

    Every echoed command appears twice: once as ``[pbond](help:...)`` followed
    by its arguments, then again whole inside a ``cxcmd:`` href. Unwrapping the
    links leaves the two forms identical, so the second is dropped. Only exact
    repeats go — the label is always kept, and text that never had a link is
    returned unchanged.

    The two copies are wrapped independently to the log panel's width, and
    ChimeraX breaks an over-long token by inserting a hyphen, so one copy can
    read ``mc-pi-\\nstacking`` where the other reads ``mc-pi-stacking``.
    Comparison therefore ignores whitespace entirely; the line breaks
    themselves are left as ChimeraX made them, since an inserted hyphen cannot
    be told apart from one belonging to the name.
    """
    blocks, previous = [], None
    for block in _LOG_LINK.sub(r"\g<label>", text).split("\n\n"):
        if not block.strip():
            continue
        collapsed = "".join(block.split())
        if collapsed != previous:
            blocks.append(block.strip())
        previous = collapsed
    return "\n\n".join(blocks)
