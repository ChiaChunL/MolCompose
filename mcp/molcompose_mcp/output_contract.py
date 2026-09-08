"""Validate typed tool output while preserving which optional fields exist."""

import functools
import json
import re

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import TypeAdapter, ValidationError

from .chimerax import ChimeraXCommandError, ChimeraXUnavailable
from .pythiastudio import PythiaStudioError


def report_tool_errors(function):
    """Expose anticipated failures, leaving unexpected bugs to the SDK.

    MCP 2.2 masks ordinary exceptions. Recoverable validation, host, and file
    errors must deliberately cross the registered boundary as ToolError so
    clients can read the instructions needed to correct the request.
    """
    declared_fields = getattr(function.__annotations__.get("return"), "__annotations__", {})

    @functools.wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ValidationError as error:
            # Nested locations can contain host dictionary keys, and custom
            # validation messages can contain inputs. Only expose declared
            # top-level schema fields, never those dynamic details.
            fields = set()
            for item in error.errors(
                include_input=False, include_url=False, include_context=False
            ):
                location = item["loc"]
                field = location[0] if location else None
                fields.add(field if field in declared_fields else "<root>")
            raise ToolError(f"Invalid tool output fields: {', '.join(sorted(fields))}") from error
        except (ValueError, OSError, ChimeraXCommandError,
                ChimeraXUnavailable, PythiaStudioError) as error:
            message = re.sub(
                r'''(?ix)
                (["']?authorization["']?\s*[:=]\s*)
                ("[^"]*"|'[^']*'|[^\r\n;}\)]+)
                ''',
                r'\1"[REDACTED]"',
                str(error),
            )
            message = re.sub(
                r'''(?ix)
                (["']?(?:api[_-]?key|apikey)["']?\s*[:=]\s*)
                ("[^"]*"|'[^']*'|[^\s,}\)]+)
                ''',
                r'\1"[REDACTED]"',
                message,
            )
            raise ToolError(message) from error

    return guarded


def preserve_output_fields(function):
    """Adapt only the registered callable; Python helpers keep returning dicts.

    MCP 2.0's TypedDict conversion fills absent NotRequired fields with None
    when dumping its output model, violating the published non-nullable schema.
    Validate the original dictionary and return it explicitly instead. The SDK
    still validates this CallToolResult against the registered output model,
    and normal clients still validate the published JSON schema.
    """
    contract = TypeAdapter(function.__annotations__["return"])

    @functools.wraps(function)
    def validated(*args, **kwargs):
        result = function(*args, **kwargs)
        if isinstance(result, CallToolResult):
            contract.validate_python(result.structured_content, strict=True)
            return result
        contract.validate_python(result, strict=True)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            structuredContent=result,
        )

    return validated
