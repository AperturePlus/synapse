"""Go resolver for Phase 2 reference resolution.

This module resolves references in Go source files using the symbol table
built in Phase 1.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable as CallableFunc

from tree_sitter import Node, Parser

from synapse.adapters.base import FileContext, SymbolTable
from synapse.adapters.go.ast_utils import GoAstUtils
from synapse.adapters.go.type_inferrer import GoTypeInferrer
from synapse.core.models import (
    IR,
    Callable,
    CallableKind,
    LanguageType,
    Module,
    Type,
    TypeKind,
    UnresolvedReference,
    Visibility,
)

logger = logging.getLogger(__name__)


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


class GoResolver:
    """Phase 2: Resolve references using symbol table."""

    def __init__(
        self,
        parser: Parser,
        project_id: str,
        language_type: LanguageType,
        id_generator: CallableFunc[[str, str | None], str],
    ) -> None:
        """Initialize the resolver.

        Args:
            parser: Configured tree-sitter parser for Go
            project_id: The project identifier
            language_type: The language type (GO)
            id_generator: Function to generate entity IDs
        """
        self._parser = parser
        self._project_id = project_id
        self._language_type = language_type
        self._generate_id = id_generator
        self._ast = GoAstUtils()
        self._module_name: str = ""

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

    def resolve_directory(
        self, source_path: Path, symbol_table: SymbolTable, module_name: str = ""
    ) -> IR:
        """Resolve references in all Go files and return IR.

        Args:
            source_path: Root directory of Go source code
            symbol_table: Symbol table from Phase 1
            module_name: Module name from go.mod

        Returns:
            IR with resolved references

        Note:
            Files are processed in sorted order to ensure deterministic results
            regardless of filesystem traversal order (Requirement 5.3).
        """
        self._module_name = module_name
        ir = IR(language_type=self._language_type)

        # Sort files for deterministic processing order (Requirement 5.3)
        go_files = sorted(source_path.rglob("*.go"))
        for go_file in go_files:
            if go_file.name.endswith("_test.go"):
                continue
            if "vendor" in go_file.parts:
                continue

            try:
                self._process_file(go_file, source_path, symbol_table, ir)
            except Exception as e:
                logger.warning(f"Failed to process {go_file}: {e}")

        return ir

    def _process_file(
        self,
        file_path: Path,
        source_root: Path,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        """Process a single Go file and populate IR.

        Args:
            file_path: Path to the Go file
            source_root: Root directory for relative path calculation
            symbol_table: Symbol table from Phase 1
            ir: IR to populate
        """
        content = file_path.read_bytes()
        tree = self._parser.parse(content)
        root = tree.root_node

        # Extract package name and build qualified name
        package_name = GoAstUtils.extract_package(root, content)
        if not package_name:
            return

        rel_path = file_path.relative_to(source_root).parent
        rel_path_str = str(rel_path).replace("\\", "/")
        if self._module_name:
            if rel_path_str == "." or rel_path_str == "":
                qualified_pkg = self._module_name
            else:
                qualified_pkg = f"{self._module_name}/{rel_path_str}"
        else:
            qualified_pkg = rel_path_str or package_name

        # Extract imports for file context
        imports = GoAstUtils.extract_imports(root, content)
        file_context = FileContext(package=qualified_pkg, imports=imports)

        # Create or get module
        module_id = self._generate_id(qualified_pkg, None)
        if module_id not in ir.modules:
            ir.modules[module_id] = Module(
                id=module_id,
                name=package_name,
                qualified_name=qualified_pkg,
                path=rel_path_str or ".",
                language_type=self._language_type,
            )

        # Process declarations
        self._process_declarations(
            root, content, qualified_pkg, file_context, symbol_table, ir
        )

    def _process_declarations(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        file_context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        """Process type and function declarations.

        Args:
            node: Current AST node
            content: Source file content
            qualified_pkg: Qualified package name
            file_context: File context for symbol resolution
            symbol_table: Symbol table from Phase 1
            ir: IR to populate
        """
        for child in node.children:
            if child.type == "type_declaration":
                self._process_type_declaration(
                    child, content, qualified_pkg, file_context, symbol_table, ir
                )
            elif child.type == "function_declaration":
                self._process_function_declaration(
                    child, content, qualified_pkg, file_context, symbol_table, ir
                )
            elif child.type == "method_declaration":
                self._process_method_declaration(
                    child, content, qualified_pkg, file_context, symbol_table, ir
                )

    def _process_type_declaration(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        file_context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        """Process a type declaration and create Type nodes."""
        for child in node.children:
            if child.type == "type_spec":
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")

                if not name_node:
                    continue

                type_name = GoAstUtils.get_node_text(name_node, content)
                qualified_name = f"{qualified_pkg}.{type_name}"

                # Determine type kind
                kind = TypeKind.STRUCT
                if type_node:
                    if type_node.type == "interface_type":
                        kind = TypeKind.INTERFACE
                    elif type_node.type == "struct_type":
                        kind = TypeKind.STRUCT

                # Determine visibility (exported if starts with uppercase)
                visibility = (
                    Visibility.PUBLIC if type_name[0].isupper() else Visibility.PACKAGE
                )

                type_id = self._generate_id(qualified_name, None)
                type_obj = Type(
                    id=type_id,
                    name=type_name,
                    qualified_name=qualified_name,
                    kind=kind,
                    language_type=self._language_type,
                    modifiers=["exported"] if visibility == Visibility.PUBLIC else [],
                )

                # Process struct embeds
                if type_node and type_node.type == "struct_type":
                    self._process_struct_embeds(
                        type_node, content, file_context, symbol_table, type_obj
                    )

                ir.types[type_id] = type_obj

                # Add to module's declared_types
                module_id = self._generate_id(qualified_pkg, None)
                if module_id in ir.modules:
                    ir.modules[module_id].declared_types.append(type_id)

    def _process_struct_embeds(
        self,
        struct_node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        type_obj: Type,
    ) -> None:
        """Process struct field declarations to find embedded types."""
        for child in struct_node.children:
            if child.type == "field_declaration_list":
                for field in child.children:
                    if field.type == "field_declaration":
                        # Check if this is an embedded field (no name, just type)
                        name_nodes = [
                            c for c in field.children if c.type == "field_identifier"
                        ]
                        type_node = field.child_by_field_name("type")

                        if not name_nodes and type_node:
                            # This is an embedded type
                            embedded_type_name = GoAstUtils.get_base_type_name(
                                type_node, content
                            )
                            resolved = symbol_table.resolve_type(
                                embedded_type_name, file_context
                            )
                            if resolved:
                                type_obj.embeds.append(
                                    self._generate_id(resolved, None)
                                )

    def _process_function_declaration(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        file_context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        """Process a function declaration."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        func_name = GoAstUtils.get_node_text(name_node, content)
        qualified_name = f"{qualified_pkg}.{func_name}"
        signature = GoAstUtils.build_signature(node, content)

        visibility = (
            Visibility.PUBLIC if func_name[0].isupper() else Visibility.PACKAGE
        )

        callable_id = self._generate_id(qualified_name, signature)
        callable_obj = Callable(
            id=callable_id,
            name=func_name,
            qualified_name=qualified_name,
            kind=CallableKind.FUNCTION,
            language_type=self._language_type,
            signature=signature,
            is_static=True,  # Go functions are essentially static
            visibility=visibility,
        )

        # Get return type
        result_node = node.child_by_field_name("result")
        if result_node:
            return_type_name = GoAstUtils.get_base_type_name(result_node, content)
            resolved = symbol_table.resolve_type(return_type_name, file_context)
            if resolved:
                callable_obj.return_type = self._generate_id(resolved, None)

        # Build local scope and find function calls in body
        body_node = node.child_by_field_name("body")
        if body_node:
            local_scope = self._build_local_scope(node, content, file_context, symbol_table)
            self._find_function_calls(
                body_node, content, file_context, symbol_table, callable_obj, ir, local_scope
            )

        ir.callables[callable_id] = callable_obj

    def _process_method_declaration(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        file_context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        """Process a method declaration (with receiver)."""
        name_node = node.child_by_field_name("name")
        receiver_node = node.child_by_field_name("receiver")

        if not name_node or not receiver_node:
            return

        method_name = GoAstUtils.get_node_text(name_node, content)
        receiver_type = GoAstUtils.extract_receiver_type(receiver_node, content)

        if not receiver_type:
            return

        qualified_name = f"{qualified_pkg}.{receiver_type}.{method_name}"
        signature = GoAstUtils.build_signature(node, content)

        visibility = (
            Visibility.PUBLIC if method_name[0].isupper() else Visibility.PACKAGE
        )

        callable_id = self._generate_id(qualified_name, signature)
        callable_obj = Callable(
            id=callable_id,
            name=method_name,
            qualified_name=qualified_name,
            kind=CallableKind.METHOD,
            language_type=self._language_type,
            signature=signature,
            is_static=False,
            visibility=visibility,
        )

        # Get return type
        result_node = node.child_by_field_name("result")
        if result_node:
            return_type_name = GoAstUtils.get_base_type_name(result_node, content)
            resolved = symbol_table.resolve_type(return_type_name, file_context)
            if resolved:
                callable_obj.return_type = self._generate_id(resolved, None)

        # Build local scope and find function calls in body
        body_node = node.child_by_field_name("body")
        if body_node:
            local_scope = self._build_local_scope(node, content, file_context, symbol_table)
            self._find_function_calls(
                body_node, content, file_context, symbol_table, callable_obj, ir, local_scope
            )

        ir.callables[callable_id] = callable_obj

        # Add to owner type's callables
        owner_qualified = f"{qualified_pkg}.{receiver_type}"
        owner_id = self._generate_id(owner_qualified, None)
        if owner_id in ir.types:
            ir.types[owner_id].callables.append(callable_id)

    def _find_function_calls(
        self,
        node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        caller: Callable,
        ir: IR,
        local_scope: GoLocalScope,
    ) -> None:
        """Find function/method calls in a code block with type-aware resolution.

        Args:
            node: Current AST node to process
            content: Source file content
            file_context: File context for symbol resolution
            symbol_table: Symbol table from Phase 1
            caller: The calling function/method
            ir: IR to populate
            local_scope: Local scope with variable type mappings
        """
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                if func_node.type == "identifier":
                    # Simple function call
                    self._resolve_simple_call(
                        func_node, content, symbol_table, caller, ir
                    )
                elif func_node.type == "selector_expression":
                    # Method call or package.function call
                    self._resolve_selector_call(
                        func_node, content, file_context, symbol_table, caller, ir, local_scope
                    )

        # Recurse into children
        for child in node.children:
            self._find_function_calls(
                child, content, file_context, symbol_table, caller, ir, local_scope
            )

    def _resolve_simple_call(
        self,
        func_node: Node,
        content: bytes,
        symbol_table: SymbolTable,
        caller: Callable,
        ir: IR,
    ) -> None:
        """Resolve a simple function call (identifier).

        Args:
            func_node: The function identifier node
            content: Source file content
            symbol_table: Symbol table from Phase 1
            caller: The calling function/method
            ir: IR to populate
        """
        func_name = GoAstUtils.get_node_text(func_node, content)
        resolved = symbol_table.resolve_callable(func_name)
        if resolved:
            signature = symbol_table.get_callable_signature(resolved) or "()"
            callee_id = self._generate_id(resolved, signature)
            if callee_id not in caller.calls:
                caller.calls.append(callee_id)
        else:
            ir.unresolved.append(UnresolvedReference(
                source_callable=caller.id,
                target_name=func_name,
                reason="Function not found in symbol table",
            ))

    def _resolve_selector_call(
        self,
        func_node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        caller: Callable,
        ir: IR,
        local_scope: GoLocalScope,
    ) -> None:
        """Resolve a selector expression call (method or pkg.func).

        Uses receiver type inference to disambiguate method calls.
        Handles chained calls by using the return type of inner calls.

        Args:
            func_node: The selector_expression node
            content: Source file content
            file_context: File context for symbol resolution
            symbol_table: Symbol table from Phase 1
            caller: The calling function/method
            ir: IR to populate
            local_scope: Local scope with variable type mappings
        """
        field_node = func_node.child_by_field_name("field")
        operand_node = func_node.child_by_field_name("operand")

        if field_node is None:
            return

        method_name = GoAstUtils.get_node_text(field_node, content)

        # Try to infer receiver type for type-aware resolution
        receiver_type: str | None = None
        inferrer = GoTypeInferrer(symbol_table, file_context, local_scope)
        is_chained = inferrer.is_chained_call(func_node)

        if operand_node:
            receiver_type = inferrer.infer_receiver_type(func_node, content)

        # Use type-aware resolution if we have a receiver type
        if receiver_type:
            resolved, error_reason = symbol_table.resolve_callable_with_receiver(
                method_name, receiver_type
            )
            if resolved:
                signature = symbol_table.get_callable_signature(resolved) or "()"
                callee_id = self._generate_id(resolved, signature)
                if callee_id not in caller.calls:
                    caller.calls.append(callee_id)
            elif error_reason:
                # Record as unresolved with specific reason
                ir.unresolved.append(UnresolvedReference(
                    source_callable=caller.id,
                    target_name=method_name,
                    context=f"receiver_type={receiver_type}",
                    reason=error_reason,
                ))
        elif is_chained:
            # Chained call but inner call's return type is unknown
            # Mark as unresolved with specific reason per Requirement 4.2
            ir.unresolved.append(UnresolvedReference(
                source_callable=caller.id,
                target_name=method_name,
                reason="Unknown receiver type from method call",
            ))
        else:
            # Fallback: try heuristic resolution without receiver type
            resolved = symbol_table.resolve_callable(method_name)
            if resolved:
                signature = symbol_table.get_callable_signature(resolved) or "()"
                callee_id = self._generate_id(resolved, signature)
                if callee_id not in caller.calls:
                    caller.calls.append(callee_id)
            # Don't mark as unresolved if receiver type unknown - could be external package
            # But if operand is a local variable, we should mark it
            elif operand_node and operand_node.type == "identifier":
                var_name = GoAstUtils.get_node_text(operand_node, content)
                if local_scope.get_type(var_name) is None:
                    # Variable not in scope - likely external package
                    pass
                else:
                    # Variable in scope but type couldn't be resolved
                    ir.unresolved.append(UnresolvedReference(
                        source_callable=caller.id,
                        target_name=method_name,
                        context=f"variable={var_name}",
                        reason="Unknown receiver type",
                    ))
