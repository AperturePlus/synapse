"""IR data models for Synapse code topology modeling system.

This module defines the core data structures for the Intermediate Representation (IR)
that abstracts code structures across different programming languages.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class LanguageType(str, Enum):
    """Supported programming languages."""

    JAVA = "java"
    GO = "go"
    PHP = "php"


class TypeKind(str, Enum):
    """Kind of type definition."""

    CLASS = "CLASS"
    INTERFACE = "INTERFACE"
    STRUCT = "STRUCT"
    ENUM = "ENUM"
    TRAIT = "TRAIT"


class CallableKind(str, Enum):
    """Kind of callable entity."""

    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    CONSTRUCTOR = "CONSTRUCTOR"


class Visibility(str, Enum):
    """Visibility/access modifier."""

    PUBLIC = "public"
    PRIVATE = "private"
    PROTECTED = "protected"
    PACKAGE = "package"  # Java default / Go unexported


class Entity(BaseModel):
    """Base class for all IR entities."""

    id: str = Field(..., description="Unique identifier")
    name: str = Field(..., description="Simple name")
    qualified_name: str = Field(..., description="Fully qualified name")


class Module(Entity):
    """Module/package representation.

    Represents a namespace boundary like Java package or Go package.
    """

    path: str = Field(..., description="File system path")
    language_type: LanguageType
    sub_modules: list[str] = Field(default_factory=list, description="Sub-module IDs")
    declared_types: list[str] = Field(default_factory=list, description="Declared type IDs")


class Type(Entity):
    """Type definition representation.

    Unified abstraction for class, interface, struct, and enum.
    """

    kind: TypeKind
    language_type: LanguageType
    modifiers: list[str] = Field(default_factory=list, description="Type modifiers")
    annotations: list[str] = Field(
        default_factory=list,
        description="Annotations/attributes applied to the type (best-effort, language-specific)",
    )
    stereotypes: list[str] = Field(
        default_factory=list,
        description="Framework stereotypes/tags inferred by enrichers (e.g., spring:service)",
    )
    extends: list[str] = Field(default_factory=list, description="Extended type IDs")
    implements: list[str] = Field(default_factory=list, description="Implemented interface IDs")
    embeds: list[str] = Field(default_factory=list, description="Embedded type IDs (Go)")
    callables: list[str] = Field(default_factory=list, description="Contained callable IDs")


class Callable(Entity):
    """Callable entity representation.

    Unified abstraction for function, method, and constructor.
    """

    kind: CallableKind
    language_type: LanguageType
    signature: str = Field(..., description="Method signature")
    is_static: bool = False
    visibility: Visibility = Visibility.PUBLIC
    return_type: str | None = Field(None, description="Return type ID")
    annotations: list[str] = Field(
        default_factory=list,
        description="Annotations/attributes applied to the callable (best-effort, language-specific)",
    )
    stereotypes: list[str] = Field(
        default_factory=list,
        description="Framework stereotypes/tags inferred by enrichers (e.g., spring:route)",
    )
    routes: list[str] = Field(
        default_factory=list,
        description="HTTP route patterns handled by this callable (e.g., 'GET /users')",
    )
    calls: list[str] = Field(default_factory=list, description="Called callable IDs")
    overrides: str | None = Field(None, description="Overridden method ID")


class Relationship(BaseModel):
    """Additional relationship inferred beyond core structural links."""

    source_id: str = Field(..., description="Source entity ID")
    target_id: str = Field(..., description="Target entity ID")
    relationship_type: str = Field(..., description="Relationship type (Neo4j rel type)")


class UnresolvedReference(BaseModel):
    """Unresolved reference from parsing.

    Represents a reference that could not be resolved during Phase 2 parsing.
    """

    source_callable: str = Field(..., description="Caller callable ID")
    target_name: str = Field(..., description="Target method name (short name)")
    context: str | None = Field(None, description="Context information")
    reason: str = Field(..., description="Reason for unresolved reference")


class IR(BaseModel):
    """Intermediate Representation root structure.

    Contains all modules, types, and callables for a language-specific codebase.
    """

    version: str = "1.0"
    language_type: LanguageType
    modules: dict[str, Module] = Field(default_factory=dict)
    types: dict[str, Type] = Field(default_factory=dict)
    callables: dict[str, Callable] = Field(default_factory=dict)
    relationships: list[Relationship] = Field(
        default_factory=list, description="Additional inferred relationships"
    )
    unresolved: list[UnresolvedReference] = Field(
        default_factory=list, description="Unresolved references"
    )

    def merge(self, other: IR) -> IR:
        """Merge two IR structures.

        Args:
            other: Another IR to merge with this one.

        Returns:
            A new IR containing data from both.
        """
        return IR(
            version=self.version,
            language_type=self.language_type,
            modules={**self.modules, **other.modules},
            types={**self.types, **other.types},
            callables={**self.callables, **other.callables},
            relationships=self.relationships + other.relationships,
            unresolved=self.unresolved + other.unresolved,
        )
