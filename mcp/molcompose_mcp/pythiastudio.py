"""Optional PythiaStudio REST client, kept out of the ChimeraX bundle.

The bundle itself never touches the network: it consumes ΔΔG *files*. This
module lets an agent fetch predictions from PythiaStudio and write them to a
file that `molcompose ddg` can then load — so the agent, not the bundle,
becomes the integration layer, and the bundle keeps its zero-service
dependency profile.

API keys are supplied by the user (environment variable `PYTHIASTUDIO_API_KEY`
or an explicit argument) and are never logged.
"""

import csv
import io
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://pythiastudio.wulab.xyz"
ENDPOINTS = {
    "pythia-ppi": "/api/tools/pythia-ppi/predict",
    "pythia": "/api/tools/pythia/scan",
}


class PythiaStudioError(RuntimeError):
    pass


def api_key(explicit: str | None = None) -> str:
    key = explicit or os.environ.get("PYTHIASTUDIO_API_KEY", "")
    if not key:
        raise PythiaStudioError(
            "no PythiaStudio API key: set PYTHIASTUDIO_API_KEY or pass one "
            "explicitly (request a key from the PythiaStudio maintainers)"
        )
    return key


def request_prediction(
    structure_path: str,
    tool: str = "pythia-ppi",
    base_url: str = DEFAULT_BASE_URL,
    key: str | None = None,
    timeout: float = 600.0,
) -> dict:
    """POST a structure to PythiaStudio and return the decoded JSON response."""
    if tool not in ENDPOINTS:
        raise PythiaStudioError(
            f"tool must be one of {', '.join(sorted(ENDPOINTS))}: {tool}"
        )
    try:
        structure = open(structure_path, "rb").read()  # noqa: SIM115
    except OSError as error:
        raise PythiaStudioError(f"cannot read structure file: {error}") from error

    boundary = "----molcompose-mcp-boundary"
    name = os.path.basename(structure_path)
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            structure,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    request = Request(  # noqa: S310 - fixed https endpoint
        f"{base_url.rstrip('/')}{ENDPOINTS[tool]}",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {api_key(key)}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise PythiaStudioError(
            f"PythiaStudio returned HTTP {error.code}; check the API key and quota"
        ) from error
    except (URLError, OSError, ValueError) as error:
        raise PythiaStudioError(f"PythiaStudio request failed: {error}") from error


def to_tabular(payload: dict) -> str:
    """Flatten a PythiaStudio mutation map into the tabular ΔΔG format.

    The exact response schema is not published, so several plausible shapes are
    accepted; anything unrecognised raises with the observed keys so the caller
    can report the real format.
    """
    records = None
    for key in ("mutations", "results", "predictions", "data"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            records = value
            break
    if records is None:
        raise PythiaStudioError(
            "could not find a mutation list in the PythiaStudio response; "
            f"top-level keys were: {', '.join(sorted(payload))}"
        )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["chain", "position", "wt", "mut", "ddG"])
    written = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        lowered = {str(k).lower(): v for k, v in record.items()}

        def pick(*names, mapping=lowered):
            for name in names:
                if mapping.get(name) not in (None, ""):
                    return mapping[name]
            return ""

        position = pick("position", "pos", "resnum", "residue")
        ddg = pick("ddg", "ddG".lower(), "score", "prediction", "value")
        if position == "" or ddg == "":
            continue
        writer.writerow(
            [
                pick("chain", "chain_id"),
                position,
                str(pick("wt", "wild_type", "from")).upper(),
                str(pick("mut", "mutant", "to")).upper(),
                ddg,
            ]
        )
        written += 1
    if not written:
        raise PythiaStudioError(
            "the PythiaStudio response contained no usable mutation records"
        )
    return buffer.getvalue()
