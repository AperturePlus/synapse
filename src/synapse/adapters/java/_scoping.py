"""Java resolver mixin for local scoping and variable type tracking."""

from __future__ import annotations

from tree_sitter import Node

from synapse.adapters.base import FileContext, SymbolTable
from synapse.adapters.java.ast_utils import JavaAstUtils
from synapse.adapters.java.local_scope import LocalScope


class _JavaScopingMixin:
    """Provides Java local scope construction and variable collection helpers."""

    def _build_local_scope(
        self, callable_node: Node, content: bytes
    ) -> LocalScope:
        """Build local scope from method parameters.

        Extracts parameter names and types from a method or constructor
        declaration to initialize the local scope for type inference.

        Args:
            callable_node: The method or constructor declaration node.
            content: Source file content as bytes.

        Returns:
            A LocalScope populated with parameter types.
        """
        scope = LocalScope()

        params_node = callable_node.child_by_field_name("parameters")
        if params_node is None:
            return scope

        for child in params_node.children:
            if child.type == "formal_parameter":
                # Get parameter name
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")

                if name_node and type_node:
                    param_name = JavaAstUtils.get_node_text(name_node, content)
                    param_type = JavaAstUtils.get_type_name(type_node, content)
                    scope.add_parameter(param_name, param_type)

            elif child.type == "spread_parameter":
                # Varargs parameter
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")

                if name_node and type_node:
                    param_name = JavaAstUtils.get_node_text(name_node, content)
                    # Varargs are arrays at runtime
                    param_type = JavaAstUtils.get_type_name(type_node, content) + "[]"
                    scope.add_parameter(param_name, param_type)

        return scope

    def _collect_local_variables(
        self,
        body_node: Node,
        content: bytes,
        scope: LocalScope,
        file_context: FileContext,
        symbol_table: SymbolTable,
    ) -> None:
        """Collect local variable declarations into scope.

        Traverses the method body to find local variable declarations
        and adds them to the scope. Handles the `var` keyword by
        inferring the type from the initializer expression.

        Args:
            body_node: The method body node to traverse.
            content: Source file content as bytes.
            scope: The LocalScope to populate.
            file_context: File context for type resolution.
            symbol_table: Symbol table for type lookups.
        """
        if body_node is None:
            return

        for child in body_node.children:
            if child.type == "local_variable_declaration":
                self._process_local_variable_declaration(
                    child, content, scope, file_context, symbol_table
                )
            elif child.type in (
                "block",
                "if_statement",
                "for_statement",
                "enhanced_for_statement",
                "while_statement",
                "do_statement",
                "try_statement",
                "switch_expression",
            ):
                # Recurse into nested blocks
                self._collect_local_variables(
                    child, content, scope, file_context, symbol_table
                )

            # Handle for loop initializers
            if child.type == "for_statement":
                init_node = child.child_by_field_name("init")
                if init_node and init_node.type == "local_variable_declaration":
                    self._process_local_variable_declaration(
                        init_node, content, scope, file_context, symbol_table
                    )

            # Handle enhanced for loop variable
            if child.type == "enhanced_for_statement":
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")
                if name_node and type_node:
                    var_name = JavaAstUtils.get_node_text(name_node, content)
                    var_type = JavaAstUtils.get_type_name(type_node, content)
                    scope.add_variable(var_name, var_type)

            # Handle try-with-resources
            if child.type == "try_statement":
                resources_node = child.child_by_field_name("resources")
                if resources_node:
                    for resource in resources_node.children:
                        if resource.type == "resource":
                            name_node = resource.child_by_field_name("name")
                            type_node = resource.child_by_field_name("type")
                            if name_node and type_node:
                                var_name = JavaAstUtils.get_node_text(name_node, content)
                                var_type = JavaAstUtils.get_type_name(type_node, content)
                                scope.add_variable(var_name, var_type)

            # Handle catch clauses
            if child.type == "catch_clause":
                catch_param = child.child_by_field_name("parameter")
                if catch_param:
                    name_node = catch_param.child_by_field_name("name")
                    type_node = catch_param.child_by_field_name("type")
                    if name_node and type_node:
                        var_name = JavaAstUtils.get_node_text(name_node, content)
                        var_type = JavaAstUtils.get_type_name(type_node, content)
                        scope.add_variable(var_name, var_type)

    def _process_local_variable_declaration(
        self,
        decl_node: Node,
        content: bytes,
        scope: LocalScope,
        file_context: FileContext,
        symbol_table: SymbolTable,
    ) -> None:
        """Process a local variable declaration and add to scope.

        Handles both explicit type declarations and `var` keyword (Java 10+)
        by inferring the type from the initializer.

        Args:
            decl_node: The local_variable_declaration node.
            content: Source file content as bytes.
            scope: The LocalScope to populate.
            file_context: File context for type resolution.
            symbol_table: Symbol table for type lookups.
        """
        type_node = decl_node.child_by_field_name("type")

        # Find variable declarators
        for child in decl_node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")

                if name_node is None:
                    continue

                var_name = JavaAstUtils.get_node_text(name_node, content)

                # Check if type is 'var' (Java 10+ local variable type inference)
                if type_node:
                    type_text = JavaAstUtils.get_node_text(type_node, content)

                    if type_text == "var":
                        # Infer type from initializer
                        if value_node:
                            inferred_type = self._infer_var_type(
                                value_node, content, scope, file_context, symbol_table
                            )
                            if inferred_type:
                                scope.add_variable(var_name, inferred_type)
                    else:
                        # Explicit type declaration
                        var_type = JavaAstUtils.get_type_name(type_node, content)
                        scope.add_variable(var_name, var_type)

    def _infer_var_type(
        self,
        value_node: Node,
        content: bytes,
        scope: LocalScope,
        file_context: FileContext,
        symbol_table: SymbolTable,
    ) -> str | None:
        """Infer type for a `var` declaration from its initializer.

        Args:
            value_node: The initializer expression node.
            content: Source file content as bytes.
            scope: Current local scope for variable lookups.
            file_context: File context for type resolution.
            symbol_table: Symbol table for type lookups.

        Returns:
            The inferred type name, or None if inference fails.
        """
        # Import here to avoid circular dependency
        from synapse.adapters.java.type_inferrer import TypeInferrer

        inferrer = TypeInferrer(symbol_table, file_context, scope)
        return inferrer.infer_type(value_node, content)

