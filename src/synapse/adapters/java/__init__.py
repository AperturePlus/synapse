"""Java language adapter submodule.

This module provides the Java adapter for parsing Java source code
into the unified Intermediate Representation (IR).
"""

from synapse.adapters.java.adapter import JavaAdapter
from synapse.adapters.java.resolver import JavaResolver, LocalScope
from synapse.adapters.java.type_inferrer import TypeInferrer

__all__ = ["JavaAdapter", "JavaResolver", "LocalScope", "TypeInferrer"]
