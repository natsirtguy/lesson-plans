"""Turning Pydantic v2 models into schemas the structured-output API accepts.

The API's JSON Schema support is a subset: nested models must be inlined rather
than referenced, every object needs ``additionalProperties: false``, and
numeric/string constraint keywords are rejected. Pydantic emits all three, so
this module normalizes its output. Stripped constraints are not lost -- the model
still validates them client-side when we call ``model_validate_json``.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel

#: Keywords the structured-output endpoint rejects. Pydantic emits these from
#: ``Field(ge=..., max_length=...)`` and friends; they stay enforced client-side.
UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "default",
    }
)


def response_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Build a self-contained JSON Schema for use as a structured-output format.

    :param schema: The Pydantic model describing the expected output.
    """
    raw = schema.model_json_schema(ref_template="#/$defs/{model}")
    defs = cast(dict[str, Any], raw.pop("$defs", {}))
    result = _normalize(raw, defs, frozenset())
    if not isinstance(result, dict):  # pragma: no cover - models are always objects
        raise TypeError("model_json_schema did not produce an object schema")
    return result


def _normalize(node: object, defs: dict[str, Any], seen: frozenset[str]) -> object:
    """Inline ``$ref`` targets, drop unsupported keywords, and close objects.

    A reference already being expanded higher up the stack degrades to an opaque
    object rather than looping forever, so a recursive model fails validation
    instead of hanging schema generation.

    :param node: The schema fragment being rewritten.
    :param defs: The ``$defs`` table lifted off the root schema.
    :param seen: Definition names currently being expanded.
    """
    if isinstance(node, list):
        return [_normalize(item, defs, seen) for item in node]
    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        name = ref.removeprefix("#/$defs/")
        if name in seen or name not in defs:
            return {"type": "object", "additionalProperties": False}
        merged = {**defs[name], **{k: v for k, v in node.items() if k != "$ref"}}
        return _normalize(merged, defs, seen | {name})

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in UNSUPPORTED_KEYWORDS:
            continue
        out[key] = _normalize(value, defs, seen)

    if out.get("type") == "object":
        out["additionalProperties"] = False
        # The endpoint expects every declared property to be required; optional
        # fields are expressed as nullable unions instead.
        properties = out.get("properties")
        if isinstance(properties, dict):
            out["required"] = list(properties.keys())
    return out
