"""Language adapters for parsing different programming languages.

This module provides the base classes and utilities for implementing
language-specific parsers that produce IR (Intermediate Representation) data.
"""

from synapse.adapters.base import (
    FileContext,
    LanguageAdapter,
    SymbolTable,
    generate_entity_id,
)
from synapse.adapters.go import GoAdapter
from synapse.adapters.java import JavaAdapter
from synapse.adapters.php import PhpAdapter

__all__ = [
    "FileContext",
    "GoAdapter",
    "JavaAdapter",
    "PhpAdapter",
    "LanguageAdapter",
    "SymbolTable",
    "generate_entity_id",
]
