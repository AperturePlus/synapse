"""Go language adapter submodule.

This module provides the Go adapter for parsing Go source code
into the unified Intermediate Representation (IR).
"""

from synapse.adapters.go.adapter import GoAdapter
from synapse.adapters.go.resolver import GoLocalScope
from synapse.adapters.go.type_inferrer import GoTypeInferrer

__all__ = ["GoAdapter", "GoLocalScope", "GoTypeInferrer"]
