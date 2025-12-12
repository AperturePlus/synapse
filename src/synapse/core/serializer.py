"""IR serialization and deserialization.

This module provides functions to serialize IR data to JSON and deserialize
JSON back to IR structures. Circular references are handled using ID references.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from synapse.core.models import IR


class SerializationError(Exception):
    """Error during serialization or deserialization."""

    def __init__(self, message: str, details: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def serialize(ir: IR) -> str:
    """Serialize an IR structure to JSON string.

    Args:
        ir: The IR structure to serialize.

    Returns:
        JSON string representation of the IR.

    Raises:
        SerializationError: If serialization fails.
    """
    try:
        # Pydantic v2 uses model_dump for dict conversion
        data = ir.model_dump(mode="json")
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        raise SerializationError(
            message="Failed to serialize IR",
            details=str(e),
        ) from e


def deserialize(json_str: str) -> IR:
    """Deserialize a JSON string to an IR structure.

    Args:
        json_str: JSON string representation of an IR.

    Returns:
        The deserialized IR structure.

    Raises:
        SerializationError: If deserialization fails with detailed error info.
    """
    try:
        data = json.loads(json_str)
        return IR.model_validate(data)
    except json.JSONDecodeError as e:
        raise SerializationError(
            message="Invalid JSON format",
            details=f"Line {e.lineno}, column {e.colno}: {e.msg}",
        ) from e
    except ValidationError as e:
        # Extract detailed validation errors
        errors = e.errors()
        error_details = []
        for err in errors:
            loc = ".".join(str(x) for x in err["loc"])
            error_details.append(f"{loc}: {err['msg']}")
        raise SerializationError(
            message="IR validation failed",
            details="; ".join(error_details),
        ) from e
    except Exception as e:
        raise SerializationError(
            message="Failed to deserialize IR",
            details=str(e),
        ) from e


def serialize_to_dict(ir: IR) -> dict[str, Any]:
    """Serialize an IR structure to a dictionary.

    Args:
        ir: The IR structure to serialize.

    Returns:
        Dictionary representation of the IR.
    """
    return ir.model_dump(mode="json")


def deserialize_from_dict(data: dict[str, Any]) -> IR:
    """Deserialize a dictionary to an IR structure.

    Args:
        data: Dictionary representation of an IR.

    Returns:
        The deserialized IR structure.

    Raises:
        SerializationError: If deserialization fails.
    """
    try:
        return IR.model_validate(data)
    except ValidationError as e:
        errors = e.errors()
        error_details = []
        for err in errors:
            loc = ".".join(str(x) for x in err["loc"])
            error_details.append(f"{loc}: {err['msg']}")
        raise SerializationError(
            message="IR validation failed",
            details="; ".join(error_details),
        ) from e
