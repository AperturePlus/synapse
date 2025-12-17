"""Go resolver mixin for local scoping and variable type tracking."""

from __future__ import annotations

from tree_sitter import Node

from synapse.adapters.base import FileContext, SymbolTable
from synapse.adapters.go.ast_utils import GoAstUtils
from synapse.adapters.go.local_scope import GoLocalScope
from synapse.adapters.go.type_inferrer import GoTypeInferrer


class _GoScopingMixin:
    """Provides Go local scope construction and variable collection helpers."""

    def _build_local_scope(
        self,
        node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
    ) -> GoLocalScope:
        """Build local scope from function/method parameters and body.

        Args:
            node: The function/method declaration node
            content: Source file content
            file_context: File context for type resolution
            symbol_table: Symbol table for type lookups

        Returns:
            GoLocalScope with variable-to-type mappings
        """
        scope = GoLocalScope()

        # Add parameters to scope
        params_node = node.child_by_field_name("parameters")
        if params_node:
            self._add_parameters_to_scope(params_node, content, file_context, symbol_table, scope)

        # Add receiver to scope (for methods)
        receiver_node = node.child_by_field_name("receiver")
        if receiver_node:
            self._add_receiver_to_scope(receiver_node, content, file_context, symbol_table, scope)

        # Collect local variables from body
        body_node = node.child_by_field_name("body")
        if body_node:
            self._collect_local_variables(body_node, content, file_context, symbol_table, scope)

        return scope

    def _add_parameters_to_scope(
        self,
        params_node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        scope: GoLocalScope,
    ) -> None:
        """Add function parameters to local scope.

        Args:
            params_node: The parameter_list node
            content: Source file content
            file_context: File context for type resolution
            symbol_table: Symbol table for type lookups
            scope: Local scope to populate
        """
        for child in params_node.children:
            if child.type == "parameter_declaration":
                type_node = child.child_by_field_name("type")
                if type_node is None:
                    continue

                type_name = GoAstUtils.get_base_type_name(type_node, content)
                resolved_type = symbol_table.resolve_type(type_name, file_context)
                final_type = resolved_type or type_name

                # Get parameter names (can be multiple: a, b int)
                for name_child in child.children:
                    if name_child.type == "identifier":
                        param_name = GoAstUtils.get_node_text(name_child, content)
                        scope.add_variable(param_name, final_type)

    def _add_receiver_to_scope(
        self,
        receiver_node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        scope: GoLocalScope,
    ) -> None:
        """Add method receiver to local scope.

        Args:
            receiver_node: The receiver parameter list node
            content: Source file content
            file_context: File context for type resolution
            symbol_table: Symbol table for type lookups
            scope: Local scope to populate
        """
        for child in receiver_node.children:
            if child.type == "parameter_declaration":
                type_node = child.child_by_field_name("type")
                if type_node is None:
                    continue

                type_name = GoAstUtils.get_base_type_name(type_node, content)
                resolved_type = symbol_table.resolve_type(type_name, file_context)
                final_type = resolved_type or type_name

                # Get receiver name
                for name_child in child.children:
                    if name_child.type == "identifier":
                        receiver_name = GoAstUtils.get_node_text(name_child, content)
                        scope.add_variable(receiver_name, final_type)

    def _collect_local_variables(
        self,
        node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        scope: GoLocalScope,
    ) -> None:
        """Collect local variable declarations from a code block.

        Handles:
        - var declarations: var x Type
        - short declarations: x := expr
        - range variables: for k, v := range expr

        Args:
            node: The block node to scan
            content: Source file content
            file_context: File context for type resolution
            symbol_table: Symbol table for type lookups
            scope: Local scope to populate
        """
        for child in node.children:
            if child.type == "var_declaration":
                self._process_var_declaration(child, content, file_context, symbol_table, scope)
            elif child.type == "short_var_declaration":
                self._process_short_var_declaration(
                    child, content, file_context, symbol_table, scope
                )
            elif child.type == "for_statement":
                self._process_for_statement(child, content, file_context, symbol_table, scope)
            elif child.type == "range_clause":
                self._process_range_clause(child, content, file_context, symbol_table, scope)

            # Recurse into nested blocks
            if child.type in ("block", "if_statement", "for_statement", "switch_statement"):
                self._collect_local_variables(child, content, file_context, symbol_table, scope)

    def _process_var_declaration(
        self,
        node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        scope: GoLocalScope,
    ) -> None:
        """Process a var declaration (var x Type or var x = expr).

        Args:
            node: The var_declaration node
            content: Source file content
            file_context: File context for type resolution
            symbol_table: Symbol table for type lookups
            scope: Local scope to populate
        """
        for child in node.children:
            if child.type == "var_spec":
                type_node = child.child_by_field_name("type")
                value_node = child.child_by_field_name("value")

                var_type: str | None = None

                # Explicit type declaration: var x Type
                if type_node:
                    type_name = GoAstUtils.get_base_type_name(type_node, content)
                    resolved = symbol_table.resolve_type(type_name, file_context)
                    var_type = resolved or type_name
                # Type inference from value: var x = expr
                elif value_node:
                    var_type = self._infer_expression_type(
                        value_node, content, file_context, symbol_table, scope
                    )

                if var_type:
                    # Get variable names
                    for name_child in child.children:
                        if name_child.type == "identifier":
                            var_name = GoAstUtils.get_node_text(name_child, content)
                            scope.add_variable(var_name, var_type)

    def _process_short_var_declaration(
        self,
        node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        scope: GoLocalScope,
    ) -> None:
        """Process a short variable declaration (x := expr).

        Args:
            node: The short_var_declaration node
            content: Source file content
            file_context: File context for type resolution
            symbol_table: Symbol table for type lookups
            scope: Local scope to populate
        """
        left_node = node.child_by_field_name("left")
        right_node = node.child_by_field_name("right")

        if left_node is None or right_node is None:
            return

        # Infer type from right-hand side
        var_type = self._infer_expression_type(
            right_node, content, file_context, symbol_table, scope
        )

        if var_type:
            # Get variable names from left side (expression_list)
            for child in left_node.children:
                if child.type == "identifier":
                    var_name = GoAstUtils.get_node_text(child, content)
                    scope.add_variable(var_name, var_type)

    def _process_for_statement(
        self,
        node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        scope: GoLocalScope,
    ) -> None:
        """Process a for statement to extract range variables.

        Args:
            node: The for_statement node
            content: Source file content
            file_context: File context for type resolution
            symbol_table: Symbol table for type lookups
            scope: Local scope to populate
        """
        for child in node.children:
            if child.type == "range_clause":
                self._process_range_clause(child, content, file_context, symbol_table, scope)

    def _process_range_clause(
        self,
        node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        scope: GoLocalScope,
    ) -> None:
        """Process a range clause (for k, v := range expr).

        Args:
            node: The range_clause node
            content: Source file content
            file_context: File context for type resolution
            symbol_table: Symbol table for type lookups
            scope: Local scope to populate
        """
        left_node = node.child_by_field_name("left")
        right_node = node.child_by_field_name("right")

        if left_node is None or right_node is None:
            return

        # Infer container type from right side
        container_type = self._infer_expression_type(
            right_node, content, file_context, symbol_table, scope
        )

        if container_type:
            # Determine element type from container type
            element_type = self._get_element_type(container_type)

            # Get variable names from left side
            var_names: list[str] = []
            for child in left_node.children:
                if child.type == "identifier":
                    var_names.append(GoAstUtils.get_node_text(child, content))

            # First variable is index/key (int for slices/arrays, key type for maps)
            # Second variable is value (element type)
            if len(var_names) >= 1:
                # Index is typically int for slices/arrays
                scope.add_variable(var_names[0], "int")
            if len(var_names) >= 2 and element_type:
                scope.add_variable(var_names[1], element_type)

    def _get_element_type(self, container_type: str) -> str | None:
        """Get the element type from a container type.

        Args:
            container_type: The container type (e.g., []User, map[string]User)

        Returns:
            The element type or None if not determinable
        """
        # Slice type: []Type
        if container_type.startswith("[]"):
            return container_type[2:]

        # Map type: map[K]V - return V
        if container_type.startswith("map["):
            # Find the closing bracket and extract value type
            bracket_count = 0
            for i, char in enumerate(container_type):
                if char == "[":
                    bracket_count += 1
                elif char == "]":
                    bracket_count -= 1
                    if bracket_count == 0:
                        return container_type[i + 1:]

        return None

    def _infer_expression_type(
        self,
        node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        scope: GoLocalScope,
    ) -> str | None:
        """Infer the type of an expression using GoTypeInferrer.

        Args:
            node: The expression node
            content: Source file content
            file_context: File context for type resolution
            symbol_table: Symbol table for type lookups
            scope: Local scope for variable lookups

        Returns:
            The inferred type or None if not determinable
        """
        inferrer = GoTypeInferrer(symbol_table, file_context, scope)
        return inferrer.infer_type(node, content)

