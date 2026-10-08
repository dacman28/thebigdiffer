"""Fail-closed validation for the smoke-tested Bedrock tool-schema subset."""

from __future__ import annotations

_SUPPORTED_SCHEMA_KEYS = {"type", "properties", "required", "additionalProperties", "enum"}
_SUPPORTED_TYPES = {"object", "string", "integer"}


def validate_bedrock_tool_config(tool_config: object) -> None:
    if not isinstance(tool_config, dict):
        raise ValueError("toolConfig must be an object")
    if set(tool_config) != {"tools", "toolChoice"}:
        raise ValueError("toolConfig must contain only tools and toolChoice")
    if tool_config.get("toolChoice") != {"auto": {}}:
        raise ValueError("toolChoice must be exactly auto")
    tools = tool_config.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ValueError("toolConfig.tools must be a non-empty array")
    names: set[str] = set()
    for index, entry in enumerate(tools):
        if not isinstance(entry, dict) or set(entry) != {"toolSpec"}:
            raise ValueError(f"tool {index} must contain exactly one toolSpec")
        spec = entry["toolSpec"]
        if not isinstance(spec, dict):
            raise ValueError(f"tool {index} toolSpec must be an object")
        if set(spec) != {"name", "description", "inputSchema", "strict"}:
            raise ValueError(f"tool {index} has unsupported toolSpec fields")
        name = spec.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"tool {index} name must be a non-empty string")
        if name in names:
            raise ValueError(f"duplicate tool name: {name}")
        names.add(name)
        if not isinstance(spec.get("description"), str) or not spec["description"]:
            raise ValueError(f"tool {name} description must be a non-empty string")
        if spec.get("strict") is not True:
            raise ValueError(f"tool {name} must enable strict tool use")
        input_schema = spec.get("inputSchema")
        if not isinstance(input_schema, dict) or set(input_schema) != {"json"}:
            raise ValueError(f"tool {name} inputSchema must contain exactly json")
        _validate_schema(input_schema["json"], location=f"tool {name} inputSchema.json")


def _validate_schema(value: object, *, location: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    unsupported = set(value) - _SUPPORTED_SCHEMA_KEYS
    if unsupported:
        raise ValueError(f"{location} uses unsupported schema keys: {sorted(unsupported)}")
    schema_type = value.get("type")
    if schema_type not in _SUPPORTED_TYPES:
        raise ValueError(f"{location} has unsupported or missing type: {schema_type!r}")
    enum = value.get("enum")
    if enum is not None:
        if schema_type != "string" or not isinstance(enum, list) or not enum:
            raise ValueError(f"{location} enum must be a non-empty string enum")
        if any(not isinstance(item, str) for item in enum):
            raise ValueError(f"{location} enum values must be strings")
    if schema_type != "object":
        if any(key in value for key in ("properties", "required", "additionalProperties")):
            raise ValueError(f"{location} uses object keywords on a non-object schema")
        return
    properties = value.get("properties")
    required = value.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ValueError(f"{location} requires properties and required")
    if value.get("additionalProperties") is not False:
        raise ValueError(f"{location} must reject additional properties")
    if any(not isinstance(item, str) for item in required) or len(set(required)) != len(required):
        raise ValueError(f"{location} required must contain unique strings")
    missing = set(required) - set(properties)
    if missing:
        raise ValueError(f"{location} requires undefined properties: {sorted(missing)}")
    for property_name, property_schema in properties.items():
        if not isinstance(property_name, str) or not property_name:
            raise ValueError(f"{location} property names must be non-empty strings")
        _validate_schema(property_schema, location=f"{location}.properties.{property_name}")
