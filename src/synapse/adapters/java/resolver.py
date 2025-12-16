"""Java resolver for Phase 2 reference resolution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable as CallableFunc

from tree_sitter import Node, Parser

from synapse.adapters.base import FileContext, SymbolTable
from synapse.adapters.java.ast_utils import JavaAstUtils
from synapse.core.models import (
    IR,
    Callable,
    CallableKind,
    LanguageType,
    Module,
    Type,
    UnresolvedReference,
)

if TYPE_CHECKING:
    from synapse.adapters.java.type_inferrer import TypeInferrer

logger = logging.getLogger(__name__)


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


class JavaResolver:
    """Phase 2: Resolve references using symbol table."""

    def __init__(
        self,
        parser: Parser,
        project_id: str,
        language_type: LanguageType,
        id_generator: CallableFunc[[str, str | None], str],
    ) -> None:
        """Initialize the resolver."""
        self._parser = parser
        self._project_id = project_id
        self._language_type = language_type
        self._generate_id = id_generator
        self._ast = JavaAstUtils()

    def resolve_directory(self, source_path: Path, symbol_table: SymbolTable) -> IR:
        """Resolve references in all Java files and return IR."""
        ir = IR(language_type=self._language_type)

        for java_file in source_path.rglob("*.java"):
            try:
                self._process_file(java_file, source_path, symbol_table, ir)
            except Exception as e:
                logger.warning(f"Failed to process {java_file}: {e}")

        return ir

    def _process_file(
        self, file_path: Path, source_root: Path, symbol_table: SymbolTable, ir: IR
    ) -> None:
        """Process a single Java file and populate IR."""
        content = file_path.read_bytes()
        tree = self._parser.parse(content)
        root = tree.root_node

        # Extract package and imports for file context
        package_name = JavaAstUtils.extract_package(root, content)
        imports = JavaAstUtils.extract_imports(root, content)
        file_context = FileContext(package=package_name, imports=imports)

        # Create or get module
        if package_name:
            module_id = self._generate_id(package_name, None)
            if module_id not in ir.modules:
                rel_path = file_path.relative_to(source_root).parent
                ir.modules[module_id] = Module(
                    id=module_id,
                    name=package_name.split(".")[-1],
                    qualified_name=package_name,
                    path=str(rel_path),
                    language_type=self._language_type,
                )

        # Process type declarations
        self._process_type_declarations(
            root, content, package_name, file_context, symbol_table, ir
        )

    def _process_type_declarations(
        self, node: Node, content: bytes, package_name: str, file_context: FileContext,
        symbol_table: SymbolTable, ir: IR, parent_type_id: str | None = None,
    ) -> None:
        """Process type declarations and populate IR."""
        type_declarations = (
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
        )

        for child in node.children:
            if child.type in type_declarations:
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue

                type_name = JavaAstUtils.get_node_text(name_node, content)

                # Build qualified name
                parent_qualified = None
                if parent_type_id and parent_type_id in ir.types:
                    parent_qualified = ir.types[parent_type_id].qualified_name

                if parent_qualified:
                    qualified_name = f"{parent_qualified}.{type_name}"
                elif package_name:
                    qualified_name = f"{package_name}.{type_name}"
                else:
                    qualified_name = type_name

                # Determine type kind
                kind = JavaAstUtils.get_type_kind(child.type)

                # Extract modifiers
                modifiers = JavaAstUtils.extract_modifiers(child, content)

                # Create type
                type_id = self._generate_id(qualified_name, None)
                type_obj = Type(
                    id=type_id,
                    name=type_name,
                    qualified_name=qualified_name,
                    kind=kind,
                    language_type=self._language_type,
                    modifiers=modifiers,
                )

                # Resolve extends/implements
                self._resolve_type_relations(
                    child, content, file_context, symbol_table, type_obj
                )

                ir.types[type_id] = type_obj

                # Add to module's declared_types
                if package_name:
                    module_id = self._generate_id(package_name, None)
                    if module_id in ir.modules:
                        ir.modules[module_id].declared_types.append(type_id)

                # Process methods in this type
                body_node = child.child_by_field_name("body")
                if body_node:
                    self._process_callable_declarations(
                        body_node, content, type_obj, file_context, symbol_table, ir
                    )
                    # Recursively process nested types
                    self._process_type_declarations(
                        body_node, content, package_name, file_context,
                        symbol_table, ir, type_id
                    )

            elif child.type in ("class_body", "interface_body", "enum_body"):
                self._process_type_declarations(
                    child, content, package_name, file_context,
                    symbol_table, ir, parent_type_id
                )

    def _resolve_type_relations(
        self, type_node: Node, content: bytes, file_context: FileContext,
        symbol_table: SymbolTable, type_obj: Type,
    ) -> None:
        """Resolve extends and implements relations for a type."""
        for child in type_node.children:
            if child.type == "superclass":
                # extends clause
                for type_ref in child.children:
                    if type_ref.type in ("type_identifier", "generic_type"):
                        type_name = JavaAstUtils.get_type_name(type_ref, content)
                        resolved = symbol_table.resolve_type(type_name, file_context)
                        if resolved:
                            type_obj.extends.append(self._generate_id(resolved, None))

            elif child.type == "super_interfaces":
                # implements clause
                for type_ref in child.children:
                    if type_ref.type in ("type_identifier", "generic_type", "type_list"):
                        if type_ref.type == "type_list":
                            for t in type_ref.children:
                                if t.type in ("type_identifier", "generic_type"):
                                    type_name = JavaAstUtils.get_type_name(t, content)
                                    resolved = symbol_table.resolve_type(
                                        type_name, file_context
                                    )
                                    if resolved:
                                        type_obj.implements.append(
                                            self._generate_id(resolved, None)
                                        )
                        else:
                            type_name = JavaAstUtils.get_type_name(type_ref, content)
                            resolved = symbol_table.resolve_type(type_name, file_context)
                            if resolved:
                                type_obj.implements.append(
                                    self._generate_id(resolved, None)
                                )

    def _process_callable_declarations(
        self, body_node: Node, content: bytes, owner_type: Type,
        file_context: FileContext, symbol_table: SymbolTable, ir: IR,
    ) -> None:
        """Process method and constructor declarations."""
        callable_declarations = ("method_declaration", "constructor_declaration")

        for child in body_node.children:
            if child.type in callable_declarations:
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    if child.type == "constructor_declaration":
                        name = owner_type.name
                    else:
                        continue
                else:
                    name = JavaAstUtils.get_node_text(name_node, content)

                signature = JavaAstUtils.build_signature(child, content)
                qualified_name = f"{owner_type.qualified_name}.{name}"

                # Determine callable kind
                if child.type == "constructor_declaration":
                    kind = CallableKind.CONSTRUCTOR
                else:
                    kind = CallableKind.METHOD

                # Extract visibility and static
                modifiers = JavaAstUtils.extract_modifiers(child, content)
                visibility = JavaAstUtils.get_visibility(modifiers)
                is_static = "static" in modifiers

                # Get return type
                return_type_id = None
                if child.type == "method_declaration":
                    return_type_node = child.child_by_field_name("type")
                    if return_type_node and return_type_node.type != "void_type":
                        type_name = JavaAstUtils.get_type_name(return_type_node, content)
                        resolved = symbol_table.resolve_type(type_name, file_context)
                        if resolved:
                            return_type_id = self._generate_id(resolved, None)

                callable_id = self._generate_id(qualified_name, signature)
                callable_obj = Callable(
                    id=callable_id,
                    name=name,
                    qualified_name=qualified_name,
                    kind=kind,
                    language_type=self._language_type,
                    signature=signature,
                    is_static=is_static,
                    visibility=visibility,
                    return_type=return_type_id,
                )

                # Build local scope for type inference
                local_scope = self._build_local_scope(child, content)

                # Find method calls in body
                method_body = child.child_by_field_name("body")
                if method_body:
                    # Collect local variables into scope
                    self._collect_local_variables(
                        method_body, content, local_scope, file_context, symbol_table
                    )
                    self._find_method_calls(
                        method_body, content, file_context, symbol_table,
                        callable_obj, ir, local_scope
                    )

                ir.callables[callable_id] = callable_obj
                owner_type.callables.append(callable_id)

    def _find_method_calls(
        self, node: Node, content: bytes, file_context: FileContext,
        symbol_table: SymbolTable, caller: Callable, ir: IR,
        local_scope: LocalScope | None = None,
    ) -> None:
        """Find method invocations in a code block with type inference.

        Handles chained calls by using the return type of inner calls.

        Args:
            node: The AST node to search for method calls.
            content: Source file content as bytes.
            file_context: File context for type resolution.
            symbol_table: Symbol table for callable lookups.
            caller: The callable containing this code block.
            ir: The IR being populated.
            local_scope: Local scope for variable type lookups.
        """
        if node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            if name_node:
                method_name = JavaAstUtils.get_node_text(name_node, content)

                # Check if this is a chained call (object is another method_invocation)
                object_node = node.child_by_field_name("object")
                is_chained = object_node is not None and object_node.type == "method_invocation"

                # Infer receiver type from the object field
                receiver_type = self._infer_receiver_type(
                    node, content, file_context, symbol_table, local_scope
                )

                # For chained calls, if receiver type is unknown, mark as unresolved
                # with specific reason per Requirement 4.2
                if is_chained and receiver_type is None:
                    ir.unresolved.append(UnresolvedReference(
                        source_callable=caller.id,
                        target_name=method_name,
                        reason="Unknown receiver type from method call",
                    ))
                else:
                    # Infer signature with type information
                    inferred_sig = self._infer_signature(
                        node, content, file_context, symbol_table, local_scope
                    )

                    # Use _match_callable for overload resolution with receiver type
                    resolved, error_reason = self._match_callable(
                        method_name, inferred_sig, symbol_table, receiver_type
                    )

                    if resolved:
                        # Use the inferred signature for ID generation since that's what was matched
                        # The inferred signature should match one of the declared signatures
                        callee_id = self._generate_id(resolved, inferred_sig)
                        if callee_id not in caller.calls:
                            caller.calls.append(callee_id)
                    else:
                        # Record as unresolved with the specific reason
                        ir.unresolved.append(UnresolvedReference(
                            source_callable=caller.id,
                            target_name=method_name,
                            reason=error_reason or "Method not found in symbol table",
                        ))

        # Recurse into children
        for child in node.children:
            self._find_method_calls(
                child, content, file_context, symbol_table, caller, ir, local_scope
            )

    def _infer_receiver_type(
        self,
        invocation_node: Node,
        content: bytes,
        file_context: FileContext | None = None,
        symbol_table: SymbolTable | None = None,
        local_scope: LocalScope | None = None,
    ) -> str | None:
        """Infer the receiver type from a method invocation.

        Determines the type of the object on which a method is being called.
        For example, in `user.getName()`, this infers the type of `user`.

        Args:
            invocation_node: The method_invocation AST node.
            content: Source file content as bytes.
            file_context: File context for type resolution (optional).
            symbol_table: Symbol table for type lookups (optional).
            local_scope: Local scope for variable lookups (optional).

        Returns:
            The qualified type name of the receiver, or None if:
            - No receiver (static method call or same-class method)
            - Receiver type cannot be determined
        """
        object_node = invocation_node.child_by_field_name("object")
        if object_node is None:
            # No explicit receiver - could be a static method or same-class method
            return None

        if file_context is None or symbol_table is None or local_scope is None:
            return None

        # Import here to avoid circular dependency
        from synapse.adapters.java.type_inferrer import TypeInferrer

        inferrer = TypeInferrer(symbol_table, file_context, local_scope)
        inferred_type = inferrer.infer_type(object_node, content)

        if inferred_type is None:
            return None

        # Resolve the inferred type to its qualified name
        resolved = symbol_table.resolve_type(inferred_type, file_context)
        return resolved

    def _infer_signature(
        self,
        invocation_node: Node,
        content: bytes,
        file_context: FileContext | None = None,
        symbol_table: SymbolTable | None = None,
        local_scope: LocalScope | None = None,
    ) -> str:
        """Infer signature from method invocation arguments.

        Uses TypeInferrer to determine the type of each argument expression,
        producing a signature that can be matched against declared method
        signatures for overload resolution.

        Args:
            invocation_node: The method_invocation AST node.
            content: Source file content as bytes.
            file_context: File context for type resolution (optional).
            symbol_table: Symbol table for type lookups (optional).
            local_scope: Local scope for variable lookups (optional).

        Returns:
            Signature string like "(String, int)" or "(?, ?)" for unresolved types.
        """
        args_node = invocation_node.child_by_field_name("arguments")
        if args_node is None:
            return "()"

        # Collect argument nodes (skip parentheses and commas)
        arg_nodes = [
            c for c in args_node.children
            if c.type not in ("(", ")", ",")
        ]

        if not arg_nodes:
            return "()"

        # If we don't have the context for type inference, fall back to placeholders
        if file_context is None or symbol_table is None or local_scope is None:
            return f"({', '.join(['?'] * len(arg_nodes))})"

        # Import here to avoid circular dependency
        from synapse.adapters.java.type_inferrer import TypeInferrer

        inferrer = TypeInferrer(symbol_table, file_context, local_scope)

        # Infer type for each argument
        arg_types: list[str] = []
        for arg_node in arg_nodes:
            inferred_type = inferrer.infer_type(arg_node, content)
            if inferred_type is not None:
                arg_types.append(inferred_type)
            else:
                arg_types.append("?")

        return f"({', '.join(arg_types)})"

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

    def _match_callable(
        self,
        method_name: str,
        inferred_sig: str,
        symbol_table: SymbolTable,
        receiver_type: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Match inferred signature against callable candidates.

        Attempts to find the best matching callable for a method invocation:
        1. If receiver_type is provided, use resolve_callable_with_receiver
           for type-aware resolution with supertype fallback
        2. Otherwise, fall back to signature-based matching
        3. Returns error reason for ambiguous matches

        Args:
            method_name: The simple name of the method being called.
            inferred_sig: The inferred signature from arguments (e.g., "(String, int)").
            symbol_table: Symbol table containing callable definitions.
            receiver_type: The qualified name of the receiver type (optional).

        Returns:
            A tuple of (qualified_name, error_reason):
            - (qualified_name, None) if a unique match is found
            - (None, error_reason) if no match or ambiguous
        """
        # If we have a receiver type, use type-aware resolution
        if receiver_type is not None:
            resolved, error = symbol_table.resolve_callable_with_receiver(
                method_name, receiver_type, inferred_sig
            )
            if resolved is not None:
                return resolved, None
            # If resolve_callable_with_receiver failed, return its error
            # unless it's "Method not found" - then try fallback
            if error and "not found" not in error.lower():
                return None, error

        # Fall back to signature-based matching (for static methods or when
        # receiver type is unknown)
        # Sort candidates for deterministic iteration order (Requirement 5.3)
        candidates = sorted(symbol_table.callable_map.get(method_name, []))
        if not candidates:
            return None, "Method not found in symbol table"

        # Parse the inferred signature to get argument types
        inferred_types = self._parse_signature(inferred_sig)
        inferred_arity = len(inferred_types)

        # Check if signature contains placeholders
        has_placeholders = "?" in inferred_types

        # Collect candidates that match by exact signature or arity
        exact_matches: list[str] = []
        arity_matches: list[str] = []

        for qualified_name in candidates:
            # Get the declared signature for this callable
            declared_sig = symbol_table.get_callable_signature(qualified_name)

            if declared_sig is None:
                # No signature info - can only match by name
                arity_matches.append(qualified_name)
                continue

            declared_types = self._parse_signature(declared_sig)
            declared_arity = len(declared_types)

            # Check for exact signature match
            if declared_sig == inferred_sig:
                exact_matches.append(qualified_name)
                continue

            # Check arity match
            if declared_arity != inferred_arity:
                # Handle varargs: varargs can match any arity >= declared_arity - 1
                if declared_types and declared_types[-1].endswith("..."):
                    varargs_min_arity = declared_arity - 1
                    if inferred_arity >= varargs_min_arity:
                        arity_matches.append(qualified_name)
                continue

            # Arity matches - check if types are compatible
            if has_placeholders:
                # With placeholders, check if non-placeholder types match
                if self._signatures_compatible(inferred_types, declared_types):
                    arity_matches.append(qualified_name)
            else:
                # No placeholders but signatures don't match exactly
                # This could be a subtype relationship - add to arity matches
                arity_matches.append(qualified_name)

        # Return exact match if unique
        if len(exact_matches) == 1:
            return exact_matches[0], None

        # Multiple exact matches is ambiguous
        if len(exact_matches) > 1:
            return None, f"Ambiguous: {len(exact_matches)} candidates"

        # No exact matches - try arity matches
        if len(arity_matches) == 1:
            return arity_matches[0], None

        if len(arity_matches) > 1:
            return None, f"Ambiguous: {len(arity_matches)} candidates"

        # No matches at all
        return None, "No callable matches the signature"

    def _signatures_compatible(
        self, inferred_types: list[str], declared_types: list[str]
    ) -> bool:
        """Check if inferred types are compatible with declared types.

        Handles placeholder types (?) which match any declared type.

        Args:
            inferred_types: List of inferred argument types (may contain ?).
            declared_types: List of declared parameter types.

        Returns:
            True if the signatures are compatible, False otherwise.
        """
        if len(inferred_types) != len(declared_types):
            return False

        for inferred, declared in zip(inferred_types, declared_types):
            if inferred == "?":
                # Placeholder matches anything
                continue
            if inferred != declared:
                # Types don't match exactly
                # Could add subtype checking here in the future
                return False

        return True

    def _parse_signature(self, signature: str) -> list[str]:
        """Parse a signature string into a list of type names.

        Args:
            signature: A signature string like "(String, int)" or "()".

        Returns:
            A list of type names, e.g., ["String", "int"] or [].
        """
        # Remove parentheses
        inner = signature.strip("()")
        if not inner:
            return []

        # Split by comma and strip whitespace
        return [t.strip() for t in inner.split(",")]
