"""Go local scope tracking.

Kept separate from the resolver to reduce file size and make scope-related
behavior easier to test and maintain.
"""

from __future__ import annotations


class GoLocalScope:
    """Tracks variable types within a Go function body.

    Used during type inference to resolve variable references to their
    declared types. Supports parameters, local variables, and nested scopes.
    """

    def __init__(self) -> None:
        """Initialize an empty local scope."""
        self._variables: dict[str, str] = {}

    def add_variable(self, name: str, type_name: str) -> None:
        """Add a variable declaration to scope.

        Args:
            name: The variable name.
            type_name: The declared type of the variable.
        """
        self._variables[name] = type_name

    def get_type(self, name: str) -> str | None:
        """Look up a variable's type by name.

        Args:
            name: The variable name to look up.

        Returns:
            The type name if found, None otherwise.
        """
        return self._variables.get(name)

    def copy(self) -> GoLocalScope:
        """Create a copy for nested scopes (blocks, closures).

        Returns:
            A new GoLocalScope with the same variable mappings.
        """
        new_scope = GoLocalScope()
        new_scope._variables = self._variables.copy()
        return new_scope

