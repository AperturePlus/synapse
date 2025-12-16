"""Core module containing IR models, serializer, and validator."""

from synapse.core.models import (
    Callable,
    CallableKind,
    Entity,
    IR,
    LanguageType,
    Module,
    Relationship,
    Type,
    TypeKind,
    UnresolvedReference,
    Visibility,
)
from synapse.core.serializer import (
    SerializationError,
    deserialize,
    deserialize_from_dict,
    serialize,
    serialize_to_dict,
)
from synapse.core.validator import (
    ValidationError,
    ValidationErrorType,
    ValidationResult,
    validate_ir,
)

__all__ = [
    "Callable",
    "CallableKind",
    "Entity",
    "IR",
    "LanguageType",
    "Module",
    "Relationship",
    "SerializationError",
    "Type",
    "TypeKind",
    "UnresolvedReference",
    "ValidationError",
    "ValidationErrorType",
    "ValidationResult",
    "Visibility",
    "deserialize",
    "deserialize_from_dict",
    "serialize",
    "serialize_to_dict",
    "validate_ir",
]
