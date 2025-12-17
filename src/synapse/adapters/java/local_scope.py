"""Java local scope tracking.

Separated from the resolver to keep `resolver.py` focused on reference resolution.
"""

from __future__ import annotations


class LocalScope:
    """Tracks variable types within a method body.

    Used during type inference to resolve variable references to their
    declared types. Supports parameters, local variables, and nested scopes.
    """

    def __init__(self) -> None:
        """Initialize an empty local scope."""
        self._variables: dict[str, str] = {}

    def add_parameter(self, name: str, type_name: str) -> None:
        """Add a method parameter to scope.

        Args:
            name: The parameter name.
            type_name: The declared type of the parameter.
        """
        self._variables[name] = type_name

    def add_variable(self, name: str, type_name: str) -> None:
        """Add a local variable declaration to scope.

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

    def copy(self) -> LocalScope:
        """Create a copy for nested scopes (blocks, lambdas).

        Returns:
            A new LocalScope with the same variable mappings.
        """
        new_scope = LocalScope()
        new_scope._variables = self._variables.copy()
        return new_scope

