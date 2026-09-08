"""Validate typed tool output while preserving which optional fields exist."""

import functools
import json

from mcp.types import CallToolResult, TextContent
from pydantic import TypeAdapter


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
